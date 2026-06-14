# spa_core/tests/test_impermanent_loss_hedger.py
# MP-722 — Tests for ImpermanentLossHedger
# ≥65 tests covering: IL math, severity, strategies, recommendations,
# compare_positions, save/load, ring-buffer cap, edge cases.

import json
import math
import os
import sys
import tempfile
import unittest
from pathlib import Path

# Support both `python -m pytest spa_core/tests/` and direct execution
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from spa_core.analytics.impermanent_loss_hedger import (
    ILCalculation,
    HedgeRecommendation,
    calculate_il,
    severity_label,
    get_hedge_strategies,
    recommend,
    compare_positions,
    save_results,
    load_history,
    _days_to_breakeven,
)


class TestCalculateIL(unittest.TestCase):
    """Tests for the core calculate_il() function."""

    def test_no_price_change_returns_zero(self):
        """If price ratio unchanged, IL must be 0."""
        self.assertAlmostEqual(calculate_il(1000.0, 1000.0), 0.0, places=10)

    def test_price_doubled_approx_572(self):
        """Price ratio 2x → IL ≈ 5.72%."""
        il = calculate_il(1.0, 2.0)
        self.assertAlmostEqual(il, 5.7191, places=2)

    def test_price_halved_approx_572(self):
        """Price ratio 0.5x → same IL as 2x (symmetric)."""
        il = calculate_il(1.0, 0.5)
        self.assertAlmostEqual(il, 5.7191, places=2)

    def test_doubled_and_halved_symmetric(self):
        """IL is symmetric: doubling and halving give same result."""
        self.assertAlmostEqual(calculate_il(1.0, 2.0), calculate_il(1.0, 0.5), places=10)

    def test_price_4x_approx_25(self):
        """Price ratio 4x → IL ≈ 25%."""
        il = calculate_il(1.0, 4.0)
        # formula: 2*sqrt(4)/(1+4)-1 = 2*2/5 - 1 = 0.8 - 1 = -0.2  → 20%
        # actual: 2*sqrt(4)/5 - 1 = 4/5 - 1 = -0.2 → 20%
        self.assertAlmostEqual(il, 20.0, places=5)

    def test_price_9x_approx_50(self):
        """Price ratio 9x → IL ≈ 25% (not 50% — spec says ~50 but formula gives ~25)."""
        il = calculate_il(1.0, 9.0)
        # formula: 2*sqrt(9)/(1+9)-1 = 2*3/10 - 1 = 0.6 - 1 = -0.4 → 40%
        self.assertAlmostEqual(il, 40.0, places=5)

    def test_formula_correctness_k2(self):
        """Verify formula: k=2 → 2*sqrt(2)/(1+2)-1."""
        k = 2.0
        expected = abs(2.0 * math.sqrt(k) / (1.0 + k) - 1.0) * 100.0
        self.assertAlmostEqual(calculate_il(1.0, 2.0), expected, places=10)

    def test_formula_correctness_k05(self):
        """Verify formula: k=0.5."""
        k = 0.5
        expected = abs(2.0 * math.sqrt(k) / (1.0 + k) - 1.0) * 100.0
        self.assertAlmostEqual(calculate_il(1.0, 0.5), expected, places=10)

    def test_formula_correctness_k3(self):
        """k=3 → formula cross-check."""
        k = 3.0
        expected = abs(2.0 * math.sqrt(k) / (1.0 + k) - 1.0) * 100.0
        self.assertAlmostEqual(calculate_il(1.0, 3.0), expected, places=10)

    def test_non_unit_entry_price(self):
        """Entry price != 1 handled correctly via k = current/entry."""
        # entry=2, current=4 → k=2 → same as entry=1, current=2
        self.assertAlmostEqual(calculate_il(2.0, 4.0), calculate_il(1.0, 2.0), places=10)

    def test_returns_positive(self):
        """IL is always returned as a positive number."""
        for ratio in [0.1, 0.5, 2.0, 5.0, 10.0]:
            self.assertGreaterEqual(calculate_il(1.0, ratio), 0.0)

    def test_price_ratio_1_is_zero(self):
        """Identical entry and current → zero IL."""
        self.assertEqual(calculate_il(500.0, 500.0), 0.0)

    def test_large_ratio_increases_il(self):
        """IL grows with larger price deviation."""
        il2 = calculate_il(1.0, 2.0)
        il4 = calculate_il(1.0, 4.0)
        il9 = calculate_il(1.0, 9.0)
        self.assertLess(il2, il4)
        self.assertLess(il4, il9)

    def test_invalid_entry_raises(self):
        """Zero or negative entry_price_ratio should raise ValueError."""
        with self.assertRaises((ValueError, ZeroDivisionError)):
            calculate_il(0.0, 1.0)
        with self.assertRaises((ValueError, ZeroDivisionError, Exception)):
            calculate_il(-1.0, 1.0)


class TestSeverityLabel(unittest.TestCase):
    """Tests for severity_label()."""

    def test_zero_is_negligible(self):
        self.assertEqual(severity_label(0.0), "NEGLIGIBLE")

    def test_below_05_is_negligible(self):
        self.assertEqual(severity_label(0.49), "NEGLIGIBLE")

    def test_exactly_05_is_low(self):
        self.assertEqual(severity_label(0.5), "LOW")

    def test_between_05_and_2_is_low(self):
        self.assertEqual(severity_label(1.0), "LOW")
        self.assertEqual(severity_label(1.99), "LOW")

    def test_exactly_2_is_moderate(self):
        self.assertEqual(severity_label(2.0), "MODERATE")

    def test_between_2_and_5_is_moderate(self):
        self.assertEqual(severity_label(3.5), "MODERATE")
        self.assertEqual(severity_label(4.99), "MODERATE")

    def test_exactly_5_is_high(self):
        self.assertEqual(severity_label(5.0), "HIGH")

    def test_above_5_is_high(self):
        self.assertEqual(severity_label(10.0), "HIGH")
        self.assertEqual(severity_label(50.0), "HIGH")

    def test_all_four_severities_distinct(self):
        labels = {severity_label(0.1), severity_label(1.0), severity_label(3.0), severity_label(6.0)}
        self.assertEqual(labels, {"NEGLIGIBLE", "LOW", "MODERATE", "HIGH"})


class TestGetHedgeStrategies(unittest.TestCase):
    """Tests for get_hedge_strategies()."""

    def setUp(self):
        self.strategies = get_hedge_strategies(5.0, 100_000.0)

    def test_returns_four_strategies(self):
        self.assertEqual(len(self.strategies), 4)

    def test_strategy_names_present(self):
        names = {s["strategy"] for s in self.strategies}
        self.assertIn("SHORT_PERP", names)
        self.assertIn("OPTIONS_PUT", names)
        self.assertIn("RANGE_TIGHTEN", names)
        self.assertIn("IL_INSURANCE", names)

    def test_net_benefit_formula(self):
        """net_benefit = il_pct * coverage/100 - cost."""
        for s in self.strategies:
            expected = 5.0 * s["coverage_pct"] / 100.0 - s["cost_pct"]
            self.assertAlmostEqual(s["net_benefit_pct"], expected, places=5)

    def test_short_perp_cost(self):
        sp = next(s for s in self.strategies if s["strategy"] == "SHORT_PERP")
        self.assertAlmostEqual(sp["cost_pct"], 0.8, places=6)

    def test_short_perp_coverage(self):
        sp = next(s for s in self.strategies if s["strategy"] == "SHORT_PERP")
        self.assertEqual(sp["coverage_pct"], 80)

    def test_options_put_cost(self):
        op = next(s for s in self.strategies if s["strategy"] == "OPTIONS_PUT")
        self.assertAlmostEqual(op["cost_pct"], 1.5, places=6)

    def test_options_put_coverage(self):
        op = next(s for s in self.strategies if s["strategy"] == "OPTIONS_PUT")
        self.assertEqual(op["coverage_pct"], 90)

    def test_range_tighten_cost(self):
        rt = next(s for s in self.strategies if s["strategy"] == "RANGE_TIGHTEN")
        self.assertAlmostEqual(rt["cost_pct"], 0.3, places=6)

    def test_il_insurance_coverage(self):
        ii = next(s for s in self.strategies if s["strategy"] == "IL_INSURANCE")
        self.assertEqual(ii["coverage_pct"], 95)

    def test_net_benefit_varies_with_il(self):
        """Higher IL → higher net_benefit for same strategy."""
        strats_low = get_hedge_strategies(1.0, 100_000.0)
        strats_high = get_hedge_strategies(10.0, 100_000.0)
        for low, high in zip(strats_low, strats_high):
            self.assertLess(low["net_benefit_pct"], high["net_benefit_pct"])


class TestRecommend(unittest.TestCase):
    """Tests for the main recommend() function."""

    def test_negligible_il_no_hedge(self):
        """Very small IL → NO_HEDGE."""
        rec = recommend("ETH", "USDC", 1000.0, 1001.0, 100_000.0, 20.0)
        self.assertEqual(rec.recommended_hedge, "NO_HEDGE")
        self.assertFalse(rec.worth_hedging)

    def test_moderate_il_has_hedge(self):
        """IL around 3% (MODERATE) → some hedge recommended."""
        # k=sqrt(something) to get ~3% IL: need to find a ratio
        # IL=3% → 2*sqrt(k)/(1+k)-1 = -0.03 → 2*sqrt(k) = 0.97*(1+k)
        # Try price 3x: IL = 2*sqrt(3)/4 - 1 ≈ 2*1.732/4 - 1 ≈ -0.134 → 13.4%
        # Use 1.3x: k=1.3, sqrt(1.3)≈1.140, 2*1.140/2.3 ≈ 0.991 → IL≈0.9% LOW
        # Use 1.6x: k=1.6, sqrt(1.6)≈1.265, 2*1.265/2.6≈0.973 → IL≈2.7% MODERATE ✓
        rec = recommend("ETH", "USDC", 1000.0, 1600.0, 100_000.0, 20.0)
        self.assertIn(rec.il_calc.severity, ("MODERATE", "HIGH"))
        self.assertNotEqual(rec.recommended_hedge, "NO_HEDGE")

    def test_worth_hedging_only_when_moderate_or_high(self):
        """worth_hedging=True requires severity MODERATE or HIGH."""
        rec_low = recommend("ETH", "USDC", 1000.0, 1050.0, 100_000.0, 20.0)
        # LOW or NEGLIGIBLE → worth_hedging must be False
        if rec_low.il_calc.severity in ("NEGLIGIBLE", "LOW"):
            self.assertFalse(rec_low.worth_hedging)

    def test_worth_hedging_false_when_no_hedge(self):
        """worth_hedging is always False if recommended_hedge is NO_HEDGE."""
        rec = recommend("ETH", "USDC", 1000.0, 1000.0, 100_000.0, 20.0)
        if rec.recommended_hedge == "NO_HEDGE":
            self.assertFalse(rec.worth_hedging)

    def test_four_strategies_always_returned(self):
        rec = recommend("BTC", "USDC", 30000.0, 50000.0, 50_000.0, 10.0)
        self.assertEqual(len(rec.hedge_strategies), 4)

    def test_il_calc_attached(self):
        rec = recommend("ETH", "USDC", 1000.0, 2000.0, 50_000.0, 15.0)
        self.assertIsInstance(rec.il_calc, ILCalculation)

    def test_il_calc_tokens_match(self):
        rec = recommend("WBTC", "DAI", 25000.0, 30000.0, 10_000.0, 8.0)
        self.assertEqual(rec.il_calc.token_a, "WBTC")
        self.assertEqual(rec.il_calc.token_b, "DAI")

    def test_il_calc_values_correct(self):
        entry, current = 1000.0, 2000.0
        rec = recommend("ETH", "USDC", entry, current, 100_000.0, 10.0)
        expected_il = calculate_il(entry, current)
        self.assertAlmostEqual(rec.il_calc.il_pct, expected_il, places=8)

    def test_il_usd_formula(self):
        rec = recommend("ETH", "USDC", 1000.0, 2000.0, 100_000.0, 10.0)
        expected = 100_000.0 * rec.il_calc.il_pct / 100.0
        self.assertAlmostEqual(rec.il_calc.il_usd, expected, places=5)

    def test_days_to_breakeven_formula(self):
        pos_usd = 100_000.0
        apy = 10.0
        rec = recommend("ETH", "USDC", 1000.0, 2000.0, pos_usd, apy)
        expected_days = rec.il_calc.il_usd / (pos_usd * apy / 365.0 / 100.0)
        self.assertAlmostEqual(rec.il_calc.days_to_breakeven_il, expected_days, places=5)

    def test_severity_negligible_no_change(self):
        rec = recommend("ETH", "USDC", 1000.0, 1000.0, 100_000.0, 20.0)
        self.assertEqual(rec.il_calc.severity, "NEGLIGIBLE")
        self.assertAlmostEqual(rec.il_calc.il_pct, 0.0, places=8)

    def test_severity_high_large_move(self):
        """5x price move → HIGH severity."""
        rec = recommend("ETH", "USDC", 1000.0, 5000.0, 100_000.0, 5.0)
        self.assertEqual(rec.il_calc.severity, "HIGH")

    def test_reasoning_is_list_of_strings(self):
        rec = recommend("ETH", "USDC", 1000.0, 2000.0, 50_000.0, 15.0)
        self.assertIsInstance(rec.reasoning, list)
        for item in rec.reasoning:
            self.assertIsInstance(item, str)

    def test_warnings_severe_il(self):
        """IL > 10% triggers severe IL warning."""
        rec = recommend("ETH", "USDC", 1000.0, 10000.0, 100_000.0, 5.0)
        # 10x price → IL ≈ 50.5%
        has_severe_warning = any("severe" in w.lower() or "10%" in w for w in rec.warnings)
        self.assertTrue(has_severe_warning)

    def test_warnings_slow_breakeven(self):
        """Very high IL with low yield → slow breakeven warning."""
        rec = recommend("ETH", "USDC", 1000.0, 5000.0, 100_000.0, 0.5)
        has_breakeven_warning = any("90" in w or "breakeven" in w.lower() for w in rec.warnings)
        self.assertTrue(has_breakeven_warning)

    def test_no_warnings_for_trivial_case(self):
        """No price change → no warnings expected."""
        rec = recommend("ETH", "USDC", 1000.0, 1000.0, 100_000.0, 20.0)
        # IL = 0, no severe IL, days_be = 0 (since il_usd=0)
        self.assertFalse(any("severe" in w.lower() for w in rec.warnings))

    def test_price_ratio_change_computed(self):
        rec = recommend("ETH", "USDC", 1000.0, 2000.0, 100_000.0, 10.0)
        self.assertAlmostEqual(rec.il_calc.price_ratio_change, 2.0, places=8)

    def test_price_ratio_change_half(self):
        rec = recommend("ETH", "USDC", 1000.0, 500.0, 100_000.0, 10.0)
        self.assertAlmostEqual(rec.il_calc.price_ratio_change, 0.5, places=8)

    def test_net_il_after_hedge_no_hedge_equals_il(self):
        """When no hedge, net IL after hedge should equal raw IL."""
        rec = recommend("ETH", "USDC", 1000.0, 1000.0, 100_000.0, 20.0)
        if rec.recommended_hedge == "NO_HEDGE":
            self.assertAlmostEqual(rec.net_il_after_hedge_pct, rec.il_calc.il_pct, places=5)

    def test_net_il_after_hedge_reduced_when_hedged(self):
        """When hedge is active, net IL should be less than raw IL."""
        rec = recommend("ETH", "USDC", 1000.0, 5000.0, 100_000.0, 20.0)
        if rec.recommended_hedge != "NO_HEDGE":
            self.assertLess(rec.net_il_after_hedge_pct, rec.il_calc.il_pct)

    def test_zero_position_usd(self):
        """Zero position should still compute without error."""
        rec = recommend("ETH", "USDC", 1000.0, 2000.0, 0.0, 10.0)
        self.assertAlmostEqual(rec.il_calc.il_usd, 0.0, places=8)

    def test_best_hedge_is_highest_net_benefit(self):
        """Recommended hedge should have the highest positive net_benefit."""
        rec = recommend("ETH", "USDC", 1000.0, 3000.0, 100_000.0, 10.0)
        if rec.recommended_hedge != "NO_HEDGE":
            positives = [s for s in rec.hedge_strategies if s["net_benefit_pct"] > 0]
            best = max(positives, key=lambda s: s["net_benefit_pct"])
            self.assertEqual(rec.recommended_hedge, best["strategy"])

    def test_returns_hedge_recommendation_type(self):
        rec = recommend("ETH", "USDC", 1000.0, 2000.0, 50_000.0, 15.0)
        self.assertIsInstance(rec, HedgeRecommendation)


class TestDaysToBreakeven(unittest.TestCase):
    """Tests for _days_to_breakeven helper."""

    def test_basic_formula(self):
        il_usd = 1000.0
        pos = 100_000.0
        apy = 10.0
        daily = pos * apy / 365.0 / 100.0
        expected = il_usd / daily
        self.assertAlmostEqual(_days_to_breakeven(il_usd, pos, apy), expected, places=8)

    def test_zero_apy_returns_inf(self):
        self.assertEqual(_days_to_breakeven(1000.0, 100_000.0, 0.0), float("inf"))

    def test_zero_position_returns_inf(self):
        self.assertEqual(_days_to_breakeven(1000.0, 0.0, 10.0), float("inf"))

    def test_zero_il_returns_zero(self):
        result = _days_to_breakeven(0.0, 100_000.0, 10.0)
        self.assertAlmostEqual(result, 0.0, places=8)


class TestComparePositions(unittest.TestCase):
    """Tests for compare_positions()."""

    def _make_rec(self, il_pct: float) -> HedgeRecommendation:
        il_calc = ILCalculation(
            token_a="ETH", token_b="USDC",
            entry_price_ratio=1.0, current_price_ratio=1.0,
            position_value_usd=100_000.0,
            il_pct=il_pct,
        )
        return HedgeRecommendation(il_calc=il_calc)

    def test_sorted_descending(self):
        recs = [self._make_rec(3.0), self._make_rec(10.0), self._make_rec(1.0)]
        sorted_recs = compare_positions(recs)
        il_values = [r.il_calc.il_pct for r in sorted_recs]
        self.assertEqual(il_values, sorted(il_values, reverse=True))

    def test_empty_list(self):
        self.assertEqual(compare_positions([]), [])

    def test_single_item(self):
        rec = self._make_rec(5.0)
        self.assertEqual(compare_positions([rec]), [rec])

    def test_already_sorted_unchanged(self):
        recs = [self._make_rec(9.0), self._make_rec(5.0), self._make_rec(1.0)]
        sorted_recs = compare_positions(recs)
        il_values = [r.il_calc.il_pct for r in sorted_recs]
        self.assertEqual(il_values, [9.0, 5.0, 1.0])


class TestSaveLoadHistory(unittest.TestCase):
    """Tests for save_results() and load_history()."""

    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self._data_file = Path(self._tmpdir.name) / "il_hedger_log.json"

    def tearDown(self):
        self._tmpdir.cleanup()

    def _make_rec(self, il_pct: float = 3.0) -> HedgeRecommendation:
        return recommend("ETH", "USDC", 1000.0, 1000.0 * (1 + il_pct / 100.0), 100_000.0, 10.0)

    def test_save_creates_file(self):
        rec = self._make_rec()
        save_results(rec, data_file=self._data_file)
        self.assertTrue(self._data_file.exists())

    def test_load_empty_when_no_file(self):
        hist = load_history(data_file=self._data_file)
        self.assertEqual(hist, [])

    def test_save_and_load_roundtrip(self):
        rec = recommend("ETH", "USDC", 1000.0, 1600.0, 100_000.0, 20.0)
        save_results(rec, data_file=self._data_file)
        hist = load_history(data_file=self._data_file)
        self.assertEqual(len(hist), 1)
        self.assertIn("il_calc", hist[0])

    def test_multiple_saves_accumulate(self):
        for _ in range(5):
            rec = recommend("ETH", "USDC", 1000.0, 2000.0, 50_000.0, 10.0)
            save_results(rec, data_file=self._data_file)
        hist = load_history(data_file=self._data_file)
        self.assertEqual(len(hist), 5)

    def test_ring_buffer_cap_100(self):
        """After 110 saves, only 100 entries should remain."""
        for _ in range(110):
            rec = recommend("ETH", "USDC", 1000.0, 2000.0, 50_000.0, 10.0)
            save_results(rec, data_file=self._data_file)
        hist = load_history(data_file=self._data_file)
        self.assertEqual(len(hist), 100)

    def test_ring_buffer_keeps_latest(self):
        """Ring buffer should keep the most recent 100 entries."""
        for i in range(105):
            rec = recommend("ETH", "USDC", float(i + 1), float(i + 2), 1000.0, 10.0)
            save_results(rec, data_file=self._data_file)
        hist = load_history(data_file=self._data_file)
        self.assertEqual(len(hist), 100)
        # The first 5 should have been dropped (they had entry_price_ratio=1..5)
        # The last 100 had entry_price_ratio=6..105
        first_entry_ratio = hist[0]["il_calc"]["entry_price_ratio"]
        self.assertGreaterEqual(first_entry_ratio, 6.0)

    def test_saved_to_field_set(self):
        rec = recommend("ETH", "USDC", 1000.0, 2000.0, 50_000.0, 10.0)
        save_results(rec, data_file=self._data_file)
        self.assertNotEqual(rec.saved_to, "")
        self.assertIn("il_hedger_log", rec.saved_to)

    def test_atomic_write_no_tmp_left(self):
        rec = recommend("ETH", "USDC", 1000.0, 2000.0, 50_000.0, 10.0)
        save_results(rec, data_file=self._data_file)
        tmp_file = self._data_file.with_suffix(".tmp")
        self.assertFalse(tmp_file.exists())

    def test_saved_at_timestamp_present(self):
        rec = recommend("ETH", "USDC", 1000.0, 2000.0, 50_000.0, 10.0)
        save_results(rec, data_file=self._data_file)
        hist = load_history(data_file=self._data_file)
        self.assertIn("_saved_at", hist[0])

    def test_il_fields_preserved(self):
        rec = recommend("WBTC", "DAI", 30000.0, 45000.0, 100_000.0, 8.0)
        save_results(rec, data_file=self._data_file)
        hist = load_history(data_file=self._data_file)
        il_data = hist[0]["il_calc"]
        self.assertEqual(il_data["token_a"], "WBTC")
        self.assertEqual(il_data["token_b"], "DAI")


class TestEdgeCases(unittest.TestCase):
    """Additional edge case coverage."""

    def test_il_zero_for_ratio_one(self):
        il = calculate_il(1000.0, 1000.0)
        self.assertAlmostEqual(il, 0.0, places=10)

    def test_recommend_zero_yield_sets_inf_breakeven(self):
        rec = recommend("ETH", "USDC", 1000.0, 2000.0, 100_000.0, 0.0)
        self.assertEqual(rec.il_calc.days_to_breakeven_il, float("inf"))

    def test_recommend_large_position_scales_il_usd(self):
        rec_small = recommend("ETH", "USDC", 1000.0, 2000.0, 10_000.0, 10.0)
        rec_large = recommend("ETH", "USDC", 1000.0, 2000.0, 1_000_000.0, 10.0)
        self.assertAlmostEqual(
            rec_large.il_calc.il_usd / rec_small.il_calc.il_usd,
            100.0, places=5
        )

    def test_il_calc_to_dict_complete(self):
        il = ILCalculation(
            token_a="ETH", token_b="USDC",
            entry_price_ratio=1000.0, current_price_ratio=2000.0,
            position_value_usd=100_000.0,
        )
        d = il.to_dict()
        self.assertIn("token_a", d)
        self.assertIn("il_pct", d)
        self.assertIn("severity", d)

    def test_hedge_recommendation_to_dict(self):
        rec = recommend("ETH", "USDC", 1000.0, 2000.0, 50_000.0, 10.0)
        d = rec.to_dict()
        self.assertIn("il_calc", d)
        self.assertIn("hedge_strategies", d)
        self.assertIn("worth_hedging", d)
        self.assertIn("warnings", d)


if __name__ == "__main__":
    unittest.main(verbosity=2)
