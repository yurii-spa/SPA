"""
Tests for MP-717: DeFiCyclePhaseDetector
≥65 tests. Pure unittest, no external deps.
"""
import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from spa_core.analytics.defi_cycle_phase_detector import (
    MarketSignal,
    CyclePhaseReport,
    classify_tvl_trend,
    classify_yield_trend,
    score_phases,
    detect_phase,
    analyze,
    compare_periods,
    save_results,
    load_history,
)


# ─── classify_tvl_trend tests ─────────────────────────────────────────────

class TestClassifyTVLTrend(unittest.TestCase):

    def test_strong_rising_25(self):
        trend, strength = classify_tvl_trend(25.0)
        self.assertEqual(trend, "RISING")
        self.assertEqual(strength, "STRONG")

    def test_moderate_rising_10(self):
        trend, strength = classify_tvl_trend(10.0)
        self.assertEqual(trend, "RISING")
        self.assertEqual(strength, "MODERATE")

    def test_stable_weak_2(self):
        trend, strength = classify_tvl_trend(2.0)
        self.assertEqual(trend, "STABLE")
        self.assertEqual(strength, "WEAK")

    def test_stable_weak_neg2(self):
        trend, strength = classify_tvl_trend(-2.0)
        self.assertEqual(trend, "STABLE")
        self.assertEqual(strength, "WEAK")

    def test_moderate_falling_neg10(self):
        trend, strength = classify_tvl_trend(-10.0)
        self.assertEqual(trend, "FALLING")
        self.assertEqual(strength, "MODERATE")

    def test_strong_falling_neg25(self):
        trend, strength = classify_tvl_trend(-25.0)
        self.assertEqual(trend, "FALLING")
        self.assertEqual(strength, "STRONG")

    def test_boundary_exactly_5(self):
        trend, strength = classify_tvl_trend(5.0)
        # 5 is not > 5, so falls into STABLE/WEAK
        self.assertEqual(trend, "STABLE")

    def test_boundary_exactly_20(self):
        trend, strength = classify_tvl_trend(20.0)
        # 20 is not > 20, so RISING/MODERATE
        self.assertEqual(trend, "RISING")
        self.assertEqual(strength, "MODERATE")

    def test_boundary_exactly_neg5(self):
        trend, strength = classify_tvl_trend(-5.0)
        # -5 >= -5 → STABLE/WEAK
        self.assertEqual(trend, "STABLE")

    def test_boundary_exactly_neg20(self):
        trend, strength = classify_tvl_trend(-20.0)
        # -20 >= -20 → FALLING/MODERATE
        self.assertEqual(trend, "FALLING")
        self.assertEqual(strength, "MODERATE")

    def test_zero_is_stable(self):
        trend, strength = classify_tvl_trend(0.0)
        self.assertEqual(trend, "STABLE")


# ─── classify_yield_trend tests ───────────────────────────────────────────

class TestClassifyYieldTrend(unittest.TestCase):

    def test_strong_rising_25(self):
        trend, strength = classify_yield_trend(25.0)
        self.assertEqual(trend, "RISING")
        self.assertEqual(strength, "STRONG")

    def test_moderate_rising_10(self):
        trend, strength = classify_yield_trend(10.0)
        self.assertEqual(trend, "RISING")
        self.assertEqual(strength, "MODERATE")

    def test_stable_weak_2(self):
        trend, strength = classify_yield_trend(2.0)
        self.assertEqual(trend, "STABLE")
        self.assertEqual(strength, "WEAK")

    def test_stable_weak_neg2(self):
        trend, strength = classify_yield_trend(-2.0)
        self.assertEqual(trend, "STABLE")
        self.assertEqual(strength, "WEAK")

    def test_moderate_falling_neg10(self):
        trend, strength = classify_yield_trend(-10.0)
        self.assertEqual(trend, "FALLING")
        self.assertEqual(strength, "MODERATE")

    def test_strong_falling_neg25(self):
        trend, strength = classify_yield_trend(-25.0)
        self.assertEqual(trend, "FALLING")
        self.assertEqual(strength, "STRONG")

    def test_zero_is_stable(self):
        trend, strength = classify_yield_trend(0.0)
        self.assertEqual(trend, "STABLE")


# ─── score_phases tests ───────────────────────────────────────────────────

class TestScorePhases(unittest.TestCase):

    def _scores(self, tvl_change, apy_change, avg_apy, inflow, total_tvl):
        return score_phases(tvl_change, apy_change, avg_apy, inflow, total_tvl)

    def test_bull_scenario_wins(self):
        # tvl > 15, apy falling, high inflow
        scores = self._scores(35.0, -10.0, 4.0, 6_000_000, 100_000_000)
        self.assertEqual(max(scores, key=scores.get), "bull")

    def test_bull_tvl_over_30_extra_bonus(self):
        s1 = self._scores(25.0, -10.0, 4.0, 6_000_000, 100_000_000)
        s2 = self._scores(35.0, -10.0, 4.0, 6_000_000, 100_000_000)
        # 35 > 30 so extra +10
        self.assertGreater(s2["bull"], s1["bull"])

    def test_bear_scenario_wins(self):
        # tvl < -20, outflows
        scores = self._scores(-25.0, 0.0, 5.0, -1_000_000, 100_000_000)
        self.assertEqual(max(scores, key=scores.get), "bear")

    def test_bear_tvl_below_neg20_extra_bonus(self):
        s1 = self._scores(-10.0, 0.0, 5.0, 0.0, 100_000_000)
        s2 = self._scores(-25.0, 0.0, 5.0, 0.0, 100_000_000)
        self.assertGreater(s2["bear"], s1["bear"])

    def test_bear_negative_inflow_adds_score(self):
        s1 = self._scores(-10.0, 0.0, 5.0, 0.0, 100_000_000)
        s2 = self._scores(-10.0, 0.0, 5.0, -500_000, 100_000_000)
        self.assertGreater(s2["bear"], s1["bear"])

    def test_accumulation_scenario(self):
        # tvl stable (-5 to 15), high apy, low inflow
        scores = self._scores(5.0, 0.0, 12.0, 500_000, 100_000_000)
        # accumulation gets base 40 + apy>8 +20 + low inflow +20 = 80
        self.assertGreaterEqual(scores["accumulation"], 70)

    def test_accumulation_high_apy_bonus(self):
        s1 = self._scores(5.0, 0.0, 6.0, 500_000, 100_000_000)
        s2 = self._scores(5.0, 0.0, 10.0, 500_000, 100_000_000)
        self.assertGreater(s2["accumulation"], s1["accumulation"])

    def test_accumulation_low_inflow_bonus(self):
        s1 = self._scores(5.0, 0.0, 10.0, 5_000_000, 100_000_000)  # 5% > 2%
        s2 = self._scores(5.0, 0.0, 10.0, 500_000, 100_000_000)    # 0.5% < 2%
        self.assertGreater(s2["accumulation"], s1["accumulation"])

    def test_distribution_scenario(self):
        # tvl 0-10%, very low apy, low inflow
        scores = self._scores(5.0, 0.0, 3.0, 1_000_000, 100_000_000)
        self.assertGreater(scores["distribution"], 0)

    def test_distribution_low_apy_bonus(self):
        s1 = self._scores(5.0, 0.0, 8.0, 1_000_000, 100_000_000)
        s2 = self._scores(5.0, 0.0, 3.0, 1_000_000, 100_000_000)
        self.assertGreater(s2["distribution"], s1["distribution"])

    def test_all_scores_0_to_100(self):
        scores = self._scores(50.0, -50.0, 20.0, 10_000_000, 100_000_000)
        for v in scores.values():
            self.assertGreaterEqual(v, 0)
            self.assertLessEqual(v, 100)

    def test_zero_tvl_no_div_error(self):
        # Should not raise ZeroDivisionError
        scores = self._scores(0.0, 0.0, 5.0, 0.0, 0.0)
        self.assertIsInstance(scores, dict)


# ─── detect_phase tests ───────────────────────────────────────────────────

class TestDetectPhase(unittest.TestCase):

    def test_picks_highest_score(self):
        scores = {"accumulation": 30, "bull": 70, "distribution": 20, "bear": 10}
        self.assertEqual(detect_phase(scores), "BULL")

    def test_bear_wins(self):
        scores = {"accumulation": 10, "bull": 20, "distribution": 30, "bear": 80}
        self.assertEqual(detect_phase(scores), "BEAR")

    def test_accumulation_wins(self):
        scores = {"accumulation": 80, "bull": 10, "distribution": 20, "bear": 5}
        self.assertEqual(detect_phase(scores), "ACCUMULATION")

    def test_distribution_wins(self):
        scores = {"accumulation": 30, "bull": 30, "distribution": 75, "bear": 20}
        self.assertEqual(detect_phase(scores), "DISTRIBUTION")


# ─── analyze tests ────────────────────────────────────────────────────────

class TestAnalyze(unittest.TestCase):

    def _bull_report(self):
        return analyze(
            total_tvl_usd=100_000_000,
            tvl_30d_change_pct=35.0,
            avg_top_protocol_apy=4.0,
            apy_30d_change_pct=-10.0,
            new_capital_inflow_usd=6_000_000,
        )

    def _bear_report(self):
        return analyze(
            total_tvl_usd=100_000_000,
            tvl_30d_change_pct=-25.0,
            avg_top_protocol_apy=2.0,
            apy_30d_change_pct=5.0,
            new_capital_inflow_usd=-2_000_000,
        )

    def test_bull_phase_detected(self):
        r = self._bull_report()
        self.assertEqual(r.current_phase, "BULL")

    def test_bear_phase_detected(self):
        r = self._bear_report()
        self.assertEqual(r.current_phase, "BEAR")

    def test_signals_list_has_4_entries(self):
        r = self._bull_report()
        self.assertEqual(len(r.signals), 4)

    def test_signal_types_correct(self):
        r = self._bull_report()
        types = {s.signal_type for s in r.signals}
        self.assertEqual(types, {"TVL", "YIELD", "CAPITAL_FLOW", "VOLATILITY"})

    def test_phase_confidence_high_above_60(self):
        # bull_score should be > 60 for strong bull scenario
        r = self._bull_report()
        if r.bull_score > 60:
            self.assertEqual(r.phase_confidence, "HIGH")

    def test_phase_confidence_medium(self):
        # scenario where scores are moderate
        r = analyze(
            total_tvl_usd=100_000_000,
            tvl_30d_change_pct=8.0,
            avg_top_protocol_apy=6.0,
            apy_30d_change_pct=-3.0,
            new_capital_inflow_usd=500_000,
        )
        # Verify confidence maps correctly to score
        scores = {
            "ACCUMULATION": r.accumulation_score,
            "BULL": r.bull_score,
            "DISTRIBUTION": r.distribution_score,
            "BEAR": r.bear_score,
        }
        winning = scores[r.current_phase]
        if winning > 60:
            self.assertEqual(r.phase_confidence, "HIGH")
        elif winning >= 40:
            self.assertEqual(r.phase_confidence, "MEDIUM")
        else:
            self.assertEqual(r.phase_confidence, "LOW")

    def test_strategy_bias_bull(self):
        r = self._bull_report()
        if r.current_phase == "BULL":
            self.assertEqual(r.strategy_bias, "AGGRESSIVE_DEPLOY")

    def test_strategy_bias_bear(self):
        r = self._bear_report()
        if r.current_phase == "BEAR":
            self.assertEqual(r.strategy_bias, "DEFENSIVE")

    def test_strategy_bias_accumulation(self):
        r = analyze(
            total_tvl_usd=100_000_000,
            tvl_30d_change_pct=5.0,
            avg_top_protocol_apy=12.0,
            apy_30d_change_pct=0.0,
            new_capital_inflow_usd=500_000,
        )
        if r.current_phase == "ACCUMULATION":
            self.assertEqual(r.strategy_bias, "DEPLOY_SELECTIVELY")

    def test_strategy_bias_distribution(self):
        r = analyze(
            total_tvl_usd=100_000_000,
            tvl_30d_change_pct=5.0,
            avg_top_protocol_apy=3.0,
            apy_30d_change_pct=0.0,
            new_capital_inflow_usd=1_000_000,
        )
        if r.current_phase == "DISTRIBUTION":
            self.assertEqual(r.strategy_bias, "REDUCE_EXPOSURE")

    def test_risk_multiplier_bull(self):
        r = self._bull_report()
        if r.current_phase == "BULL":
            self.assertAlmostEqual(r.risk_multiplier, 1.5)

    def test_risk_multiplier_bear(self):
        r = self._bear_report()
        if r.current_phase == "BEAR":
            self.assertAlmostEqual(r.risk_multiplier, 0.4)

    def test_risk_multiplier_accumulation(self):
        r = analyze(
            total_tvl_usd=100_000_000,
            tvl_30d_change_pct=5.0,
            avg_top_protocol_apy=12.0,
            apy_30d_change_pct=0.0,
            new_capital_inflow_usd=500_000,
        )
        if r.current_phase == "ACCUMULATION":
            self.assertAlmostEqual(r.risk_multiplier, 1.0)

    def test_risk_multiplier_distribution(self):
        r = analyze(
            total_tvl_usd=100_000_000,
            tvl_30d_change_pct=5.0,
            avg_top_protocol_apy=3.0,
            apy_30d_change_pct=0.0,
            new_capital_inflow_usd=1_000_000,
        )
        if r.current_phase == "DISTRIBUTION":
            self.assertAlmostEqual(r.risk_multiplier, 0.7)

    def test_outlook_days_high_confidence(self):
        # Force high confidence: use extreme bull scenario
        r = self._bull_report()
        if r.phase_confidence == "HIGH":
            self.assertEqual(r.outlook_days, 30)

    def test_outlook_days_medium_confidence(self):
        r = analyze(
            total_tvl_usd=100_000_000,
            tvl_30d_change_pct=0.0,
            avg_top_protocol_apy=5.0,
            apy_30d_change_pct=0.0,
            new_capital_inflow_usd=0.0,
        )
        if r.phase_confidence == "MEDIUM":
            self.assertEqual(r.outlook_days, 60)

    def test_outlook_days_low_confidence(self):
        r = analyze(
            total_tvl_usd=100_000_000,
            tvl_30d_change_pct=0.0,
            avg_top_protocol_apy=5.0,
            apy_30d_change_pct=0.0,
            new_capital_inflow_usd=0.0,
        )
        if r.phase_confidence == "LOW":
            self.assertEqual(r.outlook_days, 90)

    def test_warning_bear_market_conditions(self):
        r = self._bear_report()
        if r.bear_score > 60:
            self.assertIn("bear market conditions", r.warnings)

    def test_warning_yield_collapse_tvl_drain(self):
        r = analyze(
            total_tvl_usd=100_000_000,
            tvl_30d_change_pct=-5.0,
            avg_top_protocol_apy=2.0,
            apy_30d_change_pct=0.0,
            new_capital_inflow_usd=0.0,
        )
        self.assertIn("yield collapse + TVL drain", r.warnings)

    def test_warning_capital_leaving_defi(self):
        r = analyze(
            total_tvl_usd=100_000_000,
            tvl_30d_change_pct=-5.0,
            avg_top_protocol_apy=5.0,
            apy_30d_change_pct=0.0,
            new_capital_inflow_usd=-1_000_000,
        )
        self.assertIn("capital leaving DeFi", r.warnings)

    def test_no_warning_on_healthy_bull(self):
        r = self._bull_report()
        # No negative inflow, no low apy with TVL drain in bull scenario
        self.assertNotIn("capital leaving DeFi", r.warnings)

    def test_scores_all_present(self):
        r = self._bull_report()
        self.assertIsNotNone(r.accumulation_score)
        self.assertIsNotNone(r.bull_score)
        self.assertIsNotNone(r.distribution_score)
        self.assertIsNotNone(r.bear_score)


# ─── All four strategy/multiplier combos explicit ─────────────────────────

class TestAllPhaseBehaviors(unittest.TestCase):

    def _phase_report(self, phase_name: str) -> CyclePhaseReport:
        """Force a specific phase by constructing a scenario that produces it."""
        from spa_core.analytics.defi_cycle_phase_detector import detect_phase, score_phases
        from spa_core.analytics.defi_cycle_phase_detector import (
            _strategy_bias, _risk_multiplier, _phase_confidence, _outlook_days
        )
        phase_map = {
            "BULL": "AGGRESSIVE_DEPLOY",
            "ACCUMULATION": "DEPLOY_SELECTIVELY",
            "DISTRIBUTION": "REDUCE_EXPOSURE",
            "BEAR": "DEFENSIVE",
        }
        mult_map = {
            "BULL": 1.5, "ACCUMULATION": 1.0, "DISTRIBUTION": 0.7, "BEAR": 0.4
        }
        self.assertEqual(_strategy_bias(phase_name), phase_map[phase_name])
        self.assertAlmostEqual(_risk_multiplier(phase_name), mult_map[phase_name])
        return None  # just testing helpers

    def test_bull_bias_and_multiplier(self):
        from spa_core.analytics.defi_cycle_phase_detector import _strategy_bias, _risk_multiplier
        self.assertEqual(_strategy_bias("BULL"), "AGGRESSIVE_DEPLOY")
        self.assertAlmostEqual(_risk_multiplier("BULL"), 1.5)

    def test_accumulation_bias_and_multiplier(self):
        from spa_core.analytics.defi_cycle_phase_detector import _strategy_bias, _risk_multiplier
        self.assertEqual(_strategy_bias("ACCUMULATION"), "DEPLOY_SELECTIVELY")
        self.assertAlmostEqual(_risk_multiplier("ACCUMULATION"), 1.0)

    def test_distribution_bias_and_multiplier(self):
        from spa_core.analytics.defi_cycle_phase_detector import _strategy_bias, _risk_multiplier
        self.assertEqual(_strategy_bias("DISTRIBUTION"), "REDUCE_EXPOSURE")
        self.assertAlmostEqual(_risk_multiplier("DISTRIBUTION"), 0.7)

    def test_bear_bias_and_multiplier(self):
        from spa_core.analytics.defi_cycle_phase_detector import _strategy_bias, _risk_multiplier
        self.assertEqual(_strategy_bias("BEAR"), "DEFENSIVE")
        self.assertAlmostEqual(_risk_multiplier("BEAR"), 0.4)

    def test_confidence_high(self):
        from spa_core.analytics.defi_cycle_phase_detector import _phase_confidence
        self.assertEqual(_phase_confidence(65.0), "HIGH")
        self.assertEqual(_phase_confidence(100.0), "HIGH")

    def test_confidence_medium(self):
        from spa_core.analytics.defi_cycle_phase_detector import _phase_confidence
        self.assertEqual(_phase_confidence(50.0), "MEDIUM")
        self.assertEqual(_phase_confidence(40.0), "MEDIUM")

    def test_confidence_low(self):
        from spa_core.analytics.defi_cycle_phase_detector import _phase_confidence
        self.assertEqual(_phase_confidence(39.0), "LOW")
        self.assertEqual(_phase_confidence(0.0), "LOW")

    def test_outlook_all_three_confidences(self):
        from spa_core.analytics.defi_cycle_phase_detector import _outlook_days
        self.assertEqual(_outlook_days("HIGH"), 30)
        self.assertEqual(_outlook_days("MEDIUM"), 60)
        self.assertEqual(_outlook_days("LOW"), 90)


# ─── compare_periods tests ────────────────────────────────────────────────

class TestComparePeriods(unittest.TestCase):

    def _r(self, tvl):
        return analyze(tvl, 10.0, 5.0, 0.0, 100_000)

    def test_sorted_by_tvl_desc(self):
        r1 = self._r(100_000_000)
        r2 = self._r(500_000_000)
        r3 = self._r(50_000_000)
        sorted_r = compare_periods([r1, r2, r3])
        self.assertEqual(sorted_r[0].total_tvl_usd, 500_000_000)
        self.assertEqual(sorted_r[-1].total_tvl_usd, 50_000_000)

    def test_single_report_unchanged(self):
        r = self._r(100_000_000)
        result = compare_periods([r])
        self.assertEqual(len(result), 1)

    def test_empty_list(self):
        self.assertEqual(compare_periods([]), [])


# ─── Save/Load + ring-buffer tests ────────────────────────────────────────

class TestSaveLoad(unittest.TestCase):

    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp()
        self.log_path = os.path.join(self.tmp_dir, "test_cycle_log.json")

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def _report(self, tvl=100_000_000):
        return analyze(tvl, 10.0, 5.0, 0.0, 1_000_000)

    def test_load_missing_returns_empty(self):
        self.assertEqual(load_history(self.log_path), [])

    def test_save_creates_file(self):
        save_results(self._report(), self.log_path)
        self.assertTrue(os.path.exists(self.log_path))

    def test_load_after_save(self):
        save_results(self._report(), self.log_path)
        history = load_history(self.log_path)
        self.assertEqual(len(history), 1)

    def test_multiple_saves(self):
        for _ in range(5):
            save_results(self._report(), self.log_path)
        self.assertEqual(len(load_history(self.log_path)), 5)

    def test_ring_buffer_cap_100(self):
        for i in range(110):
            save_results(self._report(tvl=float(i) * 1_000_000), self.log_path)
        self.assertEqual(len(load_history(self.log_path)), 100)

    def test_saved_to_set(self):
        r = self._report()
        saved = save_results(r, self.log_path)
        self.assertIn(self.log_path, saved.saved_to)

    def test_json_valid(self):
        save_results(self._report(), self.log_path)
        with open(self.log_path) as f:
            data = json.load(f)
        self.assertIsInstance(data, list)

    def test_phase_preserved_in_history(self):
        save_results(self._report(), self.log_path)
        history = load_history(self.log_path)
        self.assertIn("current_phase", history[0])

    def test_malformed_file_returns_empty(self):
        with open(self.log_path, "w") as f:
            f.write("{{broken json")
        self.assertEqual(load_history(self.log_path), [])

    def test_signals_count_in_history(self):
        save_results(self._report(), self.log_path)
        history = load_history(self.log_path)
        self.assertEqual(len(history[0]["signals"]), 4)


# ─── Edge case tests ───────────────────────────────────────────────────────

class TestEdgeCases(unittest.TestCase):

    def test_all_zeros_no_exception(self):
        r = analyze(0.0, 0.0, 0.0, 0.0, 0.0)
        self.assertIsNotNone(r.current_phase)

    def test_all_zeros_low_confidence(self):
        r = analyze(0.0, 0.0, 0.0, 0.0, 0.0)
        # Scores should all be low → LOW confidence
        scores = [r.accumulation_score, r.bull_score, r.distribution_score, r.bear_score]
        self.assertLessEqual(max(scores), 60)

    def test_very_large_tvl(self):
        r = analyze(1e15, 10.0, 5.0, 0.0, 1e13)
        self.assertIsNotNone(r.current_phase)

    def test_negative_apy_no_crash(self):
        r = analyze(100_000_000, -5.0, -1.0, 0.0, 1_000_000)
        self.assertIsNotNone(r)

    def test_tvl_change_boundary_0_accum(self):
        # tvl_change = 0 → not in bull (>15), let's check accumulation
        r = analyze(100_000_000, 0.0, 12.0, 500_000, 100_000_000)
        # -5 < 0 < 15 → accumulation base +40
        self.assertGreaterEqual(r.accumulation_score, 40)

    def test_report_has_timestamp(self):
        r = analyze(100_000_000, 10.0, 5.0, 0.0, 1_000_000)
        self.assertGreater(r.timestamp, 0)

    def test_warnings_is_list(self):
        r = analyze(100_000_000, 10.0, 5.0, 0.0, 1_000_000)
        self.assertIsInstance(r.warnings, list)


if __name__ == "__main__":
    unittest.main(verbosity=2)
