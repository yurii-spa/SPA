"""
MP-928 — Tests for DeFiYieldCurvePositionAnalyzer
Run: python3 -m unittest spa_core.tests.test_defi_yield_curve_position_analyzer
"""

import json
import os
import sys
import tempfile
import unittest

# Ensure project root is importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from spa_core.analytics.defi_yield_curve_position_analyzer import (
    DeFiYieldCurvePositionAnalyzer,
    LABEL_RATE_ADVANTAGE,
    LABEL_NEUTRAL,
    LABEL_RATE_DISADVANTAGE,
    LABEL_EXPIRING_SOON,
    LABEL_UNDERWATER,
    FLAG_HIGH_DURATION,
    FLAG_INVERTED_ADVANTAGE,
    FLAG_NEAR_EXPIRY,
    FLAG_LARGE_DV01_EXPOSURE,
    FLAG_BREAKEVEN_NEAR,
)


def _make_pos(**kw):
    base = {
        "protocol": "Aave",
        "position_type": "fixed_lend",
        "notional_usd": 10000.0,
        "fixed_rate_pct": 6.0,
        "current_variable_rate_pct": 5.0,
        "rate_duration_days": 90,
        "breakeven_rate_pct": 4.5,
        "rate_sensitivity": 0.0001,
        "implied_vol_pct": 1.5,
    }
    base.update(kw)
    return base


class TestBasicAnalysis(unittest.TestCase):
    def setUp(self):
        self.az = DeFiYieldCurvePositionAnalyzer()
        # Redirect log to temp file
        self.tmpdir = tempfile.mkdtemp()
        import spa_core.analytics.defi_yield_curve_position_analyzer as mod
        self._orig = mod._LOG_PATH
        mod._LOG_PATH = os.path.join(self.tmpdir, "yield_curve_position_log.json")
        self.mod = mod

    def tearDown(self):
        self.mod._LOG_PATH = self._orig

    def test_returns_dict(self):
        result = self.az.analyze([_make_pos()], {})
        self.assertIsInstance(result, dict)

    def test_positions_key_present(self):
        result = self.az.analyze([_make_pos()], {})
        self.assertIn("positions", result)

    def test_aggregates_key_present(self):
        result = self.az.analyze([_make_pos()], {})
        self.assertIn("aggregates", result)

    def test_position_count(self):
        result = self.az.analyze([_make_pos(), _make_pos()], {})
        self.assertEqual(result["position_count"], 2)

    def test_empty_positions(self):
        result = self.az.analyze([], {})
        self.assertEqual(result["position_count"], 0)
        self.assertEqual(result["aggregates"]["total_notional_usd"], 0.0)

    def test_single_position_fields(self):
        result = self.az.analyze([_make_pos()], {})
        p = result["positions"][0]
        for field in [
            "protocol", "position_type", "notional_usd", "fixed_rate_pct",
            "current_variable_rate_pct", "rate_duration_days",
            "breakeven_rate_pct", "rate_sensitivity_dv01", "implied_vol_pct",
            "rate_advantage_pct", "duration_risk_score", "rate_risk_score",
            "position_dv01_usd", "net_pnl_if_rates_up_100bps_usd",
            "net_pnl_if_rates_down_100bps_usd", "label", "flags",
        ]:
            self.assertIn(field, p)

    def test_analyzed_at_present(self):
        result = self.az.analyze([_make_pos()], {})
        self.assertIn("analyzed_at", result)

    def test_analyzed_at_is_string(self):
        result = self.az.analyze([_make_pos()], {})
        self.assertIsInstance(result["analyzed_at"], str)


class TestRateAdvantage(unittest.TestCase):
    def setUp(self):
        self.az = DeFiYieldCurvePositionAnalyzer()
        import spa_core.analytics.defi_yield_curve_position_analyzer as mod
        self.tmpdir = tempfile.mkdtemp()
        self._orig = mod._LOG_PATH
        mod._LOG_PATH = os.path.join(self.tmpdir, "x.json")
        self.mod = mod

    def tearDown(self):
        self.mod._LOG_PATH = self._orig

    def test_fixed_lend_positive_advantage(self):
        pos = _make_pos(position_type="fixed_lend", fixed_rate_pct=7.0,
                        current_variable_rate_pct=5.0)
        result = self.az.analyze([pos], {})
        self.assertAlmostEqual(result["positions"][0]["rate_advantage_pct"], 2.0, places=3)

    def test_fixed_lend_negative_advantage(self):
        pos = _make_pos(position_type="fixed_lend", fixed_rate_pct=3.0,
                        current_variable_rate_pct=5.0)
        result = self.az.analyze([pos], {})
        self.assertAlmostEqual(result["positions"][0]["rate_advantage_pct"], -2.0, places=3)

    def test_fixed_borrow_positive_advantage(self):
        pos = _make_pos(position_type="fixed_borrow", fixed_rate_pct=3.0,
                        current_variable_rate_pct=5.0)
        result = self.az.analyze([pos], {})
        self.assertAlmostEqual(result["positions"][0]["rate_advantage_pct"], 2.0, places=3)

    def test_fixed_borrow_negative_advantage(self):
        pos = _make_pos(position_type="fixed_borrow", fixed_rate_pct=7.0,
                        current_variable_rate_pct=5.0)
        result = self.az.analyze([pos], {})
        self.assertAlmostEqual(result["positions"][0]["rate_advantage_pct"], -2.0, places=3)

    def test_variable_lend_zero_advantage(self):
        pos = _make_pos(position_type="variable_lend", fixed_rate_pct=None)
        result = self.az.analyze([pos], {})
        self.assertEqual(result["positions"][0]["rate_advantage_pct"], 0.0)

    def test_variable_borrow_zero_advantage(self):
        pos = _make_pos(position_type="variable_borrow", fixed_rate_pct=None)
        result = self.az.analyze([pos], {})
        self.assertEqual(result["positions"][0]["rate_advantage_pct"], 0.0)

    def test_lp_zero_advantage(self):
        pos = _make_pos(position_type="lp", fixed_rate_pct=None)
        result = self.az.analyze([pos], {})
        self.assertEqual(result["positions"][0]["rate_advantage_pct"], 0.0)

    def test_fixed_lend_equal_rates_zero(self):
        pos = _make_pos(position_type="fixed_lend", fixed_rate_pct=5.0,
                        current_variable_rate_pct=5.0)
        result = self.az.analyze([pos], {})
        self.assertAlmostEqual(result["positions"][0]["rate_advantage_pct"], 0.0, places=4)


class TestDurationRiskScore(unittest.TestCase):
    def setUp(self):
        self.az = DeFiYieldCurvePositionAnalyzer()
        import spa_core.analytics.defi_yield_curve_position_analyzer as mod
        self.tmpdir = tempfile.mkdtemp()
        self._orig = mod._LOG_PATH
        mod._LOG_PATH = os.path.join(self.tmpdir, "x.json")
        self.mod = mod

    def tearDown(self):
        self.mod._LOG_PATH = self._orig

    def test_zero_duration_zero_score(self):
        pos = _make_pos(rate_duration_days=0)
        result = self.az.analyze([pos], {})
        self.assertEqual(result["positions"][0]["duration_risk_score"], 0.0)

    def test_long_duration_high_score(self):
        pos = _make_pos(rate_duration_days=730)
        result = self.az.analyze([pos], {})
        self.assertGreater(result["positions"][0]["duration_risk_score"], 80.0)

    def test_score_between_0_and_100(self):
        for days in [1, 30, 90, 180, 365, 730]:
            pos = _make_pos(rate_duration_days=days)
            result = self.az.analyze([pos], {})
            score = result["positions"][0]["duration_risk_score"]
            self.assertGreaterEqual(score, 0.0)
            self.assertLessEqual(score, 100.0)

    def test_score_monotone_increasing(self):
        scores = []
        for days in [30, 90, 180, 365]:
            pos = _make_pos(rate_duration_days=days)
            result = self.az.analyze([pos], {})
            scores.append(result["positions"][0]["duration_risk_score"])
        for i in range(len(scores) - 1):
            self.assertLess(scores[i], scores[i + 1])

    def test_negative_duration_zero_score(self):
        pos = _make_pos(rate_duration_days=-5)
        result = self.az.analyze([pos], {})
        self.assertEqual(result["positions"][0]["duration_risk_score"], 0.0)


class TestRateRiskScore(unittest.TestCase):
    def setUp(self):
        self.az = DeFiYieldCurvePositionAnalyzer()
        import spa_core.analytics.defi_yield_curve_position_analyzer as mod
        self.tmpdir = tempfile.mkdtemp()
        self._orig = mod._LOG_PATH
        mod._LOG_PATH = os.path.join(self.tmpdir, "x.json")
        self.mod = mod

    def tearDown(self):
        self.mod._LOG_PATH = self._orig

    def test_zero_dv01_zero_score(self):
        pos = _make_pos(rate_sensitivity=0.0)
        result = self.az.analyze([pos], {})
        self.assertEqual(result["positions"][0]["rate_risk_score"], 0.0)

    def test_large_dv01_high_score(self):
        cfg = {"large_dv01_usd_threshold": 100.0}
        pos = _make_pos(rate_sensitivity=0.01, notional_usd=20000.0)
        result = self.az.analyze([pos], cfg)
        self.assertEqual(result["positions"][0]["rate_risk_score"], 100.0)

    def test_score_capped_at_100(self):
        cfg = {"large_dv01_usd_threshold": 1.0}
        pos = _make_pos(rate_sensitivity=1.0, notional_usd=1_000_000.0)
        result = self.az.analyze([pos], cfg)
        self.assertLessEqual(result["positions"][0]["rate_risk_score"], 100.0)

    def test_score_between_0_and_100(self):
        pos = _make_pos(rate_sensitivity=0.0001, notional_usd=10000.0)
        result = self.az.analyze([pos], {})
        score = result["positions"][0]["rate_risk_score"]
        self.assertGreaterEqual(score, 0.0)
        self.assertLessEqual(score, 100.0)


class TestPnLSensitivity(unittest.TestCase):
    def setUp(self):
        self.az = DeFiYieldCurvePositionAnalyzer()
        import spa_core.analytics.defi_yield_curve_position_analyzer as mod
        self.tmpdir = tempfile.mkdtemp()
        self._orig = mod._LOG_PATH
        mod._LOG_PATH = os.path.join(self.tmpdir, "x.json")
        self.mod = mod

    def tearDown(self):
        self.mod._LOG_PATH = self._orig

    def test_lend_pnl_up_negative(self):
        """Lenders lose when rates rise (bond-like)."""
        pos = _make_pos(position_type="fixed_lend", rate_sensitivity=0.001,
                        notional_usd=10000.0)
        result = self.az.analyze([pos], {})
        self.assertLess(result["positions"][0]["net_pnl_if_rates_up_100bps_usd"], 0)

    def test_lend_pnl_down_positive(self):
        pos = _make_pos(position_type="fixed_lend", rate_sensitivity=0.001,
                        notional_usd=10000.0)
        result = self.az.analyze([pos], {})
        self.assertGreater(result["positions"][0]["net_pnl_if_rates_down_100bps_usd"], 0)

    def test_borrow_pnl_up_positive(self):
        pos = _make_pos(position_type="fixed_borrow", rate_sensitivity=0.001,
                        notional_usd=10000.0)
        result = self.az.analyze([pos], {})
        self.assertGreater(result["positions"][0]["net_pnl_if_rates_up_100bps_usd"], 0)

    def test_borrow_pnl_down_negative(self):
        pos = _make_pos(position_type="fixed_borrow", rate_sensitivity=0.001,
                        notional_usd=10000.0)
        result = self.az.analyze([pos], {})
        self.assertLess(result["positions"][0]["net_pnl_if_rates_down_100bps_usd"], 0)

    def test_lp_pnl_zero(self):
        pos = _make_pos(position_type="lp", rate_sensitivity=0.001, notional_usd=10000.0)
        result = self.az.analyze([pos], {})
        self.assertEqual(result["positions"][0]["net_pnl_if_rates_up_100bps_usd"], 0.0)
        self.assertEqual(result["positions"][0]["net_pnl_if_rates_down_100bps_usd"], 0.0)

    def test_pnl_symmetry_lend(self):
        pos = _make_pos(position_type="fixed_lend", rate_sensitivity=0.001,
                        notional_usd=10000.0)
        result = self.az.analyze([pos], {})
        p = result["positions"][0]
        self.assertAlmostEqual(
            abs(p["net_pnl_if_rates_up_100bps_usd"]),
            abs(p["net_pnl_if_rates_down_100bps_usd"]),
            places=2
        )


class TestLabels(unittest.TestCase):
    def setUp(self):
        self.az = DeFiYieldCurvePositionAnalyzer()
        import spa_core.analytics.defi_yield_curve_position_analyzer as mod
        self.tmpdir = tempfile.mkdtemp()
        self._orig = mod._LOG_PATH
        mod._LOG_PATH = os.path.join(self.tmpdir, "x.json")
        self.mod = mod

    def tearDown(self):
        self.mod._LOG_PATH = self._orig

    def test_rate_advantage_label(self):
        pos = _make_pos(position_type="fixed_lend", fixed_rate_pct=8.0,
                        current_variable_rate_pct=5.0, rate_duration_days=90,
                        breakeven_rate_pct=4.0)
        result = self.az.analyze([pos], {})
        self.assertEqual(result["positions"][0]["label"], LABEL_RATE_ADVANTAGE)

    def test_rate_disadvantage_label(self):
        # fixed_rate (3.5%) > breakeven (2.0%) so NOT underwater, but < variable (6%)
        # → rate_advantage = 3.5 - 6.0 = -2.5% < -neutral_band → RATE_DISADVANTAGE
        pos = _make_pos(position_type="fixed_lend", fixed_rate_pct=3.5,
                        current_variable_rate_pct=6.0, rate_duration_days=90,
                        breakeven_rate_pct=2.0)
        result = self.az.analyze([pos], {})
        self.assertEqual(result["positions"][0]["label"], LABEL_RATE_DISADVANTAGE)

    def test_neutral_label(self):
        pos = _make_pos(position_type="fixed_lend", fixed_rate_pct=5.1,
                        current_variable_rate_pct=5.0, rate_duration_days=90,
                        breakeven_rate_pct=4.0)
        result = self.az.analyze([pos], {})
        self.assertEqual(result["positions"][0]["label"], LABEL_NEUTRAL)

    def test_expiring_soon_label(self):
        pos = _make_pos(rate_duration_days=7)
        result = self.az.analyze([pos], {})
        self.assertEqual(result["positions"][0]["label"], LABEL_EXPIRING_SOON)

    def test_expiring_soon_at_exactly_14_days(self):
        pos = _make_pos(rate_duration_days=14)
        result = self.az.analyze([pos], {})
        self.assertEqual(result["positions"][0]["label"], LABEL_EXPIRING_SOON)

    def test_not_expiring_soon_at_15_days(self):
        pos = _make_pos(rate_duration_days=15, fixed_rate_pct=8.0,
                        current_variable_rate_pct=5.0, breakeven_rate_pct=4.0)
        result = self.az.analyze([pos], {})
        self.assertNotEqual(result["positions"][0]["label"], LABEL_EXPIRING_SOON)

    def test_underwater_label_fixed_lend(self):
        # fixed_rate < breakeven → UNDERWATER
        pos = _make_pos(position_type="fixed_lend", fixed_rate_pct=3.0,
                        current_variable_rate_pct=5.0, rate_duration_days=90,
                        breakeven_rate_pct=4.0)
        result = self.az.analyze([pos], {})
        self.assertEqual(result["positions"][0]["label"], LABEL_UNDERWATER)

    def test_label_valid_value(self):
        valid_labels = {
            LABEL_RATE_ADVANTAGE, LABEL_NEUTRAL, LABEL_RATE_DISADVANTAGE,
            LABEL_EXPIRING_SOON, LABEL_UNDERWATER,
        }
        pos = _make_pos()
        result = self.az.analyze([pos], {})
        self.assertIn(result["positions"][0]["label"], valid_labels)

    def test_zero_duration_not_expiring(self):
        pos = _make_pos(rate_duration_days=0, fixed_rate_pct=8.0,
                        current_variable_rate_pct=5.0, breakeven_rate_pct=4.0)
        result = self.az.analyze([pos], {})
        self.assertNotEqual(result["positions"][0]["label"], LABEL_EXPIRING_SOON)


class TestFlags(unittest.TestCase):
    def setUp(self):
        self.az = DeFiYieldCurvePositionAnalyzer()
        import spa_core.analytics.defi_yield_curve_position_analyzer as mod
        self.tmpdir = tempfile.mkdtemp()
        self._orig = mod._LOG_PATH
        mod._LOG_PATH = os.path.join(self.tmpdir, "x.json")
        self.mod = mod

    def tearDown(self):
        self.mod._LOG_PATH = self._orig

    def test_high_duration_flag(self):
        pos = _make_pos(rate_duration_days=200)
        result = self.az.analyze([pos], {})
        self.assertIn(FLAG_HIGH_DURATION, result["positions"][0]["flags"])

    def test_no_high_duration_flag_below_threshold(self):
        pos = _make_pos(rate_duration_days=100)
        result = self.az.analyze([pos], {})
        self.assertNotIn(FLAG_HIGH_DURATION, result["positions"][0]["flags"])

    def test_high_duration_custom_threshold(self):
        pos = _make_pos(rate_duration_days=50)
        result = self.az.analyze([pos], {"high_duration_days": 30})
        self.assertIn(FLAG_HIGH_DURATION, result["positions"][0]["flags"])

    def test_inverted_advantage_flag(self):
        # fixed_lend with fixed > variable → INVERTED_ADVANTAGE
        pos = _make_pos(position_type="fixed_lend", fixed_rate_pct=8.0,
                        current_variable_rate_pct=5.0, rate_duration_days=90)
        result = self.az.analyze([pos], {})
        self.assertIn(FLAG_INVERTED_ADVANTAGE, result["positions"][0]["flags"])

    def test_no_inverted_flag_for_borrow(self):
        pos = _make_pos(position_type="fixed_borrow", fixed_rate_pct=8.0,
                        current_variable_rate_pct=5.0)
        result = self.az.analyze([pos], {})
        self.assertNotIn(FLAG_INVERTED_ADVANTAGE, result["positions"][0]["flags"])

    def test_near_expiry_flag(self):
        pos = _make_pos(rate_duration_days=7)
        result = self.az.analyze([pos], {})
        self.assertIn(FLAG_NEAR_EXPIRY, result["positions"][0]["flags"])

    def test_no_near_expiry_flag(self):
        pos = _make_pos(rate_duration_days=90)
        result = self.az.analyze([pos], {})
        self.assertNotIn(FLAG_NEAR_EXPIRY, result["positions"][0]["flags"])

    def test_large_dv01_flag(self):
        cfg = {"large_dv01_usd_threshold": 10.0}
        pos = _make_pos(rate_sensitivity=0.01, notional_usd=5000.0)
        result = self.az.analyze([pos], cfg)
        self.assertIn(FLAG_LARGE_DV01_EXPOSURE, result["positions"][0]["flags"])

    def test_no_large_dv01_flag(self):
        pos = _make_pos(rate_sensitivity=0.0000001, notional_usd=10.0)
        result = self.az.analyze([pos], {})
        self.assertNotIn(FLAG_LARGE_DV01_EXPOSURE, result["positions"][0]["flags"])

    def test_breakeven_near_flag(self):
        # variable_rate=5.0, breakeven=4.9 → 10 bps < 50 bps → BREAKEVEN_NEAR
        pos = _make_pos(current_variable_rate_pct=5.0, breakeven_rate_pct=4.9,
                        rate_duration_days=90)
        result = self.az.analyze([pos], {})
        self.assertIn(FLAG_BREAKEVEN_NEAR, result["positions"][0]["flags"])

    def test_no_breakeven_near_flag(self):
        pos = _make_pos(current_variable_rate_pct=5.0, breakeven_rate_pct=4.0,
                        rate_duration_days=90)
        result = self.az.analyze([pos], {})
        self.assertNotIn(FLAG_BREAKEVEN_NEAR, result["positions"][0]["flags"])

    def test_flags_is_list(self):
        pos = _make_pos()
        result = self.az.analyze([pos], {})
        self.assertIsInstance(result["positions"][0]["flags"], list)

    def test_multiple_flags_can_coexist(self):
        cfg = {"large_dv01_usd_threshold": 1.0, "high_duration_days": 10}
        pos = _make_pos(rate_duration_days=15, rate_sensitivity=0.01,
                        notional_usd=5000.0, current_variable_rate_pct=5.0,
                        breakeven_rate_pct=4.9)
        result = self.az.analyze([pos], cfg)
        flags = result["positions"][0]["flags"]
        self.assertGreater(len(flags), 1)


class TestAggregates(unittest.TestCase):
    def setUp(self):
        self.az = DeFiYieldCurvePositionAnalyzer()
        import spa_core.analytics.defi_yield_curve_position_analyzer as mod
        self.tmpdir = tempfile.mkdtemp()
        self._orig = mod._LOG_PATH
        mod._LOG_PATH = os.path.join(self.tmpdir, "x.json")
        self.mod = mod

    def tearDown(self):
        self.mod._LOG_PATH = self._orig

    def test_total_notional(self):
        positions = [
            _make_pos(notional_usd=10000.0),
            _make_pos(notional_usd=20000.0),
        ]
        result = self.az.analyze(positions, {})
        self.assertAlmostEqual(result["aggregates"]["total_notional_usd"], 30000.0, places=2)

    def test_portfolio_dv01(self):
        positions = [
            _make_pos(rate_sensitivity=0.001, notional_usd=10000.0),
            _make_pos(rate_sensitivity=0.002, notional_usd=5000.0),
        ]
        result = self.az.analyze(positions, {})
        expected = 10.0 + 10.0  # 0.001*10000 + 0.002*5000
        self.assertAlmostEqual(result["aggregates"]["portfolio_dv01_usd"], expected, places=3)

    def test_rate_advantage_count(self):
        positions = [
            _make_pos(position_type="fixed_lend", fixed_rate_pct=8.0,
                      current_variable_rate_pct=5.0, rate_duration_days=90,
                      breakeven_rate_pct=4.0),
            _make_pos(position_type="fixed_lend", fixed_rate_pct=3.0,
                      current_variable_rate_pct=5.0, rate_duration_days=90,
                      breakeven_rate_pct=4.0),
        ]
        result = self.az.analyze(positions, {})
        self.assertEqual(result["aggregates"]["rate_advantage_count"], 1)

    def test_best_rate_position_present(self):
        positions = [
            _make_pos(protocol="Aave", position_type="fixed_lend",
                      fixed_rate_pct=8.0, current_variable_rate_pct=5.0,
                      rate_duration_days=90, breakeven_rate_pct=4.0),
            _make_pos(protocol="Compound", position_type="fixed_lend",
                      fixed_rate_pct=3.0, current_variable_rate_pct=5.0,
                      rate_duration_days=90, breakeven_rate_pct=4.0),
        ]
        result = self.az.analyze(positions, {})
        self.assertIsNotNone(result["aggregates"]["best_rate_position"])

    def test_worst_rate_position_present(self):
        positions = [
            _make_pos(protocol="Aave", position_type="fixed_lend",
                      fixed_rate_pct=8.0, current_variable_rate_pct=5.0,
                      rate_duration_days=90, breakeven_rate_pct=4.0),
            _make_pos(protocol="Compound", position_type="fixed_lend",
                      fixed_rate_pct=3.0, current_variable_rate_pct=5.0,
                      rate_duration_days=90, breakeven_rate_pct=4.0),
        ]
        result = self.az.analyze(positions, {})
        self.assertIsNotNone(result["aggregates"]["worst_rate_position"])

    def test_label_counts_present(self):
        result = self.az.analyze([_make_pos()], {})
        self.assertIn("label_counts", result["aggregates"])

    def test_flag_counts_present(self):
        result = self.az.analyze([_make_pos()], {})
        self.assertIn("flag_counts", result["aggregates"])

    def test_aggregate_duration_risk_score(self):
        positions = [_make_pos(rate_duration_days=90), _make_pos(rate_duration_days=360)]
        result = self.az.analyze(positions, {})
        self.assertGreater(result["aggregates"]["average_duration_risk_score"], 0)

    def test_aggregate_rate_risk_score(self):
        positions = [_make_pos(rate_sensitivity=0.001, notional_usd=10000.0)]
        result = self.az.analyze(positions, {})
        self.assertGreaterEqual(result["aggregates"]["average_rate_risk_score"], 0)

    def test_empty_aggregates_defaults(self):
        result = self.az.analyze([], {})
        agg = result["aggregates"]
        self.assertIsNone(agg["best_rate_position"])
        self.assertIsNone(agg["worst_rate_position"])
        self.assertEqual(agg["rate_advantage_count"], 0)
        self.assertEqual(agg["portfolio_dv01_usd"], 0.0)


class TestDV01Calculation(unittest.TestCase):
    def setUp(self):
        self.az = DeFiYieldCurvePositionAnalyzer()
        import spa_core.analytics.defi_yield_curve_position_analyzer as mod
        self.tmpdir = tempfile.mkdtemp()
        self._orig = mod._LOG_PATH
        mod._LOG_PATH = os.path.join(self.tmpdir, "x.json")
        self.mod = mod

    def tearDown(self):
        self.mod._LOG_PATH = self._orig

    def test_dv01_calculation(self):
        pos = _make_pos(rate_sensitivity=0.001, notional_usd=10000.0)
        result = self.az.analyze([pos], {})
        self.assertAlmostEqual(
            result["positions"][0]["position_dv01_usd"], 10.0, places=3
        )

    def test_dv01_zero_notional(self):
        pos = _make_pos(rate_sensitivity=0.001, notional_usd=0.0)
        result = self.az.analyze([pos], {})
        self.assertEqual(result["positions"][0]["position_dv01_usd"], 0.0)

    def test_dv01_zero_sensitivity(self):
        pos = _make_pos(rate_sensitivity=0.0, notional_usd=10000.0)
        result = self.az.analyze([pos], {})
        self.assertEqual(result["positions"][0]["position_dv01_usd"], 0.0)


class TestRingBufferLog(unittest.TestCase):
    def setUp(self):
        import spa_core.analytics.defi_yield_curve_position_analyzer as mod
        self.tmpdir = tempfile.mkdtemp()
        self._orig = mod._LOG_PATH
        self.log_path = os.path.join(self.tmpdir, "yield_curve_position_log.json")
        mod._LOG_PATH = self.log_path
        self.mod = mod
        self.az = DeFiYieldCurvePositionAnalyzer()

    def tearDown(self):
        self.mod._LOG_PATH = self._orig

    def test_log_file_created(self):
        self.az.analyze([_make_pos()], {})
        self.assertTrue(os.path.exists(self.log_path))

    def test_log_is_valid_json(self):
        self.az.analyze([_make_pos()], {})
        with open(self.log_path) as f:
            data = json.load(f)
        self.assertIsInstance(data, list)

    def test_log_appends(self):
        self.az.analyze([_make_pos()], {})
        self.az.analyze([_make_pos()], {})
        with open(self.log_path) as f:
            data = json.load(f)
        self.assertEqual(len(data), 2)

    def test_log_ring_buffer_cap(self):
        import spa_core.analytics.defi_yield_curve_position_analyzer as mod
        orig_cap = mod._LOG_CAP
        mod._LOG_CAP = 3
        try:
            for _ in range(5):
                self.az.analyze([_make_pos()], {})
            with open(self.log_path) as f:
                data = json.load(f)
            self.assertLessEqual(len(data), 3)
        finally:
            mod._LOG_CAP = orig_cap

    def test_log_entry_has_ts(self):
        self.az.analyze([_make_pos()], {})
        with open(self.log_path) as f:
            data = json.load(f)
        self.assertIn("ts", data[0])

    def test_log_entry_has_aggregates(self):
        self.az.analyze([_make_pos()], {})
        with open(self.log_path) as f:
            data = json.load(f)
        self.assertIn("aggregates", data[0])

    def test_log_entry_has_position_count(self):
        self.az.analyze([_make_pos(), _make_pos()], {})
        with open(self.log_path) as f:
            data = json.load(f)
        self.assertEqual(data[0]["position_count"], 2)

    def test_log_with_empty_positions(self):
        self.az.analyze([], {})
        with open(self.log_path) as f:
            data = json.load(f)
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]["position_count"], 0)


class TestEdgeCases(unittest.TestCase):
    def setUp(self):
        self.az = DeFiYieldCurvePositionAnalyzer()
        import spa_core.analytics.defi_yield_curve_position_analyzer as mod
        self.tmpdir = tempfile.mkdtemp()
        self._orig = mod._LOG_PATH
        mod._LOG_PATH = os.path.join(self.tmpdir, "x.json")
        self.mod = mod

    def tearDown(self):
        self.mod._LOG_PATH = self._orig

    def test_missing_optional_fields_uses_defaults(self):
        pos = {"protocol": "TestProto", "position_type": "variable_lend",
               "notional_usd": 5000.0, "current_variable_rate_pct": 4.0}
        result = self.az.analyze([pos], {})
        self.assertIsNotNone(result["positions"][0]["label"])

    def test_none_config_uses_defaults(self):
        result = self.az.analyze([_make_pos()], None)
        self.assertIn("positions", result)

    def test_large_notional(self):
        pos = _make_pos(notional_usd=1_000_000_000.0)
        result = self.az.analyze([pos], {})
        self.assertEqual(result["positions"][0]["notional_usd"], 1_000_000_000.0)

    def test_zero_notional(self):
        pos = _make_pos(notional_usd=0.0)
        result = self.az.analyze([pos], {})
        self.assertEqual(result["positions"][0]["notional_usd"], 0.0)

    def test_high_implied_vol_stored(self):
        pos = _make_pos(implied_vol_pct=50.0)
        result = self.az.analyze([pos], {})
        self.assertAlmostEqual(result["positions"][0]["implied_vol_pct"], 50.0)

    def test_many_positions(self):
        positions = [_make_pos(notional_usd=float(i) * 1000) for i in range(1, 21)]
        result = self.az.analyze(positions, {})
        self.assertEqual(result["position_count"], 20)

    def test_protocol_name_preserved(self):
        pos = _make_pos(protocol="MySpecialProtocol")
        result = self.az.analyze([pos], {})
        self.assertEqual(result["positions"][0]["protocol"], "MySpecialProtocol")

    def test_position_type_preserved(self):
        for pt in ["fixed_lend", "fixed_borrow", "variable_lend", "variable_borrow", "lp"]:
            pos = _make_pos(position_type=pt, fixed_rate_pct=None if pt in
                            ("variable_lend", "variable_borrow", "lp") else 6.0)
            result = self.az.analyze([pos], {})
            self.assertEqual(result["positions"][0]["position_type"], pt)

    def test_custom_neutral_band(self):
        pos = _make_pos(position_type="fixed_lend", fixed_rate_pct=5.5,
                        current_variable_rate_pct=5.0, rate_duration_days=90,
                        breakeven_rate_pct=4.0)
        result_default = self.az.analyze([pos], {})
        result_wide = self.az.analyze([pos], {"neutral_band_pct": 1.0})
        self.assertEqual(result_wide["positions"][0]["label"], LABEL_NEUTRAL)


if __name__ == "__main__":
    unittest.main()
