"""
Tests for MP-946: DeFiImpermanentLossHedgingAnalyzer
Run: python3 -m unittest spa_core.tests.test_defi_impermanent_loss_hedging_analyzer -v
"""

import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from spa_core.analytics.defi_impermanent_loss_hedging_analyzer import (
    DeFiImpermanentLossHedgingAnalyzer,
    _clamp,
    _has_real_hedge,
    _compute_hedge_efficiency_score,
    _compute_net_hedged_apy,
    _compute_hedge_value_pct,
    _determine_recommendation,
    _determine_label,
    _compute_flags,
    _analyze_position,
    _compute_aggregates,
    _write_log,
    DEFAULT_CONFIG,
    LABEL_EFFECTIVE_HEDGE,
    LABEL_PARTIAL_HEDGE,
    LABEL_EXPENSIVE_HEDGE,
    LABEL_UNNECESSARY,
    LABEL_NO_HEDGE_AVAILABLE,
    FLAG_HIGH_IL,
    FLAG_CORRELATED_PAIR,
    FLAG_HEDGE_PROFITABLE,
    FLAG_COST_EXCEEDS_IL,
    FLAG_LOW_CORR_HIGH_RISK,
    REC_HEDGE,
    REC_PARTIAL,
    REC_SKIP,
)


def make_position(**kwargs):
    """Create a minimal valid position dict."""
    base = {
        "pair": "ETH/USDC",
        "token_a": "ETH",
        "token_b": "USDC",
        "lp_value_usd": 100000.0,
        "il_pct": 4.0,
        "correlation_ab": 0.5,
        "available_hedges": ["perpetual_short", "options_put"],
        "hedge_cost_annual_pct": 2.0,
        "hedge_coverage_pct": 75.0,
        "apy_with_hedge_pct": 12.0,
        "apy_without_hedge_pct": 10.0,
    }
    base.update(kwargs)
    return base


class TestClamp(unittest.TestCase):
    def test_clamp_within_range(self):
        self.assertEqual(_clamp(5.0, 0.0, 10.0), 5.0)

    def test_clamp_below_min(self):
        self.assertEqual(_clamp(-1.0, 0.0, 10.0), 0.0)

    def test_clamp_above_max(self):
        self.assertEqual(_clamp(15.0, 0.0, 10.0), 10.0)

    def test_clamp_at_boundaries(self):
        self.assertEqual(_clamp(0.0, 0.0, 10.0), 0.0)
        self.assertEqual(_clamp(10.0, 0.0, 10.0), 10.0)

    def test_clamp_equal_bounds(self):
        self.assertEqual(_clamp(5.0, 3.0, 3.0), 3.0)


class TestHasRealHedge(unittest.TestCase):
    def test_has_real_hedge_perpetual(self):
        self.assertTrue(_has_real_hedge(["perpetual_short"]))

    def test_has_real_hedge_options(self):
        self.assertTrue(_has_real_hedge(["options_put"]))

    def test_has_real_hedge_none_only(self):
        self.assertFalse(_has_real_hedge(["none"]))

    def test_has_real_hedge_empty(self):
        self.assertFalse(_has_real_hedge([]))

    def test_has_real_hedge_mixed(self):
        self.assertTrue(_has_real_hedge(["none", "delta_neutral"]))

    def test_has_real_hedge_multiple(self):
        self.assertTrue(_has_real_hedge(["perpetual_short", "options_put", "rebalancing"]))

    def test_has_real_hedge_delta_neutral(self):
        self.assertTrue(_has_real_hedge(["delta_neutral"]))


class TestHedgeEfficiencyScore(unittest.TestCase):
    def test_high_coverage_low_cost(self):
        score = _compute_hedge_efficiency_score(80.0, 5.0)
        self.assertAlmostEqual(score, 75.0, places=3)

    def test_coverage_equals_cost(self):
        score = _compute_hedge_efficiency_score(10.0, 10.0)
        self.assertAlmostEqual(score, 0.0, places=3)

    def test_cost_exceeds_coverage(self):
        score = _compute_hedge_efficiency_score(5.0, 20.0)
        self.assertAlmostEqual(score, 0.0, places=3)  # clamped to 0

    def test_full_efficiency(self):
        score = _compute_hedge_efficiency_score(100.0, 0.0)
        self.assertAlmostEqual(score, 100.0, places=3)

    def test_clamped_maximum(self):
        score = _compute_hedge_efficiency_score(110.0, 0.0)
        self.assertAlmostEqual(score, 100.0, places=3)


class TestNetHedgedApy(unittest.TestCase):
    def test_basic_computation(self):
        result = _compute_net_hedged_apy(12.0, 2.0)
        self.assertAlmostEqual(result, 10.0, places=4)

    def test_zero_cost(self):
        result = _compute_net_hedged_apy(8.0, 0.0)
        self.assertAlmostEqual(result, 8.0, places=4)

    def test_negative_net(self):
        result = _compute_net_hedged_apy(3.0, 5.0)
        self.assertAlmostEqual(result, -2.0, places=4)

    def test_large_values(self):
        result = _compute_net_hedged_apy(50.0, 10.0)
        self.assertAlmostEqual(result, 40.0, places=4)


class TestHedgeValuePct(unittest.TestCase):
    def test_equal_performance(self):
        val = _compute_hedge_value_pct(10.0, 10.0)
        self.assertAlmostEqual(val, 0.0, places=5)

    def test_hedge_better(self):
        val = _compute_hedge_value_pct(12.0, 10.0)
        self.assertAlmostEqual(val, 0.2, places=5)

    def test_hedge_worse(self):
        val = _compute_hedge_value_pct(8.0, 10.0)
        self.assertAlmostEqual(val, -0.2, places=5)

    def test_zero_without_apy(self):
        val = _compute_hedge_value_pct(5.0, 0.0)
        self.assertAlmostEqual(val, 0.0, places=5)

    def test_negative_without_apy(self):
        val = _compute_hedge_value_pct(5.0, -0.0)
        self.assertAlmostEqual(val, 0.0, places=5)


class TestDetermineRecommendation(unittest.TestCase):
    def test_hedge_when_profitable(self):
        rec = _determine_recommendation(0.1, 80.0, DEFAULT_CONFIG)
        self.assertEqual(rec, REC_HEDGE)

    def test_partial_when_slight_loss_high_coverage(self):
        rec = _determine_recommendation(-0.05, 60.0, DEFAULT_CONFIG)
        self.assertEqual(rec, REC_PARTIAL)

    def test_skip_when_big_loss(self):
        rec = _determine_recommendation(-0.5, 40.0, DEFAULT_CONFIG)
        self.assertEqual(rec, REC_SKIP)

    def test_skip_when_slight_loss_low_coverage(self):
        rec = _determine_recommendation(-0.05, 40.0, DEFAULT_CONFIG)
        self.assertEqual(rec, REC_SKIP)

    def test_hedge_exactly_at_threshold(self):
        cfg = {**DEFAULT_CONFIG, "profitable_hedge_value_threshold": 0.0}
        rec = _determine_recommendation(0.001, 50.0, cfg)
        self.assertEqual(rec, REC_HEDGE)


class TestDetermineLabel(unittest.TestCase):
    def test_effective_hedge(self):
        pos = make_position(
            il_pct=10.0,
            hedge_cost_annual_pct=5.0,
            hedge_coverage_pct=80.0,
            available_hedges=["perpetual_short"],
        )
        label = _determine_label(pos, 75.0, DEFAULT_CONFIG)
        self.assertEqual(label, LABEL_EFFECTIVE_HEDGE)

    def test_partial_hedge(self):
        pos = make_position(
            il_pct=8.0,
            hedge_cost_annual_pct=4.0,
            hedge_coverage_pct=50.0,
            available_hedges=["options_put"],
        )
        label = _determine_label(pos, 46.0, DEFAULT_CONFIG)
        self.assertEqual(label, LABEL_PARTIAL_HEDGE)

    def test_no_hedge_available(self):
        pos = make_position(
            il_pct=10.0,
            available_hedges=["none"],
        )
        label = _determine_label(pos, 50.0, DEFAULT_CONFIG)
        self.assertEqual(label, LABEL_NO_HEDGE_AVAILABLE)

    def test_no_hedge_empty(self):
        pos = make_position(
            il_pct=10.0,
            available_hedges=[],
        )
        label = _determine_label(pos, 50.0, DEFAULT_CONFIG)
        self.assertEqual(label, LABEL_NO_HEDGE_AVAILABLE)

    def test_unnecessary_low_il(self):
        pos = make_position(
            il_pct=1.0,
            hedge_cost_annual_pct=2.0,
            available_hedges=["perpetual_short"],
        )
        label = _determine_label(pos, 50.0, DEFAULT_CONFIG)
        self.assertEqual(label, LABEL_UNNECESSARY)

    def test_expensive_hedge(self):
        pos = make_position(
            il_pct=3.0,
            hedge_cost_annual_pct=8.0,
            hedge_coverage_pct=50.0,
            available_hedges=["options_put"],
        )
        label = _determine_label(pos, 42.0, DEFAULT_CONFIG)
        self.assertEqual(label, LABEL_EXPENSIVE_HEDGE)


class TestComputeFlags(unittest.TestCase):
    def test_high_il_flag(self):
        pos = make_position(il_pct=6.0, correlation_ab=0.5, lp_value_usd=10000.0,
                            hedge_cost_annual_pct=2.0)
        flags = _compute_flags(pos, 0.1, DEFAULT_CONFIG)
        self.assertIn(FLAG_HIGH_IL, flags)

    def test_correlated_pair_flag(self):
        pos = make_position(il_pct=3.0, correlation_ab=0.8, lp_value_usd=10000.0,
                            hedge_cost_annual_pct=2.0)
        flags = _compute_flags(pos, 0.1, DEFAULT_CONFIG)
        self.assertIn(FLAG_CORRELATED_PAIR, flags)

    def test_hedge_profitable_flag(self):
        pos = make_position(il_pct=3.0, correlation_ab=0.5, lp_value_usd=10000.0,
                            hedge_cost_annual_pct=1.0)
        flags = _compute_flags(pos, 0.5, DEFAULT_CONFIG)
        self.assertIn(FLAG_HEDGE_PROFITABLE, flags)

    def test_cost_exceeds_il_flag(self):
        pos = make_position(il_pct=3.0, correlation_ab=0.5, lp_value_usd=10000.0,
                            hedge_cost_annual_pct=5.0)
        flags = _compute_flags(pos, -0.1, DEFAULT_CONFIG)
        self.assertIn(FLAG_COST_EXCEEDS_IL, flags)

    def test_low_corr_high_risk_flag(self):
        pos = make_position(il_pct=3.0, correlation_ab=0.2, lp_value_usd=100000.0,
                            hedge_cost_annual_pct=2.0)
        flags = _compute_flags(pos, -0.1, DEFAULT_CONFIG)
        self.assertIn(FLAG_LOW_CORR_HIGH_RISK, flags)

    def test_low_corr_small_position_no_flag(self):
        pos = make_position(il_pct=3.0, correlation_ab=0.2, lp_value_usd=10000.0,
                            hedge_cost_annual_pct=2.0)
        flags = _compute_flags(pos, -0.1, DEFAULT_CONFIG)
        self.assertNotIn(FLAG_LOW_CORR_HIGH_RISK, flags)

    def test_no_flags_normal_position(self):
        pos = make_position(il_pct=3.0, correlation_ab=0.5, lp_value_usd=10000.0,
                            hedge_cost_annual_pct=1.0)
        flags = _compute_flags(pos, -0.1, DEFAULT_CONFIG)
        self.assertNotIn(FLAG_HIGH_IL, flags)
        self.assertNotIn(FLAG_CORRELATED_PAIR, flags)
        self.assertNotIn(FLAG_LOW_CORR_HIGH_RISK, flags)

    def test_multiple_flags_simultaneously(self):
        pos = make_position(il_pct=6.0, correlation_ab=0.8, lp_value_usd=10000.0,
                            hedge_cost_annual_pct=1.0)
        flags = _compute_flags(pos, 0.5, DEFAULT_CONFIG)
        self.assertIn(FLAG_HIGH_IL, flags)
        self.assertIn(FLAG_CORRELATED_PAIR, flags)
        self.assertIn(FLAG_HEDGE_PROFITABLE, flags)


class TestAnalyzePosition(unittest.TestCase):
    def _run(self, **kwargs):
        pos = make_position(**kwargs)
        return _analyze_position(pos, DEFAULT_CONFIG)

    def test_returns_required_keys(self):
        result = self._run()
        for key in ["hedge_efficiency_score", "net_hedged_apy", "hedge_value_pct",
                    "recommendation", "hedge_label", "flags", "il_exposure_usd"]:
            self.assertIn(key, result)

    def test_il_exposure_usd(self):
        result = self._run(lp_value_usd=100000.0, il_pct=5.0)
        self.assertAlmostEqual(result["il_exposure_usd"], 5000.0, places=2)

    def test_il_exposure_zero_il(self):
        result = self._run(lp_value_usd=100000.0, il_pct=0.0)
        self.assertAlmostEqual(result["il_exposure_usd"], 0.0, places=4)

    def test_pair_preserved(self):
        result = self._run(pair="WBTC/ETH")
        self.assertEqual(result["pair"], "WBTC/ETH")

    def test_token_fields_preserved(self):
        result = self._run(token_a="WBTC", token_b="ETH")
        self.assertEqual(result["token_a"], "WBTC")
        self.assertEqual(result["token_b"], "ETH")

    def test_efficiency_score_positive(self):
        result = self._run(hedge_coverage_pct=80.0, hedge_cost_annual_pct=5.0)
        self.assertGreater(result["hedge_efficiency_score"], 0.0)

    def test_available_hedges_preserved(self):
        result = self._run(available_hedges=["delta_neutral", "rebalancing"])
        self.assertEqual(result["available_hedges"], ["delta_neutral", "rebalancing"])


class TestComputeAggregates(unittest.TestCase):
    def _make_result(self, pair, eff, label, il_usd):
        return {
            "pair": pair,
            "hedge_efficiency_score": eff,
            "hedge_label": label,
            "il_exposure_usd": il_usd,
        }

    def test_empty_list(self):
        agg = _compute_aggregates([], DEFAULT_CONFIG)
        self.assertIsNone(agg["best_hedge_opportunity"])
        self.assertEqual(agg["effective_hedge_count"], 0)
        self.assertEqual(agg["total_il_exposure_usd"], 0.0)

    def test_single_position(self):
        results = [self._make_result("ETH/USDC", 80.0, LABEL_EFFECTIVE_HEDGE, 5000.0)]
        agg = _compute_aggregates(results, DEFAULT_CONFIG)
        self.assertEqual(agg["best_hedge_opportunity"], "ETH/USDC")
        self.assertEqual(agg["least_effective_hedge"], "ETH/USDC")

    def test_best_worst_detection(self):
        results = [
            self._make_result("A/B", 90.0, LABEL_EFFECTIVE_HEDGE, 1000.0),
            self._make_result("C/D", 30.0, LABEL_PARTIAL_HEDGE, 2000.0),
            self._make_result("E/F", 60.0, LABEL_EFFECTIVE_HEDGE, 500.0),
        ]
        agg = _compute_aggregates(results, DEFAULT_CONFIG)
        self.assertEqual(agg["best_hedge_opportunity"], "A/B")
        self.assertEqual(agg["least_effective_hedge"], "C/D")

    def test_total_il_exposure(self):
        results = [
            self._make_result("A/B", 80.0, LABEL_EFFECTIVE_HEDGE, 1000.0),
            self._make_result("C/D", 60.0, LABEL_PARTIAL_HEDGE, 2000.0),
        ]
        agg = _compute_aggregates(results, DEFAULT_CONFIG)
        self.assertAlmostEqual(agg["total_il_exposure_usd"], 3000.0, places=2)

    def test_effective_hedge_count(self):
        results = [
            self._make_result("A/B", 80.0, LABEL_EFFECTIVE_HEDGE, 100.0),
            self._make_result("C/D", 60.0, LABEL_EFFECTIVE_HEDGE, 200.0),
            self._make_result("E/F", 30.0, LABEL_PARTIAL_HEDGE, 300.0),
        ]
        agg = _compute_aggregates(results, DEFAULT_CONFIG)
        self.assertEqual(agg["effective_hedge_count"], 2)

    def test_average_efficiency(self):
        results = [
            self._make_result("A/B", 80.0, LABEL_EFFECTIVE_HEDGE, 100.0),
            self._make_result("C/D", 60.0, LABEL_PARTIAL_HEDGE, 200.0),
        ]
        agg = _compute_aggregates(results, DEFAULT_CONFIG)
        self.assertAlmostEqual(agg["average_hedge_efficiency"], 70.0, places=3)


class TestWriteLog(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.log_path = os.path.join(self.tmpdir, "il_hedging_log.json")

    def test_creates_log_file(self):
        import spa_core.analytics.defi_impermanent_loss_hedging_analyzer as m
        original = m.LOG_PATH
        m.LOG_PATH = self.log_path
        try:
            _write_log({"test": 1})
            self.assertTrue(os.path.exists(self.log_path))
        finally:
            m.LOG_PATH = original

    def test_ring_buffer_cap(self):
        import spa_core.analytics.defi_impermanent_loss_hedging_analyzer as m
        original = m.LOG_PATH
        original_cap = m.LOG_CAP
        m.LOG_PATH = self.log_path
        m.LOG_CAP = 5
        try:
            for i in range(8):
                _write_log({"i": i})
            with open(self.log_path) as f:
                data = json.load(f)
            self.assertEqual(len(data), 5)
            self.assertEqual(data[-1]["i"], 7)
        finally:
            m.LOG_PATH = original
            m.LOG_CAP = original_cap

    def test_atomic_write_tmp_removed(self):
        import spa_core.analytics.defi_impermanent_loss_hedging_analyzer as m
        original = m.LOG_PATH
        m.LOG_PATH = self.log_path
        try:
            _write_log({"test": "atomic"})
            self.assertFalse(os.path.exists(self.log_path + ".tmp"))
        finally:
            m.LOG_PATH = original


class TestDeFiImpermanentLossHedgingAnalyzer(unittest.TestCase):
    def setUp(self):
        self.analyzer = DeFiImpermanentLossHedgingAnalyzer()

    def _make_positions(self, n=1):
        return [make_position(pair=f"TOKEN{i}/USDC") for i in range(n)]

    def test_returns_dict(self):
        result = self.analyzer.analyze(self._make_positions())
        self.assertIsInstance(result, dict)

    def test_required_top_level_keys(self):
        result = self.analyzer.analyze(self._make_positions())
        for key in ["timestamp", "position_count", "positions", "aggregates"]:
            self.assertIn(key, result)

    def test_position_count_matches(self):
        result = self.analyzer.analyze(self._make_positions(3))
        self.assertEqual(result["position_count"], 3)

    def test_empty_positions(self):
        result = self.analyzer.analyze([])
        self.assertEqual(result["position_count"], 0)
        self.assertEqual(result["positions"], [])

    def test_aggregates_present(self):
        result = self.analyzer.analyze(self._make_positions(2))
        agg = result["aggregates"]
        for key in ["best_hedge_opportunity", "least_effective_hedge",
                    "total_il_exposure_usd", "average_hedge_efficiency",
                    "effective_hedge_count"]:
            self.assertIn(key, agg)

    def test_per_position_has_label(self):
        result = self.analyzer.analyze(self._make_positions())
        self.assertIn("hedge_label", result["positions"][0])

    def test_per_position_has_flags(self):
        result = self.analyzer.analyze(self._make_positions())
        self.assertIsInstance(result["positions"][0]["flags"], list)

    def test_per_position_has_recommendation(self):
        result = self.analyzer.analyze(self._make_positions())
        self.assertIn(result["positions"][0]["recommendation"],
                      [REC_HEDGE, REC_PARTIAL, REC_SKIP])

    def test_config_override_high_il_threshold(self):
        pos = [make_position(il_pct=3.0)]
        result = self.analyzer.analyze(pos, {"high_il_threshold_pct": 2.0})
        flags = result["positions"][0]["flags"]
        self.assertIn(FLAG_HIGH_IL, flags)

    def test_config_override_prevents_high_il(self):
        pos = [make_position(il_pct=4.0)]
        result = self.analyzer.analyze(pos, {"high_il_threshold_pct": 10.0})
        flags = result["positions"][0]["flags"]
        self.assertNotIn(FLAG_HIGH_IL, flags)

    def test_effective_hedge_position(self):
        pos = [make_position(
            il_pct=10.0,
            hedge_cost_annual_pct=5.0,
            hedge_coverage_pct=90.0,
            apy_with_hedge_pct=15.0,
            apy_without_hedge_pct=10.0,
            available_hedges=["perpetual_short"],
        )]
        result = self.analyzer.analyze(pos)
        self.assertEqual(result["positions"][0]["hedge_label"], LABEL_EFFECTIVE_HEDGE)

    def test_no_hedge_available_position(self):
        pos = [make_position(
            available_hedges=["none"],
            il_pct=10.0,
        )]
        result = self.analyzer.analyze(pos)
        self.assertEqual(result["positions"][0]["hedge_label"], LABEL_NO_HEDGE_AVAILABLE)

    def test_unnecessary_low_il_position(self):
        pos = [make_position(
            il_pct=1.5,
            available_hedges=["perpetual_short"],
        )]
        result = self.analyzer.analyze(pos)
        self.assertEqual(result["positions"][0]["hedge_label"], LABEL_UNNECESSARY)

    def test_expensive_hedge_position(self):
        pos = [make_position(
            il_pct=3.0,
            hedge_cost_annual_pct=10.0,
            hedge_coverage_pct=50.0,
            available_hedges=["options_put"],
        )]
        result = self.analyzer.analyze(pos)
        self.assertEqual(result["positions"][0]["hedge_label"], LABEL_EXPENSIVE_HEDGE)

    def test_il_exposure_calculation(self):
        pos = [make_position(lp_value_usd=200000.0, il_pct=5.0)]
        result = self.analyzer.analyze(pos)
        self.assertAlmostEqual(result["positions"][0]["il_exposure_usd"], 10000.0, places=1)

    def test_total_il_exposure_summed(self):
        pos = [
            make_position(lp_value_usd=100000.0, il_pct=4.0, pair="A/B"),
            make_position(lp_value_usd=50000.0, il_pct=6.0, pair="C/D"),
        ]
        result = self.analyzer.analyze(pos)
        # 4000 + 3000 = 7000
        self.assertAlmostEqual(
            result["aggregates"]["total_il_exposure_usd"], 7000.0, places=1
        )

    def test_net_hedged_apy_in_result(self):
        pos = [make_position(apy_with_hedge_pct=12.0, hedge_cost_annual_pct=2.0)]
        result = self.analyzer.analyze(pos)
        self.assertAlmostEqual(result["positions"][0]["net_hedged_apy"], 10.0, places=4)

    def test_hedge_value_pct_positive_when_hedge_better(self):
        pos = [make_position(apy_with_hedge_pct=15.0, hedge_cost_annual_pct=2.0,
                             apy_without_hedge_pct=10.0)]
        result = self.analyzer.analyze(pos)
        self.assertGreater(result["positions"][0]["hedge_value_pct"], 0.0)

    def test_recommendation_hedge_when_profitable(self):
        pos = [make_position(apy_with_hedge_pct=15.0, hedge_cost_annual_pct=2.0,
                             apy_without_hedge_pct=10.0, hedge_coverage_pct=80.0)]
        result = self.analyzer.analyze(pos)
        self.assertEqual(result["positions"][0]["recommendation"], REC_HEDGE)

    def test_recommendation_skip_when_expensive(self):
        pos = [make_position(apy_with_hedge_pct=8.0, hedge_cost_annual_pct=5.0,
                             apy_without_hedge_pct=10.0, hedge_coverage_pct=30.0)]
        result = self.analyzer.analyze(pos)
        self.assertEqual(result["positions"][0]["recommendation"], REC_SKIP)

    def test_multiple_positions_aggregates(self):
        pos = [
            make_position(pair="A/B", hedge_coverage_pct=90.0, hedge_cost_annual_pct=5.0,
                          il_pct=10.0, available_hedges=["perpetual_short"]),
            make_position(pair="C/D", hedge_coverage_pct=50.0, hedge_cost_annual_pct=3.0,
                          il_pct=8.0, available_hedges=["options_put"]),
            make_position(pair="E/F", hedge_coverage_pct=80.0, hedge_cost_annual_pct=2.0,
                          il_pct=7.0, available_hedges=["delta_neutral"]),
        ]
        result = self.analyzer.analyze(pos)
        agg = result["aggregates"]
        self.assertIsNotNone(agg["best_hedge_opportunity"])
        self.assertIsNotNone(agg["least_effective_hedge"])

    def test_high_correlation_gets_correlated_flag(self):
        pos = [make_position(correlation_ab=0.9, il_pct=4.0)]
        result = self.analyzer.analyze(pos)
        self.assertIn(FLAG_CORRELATED_PAIR, result["positions"][0]["flags"])

    def test_low_correlation_high_value_gets_risk_flag(self):
        pos = [make_position(correlation_ab=0.2, lp_value_usd=100000.0, il_pct=4.0)]
        result = self.analyzer.analyze(pos)
        self.assertIn(FLAG_LOW_CORR_HIGH_RISK, result["positions"][0]["flags"])

    def test_timestamp_in_output(self):
        result = self.analyzer.analyze(self._make_positions())
        self.assertIn("timestamp", result)
        self.assertIsInstance(result["timestamp"], str)

    def test_efficiency_score_range(self):
        pos = [make_position(hedge_coverage_pct=80.0, hedge_cost_annual_pct=5.0)]
        result = self.analyzer.analyze(pos)
        score = result["positions"][0]["hedge_efficiency_score"]
        self.assertGreaterEqual(score, 0.0)
        self.assertLessEqual(score, 100.0)

    def test_default_config_used_when_none(self):
        pos = [make_position(il_pct=6.0)]
        result = self.analyzer.analyze(pos, None)
        self.assertIn(FLAG_HIGH_IL, result["positions"][0]["flags"])

    def test_cost_exceeds_il_flag_in_result(self):
        pos = [make_position(il_pct=3.0, hedge_cost_annual_pct=8.0)]
        result = self.analyzer.analyze(pos)
        self.assertIn(FLAG_COST_EXCEEDS_IL, result["positions"][0]["flags"])

    def test_effective_hedge_count_in_aggregates(self):
        pos = [
            make_position(pair="A/B", il_pct=10.0, hedge_coverage_pct=90.0,
                          hedge_cost_annual_pct=5.0, available_hedges=["perpetual_short"]),
            make_position(pair="C/D", il_pct=5.0, hedge_coverage_pct=40.0,
                          hedge_cost_annual_pct=3.0, available_hedges=["none"]),
        ]
        result = self.analyzer.analyze(pos)
        # First is EFFECTIVE, second is NO_HEDGE_AVAILABLE
        self.assertEqual(result["aggregates"]["effective_hedge_count"], 1)

    def test_hedge_profitable_flag_set(self):
        pos = [make_position(
            apy_with_hedge_pct=15.0,
            hedge_cost_annual_pct=2.0,
            apy_without_hedge_pct=10.0,
        )]
        result = self.analyzer.analyze(pos)
        self.assertIn(FLAG_HEDGE_PROFITABLE, result["positions"][0]["flags"])

    def test_zero_il_position(self):
        pos = [make_position(il_pct=0.0)]
        result = self.analyzer.analyze(pos)
        self.assertAlmostEqual(result["positions"][0]["il_exposure_usd"], 0.0, places=4)

    def test_single_position_best_is_worst(self):
        pos = [make_position(pair="ETH/USDC")]
        result = self.analyzer.analyze(pos)
        agg = result["aggregates"]
        self.assertEqual(agg["best_hedge_opportunity"], agg["least_effective_hedge"])

    def test_average_efficiency_single(self):
        pos = [make_position(hedge_coverage_pct=75.0, hedge_cost_annual_pct=5.0)]
        result = self.analyzer.analyze(pos)
        expected = 70.0
        self.assertAlmostEqual(
            result["aggregates"]["average_hedge_efficiency"], expected, places=2
        )

    def test_config_large_position_threshold_override(self):
        pos = [make_position(correlation_ab=0.2, lp_value_usd=30000.0, il_pct=4.0)]
        result = self.analyzer.analyze(pos, {"large_position_usd": 20000.0})
        self.assertIn(FLAG_LOW_CORR_HIGH_RISK, result["positions"][0]["flags"])

    def test_delta_neutral_hedge_recognized(self):
        pos = [make_position(available_hedges=["delta_neutral"])]
        result = self.analyzer.analyze(pos)
        self.assertNotEqual(
            result["positions"][0]["hedge_label"], LABEL_NO_HEDGE_AVAILABLE
        )

    def test_rebalancing_hedge_recognized(self):
        pos = [make_position(available_hedges=["rebalancing"])]
        result = self.analyzer.analyze(pos)
        self.assertNotEqual(
            result["positions"][0]["hedge_label"], LABEL_NO_HEDGE_AVAILABLE
        )


if __name__ == "__main__":
    unittest.main()
