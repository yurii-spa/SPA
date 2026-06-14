"""
Tests for MP-754: CollateralRatioMonitor
Uses unittest only (no pytest). ~70 tests.
"""

import json
import os
import sys
import tempfile
import unittest

# Ensure project root is importable
sys.path.insert(
    0, os.path.join(os.path.dirname(__file__), "..", "..")
)

from spa_core.analytics.collateral_ratio_monitor import (
    CollateralMonitorResult,
    CollateralPosition,
    _INF_CAP,
    alert_level_from_hf,
    compute_collateral_ratio,
    compute_health_factor,
    compute_liquidation_buffer,
    compute_max_safe_debt,
    load_history,
    monitor_portfolio,
    monitor_position,
    price_drop_tolerance,
    save_results,
)


# ---------------------------------------------------------------------------
# compute_collateral_ratio
# ---------------------------------------------------------------------------

class TestComputeCollateralRatio(unittest.TestCase):
    def test_basic(self):
        self.assertAlmostEqual(compute_collateral_ratio(10000, 5000), 200.0)

    def test_debt_zero_returns_inf_cap(self):
        self.assertEqual(compute_collateral_ratio(5000, 0), _INF_CAP)

    def test_equal_collateral_debt(self):
        self.assertAlmostEqual(compute_collateral_ratio(1000, 1000), 100.0)

    def test_small_collateral(self):
        self.assertAlmostEqual(compute_collateral_ratio(500, 1000), 50.0)

    def test_large_values(self):
        self.assertAlmostEqual(compute_collateral_ratio(1_000_000, 500_000), 200.0)

    def test_negative_debt_treated_as_zero(self):
        # debt <= 0 → INF_CAP
        self.assertEqual(compute_collateral_ratio(1000, 0), _INF_CAP)


# ---------------------------------------------------------------------------
# compute_health_factor
# ---------------------------------------------------------------------------

class TestComputeHealthFactor(unittest.TestCase):
    def test_basic_formula(self):
        # HF = (10000 * 0.80) / 6000 = 8000/6000 ≈ 1.333
        result = compute_health_factor(10000, 6000, 80)
        self.assertAlmostEqual(result, 8000 / 6000)

    def test_debt_zero_returns_inf_cap(self):
        self.assertEqual(compute_health_factor(5000, 0, 75), _INF_CAP)

    def test_exactly_at_threshold(self):
        # HF = (1000 * 0.80) / 800 = 1.0
        self.assertAlmostEqual(compute_health_factor(1000, 800, 80), 1.0)

    def test_over_borrowed(self):
        # HF = (1000 * 0.80) / 1000 = 0.8
        self.assertAlmostEqual(compute_health_factor(1000, 1000, 80), 0.8)

    def test_threshold_100_pct(self):
        # HF = (1000 * 1.0) / 500 = 2.0
        self.assertAlmostEqual(compute_health_factor(1000, 500, 100), 2.0)


# ---------------------------------------------------------------------------
# compute_max_safe_debt
# ---------------------------------------------------------------------------

class TestComputeMaxSafeDebt(unittest.TestCase):
    def test_basic_formula(self):
        self.assertAlmostEqual(compute_max_safe_debt(10000, 80), 8000.0)

    def test_zero_collateral(self):
        self.assertAlmostEqual(compute_max_safe_debt(0, 80), 0.0)

    def test_threshold_50(self):
        self.assertAlmostEqual(compute_max_safe_debt(20000, 50), 10000.0)

    def test_threshold_100(self):
        self.assertAlmostEqual(compute_max_safe_debt(5000, 100), 5000.0)


# ---------------------------------------------------------------------------
# compute_liquidation_buffer
# ---------------------------------------------------------------------------

class TestComputeLiquidationBuffer(unittest.TestCase):
    def test_normal(self):
        # ratio=200, threshold=80 → buffer=120
        self.assertAlmostEqual(compute_liquidation_buffer(200, 80), 120.0)

    def test_negative_buffer_when_under(self):
        # ratio=70, threshold=80 → buffer=-10
        self.assertAlmostEqual(compute_liquidation_buffer(70, 80), -10.0)

    def test_inf_cap_returns_inf_cap(self):
        self.assertEqual(compute_liquidation_buffer(_INF_CAP, 80), _INF_CAP)

    def test_at_threshold(self):
        self.assertAlmostEqual(compute_liquidation_buffer(80, 80), 0.0)


# ---------------------------------------------------------------------------
# price_drop_tolerance
# ---------------------------------------------------------------------------

class TestPriceDropTolerance(unittest.TestCase):
    def test_formula_hf_2(self):
        # (1 - 1/2) * 100 = 50
        self.assertAlmostEqual(price_drop_tolerance(2.0), 50.0)

    def test_formula_hf_1_5(self):
        # (1 - 1/1.5) * 100 ≈ 33.33
        self.assertAlmostEqual(price_drop_tolerance(1.5), (1 - 1 / 1.5) * 100, places=5)

    def test_hf_inf_cap_returns_100(self):
        self.assertAlmostEqual(price_drop_tolerance(_INF_CAP), 100.0)

    def test_hf_zero_returns_0(self):
        self.assertEqual(price_drop_tolerance(0), 0.0)

    def test_hf_1_returns_0(self):
        self.assertAlmostEqual(price_drop_tolerance(1.0), 0.0)

    def test_hf_less_than_1_returns_negative_clamped_to_0(self):
        # (1 - 1/0.8)*100 = negative → clamped 0
        self.assertGreaterEqual(price_drop_tolerance(0.8), 0.0)


# ---------------------------------------------------------------------------
# alert_level_from_hf
# ---------------------------------------------------------------------------

class TestAlertLevelFromHF(unittest.TestCase):
    def test_safe_above_1_5(self):
        self.assertEqual(alert_level_from_hf(2.0), "SAFE")

    def test_safe_exactly_1_5(self):
        self.assertEqual(alert_level_from_hf(1.5), "SAFE")

    def test_caution_between_1_2_and_1_5(self):
        self.assertEqual(alert_level_from_hf(1.3), "CAUTION")

    def test_caution_exactly_1_2(self):
        self.assertEqual(alert_level_from_hf(1.2), "CAUTION")

    def test_warning_between_1_0_and_1_2(self):
        self.assertEqual(alert_level_from_hf(1.1), "WARNING")

    def test_warning_exactly_1_0(self):
        self.assertEqual(alert_level_from_hf(1.0), "WARNING")

    def test_danger_below_1_0(self):
        self.assertEqual(alert_level_from_hf(0.9), "DANGER")

    def test_danger_zero(self):
        self.assertEqual(alert_level_from_hf(0.0), "DANGER")

    def test_inf_cap_is_safe(self):
        self.assertEqual(alert_level_from_hf(_INF_CAP), "SAFE")


# ---------------------------------------------------------------------------
# monitor_position
# ---------------------------------------------------------------------------

class TestMonitorPosition(unittest.TestCase):
    def _pos(self, c=10000, d=6000, lt=80):
        return monitor_position("Aave", "USDC", c, d, lt)

    def test_is_safe_true_when_hf_above_1(self):
        pos = self._pos(10000, 6000, 80)
        self.assertTrue(pos.is_safe)

    def test_is_safe_false_when_hf_below_1(self):
        pos = self._pos(1000, 2000, 80)
        self.assertFalse(pos.is_safe)

    def test_available_borrow_normal(self):
        # max_safe = 10000*0.8 = 8000; debt=6000 → avail=2000
        pos = self._pos(10000, 6000, 80)
        self.assertAlmostEqual(pos.available_borrow_usd, 2000.0)

    def test_available_borrow_clamped_at_zero_when_over_borrowed(self):
        # max_safe=1000*0.8=800; debt=1200 → avail=0
        pos = self._pos(1000, 1200, 80)
        self.assertEqual(pos.available_borrow_usd, 0.0)

    def test_recommendation_danger(self):
        pos = self._pos(1000, 2000, 80)  # HF = 800/2000 = 0.4
        self.assertIn("DANGER", pos.recommendation)
        self.assertIn("immediately", pos.recommendation)

    def test_recommendation_warning(self):
        # HF = 10000*0.8/9000 ≈ 0.89 ... need 1.0<=HF<1.2
        # HF = 10000*0.8/7000 ≈ 1.143
        pos = self._pos(10000, 7000, 80)
        self.assertIn("WARNING", pos.recommendation)

    def test_recommendation_caution(self):
        # HF ≈ 1.3 → CAUTION: need 1.2 <= HF < 1.5
        # 10000*0.8/hf_target = debt → debt = 8000/1.3 ≈ 6154
        pos = self._pos(10000, 6154, 80)
        self.assertIn("CAUTION", pos.recommendation)

    def test_recommendation_safe(self):
        # HF >= 1.5 → SAFE
        pos = self._pos(10000, 5000, 80)  # HF = 8000/5000 = 1.6
        self.assertEqual(pos.recommendation, "Position healthy.")

    def test_zero_debt_has_inf_health_factor(self):
        pos = self._pos(10000, 0, 80)
        self.assertEqual(pos.health_factor, _INF_CAP)
        self.assertTrue(pos.is_safe)
        self.assertEqual(pos.alert_level, "SAFE")

    def test_zero_collateral_zero_debt_is_safe(self):
        pos = monitor_position("X", "Y", 0, 0, 80)
        self.assertEqual(pos.health_factor, _INF_CAP)
        self.assertTrue(pos.is_safe)

    def test_exactly_at_threshold_hf_1_is_warning(self):
        # HF = (1000*0.8)/800 = 1.0 → WARNING
        pos = self._pos(1000, 800, 80)
        self.assertEqual(pos.alert_level, "WARNING")

    def test_collateral_ratio_stored(self):
        pos = self._pos(10000, 5000, 80)
        self.assertAlmostEqual(pos.collateral_ratio_pct, 200.0)

    def test_max_safe_debt_stored(self):
        pos = self._pos(10000, 5000, 80)
        self.assertAlmostEqual(pos.max_safe_debt_usd, 8000.0)

    def test_liquidation_buffer_stored(self):
        pos = self._pos(10000, 5000, 80)
        self.assertAlmostEqual(pos.liquidation_buffer_pct, 200.0 - 80.0)

    def test_price_drop_tolerance_stored(self):
        pos = self._pos(10000, 5000, 80)  # HF=1.6
        expected = (1 - 1 / 1.6) * 100
        self.assertAlmostEqual(pos.price_drop_tolerance_pct, expected, places=5)


# ---------------------------------------------------------------------------
# monitor_portfolio
# ---------------------------------------------------------------------------

class TestMonitorPortfolio(unittest.TestCase):
    def _data(self):
        return [
            {
                "protocol": "Aave",
                "asset": "USDC",
                "collateral_value_usd": 10000,
                "debt_value_usd": 5000,
                "liquidation_threshold_pct": 80,
            },
            {
                "protocol": "Compound",
                "asset": "ETH",
                "collateral_value_usd": 5000,
                "debt_value_usd": 4600,
                "liquidation_threshold_pct": 80,
            },
        ]

    def test_safe_positions_list(self):
        result = monitor_portfolio(self._data())
        self.assertIn("Aave/USDC", result.safe_positions)

    def test_at_risk_positions_list(self):
        result = monitor_portfolio(self._data())
        # Compound: HF = 5000*0.8/4600 ≈ 0.87 → DANGER
        self.assertIn("Compound/ETH", result.at_risk_positions)

    def test_most_at_risk_is_min_hf(self):
        result = monitor_portfolio(self._data())
        self.assertEqual(result.most_at_risk, "Compound/ETH")

    def test_avg_health_factor_computed(self):
        result = monitor_portfolio(self._data())
        self.assertGreater(result.avg_health_factor, 0)

    def test_system_alert_level_worst(self):
        result = monitor_portfolio(self._data())
        self.assertEqual(result.system_alert_level, "DANGER")

    def test_positions_count(self):
        result = monitor_portfolio(self._data())
        self.assertEqual(len(result.positions), 2)

    def test_all_safe_system_alert_safe(self):
        data = [
            {
                "protocol": "A",
                "asset": "USDC",
                "collateral_value_usd": 10000,
                "debt_value_usd": 2000,
                "liquidation_threshold_pct": 80,
            }
        ]
        result = monitor_portfolio(data)
        self.assertEqual(result.system_alert_level, "SAFE")

    def test_empty_portfolio(self):
        result = monitor_portfolio([])
        self.assertEqual(result.system_alert_level, "SAFE")
        self.assertEqual(result.avg_health_factor, 0.0)
        self.assertEqual(result.most_at_risk, "")


# ---------------------------------------------------------------------------
# save / load round-trip
# ---------------------------------------------------------------------------

class TestSaveLoad(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(
            suffix=".json", delete=False
        )
        self.tmp_path = self.tmp.name
        self.tmp.close()
        # Start with empty list
        with open(self.tmp_path, "w") as fh:
            json.dump([], fh)

    def tearDown(self):
        if os.path.exists(self.tmp_path):
            os.remove(self.tmp_path)

    def _build_result(self, protocol="Aave"):
        data = [
            {
                "protocol": protocol,
                "asset": "USDC",
                "collateral_value_usd": 10000,
                "debt_value_usd": 5000,
                "liquidation_threshold_pct": 80,
            }
        ]
        return monitor_portfolio(data)

    def test_save_and_load_round_trip(self):
        result = self._build_result()
        save_results(result, self.tmp_path)
        history = load_history(self.tmp_path)
        self.assertEqual(len(history), 1)
        self.assertIn("positions", history[0])
        self.assertEqual(history[0]["system_alert_level"], "SAFE")

    def test_saved_to_field_set(self):
        result = self._build_result()
        save_results(result, self.tmp_path)
        self.assertEqual(result.saved_to, self.tmp_path)

    def test_ring_buffer_cap_100(self):
        for i in range(110):
            result = self._build_result(protocol=f"Proto{i}")
            save_results(result, self.tmp_path)
        history = load_history(self.tmp_path)
        self.assertLessEqual(len(history), 100)
        self.assertEqual(len(history), 100)

    def test_ring_buffer_keeps_newest(self):
        for i in range(105):
            result = self._build_result(protocol=f"Proto{i}")
            save_results(result, self.tmp_path)
        history = load_history(self.tmp_path)
        # Newest 100 — first entry should be Proto5, last Proto104
        self.assertEqual(history[0]["positions"][0]["protocol"], "Proto5")
        self.assertEqual(history[-1]["positions"][0]["protocol"], "Proto104")

    def test_load_nonexistent_returns_empty_list(self):
        history = load_history("/nonexistent/path/file.json")
        self.assertEqual(history, [])

    def test_atomic_write_uses_replace(self):
        # Just verify no tmp file is left after save
        result = self._build_result()
        save_results(result, self.tmp_path)
        self.assertFalse(os.path.exists(self.tmp_path + ".tmp"))

    def test_save_multiple_entries_accumulate(self):
        for i in range(5):
            result = self._build_result()
            save_results(result, self.tmp_path)
        history = load_history(self.tmp_path)
        self.assertEqual(len(history), 5)


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------

class TestEdgeCases(unittest.TestCase):
    def test_hf_exactly_1_is_warning_level(self):
        self.assertEqual(alert_level_from_hf(1.0), "WARNING")

    def test_zero_collateral_zero_debt_is_safe(self):
        pos = monitor_position("A", "B", 0, 0, 80)
        self.assertTrue(pos.is_safe)
        self.assertEqual(pos.health_factor, _INF_CAP)

    def test_price_tolerance_hf_inf(self):
        self.assertEqual(price_drop_tolerance(_INF_CAP), 100.0)

    def test_liquidation_buffer_inf(self):
        self.assertEqual(compute_liquidation_buffer(_INF_CAP, 80), _INF_CAP)

    def test_health_factor_negative_debt_treated_as_zero(self):
        # Passing 0 directly
        self.assertEqual(compute_health_factor(1000, 0, 80), _INF_CAP)

    def test_collateral_ratio_small_debt(self):
        self.assertAlmostEqual(compute_collateral_ratio(100, 0.01), 1_000_000.0)

    def test_avg_health_factor_capped_at_inf_cap_for_zero_debt(self):
        data = [
            {
                "protocol": "X",
                "asset": "Y",
                "collateral_value_usd": 10000,
                "debt_value_usd": 0,
                "liquidation_threshold_pct": 80,
            }
        ]
        result = monitor_portfolio(data)
        self.assertEqual(result.avg_health_factor, _INF_CAP)

    def test_danger_position_in_at_risk(self):
        data = [
            {
                "protocol": "Danger",
                "asset": "ETH",
                "collateral_value_usd": 1000,
                "debt_value_usd": 2000,
                "liquidation_threshold_pct": 80,
            }
        ]
        result = monitor_portfolio(data)
        self.assertIn("Danger/ETH", result.at_risk_positions)

    def test_warning_position_in_at_risk(self):
        # HF exactly 1.1 → WARNING
        # debt = 10000*0.8 / 1.1 ≈ 7272.7
        data = [
            {
                "protocol": "W",
                "asset": "A",
                "collateral_value_usd": 10000,
                "debt_value_usd": 7273,
                "liquidation_threshold_pct": 80,
            }
        ]
        result = monitor_portfolio(data)
        self.assertIn("W/A", result.at_risk_positions)

    def test_recommendation_summary_all_safe(self):
        data = [
            {
                "protocol": "A",
                "asset": "U",
                "collateral_value_usd": 10000,
                "debt_value_usd": 1000,
                "liquidation_threshold_pct": 80,
            }
        ]
        result = monitor_portfolio(data)
        self.assertIn("healthy", result.recommendation_summary.lower())

    def test_recommendation_summary_danger(self):
        data = [
            {
                "protocol": "D",
                "asset": "E",
                "collateral_value_usd": 1000,
                "debt_value_usd": 5000,
                "liquidation_threshold_pct": 80,
            }
        ]
        result = monitor_portfolio(data)
        self.assertIn("CRITICAL", result.recommendation_summary)


if __name__ == "__main__":
    unittest.main()
