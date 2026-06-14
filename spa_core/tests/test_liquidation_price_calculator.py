"""
Tests for MP-756: LiquidationPriceCalculator
Uses unittest only. 65+ test cases.
"""

import json
import os
import tempfile
import unittest

from spa_core.analytics.liquidation_price_calculator import (
    DEFAULT_MAINTENANCE_MARGIN,
    LiquidationResult,
    LiquidationScenario,
    alert_level,
    analyze_portfolio,
    analyze_scenario,
    compute_borrowed,
    compute_liquidation_price_long,
    compute_liquidation_price_short,
    compute_pnl_long,
    compute_pnl_short,
    compute_position_size,
    is_liquidated,
    load_history,
    price_distance_pct,
    save_results,
)


class TestComputePositionSize(unittest.TestCase):
    def test_basic(self):
        self.assertAlmostEqual(compute_position_size(1000, 2.0), 2000.0)

    def test_one_x(self):
        self.assertAlmostEqual(compute_position_size(5000, 1.0), 5000.0)

    def test_fractional_leverage(self):
        self.assertAlmostEqual(compute_position_size(1000, 1.5), 1500.0)

    def test_zero_collateral(self):
        self.assertAlmostEqual(compute_position_size(0, 3.0), 0.0)


class TestComputeBorrowed(unittest.TestCase):
    def test_basic(self):
        self.assertAlmostEqual(compute_borrowed(1000, 2.0), 1000.0)

    def test_one_x(self):
        self.assertAlmostEqual(compute_borrowed(1000, 1.0), 0.0)

    def test_three_x(self):
        self.assertAlmostEqual(compute_borrowed(1000, 3.0), 2000.0)

    def test_fractional_leverage(self):
        self.assertAlmostEqual(compute_borrowed(1000, 1.5), 500.0)


class TestLiquidationPriceLong(unittest.TestCase):
    def test_basic_two_x(self):
        # entry=1000, leverage=2, mm=0.05
        # 1000 * (1 - 0.5 + 0.025) = 1000 * 0.525 = 525
        result = compute_liquidation_price_long(1000, 2.0, 0.05)
        self.assertAlmostEqual(result, 525.0)

    def test_three_x(self):
        # 1000 * (1 - 1/3 + 0.05/3) = 1000 * (0.6667 + 0.01667) = 683.33
        result = compute_liquidation_price_long(1000, 3.0, 0.05)
        expected = 1000 * (1 - 1 / 3 + 0.05 / 3)
        self.assertAlmostEqual(result, expected, places=5)

    def test_one_x_leverage(self):
        # 1x: 1 - 1/1 + 0.05/1 = 0.05 → liquidation at 5% of entry
        result = compute_liquidation_price_long(2000, 1.0, 0.05)
        self.assertAlmostEqual(result, 2000 * 0.05)

    def test_zero_leverage_guard(self):
        result = compute_liquidation_price_long(1000, 0, 0.05)
        self.assertEqual(result, 0.0)

    def test_different_entry(self):
        result = compute_liquidation_price_long(3000, 2.0, 0.05)
        self.assertAlmostEqual(result, 3000 * 0.525)

    def test_higher_mm(self):
        result = compute_liquidation_price_long(1000, 2.0, 0.10)
        expected = 1000 * (1 - 0.5 + 0.10 / 2)
        self.assertAlmostEqual(result, expected)


class TestLiquidationPriceShort(unittest.TestCase):
    def test_basic_two_x(self):
        # 1000 * (1 + 0.5 - 0.025) = 1000 * 1.475 = 1475
        result = compute_liquidation_price_short(1000, 2.0, 0.05)
        self.assertAlmostEqual(result, 1475.0)

    def test_three_x(self):
        result = compute_liquidation_price_short(1000, 3.0, 0.05)
        expected = 1000 * (1 + 1 / 3 - 0.05 / 3)
        self.assertAlmostEqual(result, expected, places=5)

    def test_zero_leverage_guard(self):
        result = compute_liquidation_price_short(1000, 0, 0.05)
        self.assertEqual(result, 0.0)

    def test_different_entry(self):
        result = compute_liquidation_price_short(2000, 2.0, 0.05)
        self.assertAlmostEqual(result, 2000 * 1.475)


class TestComputePnlLong(unittest.TestCase):
    def test_profit_price_up(self):
        pnl = compute_pnl_long(1000, 1100, 2000)
        # (1100-1000)/1000 * 2000 = 0.1*2000 = 200
        self.assertAlmostEqual(pnl, 200.0)

    def test_loss_price_down(self):
        pnl = compute_pnl_long(1000, 900, 2000)
        self.assertAlmostEqual(pnl, -200.0)

    def test_no_change(self):
        pnl = compute_pnl_long(1000, 1000, 2000)
        self.assertAlmostEqual(pnl, 0.0)

    def test_zero_entry_guard(self):
        pnl = compute_pnl_long(0, 1000, 2000)
        self.assertEqual(pnl, 0.0)


class TestComputePnlShort(unittest.TestCase):
    def test_profit_price_down(self):
        pnl = compute_pnl_short(1000, 900, 2000)
        # (1000-900)/1000 * 2000 = 0.1*2000 = 200
        self.assertAlmostEqual(pnl, 200.0)

    def test_loss_price_up(self):
        pnl = compute_pnl_short(1000, 1100, 2000)
        self.assertAlmostEqual(pnl, -200.0)

    def test_no_change(self):
        pnl = compute_pnl_short(1000, 1000, 2000)
        self.assertAlmostEqual(pnl, 0.0)

    def test_zero_entry_guard(self):
        pnl = compute_pnl_short(0, 500, 1000)
        self.assertEqual(pnl, 0.0)


class TestCurrentEquity(unittest.TestCase):
    def test_long_equity_profitable(self):
        pnl = compute_pnl_long(1000, 1100, 2000)
        equity = 1000 + pnl
        self.assertAlmostEqual(equity, 1200.0)

    def test_long_equity_losing(self):
        pnl = compute_pnl_long(1000, 900, 2000)
        equity = 1000 + pnl
        self.assertAlmostEqual(equity, 800.0)


class TestPriceDistancePct(unittest.TestCase):
    def test_basic(self):
        # |1000 - 800| / 1000 * 100 = 20%
        result = price_distance_pct(1000, 800)
        self.assertAlmostEqual(result, 20.0)

    def test_above_liquidation(self):
        result = price_distance_pct(1200, 1000)
        self.assertAlmostEqual(result, 100 * 200 / 1200)

    def test_zero_current_guard(self):
        result = price_distance_pct(0, 800)
        self.assertEqual(result, 0.0)

    def test_current_equals_liquidation(self):
        result = price_distance_pct(1000, 1000)
        self.assertAlmostEqual(result, 0.0)


class TestAlertLevel(unittest.TestCase):
    def test_safe(self):
        self.assertEqual(alert_level(25.0), "SAFE")

    def test_caution_lower_bound(self):
        self.assertEqual(alert_level(10.0), "CAUTION")

    def test_caution_upper_bound(self):
        self.assertEqual(alert_level(20.0), "CAUTION")

    def test_warning_lower_bound(self):
        self.assertEqual(alert_level(5.0), "WARNING")

    def test_warning_upper_bound(self):
        self.assertEqual(alert_level(9.9), "WARNING")

    def test_danger(self):
        self.assertEqual(alert_level(4.9), "DANGER")

    def test_danger_zero(self):
        self.assertEqual(alert_level(0.0), "DANGER")


class TestIsLiquidated(unittest.TestCase):
    def test_long_liquidated(self):
        self.assertTrue(is_liquidated("LONG", 500, 525))

    def test_long_at_liquidation(self):
        self.assertTrue(is_liquidated("LONG", 525, 525))

    def test_long_safe(self):
        self.assertFalse(is_liquidated("LONG", 526, 525))

    def test_short_liquidated(self):
        self.assertTrue(is_liquidated("SHORT", 1500, 1475))

    def test_short_at_liquidation(self):
        self.assertTrue(is_liquidated("SHORT", 1475, 1475))

    def test_short_safe(self):
        self.assertFalse(is_liquidated("SHORT", 1474, 1475))


class TestAnalyzeScenarioRecommendations(unittest.TestCase):
    def _make_long(self, entry, current, leverage=2.0, collateral=1000.0):
        return analyze_scenario("Proto", "ETH", "LONG", entry, current, leverage, collateral)

    def test_safe_recommendation(self):
        # current well above liquidation
        s = self._make_long(1000, 1000)
        self.assertEqual(s.alert_level, "SAFE")
        self.assertIn("safe", s.recommendation.lower())

    def test_caution_recommendation(self):
        # 2x LONG: liq = 525; need current ~15% above liq → ~600
        s = self._make_long(1000, 600, leverage=2.0)
        self.assertEqual(s.alert_level, "CAUTION")
        self.assertIn("CAUTION", s.recommendation)

    def test_warning_recommendation(self):
        # 2x LONG: liq = 525; 7% above → ~562
        s = self._make_long(1000, 562, leverage=2.0)
        self.assertEqual(s.alert_level, "WARNING")
        self.assertIn("WARNING", s.recommendation)

    def test_danger_recommendation(self):
        # 2x LONG: liq = 525; 3% above → ~541
        s = self._make_long(1000, 541, leverage=2.0)
        self.assertEqual(s.alert_level, "DANGER")
        self.assertIn("DANGER", s.recommendation)

    def test_liquidated_recommendation(self):
        # price at liquidation level
        s = self._make_long(1000, 520, leverage=2.0)
        self.assertTrue(s.is_liquidated)
        self.assertIn("DANGER", s.recommendation)


class TestAnalyzePortfolioAggregation(unittest.TestCase):
    def _make_data(self):
        return [
            {
                "protocol": "Aave",
                "asset": "ETH",
                "direction": "LONG",
                "entry_price": 3000,
                "current_price": 3500,
                "leverage": 2.0,
                "collateral": 5000,
            },
            {
                "protocol": "Compound",
                "asset": "BTC",
                "direction": "SHORT",
                "entry_price": 50000,
                "current_price": 45000,
                "leverage": 2.0,
                "collateral": 10000,
            },
        ]

    def test_liquidated_positions_empty_when_safe(self):
        result = analyze_portfolio(self._make_data())
        self.assertIsInstance(result.liquidated_positions, list)

    def test_at_risk_positions(self):
        result = analyze_portfolio(self._make_data())
        self.assertIsInstance(result.at_risk_positions, list)

    def test_safest_position_is_string(self):
        result = analyze_portfolio(self._make_data())
        self.assertIn(":", result.safest_position)

    def test_most_at_risk_is_string(self):
        result = analyze_portfolio(self._make_data())
        self.assertIn(":", result.most_at_risk)

    def test_system_alert_level_valid(self):
        result = analyze_portfolio(self._make_data())
        self.assertIn(result.system_alert_level, ("SAFE", "CAUTION", "WARNING", "DANGER"))

    def test_liquidated_positions_only_true(self):
        data = [
            {
                "protocol": "Morpho",
                "asset": "ETH",
                "direction": "LONG",
                "entry_price": 1000,
                "current_price": 500,   # below liq price 525
                "leverage": 2.0,
                "collateral": 1000,
            },
            {
                "protocol": "Aave",
                "asset": "WBTC",
                "direction": "LONG",
                "entry_price": 1000,
                "current_price": 1000,
                "leverage": 2.0,
                "collateral": 1000,
            },
        ]
        result = analyze_portfolio(data)
        self.assertIn("Morpho:ETH", result.liquidated_positions)
        self.assertNotIn("Aave:WBTC", result.liquidated_positions)

    def test_at_risk_includes_warning_danger(self):
        data = [
            {
                "protocol": "Euler",
                "asset": "ETH",
                "direction": "LONG",
                "entry_price": 1000,
                "current_price": 562,  # WARNING range
                "leverage": 2.0,
                "collateral": 1000,
            },
        ]
        result = analyze_portfolio(data)
        self.assertIn("Euler:ETH", result.at_risk_positions)

    def test_safest_is_max_dist_pct(self):
        data = [
            {
                "protocol": "A",
                "asset": "ETH",
                "direction": "LONG",
                "entry_price": 1000,
                "current_price": 1000,
                "leverage": 2.0,
                "collateral": 1000,
            },
            {
                "protocol": "B",
                "asset": "ETH",
                "direction": "LONG",
                "entry_price": 1000,
                "current_price": 600,
                "leverage": 2.0,
                "collateral": 1000,
            },
        ]
        result = analyze_portfolio(data)
        self.assertEqual(result.safest_position, "A:ETH")

    def test_most_at_risk_is_min_dist_pct(self):
        data = [
            {
                "protocol": "A",
                "asset": "ETH",
                "direction": "LONG",
                "entry_price": 1000,
                "current_price": 1000,
                "leverage": 2.0,
                "collateral": 1000,
            },
            {
                "protocol": "B",
                "asset": "ETH",
                "direction": "LONG",
                "entry_price": 1000,
                "current_price": 600,
                "leverage": 2.0,
                "collateral": 1000,
            },
        ]
        result = analyze_portfolio(data)
        self.assertEqual(result.most_at_risk, "B:ETH")

    def test_worst_system_alert(self):
        data = [
            {
                "protocol": "A",
                "asset": "ETH",
                "direction": "LONG",
                "entry_price": 1000,
                "current_price": 541,  # DANGER range
                "leverage": 2.0,
                "collateral": 1000,
            },
            {
                "protocol": "B",
                "asset": "ETH",
                "direction": "LONG",
                "entry_price": 1000,
                "current_price": 1000,
                "leverage": 2.0,
                "collateral": 1000,
            },
        ]
        result = analyze_portfolio(data)
        self.assertEqual(result.system_alert_level, "DANGER")


class TestSaveLoadRoundTrip(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp()
        self.log_file = os.path.join(self.tmp_dir, "liq_test_log.json")

    def _make_result(self):
        data = [
            {
                "protocol": "Aave",
                "asset": "ETH",
                "direction": "LONG",
                "entry_price": 3000,
                "current_price": 3500,
                "leverage": 2.0,
                "collateral": 5000,
            }
        ]
        return analyze_portfolio(data)

    def test_save_creates_file(self):
        result = self._make_result()
        save_results(result, self.log_file)
        self.assertTrue(os.path.exists(self.log_file))

    def test_save_updates_saved_to(self):
        result = self._make_result()
        save_results(result, self.log_file)
        self.assertEqual(result.saved_to, self.log_file)

    def test_load_returns_list(self):
        result = self._make_result()
        save_results(result, self.log_file)
        history = load_history(self.log_file)
        self.assertIsInstance(history, list)
        self.assertEqual(len(history), 1)

    def test_load_nonexistent_returns_empty(self):
        history = load_history(os.path.join(self.tmp_dir, "nonexistent.json"))
        self.assertEqual(history, [])

    def test_multiple_saves_accumulate(self):
        for _ in range(3):
            save_results(self._make_result(), self.log_file)
        history = load_history(self.log_file)
        self.assertEqual(len(history), 3)

    def test_ring_buffer_cap_100(self):
        for _ in range(105):
            save_results(self._make_result(), self.log_file)
        history = load_history(self.log_file)
        self.assertEqual(len(history), 100)

    def test_round_trip_data_integrity(self):
        result = self._make_result()
        save_results(result, self.log_file)
        history = load_history(self.log_file)
        self.assertEqual(history[0]["system_alert_level"], result.system_alert_level)


class TestEdgeCases(unittest.TestCase):
    def test_one_x_leverage_no_borrowed(self):
        # 1x leverage: borrowed = 0, liq price = entry * 0.05
        s = analyze_scenario("P", "ETH", "LONG", 1000, 1000, 1.0, 1000)
        self.assertAlmostEqual(s.borrowed_usd, 0.0)
        self.assertAlmostEqual(s.liquidation_price_usd, 50.0)

    def test_current_equals_entry_no_pnl(self):
        s = analyze_scenario("P", "ETH", "LONG", 1000, 1000, 2.0, 1000)
        self.assertAlmostEqual(s.current_pnl_usd, 0.0)
        self.assertAlmostEqual(s.current_equity_usd, 1000.0)

    def test_empty_portfolio(self):
        result = analyze_portfolio([])
        self.assertEqual(result.liquidated_positions, [])
        self.assertEqual(result.at_risk_positions, [])
        self.assertEqual(result.safest_position, "")
        self.assertEqual(result.most_at_risk, "")
        self.assertEqual(result.system_alert_level, "SAFE")

    def test_short_pnl_at_entry(self):
        s = analyze_scenario("P", "BTC", "SHORT", 50000, 50000, 2.0, 10000)
        self.assertAlmostEqual(s.current_pnl_usd, 0.0)

    def test_scenario_fields_populated(self):
        s = analyze_scenario("Aave", "USDC", "LONG", 1.0, 1.0, 2.0, 10000)
        self.assertEqual(s.protocol, "Aave")
        self.assertEqual(s.asset, "USDC")
        self.assertEqual(s.direction, "LONG")
        self.assertIsInstance(s.alert_level, str)
        self.assertIsInstance(s.recommendation, str)


if __name__ == "__main__":
    unittest.main()
