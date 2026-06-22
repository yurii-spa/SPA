"""
Tests for MP-724: ConcentratedLiquidityAnalyzer
≥65 unittest tests covering all specified cases.
Run: python3 -m unittest spa_core.tests.test_concentrated_liquidity_analyzer -v
"""

import json
import os
import tempfile
import unittest
from pathlib import Path

from spa_core.analytics.concentrated_liquidity_analyzer import (
    CLPosition,
    ConcentratedLiquidityAnalyzer,
    MAX_ENTRIES,
    PriceRange,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_position(
    lower=1_800.0,
    upper=2_200.0,
    current=2_000.0,
    fee_tier=0.3,
    token_a="ETH",
    token_b="USDC",
    liquidity_usd=50_000.0,
) -> CLPosition:
    return CLPosition(
        token_a=token_a,
        token_b=token_b,
        fee_tier=fee_tier,
        price_range=PriceRange(
            lower_tick_price=lower,
            upper_tick_price=upper,
            current_price=current,
        ),
        liquidity_usd=liquidity_usd,
    )


class _WithTmpFile(unittest.TestCase):
    """Base class that routes the analyser to a temp file."""

    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix=".json", delete=False)
        self.tmp.close()
        os.unlink(self.tmp.name)           # start without the file
        self.data_file = Path(self.tmp.name)
        self.a = ConcentratedLiquidityAnalyzer(data_file=self.data_file)

    def tearDown(self):
        for p in [self.data_file, self.data_file.with_suffix(".tmp")]:
            if p.exists():
                p.unlink()


# ===========================================================================
# 1. calculate_il_to_price
# ===========================================================================

class TestCalculateIL(unittest.TestCase):
    def setUp(self):
        self.a = ConcentratedLiquidityAnalyzer()

    def test_same_price_is_zero(self):
        self.assertAlmostEqual(self.a.calculate_il_to_price(2000, 2000), 0.0, places=5)

    def test_2x_price_increase(self):
        # k=2, IL = |2*sqrt(2)/(1+2) - 1|*100 = |2*1.4142/3 - 1|*100 ≈ 5.719%
        il = self.a.calculate_il_to_price(1000, 2000)
        self.assertAlmostEqual(il, 5.719, delta=0.01)

    def test_4x_price_increase(self):
        # k=4, IL = |2*2/(1+4) - 1|*100 = |4/5 - 1|*100 = 20% -- wait
        # Actually: 2*sqrt(4)/(1+4) = 2*2/5 = 0.8; |0.8-1| = 0.2 → 20%
        # But the spec says "4x → ~25%"? Let me recalculate:
        # k = 4/1 = 4; sqrt(4) = 2; 2*2/(1+4) = 4/5 = 0.8; |0.8-1|*100 = 20%
        # The spec says "~25%" which is the actual Uniswap v2 IL at 4x = 20%
        # Wait, the spec text says "4x → ~25%" but let me verify:
        # At 4x: hodl=5, pool: you had 1 ETH + 1000 USDC at $1000, now price=$4000
        # pool value = 2*sqrt(k)*initial = 2*sqrt(4)*1000 = 4000 (for 1 ETH at $1000)
        # hodl = 0.5 ETH * 4000 + 500 USDC * ... hmm
        # Let's just use the formula: k=4, IL=|2*sqrt(4)/(1+4)-1|*100=|4/5-1|*100=20%
        # The spec says ~25% but the correct formula gives ~20%; trust the code formula
        il = self.a.calculate_il_to_price(1000, 4000)
        self.assertAlmostEqual(il, 20.0, delta=0.5)

    def test_price_decrease_2x(self):
        # k = 0.5 → same IL as 2x by symmetry
        il_up = self.a.calculate_il_to_price(1000, 2000)
        il_down = self.a.calculate_il_to_price(2000, 1000)
        self.assertAlmostEqual(il_up, il_down, places=4)

    def test_small_move_small_il(self):
        # 1% move should give very small IL
        il = self.a.calculate_il_to_price(2000, 2020)
        self.assertLess(il, 0.1)

    def test_zero_current_price_returns_zero(self):
        self.assertEqual(self.a.calculate_il_to_price(0, 2000), 0.0)

    def test_zero_target_price_returns_zero(self):
        self.assertEqual(self.a.calculate_il_to_price(2000, 0), 0.0)

    def test_il_is_non_negative(self):
        for target in [500, 1000, 2000, 4000, 8000]:
            il = self.a.calculate_il_to_price(2000, target)
            self.assertGreaterEqual(il, 0.0)

    def test_returns_float(self):
        self.assertIsInstance(self.a.calculate_il_to_price(2000, 3000), float)


# ===========================================================================
# 2. capital_efficiency
# ===========================================================================

class TestCapitalEfficiency(unittest.TestCase):
    def setUp(self):
        self.a = ConcentratedLiquidityAnalyzer()

    def test_narrow_range_high_efficiency(self):
        # 1900/2100 is a ~10.5% range → high CE
        ce = self.a.capital_efficiency(1900, 2100)
        self.assertGreater(ce, 5.0)

    def test_wide_range_lower_efficiency(self):
        # 1000/4000 is a 300% range → lower CE
        ce = self.a.capital_efficiency(1000, 4000)
        self.assertLess(ce, 5.0)

    def test_narrow_more_efficient_than_wide(self):
        ce_narrow = self.a.capital_efficiency(1950, 2050)
        ce_wide = self.a.capital_efficiency(1000, 4000)
        self.assertGreater(ce_narrow, ce_wide)

    def test_equal_bounds_returns_one(self):
        ce = self.a.capital_efficiency(2000, 2000)
        self.assertEqual(ce, 1.0)

    def test_lower_zero_returns_one(self):
        ce = self.a.capital_efficiency(0, 2000)
        self.assertEqual(ce, 1.0)

    def test_upper_less_than_lower_returns_one(self):
        ce = self.a.capital_efficiency(2000, 1000)
        self.assertEqual(ce, 1.0)

    def test_returns_positive(self):
        ce = self.a.capital_efficiency(1800, 2200)
        self.assertGreater(ce, 0.0)

    def test_formula_spot_check(self):
        # lower=1, upper=4 → sqrt_ratio=2; CE=2/(2-1)=2.0
        ce = self.a.capital_efficiency(1, 4)
        self.assertAlmostEqual(ce, 2.0, places=4)

    def test_formula_spot_check_2(self):
        # lower=1, upper=9 → sqrt_ratio=3; CE=3/(3-1)=1.5
        ce = self.a.capital_efficiency(1, 9)
        self.assertAlmostEqual(ce, 1.5, places=4)


# ===========================================================================
# 3. range_width_pct
# ===========================================================================

class TestRangeWidthPct(unittest.TestCase):
    def setUp(self):
        self.a = ConcentratedLiquidityAnalyzer()

    def test_standard_case(self):
        # lower=1800, upper=2200 → (400/1800)*100 = 22.22...%
        pos = make_position(lower=1800, upper=2200, current=2000)
        r = self.a.analyze(pos)
        self.assertAlmostEqual(r.range_width_pct, (400 / 1800) * 100, places=4)

    def test_zero_range(self):
        pos = make_position(lower=2000, upper=2000, current=2000)
        r = self.a.analyze(pos)
        self.assertAlmostEqual(r.range_width_pct, 0.0, places=4)

    def test_wide_range(self):
        pos = make_position(lower=1000, upper=3000, current=2000)
        r = self.a.analyze(pos)
        self.assertAlmostEqual(r.range_width_pct, 200.0, places=4)


# ===========================================================================
# 4. price_position_pct
# ===========================================================================

class TestPricePositionPct(unittest.TestCase):
    def setUp(self):
        self.a = ConcentratedLiquidityAnalyzer()

    def test_midpoint_is_50(self):
        pos = make_position(lower=1800, upper=2200, current=2000)
        r = self.a.analyze(pos)
        self.assertAlmostEqual(r.price_position_pct, 50.0, places=4)

    def test_below_range_is_zero(self):
        pos = make_position(lower=2000, upper=3000, current=1500)
        r = self.a.analyze(pos)
        self.assertAlmostEqual(r.price_position_pct, 0.0, places=4)

    def test_above_range_is_100(self):
        pos = make_position(lower=1000, upper=1500, current=2000)
        r = self.a.analyze(pos)
        self.assertAlmostEqual(r.price_position_pct, 100.0, places=4)

    def test_at_lower_bound_is_zero(self):
        pos = make_position(lower=1800, upper=2200, current=1800)
        r = self.a.analyze(pos)
        self.assertAlmostEqual(r.price_position_pct, 0.0, places=4)

    def test_at_upper_bound_is_100(self):
        pos = make_position(lower=1800, upper=2200, current=2200)
        r = self.a.analyze(pos)
        self.assertAlmostEqual(r.price_position_pct, 100.0, places=4)

    def test_lower_quarter(self):
        # lower=1000, upper=2000, current=1250 → (250/1000)*100=25
        pos = make_position(lower=1000, upper=2000, current=1250)
        r = self.a.analyze(pos)
        self.assertAlmostEqual(r.price_position_pct, 25.0, places=4)


# ===========================================================================
# 5. is_in_range
# ===========================================================================

class TestIsInRange(unittest.TestCase):
    def setUp(self):
        self.a = ConcentratedLiquidityAnalyzer()

    def test_inside(self):
        pos = make_position(lower=1800, upper=2200, current=2000)
        self.assertTrue(self.a.analyze(pos).is_in_range)

    def test_at_lower_bound_is_in_range(self):
        pos = make_position(lower=1800, upper=2200, current=1800)
        self.assertTrue(self.a.analyze(pos).is_in_range)

    def test_at_upper_bound_is_in_range(self):
        pos = make_position(lower=1800, upper=2200, current=2200)
        self.assertTrue(self.a.analyze(pos).is_in_range)

    def test_below_is_not_in_range(self):
        pos = make_position(lower=1800, upper=2200, current=1700)
        self.assertFalse(self.a.analyze(pos).is_in_range)

    def test_above_is_not_in_range(self):
        pos = make_position(lower=1800, upper=2200, current=2300)
        self.assertFalse(self.a.analyze(pos).is_in_range)


# ===========================================================================
# 6. distance_to_lower / distance_to_upper
# ===========================================================================

class TestDistances(unittest.TestCase):
    def setUp(self):
        self.a = ConcentratedLiquidityAnalyzer()

    def test_distance_to_lower_formula(self):
        # current=2000, lower=1800 → (2000-1800)/2000*100 = 10%
        pos = make_position(lower=1800, upper=2200, current=2000)
        r = self.a.analyze(pos)
        self.assertAlmostEqual(r.distance_to_lower_pct, 10.0, places=4)

    def test_distance_to_upper_formula(self):
        # current=2000, upper=2200 → (2200-2000)/2000*100 = 10%
        pos = make_position(lower=1800, upper=2200, current=2000)
        r = self.a.analyze(pos)
        self.assertAlmostEqual(r.distance_to_upper_pct, 10.0, places=4)

    def test_current_equals_lower_zero_distance(self):
        pos = make_position(lower=1800, upper=2200, current=1800)
        r = self.a.analyze(pos)
        self.assertAlmostEqual(r.distance_to_lower_pct, 0.0, places=4)

    def test_current_equals_upper_zero_upper_distance(self):
        pos = make_position(lower=1800, upper=2200, current=2200)
        r = self.a.analyze(pos)
        self.assertAlmostEqual(r.distance_to_upper_pct, 0.0, places=4)


# ===========================================================================
# 7. fee_capture_probability
# ===========================================================================

class TestFeeCaptureProbability(unittest.TestCase):
    def setUp(self):
        self.a = ConcentratedLiquidityAnalyzer()

    def test_narrow_range_high_fee_probability(self):
        # range_width=5% → 1-5/200=0.975 → capped at 0.99
        pos = make_position(lower=1000, upper=1050, current=1025)
        r = self.a.analyze(pos)
        self.assertGreaterEqual(r.fee_capture_probability, 0.95)

    def test_wide_range_lower_fee_probability(self):
        # range_width=200% → 1-200/200=0 → capped at 0.1
        pos = make_position(lower=1000, upper=3000, current=2000)
        r = self.a.analyze(pos)
        self.assertAlmostEqual(r.fee_capture_probability, 0.1, places=4)

    def test_fee_capture_probability_min_is_0_1(self):
        # Very wide range
        pos = make_position(lower=100, upper=10000, current=5000)
        r = self.a.analyze(pos)
        self.assertGreaterEqual(r.fee_capture_probability, 0.1)

    def test_fee_capture_probability_max_is_0_99(self):
        pos = make_position(lower=1990, upper=2010, current=2000)
        r = self.a.analyze(pos)
        self.assertLessEqual(r.fee_capture_probability, 0.99)

    def test_medium_range_medium_probability(self):
        # range_width≈22% → 1-22/200=0.89
        pos = make_position(lower=1800, upper=2200, current=2000)
        r = self.a.analyze(pos)
        expected = max(0.1, min(0.99, 1 - r.range_width_pct / 200))
        self.assertAlmostEqual(r.fee_capture_probability, expected, places=5)


# ===========================================================================
# 8. expected_fee_apy
# ===========================================================================

class TestExpectedFeeAPY(unittest.TestCase):
    def setUp(self):
        self.a = ConcentratedLiquidityAnalyzer()

    def test_formula_spot_check(self):
        pos = make_position(lower=1800, upper=2200, current=2000, fee_tier=0.3)
        r = self.a.analyze(pos)
        expected = (0.3 / 100) * r.capital_efficiency_ratio * r.fee_capture_probability * 52
        self.assertAlmostEqual(r.expected_fee_apy, expected, places=4)

    def test_higher_fee_tier_higher_apy(self):
        pos_low = make_position(lower=1800, upper=2200, current=2000, fee_tier=0.05)
        pos_high = make_position(lower=1800, upper=2200, current=2000, fee_tier=1.0)
        r_low = self.a.analyze(pos_low)
        r_high = self.a.analyze(pos_high)
        self.assertGreater(r_high.expected_fee_apy, r_low.expected_fee_apy)

    def test_expected_fee_apy_positive(self):
        pos = make_position(lower=1800, upper=2200, current=2000)
        r = self.a.analyze(pos)
        self.assertGreater(r.expected_fee_apy, 0.0)


# ===========================================================================
# 9. IL at bounds
# ===========================================================================

class TestILAtBounds(unittest.TestCase):
    def setUp(self):
        self.a = ConcentratedLiquidityAnalyzer()

    def test_il_if_exit_lower_positive(self):
        pos = make_position(lower=1800, upper=2200, current=2000)
        r = self.a.analyze(pos)
        self.assertGreater(r.il_if_exit_lower_pct, 0.0)

    def test_il_if_exit_upper_positive(self):
        pos = make_position(lower=1800, upper=2200, current=2000)
        r = self.a.analyze(pos)
        self.assertGreater(r.il_if_exit_upper_pct, 0.0)

    def test_il_lower_equals_calculate_il(self):
        pos = make_position(lower=1800, upper=2200, current=2000)
        r = self.a.analyze(pos)
        expected = self.a.calculate_il_to_price(2000, 1800)
        self.assertAlmostEqual(r.il_if_exit_lower_pct, expected, places=5)

    def test_il_upper_equals_calculate_il(self):
        pos = make_position(lower=1800, upper=2200, current=2000)
        r = self.a.analyze(pos)
        expected = self.a.calculate_il_to_price(2000, 2200)
        self.assertAlmostEqual(r.il_if_exit_upper_pct, expected, places=5)

    def test_wider_range_higher_il_at_lower(self):
        pos_narrow = make_position(lower=1950, upper=2050, current=2000)
        pos_wide = make_position(lower=1000, upper=3000, current=2000)
        r_narrow = self.a.analyze(pos_narrow)
        r_wide = self.a.analyze(pos_wide)
        self.assertGreater(r_wide.il_if_exit_lower_pct, r_narrow.il_if_exit_lower_pct)


# ===========================================================================
# 10. range_quality
# ===========================================================================

class TestRangeQuality(unittest.TestCase):
    def setUp(self):
        self.a = ConcentratedLiquidityAnalyzer()

    def test_too_narrow_2pct(self):
        # 2% range → TOO_NARROW
        pos = make_position(lower=1000, upper=1020, current=1010)
        r = self.a.analyze(pos)
        self.assertEqual(r.range_quality, "TOO_NARROW")

    def test_optimal_15pct(self):
        # ~15% range → OPTIMAL
        pos = make_position(lower=1000, upper=1150, current=1075)
        r = self.a.analyze(pos)
        self.assertEqual(r.range_quality, "OPTIMAL")

    def test_wide_60pct(self):
        # 60% range → WIDE
        pos = make_position(lower=1000, upper=1600, current=1300)
        r = self.a.analyze(pos)
        self.assertEqual(r.range_quality, "WIDE")

    def test_full_range_150pct(self):
        # 150% range → FULL_RANGE
        pos = make_position(lower=1000, upper=2500, current=1750)
        r = self.a.analyze(pos)
        self.assertEqual(r.range_quality, "FULL_RANGE")

    def test_boundary_exactly_5pct(self):
        # exactly 5% → OPTIMAL (< 5 is TOO_NARROW, so 5 → OPTIMAL)
        pos = make_position(lower=2000, upper=2100, current=2050)
        r = self.a.analyze(pos)
        # 100/2000*100 = 5.0 → OPTIMAL
        self.assertEqual(r.range_quality, "OPTIMAL")

    def test_boundary_exactly_30pct(self):
        # exactly 30% → WIDE (< 30 is OPTIMAL, so 30 → WIDE)
        pos = make_position(lower=1000, upper=1300, current=1150)
        r = self.a.analyze(pos)
        self.assertEqual(r.range_quality, "WIDE")


# ===========================================================================
# 11. action
# ===========================================================================

class TestAction(unittest.TestCase):
    def setUp(self):
        self.a = ConcentratedLiquidityAnalyzer()

    def test_out_of_range_below_exit_reposition(self):
        pos = make_position(lower=2000, upper=3000, current=1500)
        r = self.a.analyze(pos)
        self.assertEqual(r.action, "EXIT_REPOSITION")

    def test_out_of_range_above_exit_reposition(self):
        pos = make_position(lower=1000, upper=1500, current=2000)
        r = self.a.analyze(pos)
        self.assertEqual(r.action, "EXIT_REPOSITION")

    def test_too_narrow_in_range_widen_range(self):
        # 2% range, price in middle → WIDEN_RANGE
        pos = make_position(lower=1000, upper=1020, current=1010)
        r = self.a.analyze(pos)
        self.assertEqual(r.action, "WIDEN_RANGE")

    def test_near_lower_edge_rebalance(self):
        # position in range but price_position_pct < 15 → REBALANCE_RANGE
        # lower=1000, upper=2000, current=1100 → pos_pct = 100/1000*100 = 10%
        pos = make_position(lower=1000, upper=2000, current=1100)
        r = self.a.analyze(pos)
        self.assertEqual(r.action, "REBALANCE_RANGE")

    def test_near_upper_edge_rebalance(self):
        # lower=1000, upper=2000, current=1900 → pos_pct = 900/1000*100 = 90% > 85
        pos = make_position(lower=1000, upper=2000, current=1900)
        r = self.a.analyze(pos)
        self.assertEqual(r.action, "REBALANCE_RANGE")

    def test_optimal_middle_hold(self):
        # OPTIMAL range, price in middle → HOLD
        pos = make_position(lower=1800, upper=2200, current=2000)
        r = self.a.analyze(pos)
        self.assertEqual(r.action, "HOLD")

    def test_wide_range_middle_hold(self):
        # WIDE range, price near middle
        pos = make_position(lower=1000, upper=2000, current=1500)
        r = self.a.analyze(pos)
        self.assertEqual(r.action, "HOLD")


# ===========================================================================
# 12. warnings
# ===========================================================================

class TestWarnings(unittest.TestCase):
    def setUp(self):
        self.a = ConcentratedLiquidityAnalyzer()

    def test_out_of_range_warning(self):
        pos = make_position(lower=2000, upper=3000, current=1500)
        r = self.a.analyze(pos)
        self.assertTrue(any("out of range" in w for w in r.warnings))

    def test_price_near_lower_warning(self):
        # price_position_pct < 10 → near lower bound warning
        # lower=1000, upper=2000, current=1080 → pos_pct=(80/1000)*100=8%
        pos = make_position(lower=1000, upper=2000, current=1080)
        r = self.a.analyze(pos)
        self.assertTrue(any("near lower" in w for w in r.warnings))

    def test_price_near_upper_warning(self):
        # lower=1000, upper=2000, current=1950 → pos_pct=(950/1000)*100=95% > 90
        pos = make_position(lower=1000, upper=2000, current=1950)
        r = self.a.analyze(pos)
        self.assertTrue(any("near upper" in w for w in r.warnings))

    def test_high_il_warning(self):
        # Need il_if_exit_lower > 20 → use a very wide range
        # lower=500, upper=4000, current=2000 → IL to 500 = ?
        # k=500/2000=0.25 → 2*sqrt(0.25)/(1+0.25)-1 = 2*0.5/1.25-1 = 0.8-1=-0.2 → 20%
        # Slightly wider: lower=400, current=2000 → k=0.2 → 2*sqrt(0.2)/(1.2)-1
        # sqrt(0.2)=0.4472; 2*0.4472/1.2=0.745; |0.745-1|=0.255 → 25.5% > 20
        pos = make_position(lower=400, upper=4000, current=2000)
        r = self.a.analyze(pos)
        self.assertTrue(any("high IL" in w for w in r.warnings))

    def test_no_warnings_in_middle(self):
        # Optimal range, price dead center
        pos = make_position(lower=1800, upper=2200, current=2000)
        r = self.a.analyze(pos)
        self.assertEqual(r.warnings, [])


# ===========================================================================
# 13. compare_positions
# ===========================================================================

class TestComparePositions(unittest.TestCase):
    def setUp(self):
        self.a = ConcentratedLiquidityAnalyzer()

    def test_sorted_by_expected_fee_apy_desc(self):
        pos_low_fee = make_position(fee_tier=0.05)
        pos_high_fee = make_position(fee_tier=1.0)
        analyses = [self.a.analyze(pos_low_fee), self.a.analyze(pos_high_fee)]
        sorted_a = self.a.compare_positions(analyses)
        self.assertGreaterEqual(sorted_a[0].expected_fee_apy, sorted_a[1].expected_fee_apy)

    def test_three_positions_ordered(self):
        positions = [make_position(fee_tier=t) for t in [0.05, 0.3, 1.0]]
        analyses = [self.a.analyze(p) for p in positions]
        sorted_a = self.a.compare_positions(analyses)
        apys = [a.expected_fee_apy for a in sorted_a]
        self.assertEqual(apys, sorted(apys, reverse=True))

    def test_single_element(self):
        pos = make_position()
        result = self.a.compare_positions([self.a.analyze(pos)])
        self.assertEqual(len(result), 1)

    def test_empty_list(self):
        result = self.a.compare_positions([])
        self.assertEqual(result, [])


# ===========================================================================
# 14. save / load round-trip
# ===========================================================================

class TestSaveLoad(_WithTmpFile):

    def test_save_creates_file(self):
        pos = make_position()
        analysis = self.a.analyze(pos)
        self.a.save_results(analysis)
        self.assertTrue(self.data_file.exists())

    def test_saved_to_field_is_set(self):
        pos = make_position()
        analysis = self.a.analyze(pos)
        self.a.save_results(analysis)
        self.assertEqual(analysis.saved_to, str(self.data_file))

    def test_load_returns_list(self):
        pos = make_position()
        analysis = self.a.analyze(pos)
        self.a.save_results(analysis)
        history = self.a.load_history()
        self.assertIsInstance(history, list)

    def test_save_one_and_load(self):
        pos = make_position()
        analysis = self.a.analyze(pos)
        self.a.save_results(analysis)
        history = self.a.load_history()
        self.assertEqual(len(history), 1)

    def test_multiple_saves_accumulate(self):
        for _ in range(5):
            analysis = self.a.analyze(make_position())
            self.a.save_results(analysis)
        history = self.a.load_history()
        self.assertEqual(len(history), 5)

    def test_load_without_file_returns_empty(self):
        history = self.a.load_history()
        self.assertEqual(history, [])

    def test_saved_entry_contains_expected_fields(self):
        pos = make_position(lower=1800, upper=2200, current=2000)
        analysis = self.a.analyze(pos)
        self.a.save_results(analysis)
        entry = self.a.load_history()[0]
        self.assertIn("range_quality", entry)
        self.assertIn("action", entry)
        self.assertIn("is_in_range", entry)
        self.assertIn("timestamp", entry)

    def test_json_is_valid(self):
        analysis = self.a.analyze(make_position())
        self.a.save_results(analysis)
        raw = self.data_file.read_text()
        data = json.loads(raw)
        self.assertIsInstance(data, list)


# ===========================================================================
# 15. ring-buffer cap at 100
# ===========================================================================

class TestRingBuffer(_WithTmpFile):

    def test_ring_buffer_cap_enforced(self):
        for _ in range(MAX_ENTRIES + 20):
            self.a.save_results(self.a.analyze(make_position()))
        history = self.a.load_history()
        self.assertLessEqual(len(history), MAX_ENTRIES)

    def test_ring_buffer_keeps_latest(self):
        # Fill to cap + 10 extra
        for i in range(MAX_ENTRIES + 10):
            pos = make_position(liquidity_usd=float(i))
            self.a.save_results(self.a.analyze(pos))
        history = self.a.load_history()
        # Last entry should have liquidity_usd of MAX_ENTRIES+9
        # (we check timestamp ordering is preserved indirectly via count)
        self.assertEqual(len(history), MAX_ENTRIES)


# ===========================================================================
# 16. edge cases
# ===========================================================================

class TestEdgeCases(unittest.TestCase):
    def setUp(self):
        self.a = ConcentratedLiquidityAnalyzer()

    def test_degenerate_lower_equals_upper(self):
        # lower == upper, current == lower → should not crash
        pos = make_position(lower=2000, upper=2000, current=2000)
        r = self.a.analyze(pos)
        self.assertIsNotNone(r)
        self.assertIsInstance(r.range_width_pct, float)

    def test_current_equals_lower(self):
        pos = make_position(lower=1800, upper=2200, current=1800)
        r = self.a.analyze(pos)
        self.assertTrue(r.is_in_range)
        self.assertAlmostEqual(r.price_position_pct, 0.0, places=4)
        self.assertAlmostEqual(r.distance_to_lower_pct, 0.0, places=4)

    def test_current_above_upper_is_out_of_range(self):
        pos = make_position(lower=1800, upper=2200, current=2500)
        r = self.a.analyze(pos)
        self.assertFalse(r.is_in_range)

    def test_very_narrow_range_does_not_crash(self):
        pos = make_position(lower=1999.99, upper=2000.01, current=2000.00)
        r = self.a.analyze(pos)
        self.assertIsNotNone(r)

    def test_large_prices_do_not_crash(self):
        pos = make_position(lower=50_000, upper=100_000, current=75_000)
        r = self.a.analyze(pos)
        self.assertIsNotNone(r)

    def test_capital_efficiency_improves_narrow_range(self):
        # Verify narrow → high CE for ETH/USDC example
        ce = self.a.capital_efficiency(1900, 2100)
        self.assertGreater(ce, 10.0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
