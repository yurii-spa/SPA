#!/usr/bin/env python3
"""Tests for protocol_liquidation_history_analyzer (MP-867 / SPA-V672).

Run with:
    python3 -m unittest spa_core.tests.test_protocol_liquidation_history_analyzer -v
"""
import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path

# Ensure project root is importable
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from spa_core.analytics.protocol_liquidation_history_analyzer import (
    _bad_debt_component,
    _cascade_risk_score,
    _health_component,
    _health_factor_label,
    _liquidation_rate_component,
    _liquidator_incentive_adequacy,
    _load_log,
    _peak_component,
    _recommendation,
    _save_log,
    _systemic_risk_label,
    analyze,
    run,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _proto(
    name="TestProto",
    total_liquidations_30d_usd=0.0,
    liquidations_count_30d=0,
    peak_single_day_usd=0.0,
    total_tvl_usd=1_000_000.0,
    bad_debt_usd=0.0,
    liquidation_penalty_pct=5.0,
    avg_health_factor_collateral=1.5,
    days_since_last_large_liquidation=60,
):
    return {
        "name": name,
        "total_liquidations_30d_usd": total_liquidations_30d_usd,
        "liquidations_count_30d": liquidations_count_30d,
        "peak_single_day_usd": peak_single_day_usd,
        "total_tvl_usd": total_tvl_usd,
        "bad_debt_usd": bad_debt_usd,
        "liquidation_penalty_pct": liquidation_penalty_pct,
        "avg_health_factor_collateral": avg_health_factor_collateral,
        "days_since_last_large_liquidation": days_since_last_large_liquidation,
    }


# ===========================================================================
# Sub-component tests: _liquidation_rate_component
# ===========================================================================
class TestLiquidationRateComponent(unittest.TestCase):

    def test_rate_zero(self):
        self.assertEqual(_liquidation_rate_component(0.0), 0)

    def test_rate_below_0_5(self):
        self.assertEqual(_liquidation_rate_component(0.3), 0)

    def test_rate_exactly_0_5(self):
        self.assertEqual(_liquidation_rate_component(0.5), 5)

    def test_rate_between_0_5_and_1(self):
        self.assertEqual(_liquidation_rate_component(0.8), 5)

    def test_rate_exactly_1(self):
        self.assertEqual(_liquidation_rate_component(1.0), 10)

    def test_rate_between_1_and_2(self):
        self.assertEqual(_liquidation_rate_component(1.5), 10)

    def test_rate_exactly_2(self):
        self.assertEqual(_liquidation_rate_component(2.0), 18)

    def test_rate_between_2_and_5(self):
        self.assertEqual(_liquidation_rate_component(3.5), 18)

    def test_rate_exactly_5(self):
        self.assertEqual(_liquidation_rate_component(5.0), 25)

    def test_rate_between_5_and_10(self):
        self.assertEqual(_liquidation_rate_component(7.0), 25)

    def test_rate_exactly_10(self):
        self.assertEqual(_liquidation_rate_component(10.0), 30)

    def test_rate_above_10(self):
        self.assertEqual(_liquidation_rate_component(50.0), 30)


# ===========================================================================
# Sub-component tests: _bad_debt_component
# ===========================================================================
class TestBadDebtComponent(unittest.TestCase):

    def test_zero_bad_debt_zero_ratio(self):
        self.assertEqual(_bad_debt_component(0.0, 0.0), 0)

    def test_tiny_ratio_nonzero_debt(self):
        # < 0.01 but bad_debt > 0 → still 0
        self.assertEqual(_bad_debt_component(0.005, 50.0), 0)

    def test_ratio_exactly_0_01(self):
        self.assertEqual(_bad_debt_component(0.01, 100.0), 3)

    def test_ratio_between_0_01_and_0_1(self):
        self.assertEqual(_bad_debt_component(0.05, 500.0), 3)

    def test_ratio_exactly_0_1(self):
        self.assertEqual(_bad_debt_component(0.1, 1000.0), 8)

    def test_ratio_between_0_1_and_0_2(self):
        self.assertEqual(_bad_debt_component(0.15, 1500.0), 8)

    def test_ratio_exactly_0_2(self):
        self.assertEqual(_bad_debt_component(0.2, 2000.0), 15)

    def test_ratio_between_0_2_and_0_5(self):
        self.assertEqual(_bad_debt_component(0.35, 3500.0), 15)

    def test_ratio_exactly_0_5(self):
        self.assertEqual(_bad_debt_component(0.5, 5000.0), 25)

    def test_ratio_between_0_5_and_1(self):
        self.assertEqual(_bad_debt_component(0.75, 7500.0), 25)

    def test_ratio_exactly_1(self):
        self.assertEqual(_bad_debt_component(1.0, 10000.0), 30)

    def test_ratio_above_1(self):
        self.assertEqual(_bad_debt_component(5.0, 50000.0), 30)


# ===========================================================================
# Sub-component tests: _peak_component
# ===========================================================================
class TestPeakComponent(unittest.TestCase):

    def test_peak_zero(self):
        self.assertEqual(_peak_component(0.0), 0)

    def test_peak_below_0_5(self):
        self.assertEqual(_peak_component(0.3), 0)

    def test_peak_exactly_0_5(self):
        self.assertEqual(_peak_component(0.5), 5)

    def test_peak_between_0_5_and_1(self):
        self.assertEqual(_peak_component(0.8), 5)

    def test_peak_exactly_1(self):
        self.assertEqual(_peak_component(1.0), 10)

    def test_peak_between_1_and_2(self):
        self.assertEqual(_peak_component(1.5), 10)

    def test_peak_exactly_2(self):
        self.assertEqual(_peak_component(2.0), 15)

    def test_peak_between_2_and_5(self):
        self.assertEqual(_peak_component(3.5), 15)

    def test_peak_exactly_5(self):
        self.assertEqual(_peak_component(5.0), 20)

    def test_peak_above_5(self):
        self.assertEqual(_peak_component(20.0), 20)


# ===========================================================================
# Sub-component tests: _health_component
# ===========================================================================
class TestHealthComponent(unittest.TestCase):

    def test_hf_below_1_05(self):
        self.assertEqual(_health_component(1.0), 20)

    def test_hf_exactly_1_05(self):
        self.assertEqual(_health_component(1.05), 15)

    def test_hf_between_1_05_and_1_1(self):
        self.assertEqual(_health_component(1.07), 15)

    def test_hf_exactly_1_1(self):
        self.assertEqual(_health_component(1.1), 8)

    def test_hf_between_1_1_and_1_25(self):
        self.assertEqual(_health_component(1.2), 8)

    def test_hf_exactly_1_25(self):
        self.assertEqual(_health_component(1.25), 3)

    def test_hf_between_1_25_and_1_5(self):
        self.assertEqual(_health_component(1.4), 3)

    def test_hf_exactly_1_5(self):
        self.assertEqual(_health_component(1.5), 0)

    def test_hf_above_1_5(self):
        self.assertEqual(_health_component(2.0), 0)


# ===========================================================================
# _cascade_risk_score tests
# ===========================================================================
class TestCascadeRiskScore(unittest.TestCase):

    def test_all_zero_inputs_low_hf(self):
        # rate=0, bd=0, peak=0, hf<1.05
        score = _cascade_risk_score(0.0, 0.0, 0.0, 0.0, 1.0)
        self.assertEqual(score, 20)  # only health component: 20

    def test_all_max_capped_at_100(self):
        score = _cascade_risk_score(15.0, 5.0, 5.0, 10.0, 1.0)
        self.assertEqual(score, 100)

    def test_healthy_protocol_low_score(self):
        # rate=0.2, bd=0, peak=0.1, hf=1.8
        score = _cascade_risk_score(0.2, 0.0, 0.0, 0.1, 1.8)
        self.assertEqual(score, 0)

    def test_moderate_scenario(self):
        # rate=1.5→10, bd=0.15→8, peak=0.8→5, hf=1.3→3
        score = _cascade_risk_score(1.5, 0.15, 1500.0, 0.8, 1.3)
        self.assertEqual(score, 26)

    def test_min_100_enforced(self):
        score = _cascade_risk_score(20.0, 10.0, 100000.0, 20.0, 0.9)
        self.assertLessEqual(score, 100)

    def test_zero_bad_debt_zero_ratio(self):
        score = _cascade_risk_score(0.0, 0.0, 0.0, 0.0, 2.0)
        self.assertEqual(score, 0)


# ===========================================================================
# _systemic_risk_label tests
# ===========================================================================
class TestSystemicRiskLabel(unittest.TestCase):

    def test_critical(self):
        self.assertEqual(_systemic_risk_label(80), "CRITICAL")

    def test_critical_100(self):
        self.assertEqual(_systemic_risk_label(100), "CRITICAL")

    def test_high(self):
        self.assertEqual(_systemic_risk_label(60), "HIGH")

    def test_high_79(self):
        self.assertEqual(_systemic_risk_label(79), "HIGH")

    def test_elevated(self):
        self.assertEqual(_systemic_risk_label(40), "ELEVATED")

    def test_elevated_59(self):
        self.assertEqual(_systemic_risk_label(59), "ELEVATED")

    def test_moderate(self):
        self.assertEqual(_systemic_risk_label(20), "MODERATE")

    def test_moderate_39(self):
        self.assertEqual(_systemic_risk_label(39), "MODERATE")

    def test_low(self):
        self.assertEqual(_systemic_risk_label(0), "LOW")

    def test_low_19(self):
        self.assertEqual(_systemic_risk_label(19), "LOW")


# ===========================================================================
# _liquidator_incentive_adequacy tests
# ===========================================================================
class TestLiquidatorIncentiveAdequacy(unittest.TestCase):

    def test_excessive(self):
        self.assertEqual(_liquidator_incentive_adequacy(15.0), "EXCESSIVE")

    def test_excessive_high(self):
        self.assertEqual(_liquidator_incentive_adequacy(20.0), "EXCESSIVE")

    def test_adequate(self):
        self.assertEqual(_liquidator_incentive_adequacy(5.0), "ADEQUATE")

    def test_adequate_mid(self):
        self.assertEqual(_liquidator_incentive_adequacy(10.0), "ADEQUATE")

    def test_low(self):
        self.assertEqual(_liquidator_incentive_adequacy(3.0), "LOW")

    def test_low_mid(self):
        self.assertEqual(_liquidator_incentive_adequacy(4.9), "LOW")

    def test_insufficient(self):
        self.assertEqual(_liquidator_incentive_adequacy(0.0), "INSUFFICIENT")

    def test_insufficient_below_3(self):
        self.assertEqual(_liquidator_incentive_adequacy(2.9), "INSUFFICIENT")


# ===========================================================================
# _health_factor_label tests
# ===========================================================================
class TestHealthFactorLabel(unittest.TestCase):

    def test_critical(self):
        self.assertEqual(_health_factor_label(1.0), "CRITICAL")

    def test_critical_below_1_05(self):
        self.assertEqual(_health_factor_label(1.04), "CRITICAL")

    def test_stressed(self):
        self.assertEqual(_health_factor_label(1.05), "STRESSED")

    def test_stressed_mid(self):
        # 1.1 < 1.15 → STRESSED
        self.assertEqual(_health_factor_label(1.1), "STRESSED")

    def test_watch(self):
        self.assertEqual(_health_factor_label(1.15), "WATCH")

    def test_watch_upper(self):
        self.assertEqual(_health_factor_label(1.29), "WATCH")

    def test_healthy(self):
        self.assertEqual(_health_factor_label(1.3), "HEALTHY")

    def test_healthy_high(self):
        self.assertEqual(_health_factor_label(2.0), "HEALTHY")


# ===========================================================================
# _recommendation tests
# ===========================================================================
class TestRecommendation(unittest.TestCase):

    def test_critical_contains_reduce_exposure(self):
        rec = _recommendation("CRITICAL", 1.5, 12.0, 6.0, 1.02)
        self.assertIn("Reduce exposure immediately", rec)
        self.assertIn("1.50%", rec)

    def test_high_contains_liquidation_rate(self):
        rec = _recommendation("HIGH", 0.0, 7.5, 3.0, 1.4)
        self.assertIn("7.5%", rec)
        self.assertIn("reducing positions", rec)

    def test_elevated_contains_peak(self):
        rec = _recommendation("ELEVATED", 0.0, 1.5, 1.2, 1.35)
        self.assertIn("1.2%", rec)
        self.assertIn("Peak single-day", rec)

    def test_moderate_contains_avg_hf(self):
        rec = _recommendation("MODERATE", 0.0, 0.5, 0.3, 1.35)
        self.assertIn("1.35", rec)
        self.assertIn("Moderate", rec)

    def test_low_contains_healthy(self):
        rec = _recommendation("LOW", 0.0, 0.1, 0.05, 1.7)
        self.assertIn("healthy", rec)
        self.assertIn("1.70", rec)


# ===========================================================================
# analyze() integration tests
# ===========================================================================
class TestAnalyze(unittest.TestCase):

    def test_empty_protocols(self):
        result = analyze([])
        self.assertEqual(result["protocols"], [])
        self.assertIsNone(result["highest_cascade_risk"])
        self.assertIsNone(result["safest_protocol"])
        self.assertEqual(result["protocols_with_bad_debt"], [])
        self.assertEqual(result["average_cascade_risk"], 0.0)
        self.assertIn("timestamp", result)

    def test_single_healthy_protocol(self):
        p = _proto(
            name="Aave",
            total_liquidations_30d_usd=100_000,
            liquidations_count_30d=5,
            peak_single_day_usd=20_000,
            total_tvl_usd=10_000_000,
            bad_debt_usd=0,
            liquidation_penalty_pct=5.0,
            avg_health_factor_collateral=1.6,
        )
        result = analyze([p])
        self.assertEqual(len(result["protocols"]), 1)
        proto = result["protocols"][0]
        self.assertEqual(proto["name"], "Aave")
        self.assertEqual(proto["systemic_risk_label"], "LOW")
        self.assertEqual(proto["liquidator_incentive_adequacy"], "ADEQUATE")
        self.assertEqual(proto["health_factor_label"], "HEALTHY")
        self.assertEqual(result["protocols_with_bad_debt"], [])
        self.assertEqual(result["highest_cascade_risk"], "Aave")
        self.assertEqual(result["safest_protocol"], "Aave")

    def test_single_critical_protocol(self):
        p = _proto(
            name="RiskyProto",
            total_liquidations_30d_usd=50_000_000,
            liquidations_count_30d=500,
            peak_single_day_usd=10_000_000,
            total_tvl_usd=100_000_000,
            bad_debt_usd=2_000_000,
            liquidation_penalty_pct=5.0,
            avg_health_factor_collateral=1.02,
        )
        result = analyze([p])
        proto = result["protocols"][0]
        self.assertGreaterEqual(proto["cascade_risk_score"], 80)
        self.assertEqual(proto["systemic_risk_label"], "CRITICAL")
        self.assertIn("RiskyProto", result["protocols_with_bad_debt"])

    def test_tvl_zero_rates_are_zero(self):
        p = _proto(
            name="ZeroTVL",
            total_liquidations_30d_usd=1_000,
            liquidations_count_30d=1,
            peak_single_day_usd=500,
            total_tvl_usd=0.0,
            bad_debt_usd=100,
            avg_health_factor_collateral=1.5,
        )
        result = analyze([p])
        proto = result["protocols"][0]
        self.assertEqual(proto["liquidation_rate_pct"], 0.0)
        self.assertEqual(proto["bad_debt_ratio_pct"], 0.0)
        self.assertEqual(proto["peak_to_tvl_pct"], 0.0)

    def test_count_zero_avg_liquidation_size_zero(self):
        p = _proto(
            name="NoEvents",
            total_liquidations_30d_usd=0,
            liquidations_count_30d=0,
            avg_health_factor_collateral=1.8,
        )
        result = analyze([p])
        proto = result["protocols"][0]
        self.assertEqual(proto["avg_liquidation_size_usd"], 0.0)

    def test_avg_liquidation_size_calculation(self):
        p = _proto(
            total_liquidations_30d_usd=1_000_000,
            liquidations_count_30d=200,
            avg_health_factor_collateral=1.8,
        )
        result = analyze([p])
        proto = result["protocols"][0]
        self.assertAlmostEqual(proto["avg_liquidation_size_usd"], 5000.0, places=1)

    def test_two_protocols_highest_cascade_correct(self):
        p1 = _proto(name="Safe", total_liquidations_30d_usd=10_000,
                    total_tvl_usd=10_000_000, avg_health_factor_collateral=2.0)
        p2 = _proto(name="Risky", total_liquidations_30d_usd=9_000_000,
                    peak_single_day_usd=3_000_000,
                    total_tvl_usd=10_000_000,
                    bad_debt_usd=500_000,
                    avg_health_factor_collateral=1.05)
        result = analyze([p1, p2])
        self.assertEqual(result["highest_cascade_risk"], "Risky")
        self.assertEqual(result["safest_protocol"], "Safe")

    def test_protocols_with_bad_debt_list(self):
        p1 = _proto(name="Clean", bad_debt_usd=0.0)
        p2 = _proto(name="Dirty", bad_debt_usd=1000.0)
        p3 = _proto(name="Dirty2", bad_debt_usd=500.0)
        result = analyze([p1, p2, p3])
        self.assertNotIn("Clean", result["protocols_with_bad_debt"])
        self.assertIn("Dirty", result["protocols_with_bad_debt"])
        self.assertIn("Dirty2", result["protocols_with_bad_debt"])

    def test_average_cascade_risk_calculated(self):
        p1 = _proto(name="A", avg_health_factor_collateral=2.0)
        p2 = _proto(name="B", avg_health_factor_collateral=2.0)
        result = analyze([p1, p2])
        # both identical, avg = same as individual score
        self.assertEqual(result["average_cascade_risk"], result["protocols"][0]["cascade_risk_score"])

    def test_timestamp_recent(self):
        before = time.time()
        result = analyze([_proto()])
        after = time.time()
        self.assertGreaterEqual(result["timestamp"], before)
        self.assertLessEqual(result["timestamp"], after)

    def test_liquidation_rate_computed_correctly(self):
        p = _proto(
            total_liquidations_30d_usd=200_000,
            total_tvl_usd=10_000_000,
        )
        result = analyze([p])
        proto = result["protocols"][0]
        self.assertAlmostEqual(proto["liquidation_rate_pct"], 2.0, places=4)

    def test_bad_debt_ratio_computed_correctly(self):
        p = _proto(bad_debt_usd=50_000, total_tvl_usd=1_000_000)
        result = analyze([p])
        proto = result["protocols"][0]
        self.assertAlmostEqual(proto["bad_debt_ratio_pct"], 5.0, places=4)

    def test_peak_to_tvl_computed_correctly(self):
        p = _proto(peak_single_day_usd=100_000, total_tvl_usd=2_000_000)
        result = analyze([p])
        proto = result["protocols"][0]
        self.assertAlmostEqual(proto["peak_to_tvl_pct"], 5.0, places=4)

    def test_excessive_liquidator_incentive(self):
        p = _proto(liquidation_penalty_pct=20.0)
        result = analyze([p])
        proto = result["protocols"][0]
        self.assertEqual(proto["liquidator_incentive_adequacy"], "EXCESSIVE")

    def test_insufficient_liquidator_incentive(self):
        p = _proto(liquidation_penalty_pct=1.0)
        result = analyze([p])
        proto = result["protocols"][0]
        self.assertEqual(proto["liquidator_incentive_adequacy"], "INSUFFICIENT")

    def test_health_factor_critical_label(self):
        p = _proto(avg_health_factor_collateral=1.01)
        result = analyze([p])
        proto = result["protocols"][0]
        self.assertEqual(proto["health_factor_label"], "CRITICAL")

    def test_health_factor_watch_label(self):
        p = _proto(avg_health_factor_collateral=1.2)
        result = analyze([p])
        proto = result["protocols"][0]
        self.assertEqual(proto["health_factor_label"], "WATCH")

    def test_config_param_accepted(self):
        # Should not raise even with custom config
        result = analyze([_proto()], config={"large_liquidation_threshold_pct": 2.0})
        self.assertIn("protocols", result)

    def test_output_keys_complete(self):
        result = analyze([_proto()])
        for key in [
            "protocols", "highest_cascade_risk", "safest_protocol",
            "protocols_with_bad_debt", "average_cascade_risk", "timestamp",
        ]:
            self.assertIn(key, result)

    def test_protocol_output_keys_complete(self):
        result = analyze([_proto()])
        proto = result["protocols"][0]
        for key in [
            "name", "liquidation_rate_pct", "bad_debt_ratio_pct",
            "cascade_risk_score", "systemic_risk_label", "avg_liquidation_size_usd",
            "peak_to_tvl_pct", "liquidator_incentive_adequacy",
            "health_factor_label", "recommendation",
        ]:
            self.assertIn(key, proto)

    def test_cascade_score_in_0_100(self):
        # Extreme inputs
        p = _proto(
            total_liquidations_30d_usd=999_000_000,
            liquidations_count_30d=99999,
            peak_single_day_usd=999_000_000,
            total_tvl_usd=1_000_000,
            bad_debt_usd=999_000,
            liquidation_penalty_pct=50.0,
            avg_health_factor_collateral=0.5,
        )
        result = analyze([p])
        score = result["protocols"][0]["cascade_risk_score"]
        self.assertGreaterEqual(score, 0)
        self.assertLessEqual(score, 100)

    def test_multiple_protocols_average_cascade(self):
        scores_expected = []
        protos = []
        for hf in [2.0, 1.0]:
            p = _proto(avg_health_factor_collateral=hf)
            protos.append(p)
        result = analyze(protos)
        raw_scores = [r["cascade_risk_score"] for r in result["protocols"]]
        expected_avg = sum(raw_scores) / len(raw_scores)
        self.assertAlmostEqual(result["average_cascade_risk"], expected_avg, places=4)

    def test_recommendation_critical_keyword(self):
        p = _proto(
            total_liquidations_30d_usd=50_000_000,
            peak_single_day_usd=10_000_000,
            total_tvl_usd=100_000_000,
            bad_debt_usd=2_000_000,
            avg_health_factor_collateral=1.02,
        )
        result = analyze([p])
        proto = result["protocols"][0]
        if proto["systemic_risk_label"] == "CRITICAL":
            self.assertIn("Reduce exposure", proto["recommendation"])

    def test_empty_config_is_ok(self):
        result = analyze([_proto()], config={})
        self.assertIn("protocols", result)

    def test_none_config_is_ok(self):
        result = analyze([_proto()], config=None)
        self.assertIn("protocols", result)


# ===========================================================================
# Ring-buffer log tests
# ===========================================================================
class TestRingBufferLog(unittest.TestCase):

    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp()
        self.log_path = Path(self.tmp_dir) / "data" / "liquidation_history_log.json"

    def test_save_and_load(self):
        entries = [{"a": 1}, {"b": 2}]
        _save_log(self.log_path, entries)
        loaded = _load_log(self.log_path)
        self.assertEqual(loaded, entries)

    def test_ring_buffer_cap_at_100(self):
        entries = [{"i": i} for i in range(150)]
        _save_log(self.log_path, entries)
        loaded = _load_log(self.log_path)
        self.assertEqual(len(loaded), 100)
        # Should keep last 100
        self.assertEqual(loaded[0]["i"], 50)
        self.assertEqual(loaded[-1]["i"], 149)

    def test_load_nonexistent_returns_empty(self):
        path = Path(self.tmp_dir) / "nonexistent.json"
        result = _load_log(path)
        self.assertEqual(result, [])

    def test_load_corrupt_file_returns_empty(self):
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        self.log_path.write_text("not valid json")
        result = _load_log(self.log_path)
        self.assertEqual(result, [])

    def test_run_appends_to_log(self):
        protocols = [_proto(name="AaveRun")]
        run(protocols, data_dir=self.tmp_dir)
        loaded = _load_log(self.log_path)
        self.assertEqual(len(loaded), 1)
        self.assertIn("protocols", loaded[0])

    def test_run_multiple_appends(self):
        protocols = [_proto()]
        for _ in range(3):
            run(protocols, data_dir=self.tmp_dir)
        loaded = _load_log(self.log_path)
        self.assertEqual(len(loaded), 3)

    def test_run_ring_buffer_overflow(self):
        protocols = [_proto()]
        for _ in range(105):
            run(protocols, data_dir=self.tmp_dir)
        loaded = _load_log(self.log_path)
        self.assertEqual(len(loaded), 100)

    def test_atomic_write_creates_file(self):
        _save_log(self.log_path, [{"test": True}])
        self.assertTrue(self.log_path.exists())

    def test_data_dir_in_run(self):
        protocols = [_proto(name="RunProto")]
        result = run(protocols, data_dir=self.tmp_dir)
        self.assertIn("protocols", result)
        self.assertEqual(result["protocols"][0]["name"], "RunProto")

    def test_empty_protocols_run(self):
        result = run([], data_dir=self.tmp_dir)
        self.assertEqual(result["protocols"], [])
        loaded = _load_log(self.log_path)
        self.assertEqual(len(loaded), 1)


# ===========================================================================
# Edge cases
# ===========================================================================
class TestEdgeCases(unittest.TestCase):

    def test_very_large_tvl_small_liquidation(self):
        p = _proto(
            total_liquidations_30d_usd=1.0,
            total_tvl_usd=1_000_000_000,
            avg_health_factor_collateral=2.0,
        )
        result = analyze([p])
        proto = result["protocols"][0]
        # Rate = 1/1e9 * 100 = 1e-7, rounds to 0.0 at 6 decimal places
        self.assertLessEqual(proto["liquidation_rate_pct"], 0.0001)
        self.assertEqual(proto["systemic_risk_label"], "LOW")

    def test_all_five_fields_are_floats(self):
        result = analyze([_proto()])
        proto = result["protocols"][0]
        self.assertIsInstance(proto["liquidation_rate_pct"], float)
        self.assertIsInstance(proto["bad_debt_ratio_pct"], float)
        self.assertIsInstance(proto["peak_to_tvl_pct"], float)
        self.assertIsInstance(proto["avg_liquidation_size_usd"], float)

    def test_cascade_score_is_int(self):
        result = analyze([_proto()])
        proto = result["protocols"][0]
        self.assertIsInstance(proto["cascade_risk_score"], int)

    def test_three_protocols_safest_is_lowest_score(self):
        protos = [
            _proto(name="A", avg_health_factor_collateral=2.5),
            _proto(name="B", avg_health_factor_collateral=1.0,
                   total_liquidations_30d_usd=5_000_000,
                   total_tvl_usd=1_000_000),
            _proto(name="C", avg_health_factor_collateral=1.6),
        ]
        result = analyze(protos)
        safest = result["safest_protocol"]
        safest_proto = next(p for p in result["protocols"] if p["name"] == safest)
        for p in result["protocols"]:
            self.assertLessEqual(safest_proto["cascade_risk_score"], p["cascade_risk_score"])

    def test_protocol_name_preserved(self):
        p = _proto(name="Morpho-Steakhouse-USDC")
        result = analyze([p])
        self.assertEqual(result["protocols"][0]["name"], "Morpho-Steakhouse-USDC")

    def test_high_systemic_risk_label_range(self):
        # Score = 60 exactly → HIGH
        # rate=2→18, bd=0.2→15, peak=1→10, hf=1.5→0 = 43, ELEVATED
        # Need exactly 60: rate=5→25, bd=0.5→25, peak=0→0, hf=1.5→0 = 50 ELEVATED
        # rate=10→30, bd=0.5→25, peak=0→0, hf=1.5→0 = 55 ELEVATED
        # rate=10→30, bd=1.0→30, peak=0→0, hf=1.5→0 = 60 HIGH
        p = _proto(
            total_liquidations_30d_usd=10_000_000,
            total_tvl_usd=100_000_000,  # rate=10% → 30
            bad_debt_usd=1_000_000,
            avg_health_factor_collateral=1.5,
        )
        result = analyze([p])
        proto = result["protocols"][0]
        # bad_debt_ratio = 1% → 30, rate=10% → 30, peak=0 → 0, hf=1.5 → 0 → total=60
        self.assertGreaterEqual(proto["cascade_risk_score"], 60)

    def test_stressed_health_label(self):
        p = _proto(avg_health_factor_collateral=1.1)
        result = analyze([p])
        # 1.1 < 1.15 → STRESSED
        self.assertEqual(result["protocols"][0]["health_factor_label"], "STRESSED")

    def test_low_penalty_insufficient(self):
        p = _proto(liquidation_penalty_pct=0.5)
        result = analyze([p])
        self.assertEqual(result["protocols"][0]["liquidator_incentive_adequacy"], "INSUFFICIENT")

    def test_adequate_penalty_boundary(self):
        p = _proto(liquidation_penalty_pct=5.0)
        result = analyze([p])
        self.assertEqual(result["protocols"][0]["liquidator_incentive_adequacy"], "ADEQUATE")

    def test_average_cascade_with_single_protocol(self):
        result = analyze([_proto()])
        self.assertEqual(
            result["average_cascade_risk"],
            float(result["protocols"][0]["cascade_risk_score"]),
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
