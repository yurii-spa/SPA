"""
Tests for MP-1037: ProtocolDeFiConcentratedLiquidityRangeOptimizer
≥90 unittest tests covering all specified cases.
Run: python3 -m unittest spa_core.tests.test_protocol_defi_concentrated_liquidity_range_optimizer -v
"""

import json
import math
import os
import tempfile
import unittest
from pathlib import Path

from spa_core.analytics.protocol_defi_concentrated_liquidity_range_optimizer import (
    ConcentratedLiquidityInput,
    ConcentratedLiquidityResult,
    ProtocolDeFiConcentratedLiquidityRangeOptimizer,
    MAX_ENTRIES,
    DATA_FILE,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_input(
    current_price=2_000.0,
    lower_tick_price=1_800.0,
    upper_tick_price=2_200.0,
    price_volatility_30d_pct=10.0,
    fee_tier_bps=30,
    daily_volume_usd=1_000_000.0,
    position_size_usd=50_000.0,
) -> ConcentratedLiquidityInput:
    return ConcentratedLiquidityInput(
        current_price=current_price,
        lower_tick_price=lower_tick_price,
        upper_tick_price=upper_tick_price,
        price_volatility_30d_pct=price_volatility_30d_pct,
        fee_tier_bps=fee_tier_bps,
        daily_volume_usd=daily_volume_usd,
        position_size_usd=position_size_usd,
    )


class _WithTmpFile(unittest.TestCase):
    """Base class that routes the optimizer to a temp file."""

    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp()
        self.data_file = Path(self.tmp_dir) / "concentrated_liquidity_range_log.json"
        self.optimizer = ProtocolDeFiConcentratedLiquidityRangeOptimizer(
            data_file=self.data_file
        )


# ===========================================================================
# 1. _is_in_range
# ===========================================================================


class TestIsInRange(_WithTmpFile):

    def test_price_exactly_at_lower(self):
        self.assertTrue(self.optimizer._is_in_range(1_800.0, 1_800.0, 2_200.0))

    def test_price_exactly_at_upper(self):
        self.assertTrue(self.optimizer._is_in_range(2_200.0, 1_800.0, 2_200.0))

    def test_price_midpoint(self):
        self.assertTrue(self.optimizer._is_in_range(2_000.0, 1_800.0, 2_200.0))

    def test_price_below_lower(self):
        self.assertFalse(self.optimizer._is_in_range(1_500.0, 1_800.0, 2_200.0))

    def test_price_above_upper(self):
        self.assertFalse(self.optimizer._is_in_range(2_500.0, 1_800.0, 2_200.0))

    def test_zero_price(self):
        self.assertFalse(self.optimizer._is_in_range(0.0, 1_800.0, 2_200.0))

    def test_degenerate_range_equal_bounds(self):
        self.assertTrue(self.optimizer._is_in_range(1_000.0, 1_000.0, 1_000.0))

    def test_narrow_range(self):
        self.assertTrue(self.optimizer._is_in_range(1_001.0, 1_000.0, 1_002.0))


# ===========================================================================
# 2. _range_utilization_pct
# ===========================================================================


class TestRangeUtilization(_WithTmpFile):

    def test_in_range_wide_low_vol_high_util(self):
        """Wide range (±50%), low vol → utilization near 100%."""
        util = self.optimizer._range_utilization_pct(2_000, 1_000, 4_000, 5.0)
        self.assertGreater(util, 80.0)

    def test_in_range_narrow_high_vol_low_util(self):
        """Narrow range (±1%), high vol → lower utilization."""
        util_wide = self.optimizer._range_utilization_pct(2_000, 1_000, 4_000, 30.0)
        util_narrow = self.optimizer._range_utilization_pct(2_000, 1_980, 2_020, 30.0)
        self.assertLess(util_narrow, util_wide)

    def test_out_of_range_below_gives_low_util(self):
        """Price below lower → near-zero utilization."""
        util = self.optimizer._range_utilization_pct(1_000, 1_800, 2_200, 10.0)
        self.assertLessEqual(util, 5.0)

    def test_out_of_range_above_gives_low_util(self):
        """Price above upper → near-zero utilization."""
        util = self.optimizer._range_utilization_pct(3_000, 1_800, 2_200, 10.0)
        self.assertLessEqual(util, 5.0)

    def test_util_at_most_100(self):
        util = self.optimizer._range_utilization_pct(2_000, 1_000, 4_000, 1.0)
        self.assertLessEqual(util, 100.0)

    def test_util_at_least_0(self):
        util = self.optimizer._range_utilization_pct(0, 1_800, 2_200, 10.0)
        self.assertGreaterEqual(util, 0.0)

    def test_zero_volatility_max_util(self):
        """Zero vol → range always stays in (treated as max)."""
        util = self.optimizer._range_utilization_pct(2_000, 1_800, 2_200, 0.0)
        self.assertGreaterEqual(util, 80.0)

    def test_returns_float(self):
        util = self.optimizer._range_utilization_pct(2_000, 1_800, 2_200, 10.0)
        self.assertIsInstance(util, float)

    def test_wider_range_higher_util(self):
        """Wider range → higher (or equal) utilization for same volatility."""
        util_narrow = self.optimizer._range_utilization_pct(2_000, 1_900, 2_100, 10.0)
        util_wide = self.optimizer._range_utilization_pct(2_000, 1_500, 2_500, 10.0)
        self.assertLessEqual(util_narrow, util_wide)


# ===========================================================================
# 3. _capital_efficiency_multiplier
# ===========================================================================


class TestCapitalEfficiency(_WithTmpFile):

    def test_in_range_greater_than_one(self):
        eff = self.optimizer._capital_efficiency_multiplier(1_800, 2_200, 2_000)
        self.assertGreater(eff, 1.0)

    def test_out_of_range_gives_one(self):
        eff = self.optimizer._capital_efficiency_multiplier(1_800, 2_200, 1_000)
        self.assertAlmostEqual(eff, 1.0, places=4)

    def test_narrow_range_high_efficiency(self):
        """Narrower range → higher capital efficiency."""
        eff_wide = self.optimizer._capital_efficiency_multiplier(1_000, 4_000, 2_000)
        eff_narrow = self.optimizer._capital_efficiency_multiplier(1_900, 2_100, 2_000)
        self.assertGreater(eff_narrow, eff_wide)

    def test_capped_at_500(self):
        """Very tight range → efficiency capped at 500."""
        eff = self.optimizer._capital_efficiency_multiplier(1_999.9, 2_000.1, 2_000)
        self.assertLessEqual(eff, 500.0)

    def test_returns_float(self):
        eff = self.optimizer._capital_efficiency_multiplier(1_800, 2_200, 2_000)
        self.assertIsInstance(eff, float)

    def test_formula_correctness(self):
        """Verify: 1 / (1 - sqrt(lower/upper)) for a known range."""
        lower, upper = 1_600.0, 2_500.0
        expected = 1.0 / (1.0 - math.sqrt(lower / upper))
        eff = self.optimizer._capital_efficiency_multiplier(lower, upper, 2_000)
        self.assertAlmostEqual(eff, round(min(500.0, max(1.0, expected)), 4), places=3)

    def test_symmetric_range(self):
        """Equal-distance range around current price is in-range."""
        eff = self.optimizer._capital_efficiency_multiplier(500, 2_000, 1_000)
        self.assertGreater(eff, 1.0)

    def test_zero_lower_returns_one(self):
        """Edge: lower = 0 → avoid division; return 1.0."""
        eff = self.optimizer._capital_efficiency_multiplier(0, 2_000, 1_000)
        self.assertAlmostEqual(eff, 1.0, places=4)


# ===========================================================================
# 4. _expected_fee_apy_pct
# ===========================================================================


class TestExpectedFeeApy(_WithTmpFile):

    def test_basic_calculation(self):
        """Verify formula: fee_rate * volume_turnover * 365 * util / 100 * 100."""
        fee_apy = self.optimizer._expected_fee_apy_pct(30, 1_000_000, 100_000, 80.0)
        expected = 0.003 * (1_000_000 / 100_000) * 365 * 0.80 * 100
        self.assertAlmostEqual(fee_apy, min(1000.0, round(expected, 4)), places=2)

    def test_zero_volume_gives_zero(self):
        fee_apy = self.optimizer._expected_fee_apy_pct(30, 0, 100_000, 80.0)
        self.assertAlmostEqual(fee_apy, 0.0, places=4)

    def test_zero_position_gives_zero(self):
        fee_apy = self.optimizer._expected_fee_apy_pct(30, 1_000_000, 0, 80.0)
        self.assertAlmostEqual(fee_apy, 0.0, places=4)

    def test_zero_utilization_gives_zero(self):
        fee_apy = self.optimizer._expected_fee_apy_pct(30, 1_000_000, 100_000, 0.0)
        self.assertAlmostEqual(fee_apy, 0.0, places=4)

    def test_capped_at_1000(self):
        """Extreme parameters → capped at 1000%."""
        fee_apy = self.optimizer._expected_fee_apy_pct(10000, 1e12, 1.0, 100.0)
        self.assertAlmostEqual(fee_apy, 1000.0, places=2)

    def test_higher_fee_tier_higher_apy(self):
        apy_low = self.optimizer._expected_fee_apy_pct(5, 1_000_000, 100_000, 80.0)
        apy_high = self.optimizer._expected_fee_apy_pct(100, 1_000_000, 100_000, 80.0)
        self.assertGreater(apy_high, apy_low)

    def test_higher_volume_higher_apy(self):
        apy_low = self.optimizer._expected_fee_apy_pct(30, 100_000, 100_000, 80.0)
        apy_high = self.optimizer._expected_fee_apy_pct(30, 10_000_000, 100_000, 80.0)
        self.assertGreater(apy_high, apy_low)

    def test_returns_float(self):
        fee_apy = self.optimizer._expected_fee_apy_pct(30, 1_000_000, 100_000, 80.0)
        self.assertIsInstance(fee_apy, float)

    def test_result_non_negative(self):
        for util in [0, 25, 50, 100]:
            apy = self.optimizer._expected_fee_apy_pct(30, 1_000_000, 100_000, util)
            self.assertGreaterEqual(apy, 0.0)


# ===========================================================================
# 5. _il_risk_score
# ===========================================================================


class TestIlRiskScore(_WithTmpFile):

    def test_out_of_range_gives_100(self):
        """Price outside range → max IL risk."""
        risk = self.optimizer._il_risk_score(1_000, 1_800, 2_200, 10.0)
        self.assertAlmostEqual(risk, 100.0, places=2)

    def test_wide_range_low_vol_low_risk(self):
        """Very wide range, low vol → low IL risk."""
        risk = self.optimizer._il_risk_score(2_000, 500, 8_000, 5.0)
        self.assertLess(risk, 20.0)

    def test_narrow_range_high_vol_high_risk(self):
        """Narrow range, high vol → high IL risk."""
        risk = self.optimizer._il_risk_score(2_000, 1_990, 2_010, 30.0)
        self.assertGreater(risk, 80.0)

    def test_risk_capped_at_100(self):
        risk = self.optimizer._il_risk_score(2_000, 1_999, 2_001, 50.0)
        self.assertLessEqual(risk, 100.0)

    def test_risk_at_least_0(self):
        risk = self.optimizer._il_risk_score(2_000, 1_000, 4_000, 1.0)
        self.assertGreaterEqual(risk, 0.0)

    def test_zero_current_price_gives_100(self):
        risk = self.optimizer._il_risk_score(0, 1_800, 2_200, 10.0)
        self.assertAlmostEqual(risk, 100.0, places=2)

    def test_returns_float(self):
        risk = self.optimizer._il_risk_score(2_000, 1_800, 2_200, 10.0)
        self.assertIsInstance(risk, float)

    def test_wider_range_lower_risk(self):
        """Wider range → lower IL risk for same vol."""
        risk_narrow = self.optimizer._il_risk_score(2_000, 1_900, 2_100, 10.0)
        risk_wide = self.optimizer._il_risk_score(2_000, 1_000, 4_000, 10.0)
        self.assertGreater(risk_narrow, risk_wide)

    def test_higher_vol_higher_risk(self):
        """Same range, higher vol → higher IL risk."""
        risk_low = self.optimizer._il_risk_score(2_000, 1_500, 2_500, 5.0)
        risk_high = self.optimizer._il_risk_score(2_000, 1_500, 2_500, 50.0)
        self.assertGreater(risk_high, risk_low)


# ===========================================================================
# 6. _composite_score
# ===========================================================================


class TestCompositeScore(_WithTmpFile):

    def test_all_best_gives_100(self):
        """util=100, il_risk=0, fee_apy=100 → composite=100."""
        score = self.optimizer._composite_score(100, 0, 100)
        self.assertAlmostEqual(score, 100.0, places=2)

    def test_all_worst_gives_low(self):
        """util=0, il_risk=100, fee_apy=0 → composite=0."""
        score = self.optimizer._composite_score(0, 100, 0)
        self.assertAlmostEqual(score, 0.0, places=2)

    def test_neutral_gives_40(self):
        """util=50, il_risk=50, fee_apy=0 → 50*0.4 + 50*0.4 + 0 = 40."""
        score = self.optimizer._composite_score(50, 50, 0)
        self.assertAlmostEqual(score, 40.0, places=2)

    def test_fee_apy_capped_at_100_for_composite(self):
        score_200 = self.optimizer._composite_score(80, 20, 200)
        score_100 = self.optimizer._composite_score(80, 20, 100)
        self.assertAlmostEqual(score_200, score_100, places=2)

    def test_score_in_bounds(self):
        for util in [0, 50, 100]:
            for il in [0, 50, 100]:
                for fee in [0, 50, 100, 500]:
                    score = self.optimizer._composite_score(util, il, fee)
                    self.assertGreaterEqual(score, 0.0)
                    self.assertLessEqual(score, 100.0)

    def test_returns_float(self):
        score = self.optimizer._composite_score(70, 30, 50)
        self.assertIsInstance(score, float)

    def test_weights_match_spec(self):
        """Verify util weight 0.40, il_safety weight 0.40, fee weight 0.20."""
        # util only: composite = 100 * 0.4 + 0 + 0 = 40
        score = self.optimizer._composite_score(100, 100, 0)
        self.assertAlmostEqual(score, 40.0, places=2)


# ===========================================================================
# 7. _label
# ===========================================================================


class TestLabel(_WithTmpFile):

    def test_out_of_range_label(self):
        lbl = self.optimizer._label(90, False, 0, 5.0)
        self.assertEqual(lbl, "OUT_OF_RANGE_RISK")

    def test_wide_range_label_low_efficiency(self):
        """Low capital efficiency multiplier → WIDE_RANGE regardless of score."""
        lbl = self.optimizer._label(90, True, 90, 1.2)
        self.assertEqual(lbl, "WIDE_RANGE")

    def test_optimal_range_label(self):
        lbl = self.optimizer._label(80, True, 80, 5.0)
        self.assertEqual(lbl, "OPTIMAL_RANGE")

    def test_efficient_label(self):
        lbl = self.optimizer._label(60, True, 60, 3.0)
        self.assertEqual(lbl, "EFFICIENT")

    def test_suboptimal_label(self):
        lbl = self.optimizer._label(40, True, 40, 3.0)
        self.assertEqual(lbl, "SUBOPTIMAL")

    def test_wide_range_label_low_score(self):
        lbl = self.optimizer._label(20, True, 20, 3.0)
        self.assertEqual(lbl, "WIDE_RANGE")

    def test_valid_labels_always(self):
        valid = {
            "OPTIMAL_RANGE", "EFFICIENT", "SUBOPTIMAL",
            "WIDE_RANGE", "OUT_OF_RANGE_RISK"
        }
        for score in range(0, 101, 10):
            for in_range in [True, False]:
                for eff in [1.0, 2.0, 5.0]:
                    lbl = self.optimizer._label(float(score), in_range, float(score), eff)
                    self.assertIn(lbl, valid)


# ===========================================================================
# 8. Full analyze() integration
# ===========================================================================


class TestAnalyze(_WithTmpFile):

    def test_returns_result_type(self):
        result = self.optimizer.analyze(make_input())
        self.assertIsInstance(result, ConcentratedLiquidityResult)

    def test_in_range_flag_correct(self):
        result = self.optimizer.analyze(make_input())
        self.assertTrue(result.is_in_range)

    def test_out_of_range_flag_correct(self):
        result = self.optimizer.analyze(make_input(current_price=1_000.0))
        self.assertFalse(result.is_in_range)

    def test_out_of_range_label(self):
        result = self.optimizer.analyze(make_input(current_price=500.0))
        self.assertEqual(result.label, "OUT_OF_RANGE_RISK")

    def test_il_risk_100_when_out_of_range(self):
        result = self.optimizer.analyze(make_input(current_price=3_000.0))
        self.assertAlmostEqual(result.il_risk_score, 100.0, places=2)

    def test_efficiency_1_when_out_of_range(self):
        result = self.optimizer.analyze(make_input(current_price=5_000.0))
        self.assertAlmostEqual(result.capital_efficiency_multiplier, 1.0, places=4)

    def test_scores_in_bounds(self):
        result = self.optimizer.analyze(make_input())
        self.assertGreaterEqual(result.range_utilization_pct, 0.0)
        self.assertLessEqual(result.range_utilization_pct, 100.0)
        self.assertGreaterEqual(result.il_risk_score, 0.0)
        self.assertLessEqual(result.il_risk_score, 100.0)
        self.assertGreaterEqual(result.composite_score, 0.0)
        self.assertLessEqual(result.composite_score, 100.0)
        self.assertGreaterEqual(result.expected_fee_apy_pct, 0.0)
        self.assertGreater(result.capital_efficiency_multiplier, 0.0)

    def test_label_is_valid(self):
        result = self.optimizer.analyze(make_input())
        valid = {
            "OPTIMAL_RANGE", "EFFICIENT", "SUBOPTIMAL",
            "WIDE_RANGE", "OUT_OF_RANGE_RISK"
        }
        self.assertIn(result.label, valid)

    def test_inputs_echoed_in_result(self):
        inp = make_input(
            current_price=2_000.0,
            lower_tick_price=1_800.0,
            upper_tick_price=2_200.0,
            price_volatility_30d_pct=15.0,
            fee_tier_bps=100,
            daily_volume_usd=2_000_000.0,
            position_size_usd=25_000.0,
        )
        result = self.optimizer.analyze(inp)
        self.assertAlmostEqual(result.current_price, 2_000.0, places=4)
        self.assertAlmostEqual(result.lower_tick_price, 1_800.0, places=4)
        self.assertAlmostEqual(result.upper_tick_price, 2_200.0, places=4)
        self.assertAlmostEqual(result.price_volatility_30d_pct, 15.0, places=3)
        self.assertEqual(result.fee_tier_bps, 100)
        self.assertAlmostEqual(result.daily_volume_usd, 2_000_000.0, places=1)
        self.assertAlmostEqual(result.position_size_usd, 25_000.0, places=1)

    def test_deterministic(self):
        inp = make_input()
        r1 = self.optimizer.analyze(inp)
        r2 = self.optimizer.analyze(inp)
        self.assertAlmostEqual(r1.composite_score, r2.composite_score, places=5)
        self.assertEqual(r1.label, r2.label)

    def test_narrow_range_higher_efficiency(self):
        """Narrower range → higher capital_efficiency_multiplier."""
        wide = self.optimizer.analyze(make_input(
            lower_tick_price=500, upper_tick_price=8_000
        ))
        narrow = self.optimizer.analyze(make_input(
            lower_tick_price=1_900, upper_tick_price=2_100
        ))
        self.assertGreater(
            narrow.capital_efficiency_multiplier,
            wide.capital_efficiency_multiplier
        )

    def test_higher_fee_tier_higher_fee_apy(self):
        low = self.optimizer.analyze(make_input(fee_tier_bps=5))
        high = self.optimizer.analyze(make_input(fee_tier_bps=100))
        self.assertGreater(high.expected_fee_apy_pct, low.expected_fee_apy_pct)


# ===========================================================================
# 9. Batch analyze
# ===========================================================================


class TestAnalyzeBatch(_WithTmpFile):

    def test_empty_batch_returns_empty(self):
        results = self.optimizer.analyze_batch([])
        self.assertEqual(results, [])

    def test_single_item_batch(self):
        results = self.optimizer.analyze_batch([make_input()])
        self.assertEqual(len(results), 1)

    def test_multi_item_batch_order_preserved(self):
        prices = [1_500.0, 2_000.0, 2_500.0]
        inputs = [make_input(current_price=p) for p in prices]
        results = self.optimizer.analyze_batch(inputs)
        for i, p in enumerate(prices):
            self.assertAlmostEqual(results[i].current_price, p, places=4)

    def test_batch_length_matches(self):
        inputs = [make_input() for _ in range(8)]
        results = self.optimizer.analyze_batch(inputs)
        self.assertEqual(len(results), 8)


# ===========================================================================
# 10. best_range
# ===========================================================================


class TestBestRange(_WithTmpFile):

    def test_best_has_highest_composite(self):
        inputs = [
            make_input(current_price=500),    # out of range
            make_input(current_price=2_000),  # in range
            make_input(current_price=1_900),  # in range
        ]
        results = self.optimizer.analyze_batch(inputs)
        best = self.optimizer.best_range(results)
        max_comp = max(r.composite_score for r in results)
        self.assertAlmostEqual(best.composite_score, max_comp, places=5)

    def test_best_range_raises_on_empty(self):
        with self.assertRaises(ValueError):
            self.optimizer.best_range([])

    def test_single_result_is_best(self):
        result = self.optimizer.analyze(make_input())
        best = self.optimizer.best_range([result])
        self.assertAlmostEqual(best.composite_score, result.composite_score, places=5)


# ===========================================================================
# 11. filter_by_label & filter_in_range
# ===========================================================================


class TestFilters(_WithTmpFile):

    def _batch(self):
        inputs = [
            make_input(current_price=2_000),  # in range
            make_input(current_price=1_000),  # out of range
            make_input(current_price=2_100),  # in range
        ]
        return self.optimizer.analyze_batch(inputs)

    def test_filter_by_label_returns_only_matching(self):
        results = self._batch()
        for lbl in {
            "OPTIMAL_RANGE", "EFFICIENT", "SUBOPTIMAL",
            "WIDE_RANGE", "OUT_OF_RANGE_RISK"
        }:
            filtered = self.optimizer.filter_by_label(results, lbl)
            for r in filtered:
                self.assertEqual(r.label, lbl)

    def test_filter_in_range_returns_in_range(self):
        results = self._batch()
        in_range = self.optimizer.filter_in_range(results)
        for r in in_range:
            self.assertTrue(r.is_in_range)

    def test_filter_in_range_excludes_out_of_range(self):
        results = self._batch()
        in_range = self.optimizer.filter_in_range(results)
        for r in in_range:
            self.assertNotEqual(r.label, "OUT_OF_RANGE_RISK")

    def test_filter_by_nonexistent_label(self):
        results = self._batch()
        filtered = self.optimizer.filter_by_label(results, "FAKE_LABEL")
        self.assertEqual(filtered, [])


# ===========================================================================
# 12. save_results / load_history / ring-buffer
# ===========================================================================


class TestPersistence(_WithTmpFile):

    def test_save_creates_file(self):
        result = self.optimizer.analyze(make_input())
        self.optimizer.save_results([result])
        self.assertTrue(self.data_file.exists())

    def test_saved_file_is_valid_json(self):
        result = self.optimizer.analyze(make_input())
        self.optimizer.save_results([result])
        with open(self.data_file) as f:
            data = json.load(f)
        self.assertIsInstance(data, list)

    def test_load_history_returns_list(self):
        result = self.optimizer.analyze(make_input())
        self.optimizer.save_results([result])
        history = self.optimizer.load_history()
        self.assertIsInstance(history, list)

    def test_load_history_empty_when_no_file(self):
        history = self.optimizer.load_history()
        self.assertEqual(history, [])

    def test_ring_buffer_cap(self):
        result = self.optimizer.analyze(make_input())
        for _ in range(MAX_ENTRIES + 25):
            self.optimizer.save_results([result])
        history = self.optimizer.load_history()
        self.assertLessEqual(len(history), MAX_ENTRIES)

    def test_saved_entry_has_required_fields(self):
        result = self.optimizer.analyze(make_input())
        self.optimizer.save_results([result])
        history = self.optimizer.load_history()
        entry = history[-1]
        self.assertIn("timestamp", entry)
        self.assertIn("range_utilization_pct", entry)
        self.assertIn("expected_fee_apy_pct", entry)
        self.assertIn("il_risk_score", entry)
        self.assertIn("capital_efficiency_multiplier", entry)
        self.assertIn("composite_score", entry)
        self.assertIn("label", entry)
        self.assertIn("is_in_range", entry)

    def test_multiple_saves_accumulate(self):
        r1 = self.optimizer.analyze(make_input(current_price=2_000))
        r2 = self.optimizer.analyze(make_input(current_price=2_100))
        self.optimizer.save_results([r1])
        self.optimizer.save_results([r2])
        history = self.optimizer.load_history()
        self.assertEqual(len(history), 2)

    def test_atomic_write_no_tmp_left(self):
        result = self.optimizer.analyze(make_input())
        self.optimizer.save_results([result])
        tmp = self.data_file.with_suffix(".tmp")
        self.assertFalse(tmp.exists())

    def test_batch_save_appends_all(self):
        results = self.optimizer.analyze_batch([make_input() for _ in range(6)])
        self.optimizer.save_results(results)
        history = self.optimizer.load_history()
        self.assertEqual(len(history), 6)

    def test_saved_entry_has_correct_in_range_value(self):
        result_in = self.optimizer.analyze(make_input(current_price=2_000))
        result_out = self.optimizer.analyze(make_input(current_price=500))
        self.optimizer.save_results([result_in, result_out])
        history = self.optimizer.load_history()
        self.assertTrue(history[0]["is_in_range"])
        self.assertFalse(history[1]["is_in_range"])


# ===========================================================================
# 13. Edge / boundary cases
# ===========================================================================


class TestEdgeCases(_WithTmpFile):

    def test_equal_lower_upper(self):
        """Degenerate range: lower == upper == current."""
        result = self.optimizer.analyze(make_input(
            current_price=2_000, lower_tick_price=2_000, upper_tick_price=2_000
        ))
        self.assertIsInstance(result, ConcentratedLiquidityResult)

    def test_very_small_position_size(self):
        result = self.optimizer.analyze(make_input(position_size_usd=0.01))
        self.assertIsInstance(result, ConcentratedLiquidityResult)

    def test_zero_position_size(self):
        result = self.optimizer.analyze(make_input(position_size_usd=0.0))
        self.assertAlmostEqual(result.expected_fee_apy_pct, 0.0, places=4)

    def test_very_high_volatility(self):
        result = self.optimizer.analyze(make_input(price_volatility_30d_pct=500.0))
        self.assertIsInstance(result, ConcentratedLiquidityResult)
        self.assertGreaterEqual(result.il_risk_score, 0.0)
        self.assertLessEqual(result.il_risk_score, 100.0)

    def test_price_at_lower_boundary(self):
        result = self.optimizer.analyze(make_input(current_price=1_800.0))
        self.assertTrue(result.is_in_range)

    def test_price_at_upper_boundary(self):
        result = self.optimizer.analyze(make_input(current_price=2_200.0))
        self.assertTrue(result.is_in_range)

    def test_very_large_volume(self):
        result = self.optimizer.analyze(make_input(daily_volume_usd=1e12))
        self.assertAlmostEqual(result.expected_fee_apy_pct, 1000.0, places=2)

    def test_1bp_fee_tier(self):
        result = self.optimizer.analyze(make_input(fee_tier_bps=1))
        self.assertGreaterEqual(result.expected_fee_apy_pct, 0.0)

    def test_10000bp_fee_tier(self):
        result = self.optimizer.analyze(make_input(fee_tier_bps=10000))
        self.assertLessEqual(result.expected_fee_apy_pct, 1000.0)

    def test_result_all_fields_present(self):
        result = self.optimizer.analyze(make_input())
        self.assertTrue(hasattr(result, "range_utilization_pct"))
        self.assertTrue(hasattr(result, "expected_fee_apy_pct"))
        self.assertTrue(hasattr(result, "il_risk_score"))
        self.assertTrue(hasattr(result, "capital_efficiency_multiplier"))
        self.assertTrue(hasattr(result, "composite_score"))
        self.assertTrue(hasattr(result, "label"))
        self.assertTrue(hasattr(result, "is_in_range"))


if __name__ == "__main__":
    unittest.main()
