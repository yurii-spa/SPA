"""
Tests for MP-1036: DeFiProtocolYieldTokenizationRiskAnalyzer
≥90 unittest tests covering all specified cases.
Run: python3 -m unittest spa_core.tests.test_defi_protocol_yield_tokenization_risk_analyzer -v
"""

import json
import tempfile
import unittest
from pathlib import Path

from spa_core.analytics.defi_protocol_yield_tokenization_risk_analyzer import (
    DeFiProtocolYieldTokenizationRiskAnalyzer,
    YieldTokenizationInput,
    YieldTokenizationResult,
    MAX_ENTRIES,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_input(
    protocol_name="Pendle-USDC",
    maturity_days=180,
    fixed_rate_pct=8.0,
    implied_apy_pct=9.0,
    underlying_apy_pct=6.0,
    tvl_usd=50_000_000.0,
    pt_market_depth_usd=5_000_000.0,
    days_to_maturity=90,
) -> YieldTokenizationInput:
    return YieldTokenizationInput(
        protocol_name=protocol_name,
        maturity_days=maturity_days,
        fixed_rate_pct=fixed_rate_pct,
        implied_apy_pct=implied_apy_pct,
        underlying_apy_pct=underlying_apy_pct,
        tvl_usd=tvl_usd,
        pt_market_depth_usd=pt_market_depth_usd,
        days_to_maturity=days_to_maturity,
    )


class _WithTmpFile(unittest.TestCase):
    """Base class that routes the analyser to a temp file."""

    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp()
        self.data_file = Path(self.tmp_dir) / "yield_tokenization_risk_log.json"
        self.analyzer = DeFiProtocolYieldTokenizationRiskAnalyzer(
            data_file=self.data_file
        )


# ===========================================================================
# 1. Rate Lock Value Score
# ===========================================================================


class TestRateLockValueScore(_WithTmpFile):

    def test_neutral_rate_gives_50(self):
        """fixed_rate == underlying → score 50."""
        score = self.analyzer._rate_lock_value_score(5.0, 5.0)
        self.assertAlmostEqual(score, 50.0, places=2)

    def test_premium_increases_score(self):
        """fixed_rate 2pp above underlying → score 70."""
        score = self.analyzer._rate_lock_value_score(7.0, 5.0)
        self.assertAlmostEqual(score, 70.0, places=2)

    def test_discount_decreases_score(self):
        """fixed_rate 2pp below underlying → score 30."""
        score = self.analyzer._rate_lock_value_score(3.0, 5.0)
        self.assertAlmostEqual(score, 30.0, places=2)

    def test_large_premium_capped_at_100(self):
        """Extreme premium cannot exceed 100."""
        score = self.analyzer._rate_lock_value_score(20.0, 2.0)
        self.assertEqual(score, 100.0)

    def test_large_discount_clamped_at_0(self):
        """Extreme discount cannot go below 0."""
        score = self.analyzer._rate_lock_value_score(0.0, 10.0)
        self.assertEqual(score, 0.0)

    def test_zero_rates_gives_50(self):
        """Both zero → neutral (50)."""
        score = self.analyzer._rate_lock_value_score(0.0, 0.0)
        self.assertAlmostEqual(score, 50.0, places=2)

    def test_half_pp_premium(self):
        """0.5pp premium → score 55."""
        score = self.analyzer._rate_lock_value_score(5.5, 5.0)
        self.assertAlmostEqual(score, 55.0, places=2)

    def test_negative_fixed_rate(self):
        """Negative fixed rate → score 0 (deeply unattractive)."""
        score = self.analyzer._rate_lock_value_score(-2.0, 5.0)
        self.assertEqual(score, 0.0)

    def test_returns_float(self):
        score = self.analyzer._rate_lock_value_score(8.0, 6.0)
        self.assertIsInstance(score, float)

    def test_score_in_bounds(self):
        for fixed in range(-5, 20):
            for underlying in range(0, 15):
                score = self.analyzer._rate_lock_value_score(
                    float(fixed), float(underlying)
                )
                self.assertGreaterEqual(score, 0.0)
                self.assertLessEqual(score, 100.0)


# ===========================================================================
# 2. Maturity Risk Score
# ===========================================================================


class TestMaturityRiskScore(_WithTmpFile):

    def test_zero_days_gives_zero(self):
        score = self.analyzer._maturity_risk_score(0)
        self.assertAlmostEqual(score, 0.0, places=2)

    def test_730_days_gives_100(self):
        score = self.analyzer._maturity_risk_score(730)
        self.assertAlmostEqual(score, 100.0, places=2)

    def test_365_days_gives_50(self):
        score = self.analyzer._maturity_risk_score(365)
        self.assertAlmostEqual(score, 50.0, places=2)

    def test_beyond_730_capped_at_100(self):
        score = self.analyzer._maturity_risk_score(1000)
        self.assertEqual(score, 100.0)

    def test_90_days(self):
        score = self.analyzer._maturity_risk_score(90)
        expected = round(90 / 730 * 100, 2)
        self.assertAlmostEqual(score, expected, places=2)

    def test_180_days(self):
        score = self.analyzer._maturity_risk_score(180)
        expected = round(180 / 730 * 100, 2)
        self.assertAlmostEqual(score, expected, places=2)

    def test_returns_float(self):
        score = self.analyzer._maturity_risk_score(100)
        self.assertIsInstance(score, float)

    def test_monotone_increasing(self):
        """Longer maturity always gives higher score."""
        prev = self.analyzer._maturity_risk_score(0)
        for days in [30, 90, 180, 365, 730]:
            current = self.analyzer._maturity_risk_score(days)
            self.assertGreaterEqual(current, prev)
            prev = current

    def test_score_in_bounds(self):
        for days in [0, 1, 30, 90, 180, 365, 500, 730, 1000]:
            score = self.analyzer._maturity_risk_score(days)
            self.assertGreaterEqual(score, 0.0)
            self.assertLessEqual(score, 100.0)


# ===========================================================================
# 3. Liquidity Exit Risk
# ===========================================================================


class TestLiquidityExitRisk(_WithTmpFile):

    def test_zero_depth_gives_100(self):
        risk = self.analyzer._liquidity_exit_risk(0, 10_000_000)
        self.assertAlmostEqual(risk, 100.0, places=2)

    def test_depth_equals_50_pct_tvl_gives_0(self):
        """50% depth ratio → 0 risk."""
        risk = self.analyzer._liquidity_exit_risk(5_000_000, 10_000_000)
        self.assertAlmostEqual(risk, 0.0, places=2)

    def test_depth_above_50_pct_clamped_at_0(self):
        """Depth > 50% still → 0 risk (clamped)."""
        risk = self.analyzer._liquidity_exit_risk(8_000_000, 10_000_000)
        self.assertAlmostEqual(risk, 0.0, places=2)

    def test_25_pct_depth_gives_50(self):
        """25% depth ratio → 50 risk (midpoint)."""
        risk = self.analyzer._liquidity_exit_risk(2_500_000, 10_000_000)
        self.assertAlmostEqual(risk, 50.0, places=2)

    def test_zero_tvl_gives_100(self):
        """Zero TVL → maximum risk."""
        risk = self.analyzer._liquidity_exit_risk(1_000_000, 0)
        self.assertAlmostEqual(risk, 100.0, places=2)

    def test_depth_greater_than_tvl_gives_0(self):
        """Depth larger than TVL is over-provisioned → 0 risk."""
        risk = self.analyzer._liquidity_exit_risk(15_000_000, 10_000_000)
        self.assertAlmostEqual(risk, 0.0, places=2)

    def test_returns_float(self):
        risk = self.analyzer._liquidity_exit_risk(1_000_000, 5_000_000)
        self.assertIsInstance(risk, float)

    def test_monotone_decreasing_with_depth(self):
        """More depth → lower risk."""
        prev = self.analyzer._liquidity_exit_risk(0, 10_000_000)
        for depth in [1_000_000, 2_000_000, 4_000_000, 5_000_000]:
            current = self.analyzer._liquidity_exit_risk(depth, 10_000_000)
            self.assertLessEqual(current, prev)
            prev = current

    def test_risk_in_bounds(self):
        for depth in [0, 500_000, 1_000_000, 5_000_000, 10_000_000]:
            risk = self.analyzer._liquidity_exit_risk(depth, 10_000_000)
            self.assertGreaterEqual(risk, 0.0)
            self.assertLessEqual(risk, 100.0)


# ===========================================================================
# 4. Yield Capture Efficiency
# ===========================================================================


class TestYieldCaptureEfficiency(_WithTmpFile):

    def test_equal_rates_gives_100_pct(self):
        eff = self.analyzer._yield_capture_efficiency_pct(8.0, 8.0)
        self.assertAlmostEqual(eff, 100.0, places=2)

    def test_fixed_below_implied_gives_below_100(self):
        eff = self.analyzer._yield_capture_efficiency_pct(7.0, 10.0)
        self.assertAlmostEqual(eff, 70.0, places=2)

    def test_fixed_above_implied_gives_above_100(self):
        eff = self.analyzer._yield_capture_efficiency_pct(12.0, 10.0)
        self.assertAlmostEqual(eff, 120.0, places=2)

    def test_zero_implied_gives_zero(self):
        eff = self.analyzer._yield_capture_efficiency_pct(8.0, 0.0)
        self.assertAlmostEqual(eff, 0.0, places=2)

    def test_extreme_above_implied_capped_at_200(self):
        eff = self.analyzer._yield_capture_efficiency_pct(100.0, 1.0)
        self.assertAlmostEqual(eff, 200.0, places=2)

    def test_zero_fixed_gives_zero(self):
        eff = self.analyzer._yield_capture_efficiency_pct(0.0, 10.0)
        self.assertAlmostEqual(eff, 0.0, places=2)

    def test_returns_float(self):
        eff = self.analyzer._yield_capture_efficiency_pct(8.0, 9.0)
        self.assertIsInstance(eff, float)

    def test_efficiency_in_bounds(self):
        for fixed in [0, 5, 10, 15, 50]:
            for implied in [0.1, 5, 10, 20]:
                eff = self.analyzer._yield_capture_efficiency_pct(
                    float(fixed), float(implied)
                )
                self.assertGreaterEqual(eff, 0.0)
                self.assertLessEqual(eff, 200.0)

    def test_negative_implied_gives_zero(self):
        eff = self.analyzer._yield_capture_efficiency_pct(5.0, -1.0)
        self.assertAlmostEqual(eff, 0.0, places=2)


# ===========================================================================
# 5. Composite Score
# ===========================================================================


class TestCompositeScore(_WithTmpFile):

    def test_all_perfect_gives_high_score(self):
        """rate_lock=100, maturity_safe=100, liquidity_safe=100, eff=100 → 100."""
        score = self.analyzer._composite_score(100, 0, 0, 100)
        self.assertAlmostEqual(score, 100.0, places=2)

    def test_all_worst_gives_low_score(self):
        """rate_lock=0, maturity_risky=100, liquidity_risky=100, eff=0 → 0."""
        score = self.analyzer._composite_score(0, 100, 100, 0)
        self.assertAlmostEqual(score, 0.0, places=2)

    def test_neutral_gives_50(self):
        """Neutral inputs → 50."""
        score = self.analyzer._composite_score(50, 50, 50, 50)
        self.assertAlmostEqual(score, 50.0, places=2)

    def test_weights_sum_to_one(self):
        """Verify weights: 0.35+0.25+0.25+0.15 = 1.0"""
        # rate_lock=100 only → 0.35*100 = 35
        score = self.analyzer._composite_score(100, 100, 100, 0)
        # maturity_safe=0, liq_safe=0, eff_norm=0
        self.assertAlmostEqual(score, 35.0, places=2)

    def test_efficiency_capped_at_100_for_composite(self):
        """Efficiency > 100% should be treated as 100 in composite."""
        score_capped = self.analyzer._composite_score(50, 50, 50, 150)
        score_hundred = self.analyzer._composite_score(50, 50, 50, 100)
        self.assertAlmostEqual(score_capped, score_hundred, places=2)

    def test_composite_in_bounds(self):
        for rl in [0, 50, 100]:
            for mr in [0, 50, 100]:
                for lr in [0, 50, 100]:
                    for eff in [0, 50, 100]:
                        score = self.analyzer._composite_score(rl, mr, lr, eff)
                        self.assertGreaterEqual(score, 0.0)
                        self.assertLessEqual(score, 100.0)

    def test_returns_float(self):
        score = self.analyzer._composite_score(60, 30, 20, 80)
        self.assertIsInstance(score, float)


# ===========================================================================
# 6. Label Assignment
# ===========================================================================


class TestLabelAssignment(_WithTmpFile):

    def test_label_ideal(self):
        self.assertEqual(self.analyzer._label(80.0), "IDEAL_YIELD_STRIP")

    def test_label_ideal_boundary(self):
        self.assertEqual(self.analyzer._label(75.0), "IDEAL_YIELD_STRIP")

    def test_label_good(self):
        self.assertEqual(self.analyzer._label(65.0), "GOOD_OPPORTUNITY")

    def test_label_good_boundary(self):
        self.assertEqual(self.analyzer._label(60.0), "GOOD_OPPORTUNITY")

    def test_label_moderate(self):
        self.assertEqual(self.analyzer._label(52.0), "MODERATE_RISK")

    def test_label_moderate_boundary(self):
        self.assertEqual(self.analyzer._label(45.0), "MODERATE_RISK")

    def test_label_high_risk(self):
        self.assertEqual(self.analyzer._label(38.0), "HIGH_RISK")

    def test_label_high_risk_boundary(self):
        self.assertEqual(self.analyzer._label(30.0), "HIGH_RISK")

    def test_label_avoid(self):
        self.assertEqual(self.analyzer._label(20.0), "AVOID")

    def test_label_avoid_zero(self):
        self.assertEqual(self.analyzer._label(0.0), "AVOID")

    def test_all_valid_labels(self):
        valid = {
            "IDEAL_YIELD_STRIP", "GOOD_OPPORTUNITY",
            "MODERATE_RISK", "HIGH_RISK", "AVOID"
        }
        for score in range(0, 101, 5):
            self.assertIn(self.analyzer._label(float(score)), valid)


# ===========================================================================
# 7. Full analyze() integration
# ===========================================================================


class TestAnalyze(_WithTmpFile):

    def test_returns_result_type(self):
        result = self.analyzer.analyze(make_input())
        self.assertIsInstance(result, YieldTokenizationResult)

    def test_protocol_name_preserved(self):
        result = self.analyzer.analyze(make_input(protocol_name="TestProtocol"))
        self.assertEqual(result.protocol_name, "TestProtocol")

    def test_scores_in_bounds(self):
        result = self.analyzer.analyze(make_input())
        self.assertGreaterEqual(result.rate_lock_value_score, 0.0)
        self.assertLessEqual(result.rate_lock_value_score, 100.0)
        self.assertGreaterEqual(result.maturity_risk_score, 0.0)
        self.assertLessEqual(result.maturity_risk_score, 100.0)
        self.assertGreaterEqual(result.liquidity_exit_risk, 0.0)
        self.assertLessEqual(result.liquidity_exit_risk, 100.0)
        self.assertGreaterEqual(result.composite_score, 0.0)
        self.assertLessEqual(result.composite_score, 100.0)

    def test_label_is_valid_string(self):
        result = self.analyzer.analyze(make_input())
        valid = {
            "IDEAL_YIELD_STRIP", "GOOD_OPPORTUNITY",
            "MODERATE_RISK", "HIGH_RISK", "AVOID"
        }
        self.assertIn(result.label, valid)

    def test_high_premium_leads_to_good_label(self):
        """fixed_rate >> underlying → at least GOOD_OPPORTUNITY."""
        result = self.analyzer.analyze(make_input(
            fixed_rate_pct=15.0,
            underlying_apy_pct=5.0,
            days_to_maturity=30,
            pt_market_depth_usd=5_000_000,
            tvl_usd=10_000_000,
        ))
        self.assertIn(result.label, {"IDEAL_YIELD_STRIP", "GOOD_OPPORTUNITY"})

    def test_high_risk_long_maturity(self):
        """Very long maturity + thin depth → HIGH_RISK or AVOID."""
        result = self.analyzer.analyze(make_input(
            fixed_rate_pct=5.0,
            underlying_apy_pct=5.0,
            days_to_maturity=700,
            pt_market_depth_usd=100_000,
            tvl_usd=50_000_000,
        ))
        self.assertIn(result.label, {"HIGH_RISK", "AVOID"})

    def test_inputs_echoed_in_result(self):
        inp = make_input(
            fixed_rate_pct=7.5,
            implied_apy_pct=8.0,
            underlying_apy_pct=6.0,
            tvl_usd=20_000_000,
            pt_market_depth_usd=2_000_000,
            days_to_maturity=60,
        )
        result = self.analyzer.analyze(inp)
        self.assertAlmostEqual(result.fixed_rate_pct, 7.5, places=4)
        self.assertAlmostEqual(result.implied_apy_pct, 8.0, places=4)
        self.assertAlmostEqual(result.underlying_apy_pct, 6.0, places=4)
        self.assertAlmostEqual(result.tvl_usd, 20_000_000, places=1)
        self.assertEqual(result.days_to_maturity, 60)

    def test_zero_depth_with_bad_other_metrics_risky(self):
        """Zero depth + neutral rate + long maturity → HIGH_RISK or AVOID."""
        result = self.analyzer.analyze(make_input(
            pt_market_depth_usd=0.0,
            fixed_rate_pct=5.0,
            underlying_apy_pct=5.0,
            days_to_maturity=700,
        ))
        self.assertIn(result.label, {"HIGH_RISK", "AVOID"})

    def test_near_maturity_low_maturity_risk(self):
        result = self.analyzer.analyze(make_input(days_to_maturity=1))
        self.assertLess(result.maturity_risk_score, 1.0)

    def test_efficiency_ratio_calculated(self):
        result = self.analyzer.analyze(make_input(
            fixed_rate_pct=8.0,
            implied_apy_pct=10.0,
        ))
        self.assertAlmostEqual(result.yield_capture_efficiency_pct, 80.0, places=2)


# ===========================================================================
# 8. Batch analyze
# ===========================================================================


class TestAnalyzeBatch(_WithTmpFile):

    def test_empty_batch_returns_empty(self):
        results = self.analyzer.analyze_batch([])
        self.assertEqual(results, [])

    def test_single_item_batch(self):
        results = self.analyzer.analyze_batch([make_input()])
        self.assertEqual(len(results), 1)

    def test_multi_item_batch_order_preserved(self):
        names = ["ProtA", "ProtB", "ProtC"]
        inputs = [make_input(protocol_name=n) for n in names]
        results = self.analyzer.analyze_batch(inputs)
        for i, name in enumerate(names):
            self.assertEqual(results[i].protocol_name, name)

    def test_batch_length_matches(self):
        inputs = [make_input() for _ in range(7)]
        results = self.analyzer.analyze_batch(inputs)
        self.assertEqual(len(results), 7)


# ===========================================================================
# 9. best_opportunity
# ===========================================================================


class TestBestOpportunity(_WithTmpFile):

    def test_best_has_highest_composite(self):
        inputs = [
            make_input(fixed_rate_pct=15.0, days_to_maturity=10),
            make_input(fixed_rate_pct=5.0, days_to_maturity=700),
            make_input(fixed_rate_pct=8.0, days_to_maturity=90),
        ]
        results = self.analyzer.analyze_batch(inputs)
        best = self.analyzer.best_opportunity(results)
        max_composite = max(r.composite_score for r in results)
        self.assertAlmostEqual(best.composite_score, max_composite, places=5)

    def test_best_opportunity_raises_on_empty(self):
        with self.assertRaises(ValueError):
            self.analyzer.best_opportunity([])

    def test_single_result_is_best(self):
        result = self.analyzer.analyze(make_input())
        best = self.analyzer.best_opportunity([result])
        self.assertEqual(best.protocol_name, result.protocol_name)


# ===========================================================================
# 10. filter_by_label & filter_investable
# ===========================================================================


class TestFilters(_WithTmpFile):

    def _batch(self):
        inputs = [
            make_input(fixed_rate_pct=15.0, days_to_maturity=10, pt_market_depth_usd=5_000_000),
            make_input(fixed_rate_pct=8.0, days_to_maturity=90),
            make_input(fixed_rate_pct=2.0, days_to_maturity=700, pt_market_depth_usd=0),
        ]
        return self.analyzer.analyze_batch(inputs)

    def test_filter_by_label_returns_only_matching(self):
        results = self._batch()
        for lbl in {"IDEAL_YIELD_STRIP", "GOOD_OPPORTUNITY", "MODERATE_RISK",
                    "HIGH_RISK", "AVOID"}:
            filtered = self.analyzer.filter_by_label(results, lbl)
            for r in filtered:
                self.assertEqual(r.label, lbl)

    def test_filter_investable_labels(self):
        results = self._batch()
        investable = self.analyzer.filter_investable(results)
        for r in investable:
            self.assertIn(r.label, {"IDEAL_YIELD_STRIP", "GOOD_OPPORTUNITY"})

    def test_filter_investable_excludes_risky(self):
        risky = make_input(
            fixed_rate_pct=2.0, underlying_apy_pct=10.0,
            days_to_maturity=700, pt_market_depth_usd=0
        )
        result = self.analyzer.analyze(risky)
        # Should not be in investable labels if label is HIGH_RISK or AVOID
        if result.label in {"HIGH_RISK", "AVOID"}:
            investable = self.analyzer.filter_investable([result])
            self.assertEqual(len(investable), 0)

    def test_filter_by_nonexistent_label(self):
        results = self._batch()
        filtered = self.analyzer.filter_by_label(results, "NONEXISTENT")
        self.assertEqual(filtered, [])


# ===========================================================================
# 11. save_results / load_history / ring-buffer
# ===========================================================================


class TestPersistence(_WithTmpFile):

    def test_save_creates_file(self):
        result = self.analyzer.analyze(make_input())
        self.analyzer.save_results([result])
        self.assertTrue(self.data_file.exists())

    def test_saved_file_is_valid_json(self):
        result = self.analyzer.analyze(make_input())
        self.analyzer.save_results([result])
        with open(self.data_file) as f:
            data = json.load(f)
        self.assertIsInstance(data, list)

    def test_load_history_returns_list(self):
        result = self.analyzer.analyze(make_input())
        self.analyzer.save_results([result])
        history = self.analyzer.load_history()
        self.assertIsInstance(history, list)

    def test_load_history_returns_empty_when_no_file(self):
        history = self.analyzer.load_history()
        self.assertEqual(history, [])

    def test_ring_buffer_cap(self):
        result = self.analyzer.analyze(make_input())
        for _ in range(MAX_ENTRIES + 20):
            self.analyzer.save_results([result])
        history = self.analyzer.load_history()
        self.assertLessEqual(len(history), MAX_ENTRIES)

    def test_saved_entry_has_required_fields(self):
        result = self.analyzer.analyze(make_input(protocol_name="Pendle-X"))
        self.analyzer.save_results([result])
        history = self.analyzer.load_history()
        entry = history[-1]
        self.assertIn("timestamp", entry)
        self.assertIn("protocol_name", entry)
        self.assertIn("composite_score", entry)
        self.assertIn("label", entry)
        self.assertEqual(entry["protocol_name"], "Pendle-X")

    def test_multiple_saves_accumulate(self):
        r1 = self.analyzer.analyze(make_input(protocol_name="A"))
        r2 = self.analyzer.analyze(make_input(protocol_name="B"))
        self.analyzer.save_results([r1])
        self.analyzer.save_results([r2])
        history = self.analyzer.load_history()
        self.assertEqual(len(history), 2)

    def test_atomic_write_no_tmp_left(self):
        result = self.analyzer.analyze(make_input())
        self.analyzer.save_results([result])
        tmp = self.data_file.with_suffix(".tmp")
        self.assertFalse(tmp.exists())

    def test_batch_save_appends_all(self):
        results = self.analyzer.analyze_batch([make_input() for _ in range(5)])
        self.analyzer.save_results(results)
        history = self.analyzer.load_history()
        self.assertEqual(len(history), 5)


# ===========================================================================
# 12. Edge / boundary cases
# ===========================================================================


class TestEdgeCases(_WithTmpFile):

    def test_zero_tvl_analyze(self):
        result = self.analyzer.analyze(make_input(tvl_usd=0))
        self.assertAlmostEqual(result.liquidity_exit_risk, 100.0, places=2)

    def test_very_large_tvl(self):
        result = self.analyzer.analyze(make_input(tvl_usd=1e12))
        self.assertIsInstance(result, YieldTokenizationResult)

    def test_very_large_depth(self):
        result = self.analyzer.analyze(make_input(pt_market_depth_usd=1e12))
        self.assertAlmostEqual(result.liquidity_exit_risk, 0.0, places=2)

    def test_identical_rates(self):
        result = self.analyzer.analyze(make_input(
            fixed_rate_pct=5.0,
            implied_apy_pct=5.0,
            underlying_apy_pct=5.0,
        ))
        self.assertAlmostEqual(result.rate_lock_value_score, 50.0, places=2)
        self.assertAlmostEqual(result.yield_capture_efficiency_pct, 100.0, places=2)

    def test_days_to_maturity_equals_730(self):
        result = self.analyzer.analyze(make_input(days_to_maturity=730))
        self.assertAlmostEqual(result.maturity_risk_score, 100.0, places=2)

    def test_days_to_maturity_zero(self):
        result = self.analyzer.analyze(make_input(days_to_maturity=0))
        self.assertAlmostEqual(result.maturity_risk_score, 0.0, places=2)

    def test_analyse_deterministic(self):
        """Same input → same result."""
        inp = make_input()
        r1 = self.analyzer.analyze(inp)
        r2 = self.analyzer.analyze(inp)
        self.assertAlmostEqual(r1.composite_score, r2.composite_score, places=5)
        self.assertEqual(r1.label, r2.label)

    def test_very_small_implied_apy(self):
        result = self.analyzer.analyze(make_input(
            implied_apy_pct=0.001,
            fixed_rate_pct=0.0,
        ))
        self.assertGreaterEqual(result.yield_capture_efficiency_pct, 0.0)

    def test_negative_underlying_apy(self):
        result = self.analyzer.analyze(make_input(underlying_apy_pct=-5.0))
        # Premium increases, so rate_lock_value_score should be higher
        result_base = self.analyzer.analyze(make_input(underlying_apy_pct=5.0))
        self.assertGreater(result.rate_lock_value_score, result_base.rate_lock_value_score)


if __name__ == "__main__":
    unittest.main()
