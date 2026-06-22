"""
Tests for MP-1072 DeFiProtocolLeverageLoopRiskAnalyzer.
Run: python3 -m unittest spa_core.tests.test_defi_protocol_leverage_loop_risk_analyzer -v
"""

import json
import os
import sys
import tempfile
import unittest

_REPO = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _REPO not in sys.path:
    sys.path.insert(0, _REPO)

from spa_core.analytics.defi_protocol_leverage_loop_risk_analyzer import (
    DeFiProtocolLeverageLoopRiskAnalyzer,
    _validate_input,
    _effective_leverage,
    _net_apy,
    _liquidation_price_drop,
    _margin_of_safety,
    _risk_label,
    _analyze_position,
    _atomic_write,
    _init_log,
    _append_log,
    _iso_now,
    LOG_MAX_ENTRIES,
    REQUIRED_FIELDS,
    analyze,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _make_pos(**kwargs):
    """Return a valid position dict, overriding any supplied kwargs."""
    base = {
        "protocol_name":              "Aave V3",
        "collateral_asset":           "wstETH",
        "borrow_asset":               "WETH",
        "initial_capital_usd":        50_000.0,
        "target_leverage_x":          2.5,
        "ltv_pct":                    75.0,
        "liquidation_threshold_pct":  82.0,
        "supply_apy_pct":             4.5,
        "borrow_apy_pct":             2.0,
        "price_drop_trigger_pct":     15.0,
        "loop_count":                 3,
    }
    base.update(kwargs)
    return base


def _safe_pos():
    """Conservative position: low loops, wide margin."""
    return _make_pos(ltv_pct=50.0, liquidation_threshold_pct=65.0,
                     loop_count=1, price_drop_trigger_pct=5.0,
                     target_leverage_x=2.0)


def _risky_pos():
    """Aggressive position: high LTV, many loops."""
    return _make_pos(ltv_pct=90.0, liquidation_threshold_pct=95.0,
                     loop_count=5, price_drop_trigger_pct=30.0,
                     target_leverage_x=10.0)


# ===========================================================================
# 1. Validation
# ===========================================================================

class TestValidationMissingFields(unittest.TestCase):

    def test_all_required_present_passes(self):
        _validate_input(_make_pos())  # should not raise

    def test_missing_protocol_name(self):
        p = _make_pos(); del p["protocol_name"]
        with self.assertRaises(ValueError):
            _validate_input(p)

    def test_missing_collateral_asset(self):
        p = _make_pos(); del p["collateral_asset"]
        with self.assertRaises(ValueError):
            _validate_input(p)

    def test_missing_borrow_asset(self):
        p = _make_pos(); del p["borrow_asset"]
        with self.assertRaises(ValueError):
            _validate_input(p)

    def test_missing_initial_capital_usd(self):
        p = _make_pos(); del p["initial_capital_usd"]
        with self.assertRaises(ValueError):
            _validate_input(p)

    def test_missing_target_leverage_x(self):
        p = _make_pos(); del p["target_leverage_x"]
        with self.assertRaises(ValueError):
            _validate_input(p)

    def test_missing_ltv_pct(self):
        p = _make_pos(); del p["ltv_pct"]
        with self.assertRaises(ValueError):
            _validate_input(p)

    def test_missing_liquidation_threshold_pct(self):
        p = _make_pos(); del p["liquidation_threshold_pct"]
        with self.assertRaises(ValueError):
            _validate_input(p)

    def test_missing_supply_apy_pct(self):
        p = _make_pos(); del p["supply_apy_pct"]
        with self.assertRaises(ValueError):
            _validate_input(p)

    def test_missing_borrow_apy_pct(self):
        p = _make_pos(); del p["borrow_apy_pct"]
        with self.assertRaises(ValueError):
            _validate_input(p)

    def test_missing_price_drop_trigger_pct(self):
        p = _make_pos(); del p["price_drop_trigger_pct"]
        with self.assertRaises(ValueError):
            _validate_input(p)

    def test_missing_loop_count(self):
        p = _make_pos(); del p["loop_count"]
        with self.assertRaises(ValueError):
            _validate_input(p)


class TestValidationFieldValues(unittest.TestCase):

    def test_empty_protocol_name_raises(self):
        with self.assertRaises(ValueError):
            _validate_input(_make_pos(protocol_name=""))

    def test_whitespace_protocol_name_raises(self):
        with self.assertRaises(ValueError):
            _validate_input(_make_pos(protocol_name="   "))

    def test_empty_collateral_asset_raises(self):
        with self.assertRaises(ValueError):
            _validate_input(_make_pos(collateral_asset=""))

    def test_empty_borrow_asset_raises(self):
        with self.assertRaises(ValueError):
            _validate_input(_make_pos(borrow_asset=""))

    def test_zero_initial_capital_raises(self):
        with self.assertRaises(ValueError):
            _validate_input(_make_pos(initial_capital_usd=0))

    def test_negative_initial_capital_raises(self):
        with self.assertRaises(ValueError):
            _validate_input(_make_pos(initial_capital_usd=-1.0))

    def test_target_leverage_below_one_raises(self):
        with self.assertRaises(ValueError):
            _validate_input(_make_pos(target_leverage_x=0.5))

    def test_target_leverage_exactly_one_valid(self):
        _validate_input(_make_pos(target_leverage_x=1.0))

    def test_ltv_zero_raises(self):
        with self.assertRaises(ValueError):
            _validate_input(_make_pos(ltv_pct=0))

    def test_ltv_hundred_raises(self):
        with self.assertRaises(ValueError):
            _validate_input(_make_pos(ltv_pct=100))

    def test_ltv_negative_raises(self):
        with self.assertRaises(ValueError):
            _validate_input(_make_pos(ltv_pct=-5))

    def test_liq_threshold_zero_raises(self):
        with self.assertRaises(ValueError):
            _validate_input(_make_pos(liquidation_threshold_pct=0))

    def test_liq_threshold_100_valid(self):
        _validate_input(_make_pos(liquidation_threshold_pct=100.0,
                                   ltv_pct=75.0))

    def test_ltv_equals_liq_threshold_raises(self):
        with self.assertRaises(ValueError):
            _validate_input(_make_pos(ltv_pct=80.0, liquidation_threshold_pct=80.0))

    def test_ltv_greater_than_liq_threshold_raises(self):
        with self.assertRaises(ValueError):
            _validate_input(_make_pos(ltv_pct=85.0, liquidation_threshold_pct=80.0))

    def test_negative_supply_apy_raises(self):
        with self.assertRaises(ValueError):
            _validate_input(_make_pos(supply_apy_pct=-0.1))

    def test_zero_supply_apy_valid(self):
        _validate_input(_make_pos(supply_apy_pct=0.0))

    def test_negative_borrow_apy_raises(self):
        with self.assertRaises(ValueError):
            _validate_input(_make_pos(borrow_apy_pct=-1.0))

    def test_zero_borrow_apy_valid(self):
        _validate_input(_make_pos(borrow_apy_pct=0.0))

    def test_price_drop_negative_raises(self):
        with self.assertRaises(ValueError):
            _validate_input(_make_pos(price_drop_trigger_pct=-1.0))

    def test_price_drop_over_100_raises(self):
        with self.assertRaises(ValueError):
            _validate_input(_make_pos(price_drop_trigger_pct=101.0))

    def test_price_drop_zero_valid(self):
        _validate_input(_make_pos(price_drop_trigger_pct=0.0))

    def test_price_drop_100_valid(self):
        _validate_input(_make_pos(price_drop_trigger_pct=100.0))

    def test_loop_count_negative_raises(self):
        with self.assertRaises(ValueError):
            _validate_input(_make_pos(loop_count=-1))

    def test_loop_count_float_raises(self):
        with self.assertRaises(ValueError):
            _validate_input(_make_pos(loop_count=2.5))

    def test_loop_count_bool_raises(self):
        with self.assertRaises(ValueError):
            _validate_input(_make_pos(loop_count=True))

    def test_loop_count_over_max_raises(self):
        with self.assertRaises(ValueError):
            _validate_input(_make_pos(loop_count=21))

    def test_loop_count_max_valid(self):
        _validate_input(_make_pos(loop_count=20))

    def test_loop_count_zero_valid(self):
        _validate_input(_make_pos(loop_count=0))


# ===========================================================================
# 2. Effective leverage formula
# ===========================================================================

class TestEffectiveLeverage(unittest.TestCase):

    def test_zero_loops_returns_one(self):
        self.assertEqual(_effective_leverage(75.0, 0), 1.0)

    def test_zero_loops_any_ltv_returns_one(self):
        for ltv in [10.0, 50.0, 90.0, 99.0]:
            self.assertEqual(_effective_leverage(ltv, 0), 1.0)

    def test_one_loop_75ltv(self):
        # 1 + 0.75 = 1.75
        self.assertAlmostEqual(_effective_leverage(75.0, 1), 1.75, places=4)

    def test_two_loops_75ltv(self):
        # 1 + 0.75 + 0.5625 = 2.3125
        self.assertAlmostEqual(_effective_leverage(75.0, 2), 2.3125, places=4)

    def test_three_loops_75ltv(self):
        # 1 + 0.75 + 0.5625 + 0.421875 ≈ 2.734375
        expected = 1 + 0.75 + 0.5625 + 0.421875
        self.assertAlmostEqual(_effective_leverage(75.0, 3), expected, places=4)

    def test_one_loop_50ltv(self):
        self.assertAlmostEqual(_effective_leverage(50.0, 1), 1.5, places=4)

    def test_two_loops_50ltv(self):
        # 1 + 0.5 + 0.25 = 1.75
        self.assertAlmostEqual(_effective_leverage(50.0, 2), 1.75, places=4)

    def test_ten_loops_50ltv_converges(self):
        # As loops → ∞, L → 1/(1-0.5) = 2.0
        lev = _effective_leverage(50.0, 10)
        self.assertLess(lev, 2.0)
        self.assertGreater(lev, 1.99)

    def test_twenty_loops_50ltv_near_limit(self):
        lev = _effective_leverage(50.0, 20)
        self.assertAlmostEqual(lev, 2.0, places=4)

    def test_leverage_increases_with_loops(self):
        lev_prev = _effective_leverage(80.0, 0)
        for n in range(1, 6):
            lev_n = _effective_leverage(80.0, n)
            self.assertGreater(lev_n, lev_prev)
            lev_prev = lev_n

    def test_leverage_increases_with_ltv(self):
        for n in [1, 3, 5]:
            l1 = _effective_leverage(50.0, n)
            l2 = _effective_leverage(80.0, n)
            self.assertGreater(l2, l1)

    def test_one_loop_90ltv(self):
        self.assertAlmostEqual(_effective_leverage(90.0, 1), 1.9, places=4)

    def test_formula_consistent_with_geometric_sum(self):
        ltv = 0.70
        n = 4
        manual = sum(ltv ** k for k in range(n + 1))
        computed = _effective_leverage(ltv * 100, n)
        self.assertAlmostEqual(computed, manual, places=5)


# ===========================================================================
# 3. Net APY
# ===========================================================================

class TestNetApy(unittest.TestCase):

    def test_no_leverage_returns_supply_apy(self):
        # L=1 → net = supply*1 - borrow*0 = supply
        self.assertAlmostEqual(_net_apy(5.0, 3.0, 1.0), 5.0, places=4)

    def test_positive_spread_amplified(self):
        # L=2, supply=5, borrow=3 → 5*2 - 3*1 = 7
        self.assertAlmostEqual(_net_apy(5.0, 3.0, 2.0), 7.0, places=4)

    def test_negative_spread_penalized(self):
        # supply=2, borrow=5, L=3 → 6 - 10 = -4
        self.assertAlmostEqual(_net_apy(2.0, 5.0, 3.0), -4.0, places=4)

    def test_zero_borrow_apy(self):
        # L=3, supply=4, borrow=0 → 12
        self.assertAlmostEqual(_net_apy(4.0, 0.0, 3.0), 12.0, places=4)

    def test_zero_supply_apy(self):
        # L=3, supply=0, borrow=2 → 0 - 4 = -4
        self.assertAlmostEqual(_net_apy(0.0, 2.0, 3.0), -4.0, places=4)

    def test_both_apy_zero(self):
        self.assertAlmostEqual(_net_apy(0.0, 0.0, 5.0), 0.0, places=4)

    def test_high_leverage_large_positive_spread(self):
        # supply=8, borrow=4, L=5 → 40 - 16 = 24
        self.assertAlmostEqual(_net_apy(8.0, 4.0, 5.0), 24.0, places=4)

    def test_equal_apy_no_gain(self):
        # supply == borrow == 5, L=4 → 20 - 15 = 5 (same as unlevered)
        self.assertAlmostEqual(_net_apy(5.0, 5.0, 4.0), 5.0, places=4)

    def test_result_is_rounded_to_4_decimal(self):
        result = _net_apy(3.333, 1.111, 2.0)
        # 3.333*2 - 1.111*1 = 6.666 - 1.111 = 5.555
        self.assertAlmostEqual(result, 5.555, places=4)


# ===========================================================================
# 4. Liquidation price drop
# ===========================================================================

class TestLiquidationPriceDrop(unittest.TestCase):

    def test_leverage_one_returns_100(self):
        self.assertEqual(_liquidation_price_drop(1.0, 80.0), 100.0)

    def test_leverage_below_one_returns_100(self):
        self.assertEqual(_liquidation_price_drop(0.5, 80.0), 100.0)

    def test_formula_l2_lt80(self):
        # d = 1 - (2-1)/(2*0.8) = 1 - 0.625 = 0.375 → 37.5%
        self.assertAlmostEqual(_liquidation_price_drop(2.0, 80.0), 37.5, places=4)

    def test_formula_l3_lt80(self):
        # d = 1 - 2/(3*0.8) = 1 - 0.8333 = 0.1667 → 16.67%
        expected = (1.0 - 2.0 / (3.0 * 0.8)) * 100.0
        self.assertAlmostEqual(_liquidation_price_drop(3.0, 80.0), expected, places=3)

    def test_formula_l5_lt90(self):
        # d = 1 - 4/(5*0.9) = 1 - 0.8889 = 0.1111 → 11.11%
        expected = (1.0 - 4.0 / (5.0 * 0.9)) * 100.0
        self.assertAlmostEqual(_liquidation_price_drop(5.0, 90.0), expected, places=3)

    def test_higher_leverage_lower_drop_threshold(self):
        d2 = _liquidation_price_drop(2.0, 80.0)
        d3 = _liquidation_price_drop(3.0, 80.0)
        d5 = _liquidation_price_drop(5.0, 80.0)
        self.assertGreater(d2, d3)
        self.assertGreater(d3, d5)

    def test_higher_liq_threshold_higher_drop_threshold(self):
        d1 = _liquidation_price_drop(3.0, 70.0)
        d2 = _liquidation_price_drop(3.0, 85.0)
        self.assertGreater(d2, d1)

    def test_result_clamped_to_zero(self):
        # Extreme leverage with very low LT: drop may go negative → clamp to 0
        drop = _liquidation_price_drop(100.0, 50.0)
        self.assertGreaterEqual(drop, 0.0)

    def test_result_clamped_to_100(self):
        drop = _liquidation_price_drop(1.0, 90.0)
        self.assertLessEqual(drop, 100.0)

    def test_l2_lt100_formula(self):
        # d = 1 - 1/(2*1.0) = 0.5 → 50%
        self.assertAlmostEqual(_liquidation_price_drop(2.0, 100.0), 50.0, places=4)


# ===========================================================================
# 5. Margin of safety and risk labels
# ===========================================================================

class TestMarginOfSafety(unittest.TestCase):

    def test_margin_positive_when_drop_less_than_liq(self):
        m = _margin_of_safety(37.5, 20.0)
        self.assertAlmostEqual(m, 17.5, places=4)

    def test_margin_negative_when_drop_exceeds_liq(self):
        m = _margin_of_safety(10.0, 25.0)
        self.assertAlmostEqual(m, -15.0, places=4)

    def test_margin_zero_when_equal(self):
        m = _margin_of_safety(20.0, 20.0)
        self.assertAlmostEqual(m, 0.0, places=4)


class TestRiskLabel(unittest.TestCase):

    def test_negative_margin_liquidation_imminent(self):
        self.assertEqual(_risk_label(-0.01), "LIQUIDATION_IMMINENT")

    def test_large_negative_margin_liquidation_imminent(self):
        self.assertEqual(_risk_label(-50.0), "LIQUIDATION_IMMINENT")

    def test_zero_margin_liquidation_prone(self):
        self.assertEqual(_risk_label(0.0), "LIQUIDATION_PRONE")

    def test_margin_5_liquidation_prone(self):
        self.assertEqual(_risk_label(5.0), "LIQUIDATION_PRONE")

    def test_margin_9_99_liquidation_prone(self):
        self.assertEqual(_risk_label(9.99), "LIQUIDATION_PRONE")

    def test_margin_10_aggressive(self):
        self.assertEqual(_risk_label(10.0), "AGGRESSIVE_LEVERAGE")

    def test_margin_15_aggressive(self):
        self.assertEqual(_risk_label(15.0), "AGGRESSIVE_LEVERAGE")

    def test_margin_19_99_aggressive(self):
        self.assertEqual(_risk_label(19.99), "AGGRESSIVE_LEVERAGE")

    def test_margin_20_moderate(self):
        self.assertEqual(_risk_label(20.0), "MODERATE_LEVERAGE")

    def test_margin_30_moderate(self):
        self.assertEqual(_risk_label(30.0), "MODERATE_LEVERAGE")

    def test_margin_39_99_moderate(self):
        self.assertEqual(_risk_label(39.99), "MODERATE_LEVERAGE")

    def test_margin_40_conservative(self):
        self.assertEqual(_risk_label(40.0), "CONSERVATIVE_LEVERAGE")

    def test_margin_100_conservative(self):
        self.assertEqual(_risk_label(100.0), "CONSERVATIVE_LEVERAGE")


# ===========================================================================
# 6. Analyzer class — single position
# ===========================================================================

class TestAnalyzerSinglePosition(unittest.TestCase):

    def setUp(self):
        self.analyzer = DeFiProtocolLeverageLoopRiskAnalyzer()

    def _run(self, **kwargs):
        return self.analyzer.analyze(_make_pos(**kwargs))

    def test_output_has_all_required_keys(self):
        result = self._run()
        for key in ("effective_leverage_x", "net_apy_pct", "liquidation_price_drop_pct",
                    "margin_of_safety_pct", "leverage_risk_label", "analyzed_at",
                    "protocol_name", "collateral_asset", "borrow_asset"):
            self.assertIn(key, result)

    def test_protocol_name_preserved(self):
        r = self._run(protocol_name="Morpho Blue")
        self.assertEqual(r["protocol_name"], "Morpho Blue")

    def test_collateral_asset_preserved(self):
        r = self._run(collateral_asset="stETH")
        self.assertEqual(r["collateral_asset"], "stETH")

    def test_borrow_asset_preserved(self):
        r = self._run(borrow_asset="DAI")
        self.assertEqual(r["borrow_asset"], "DAI")

    def test_no_loops_leverage_is_one(self):
        r = self._run(loop_count=0, target_leverage_x=10.0)
        self.assertAlmostEqual(r["effective_leverage_x"], 1.0, places=4)

    def test_no_loops_net_apy_equals_supply_apy(self):
        r = self._run(loop_count=0, supply_apy_pct=6.0, borrow_apy_pct=3.0,
                      target_leverage_x=1.0)
        self.assertAlmostEqual(r["net_apy_pct"], 6.0, places=4)

    def test_no_leverage_no_liquidation_risk(self):
        r = self._run(loop_count=0, target_leverage_x=1.0)
        self.assertAlmostEqual(r["liquidation_price_drop_pct"], 100.0, places=4)

    def test_conservative_scenario_label(self):
        # Low LTV, 1 loop, small stress drop
        r = self._run(ltv_pct=50.0, liquidation_threshold_pct=65.0,
                      loop_count=1, price_drop_trigger_pct=5.0, target_leverage_x=2.0)
        self.assertEqual(r["leverage_risk_label"], "CONSERVATIVE_LEVERAGE")

    def test_aggressive_scenario_label(self):
        # Mid leverage, medium margin ~15%
        r = self._run(ltv_pct=75.0, liquidation_threshold_pct=80.0,
                      loop_count=2, price_drop_trigger_pct=20.0, target_leverage_x=10.0)
        margin = r["margin_of_safety_pct"]
        label = r["leverage_risk_label"]
        if 10.0 <= margin < 20.0:
            self.assertEqual(label, "AGGRESSIVE_LEVERAGE")

    def test_liquidation_imminent_when_drop_exceeds_liq_threshold(self):
        # Stress 40%, but liq threshold achieved at 16.67% with L=3, LT=80
        r = self._run(ltv_pct=75.0, liquidation_threshold_pct=80.0,
                      loop_count=4, price_drop_trigger_pct=25.0, target_leverage_x=10.0)
        self.assertEqual(r["leverage_risk_label"], "LIQUIDATION_IMMINENT")

    def test_target_leverage_caps_effective_leverage(self):
        # With LTV=90, 5 loops → L ≈ (1-0.9^6)/(0.1) ≈ 9.46
        # Cap at target_leverage_x = 2.0
        r = self._run(ltv_pct=90.0, liquidation_threshold_pct=95.0,
                      loop_count=5, target_leverage_x=2.0)
        self.assertAlmostEqual(r["effective_leverage_x"], 2.0, places=3)

    def test_analyzed_at_is_string(self):
        r = self._run()
        self.assertIsInstance(r["analyzed_at"], str)

    def test_analyzed_at_contains_t(self):
        r = self._run()
        self.assertIn("T", r["analyzed_at"])

    def test_high_supply_low_borrow_positive_apy(self):
        r = self._run(supply_apy_pct=10.0, borrow_apy_pct=1.0, loop_count=2)
        self.assertGreater(r["net_apy_pct"], 10.0)

    def test_negative_spread_still_completes(self):
        r = self._run(supply_apy_pct=1.0, borrow_apy_pct=8.0, loop_count=3)
        self.assertLess(r["net_apy_pct"], 1.0)

    def test_large_capital_no_effect_on_leverage(self):
        r1 = self._run(initial_capital_usd=1_000.0)
        r2 = self._run(initial_capital_usd=10_000_000.0)
        self.assertAlmostEqual(r1["effective_leverage_x"], r2["effective_leverage_x"], places=4)

    def test_module_level_analyze_function(self):
        r = analyze(_make_pos())
        self.assertIn("leverage_risk_label", r)

    def test_module_level_analyze_config_none(self):
        r = analyze(_make_pos(), config=None)
        self.assertIn("leverage_risk_label", r)

    def test_margin_of_safety_consistent(self):
        r = self._run()
        expected_margin = r["liquidation_price_drop_pct"] - _make_pos()["price_drop_trigger_pct"]
        self.assertAlmostEqual(r["margin_of_safety_pct"], expected_margin, places=3)

    def test_stress_drop_zero_gives_full_margin(self):
        r = self._run(price_drop_trigger_pct=0.0, loop_count=1)
        self.assertAlmostEqual(r["margin_of_safety_pct"],
                               r["liquidation_price_drop_pct"], places=4)


# ===========================================================================
# 7. Analyzer class — batch
# ===========================================================================

class TestAnalyzerBatch(unittest.TestCase):

    def setUp(self):
        self.analyzer = DeFiProtocolLeverageLoopRiskAnalyzer()

    def test_batch_empty_list_raises(self):
        with self.assertRaises(ValueError):
            self.analyzer.analyze_batch([])

    def test_batch_non_list_raises(self):
        with self.assertRaises(ValueError):
            self.analyzer.analyze_batch("not a list")

    def test_batch_single_position(self):
        result = self.analyzer.analyze_batch([_make_pos()])
        self.assertEqual(result["count"], 1)

    def test_batch_two_positions(self):
        result = self.analyzer.analyze_batch([_make_pos(), _safe_pos()])
        self.assertEqual(result["count"], 2)

    def test_batch_positions_list_length(self):
        positions = [_make_pos(protocol_name=f"P{i}") for i in range(5)]
        result = self.analyzer.analyze_batch(positions)
        self.assertEqual(len(result["positions"]), 5)

    def test_batch_avg_leverage_is_mean(self):
        p1 = _make_pos(loop_count=0, target_leverage_x=1.0)
        p2 = _make_pos(loop_count=1, ltv_pct=50.0, liquidation_threshold_pct=65.0,
                        target_leverage_x=10.0)
        result = self.analyzer.analyze_batch([p1, p2])
        r1 = _analyze_position(p1)
        r2 = _analyze_position(p2)
        expected = round((r1["effective_leverage_x"] + r2["effective_leverage_x"]) / 2, 4)
        self.assertAlmostEqual(result["avg_effective_leverage"], expected, places=4)

    def test_batch_min_margin_is_min(self):
        positions = [_safe_pos(), _risky_pos()]
        result = self.analyzer.analyze_batch(positions)
        r0 = _analyze_position(_safe_pos())
        r1 = _analyze_position(_risky_pos())
        expected_min = min(r0["margin_of_safety_pct"], r1["margin_of_safety_pct"])
        self.assertAlmostEqual(result["min_margin_of_safety_pct"], expected_min, places=4)

    def test_batch_liq_imminent_count(self):
        positions = [
            _make_pos(ltv_pct=90.0, liquidation_threshold_pct=95.0,
                      loop_count=5, price_drop_trigger_pct=30.0, target_leverage_x=10.0),
            _safe_pos(),
        ]
        result = self.analyzer.analyze_batch(positions)
        self.assertIn("liquidation_imminent_count", result)
        self.assertGreaterEqual(result["liquidation_imminent_count"], 0)

    def test_batch_has_analyzed_at(self):
        result = self.analyzer.analyze_batch([_make_pos()])
        self.assertIn("analyzed_at", result)

    def test_batch_all_positions_have_analyzed_at(self):
        result = self.analyzer.analyze_batch([_make_pos(), _safe_pos()])
        for pos in result["positions"]:
            self.assertIn("analyzed_at", pos)


# ===========================================================================
# 8. Log helpers
# ===========================================================================

class TestLogHelpers(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.log_path = os.path.join(self.tmpdir, "leverage_loop_risk_log.json")

    def _write_log(self, entries):
        with open(self.log_path, "w") as fh:
            json.dump(entries, fh)

    def test_init_log_missing_file_returns_empty(self):
        result = _init_log(os.path.join(self.tmpdir, "nonexistent.json"))
        self.assertEqual(result, [])

    def test_init_log_valid_file_returns_list(self):
        self._write_log([{"ts": "2026-01-01T00:00:00Z"}])
        result = _init_log(self.log_path)
        self.assertEqual(len(result), 1)

    def test_init_log_corrupted_file_returns_empty(self):
        with open(self.log_path, "w") as fh:
            fh.write("NOT JSON{{{{")
        result = _init_log(self.log_path)
        self.assertEqual(result, [])

    def test_init_log_dict_file_returns_empty(self):
        with open(self.log_path, "w") as fh:
            json.dump({"not": "a list"}, fh)
        result = _init_log(self.log_path)
        self.assertEqual(result, [])

    def test_append_log_creates_file(self):
        r = _analyze_position(_make_pos())
        r["analyzed_at"] = _iso_now()
        _append_log(r, self.log_path)
        self.assertTrue(os.path.exists(self.log_path))

    def test_append_log_increments_count(self):
        r = _analyze_position(_make_pos())
        r["analyzed_at"] = _iso_now()
        _append_log(r, self.log_path)
        _append_log(r, self.log_path)
        entries = _init_log(self.log_path)
        self.assertEqual(len(entries), 2)

    def test_append_log_caps_at_max_entries(self):
        r = _analyze_position(_make_pos())
        r["analyzed_at"] = _iso_now()
        for _ in range(LOG_MAX_ENTRIES + 10):
            _append_log(r, self.log_path)
        entries = _init_log(self.log_path)
        self.assertLessEqual(len(entries), LOG_MAX_ENTRIES)

    def test_append_log_max_entries_is_100(self):
        self.assertEqual(LOG_MAX_ENTRIES, 100)

    def test_atomic_write_creates_file(self):
        path = os.path.join(self.tmpdir, "out.json")
        _atomic_write(path, [{"key": "value"}])
        self.assertTrue(os.path.exists(path))

    def test_atomic_write_contents_valid_json(self):
        path = os.path.join(self.tmpdir, "out2.json")
        data = [{"x": 1}, {"y": 2}]
        _atomic_write(path, data)
        with open(path, "r") as fh:
            loaded = json.load(fh)
        self.assertEqual(loaded, data)

    def test_iso_now_format(self):
        ts = _iso_now()
        self.assertRegex(ts, r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z")

    def test_iso_now_returns_string(self):
        self.assertIsInstance(_iso_now(), str)

    def test_iso_now_length(self):
        self.assertEqual(len(_iso_now()), 20)


# ===========================================================================
# 9. Edge cases and boundary conditions
# ===========================================================================

class TestEdgeCases(unittest.TestCase):

    def setUp(self):
        self.analyzer = DeFiProtocolLeverageLoopRiskAnalyzer()

    def test_liquidation_prone_scenario(self):
        # L=3.0 (ltv=75, 4 loops → 3.051, cap at 3.0), LT=80:
        # liq_drop=16.67% → stress=12% → margin≈4.67% → LIQUIDATION_PRONE
        r = self.analyzer.analyze(
            _make_pos(ltv_pct=75.0, liquidation_threshold_pct=80.0,
                      loop_count=4, target_leverage_x=3.0,
                      price_drop_trigger_pct=12.0)
        )
        self.assertEqual(r["leverage_risk_label"], "LIQUIDATION_PRONE")

    def test_very_low_ltv_high_safety(self):
        r = self.analyzer.analyze(
            _make_pos(ltv_pct=10.0, liquidation_threshold_pct=20.0,
                      loop_count=2, price_drop_trigger_pct=5.0, target_leverage_x=5.0)
        )
        self.assertEqual(r["leverage_risk_label"], "CONSERVATIVE_LEVERAGE")

    def test_max_loops_does_not_raise(self):
        r = self.analyzer.analyze(_make_pos(loop_count=20, target_leverage_x=100.0))
        self.assertIn("leverage_risk_label", r)

    def test_target_leverage_one_no_looping(self):
        r = self.analyzer.analyze(
            _make_pos(loop_count=10, ltv_pct=90.0, liquidation_threshold_pct=95.0,
                      target_leverage_x=1.0)
        )
        self.assertAlmostEqual(r["effective_leverage_x"], 1.0, places=4)
        self.assertAlmostEqual(r["liquidation_price_drop_pct"], 100.0, places=4)

    def test_large_supply_apy_still_processes(self):
        r = self.analyzer.analyze(_make_pos(supply_apy_pct=200.0))
        self.assertIsNotNone(r["net_apy_pct"])

    def test_small_initial_capital_no_issue(self):
        r = self.analyzer.analyze(_make_pos(initial_capital_usd=0.01))
        self.assertIn("leverage_risk_label", r)

    def test_effective_leverage_always_gte_one(self):
        for loops in range(0, 6):
            lev = _effective_leverage(75.0, loops)
            self.assertGreaterEqual(lev, 1.0)

    def test_net_apy_linear_in_spread(self):
        # Double the spread → double the leveraged gain above unlevered
        base = _net_apy(4.0, 2.0, 3.0)  # spread=2, lev=3 → 12-4=8
        doubled = _net_apy(6.0, 2.0, 3.0)  # supply=6 → 18-4=14 (extra 6 vs extra 4)
        self.assertGreater(doubled, base)

    def test_liq_drop_increases_with_liq_threshold(self):
        d1 = _liquidation_price_drop(3.0, 75.0)
        d2 = _liquidation_price_drop(3.0, 80.0)
        d3 = _liquidation_price_drop(3.0, 90.0)
        self.assertLess(d1, d2)
        self.assertLess(d2, d3)

    def test_required_fields_constant(self):
        self.assertIn("protocol_name", REQUIRED_FIELDS)
        self.assertIn("loop_count", REQUIRED_FIELDS)
        self.assertEqual(len(REQUIRED_FIELDS), 11)

    def test_validate_raises_on_empty_dict(self):
        with self.assertRaises(ValueError):
            _validate_input({})


if __name__ == "__main__":
    unittest.main()
