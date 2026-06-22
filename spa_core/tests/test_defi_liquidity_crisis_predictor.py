"""
Tests for MP-839 DeFiLiquidityCrisisPredictor
Run: python3 -m unittest spa_core.tests.test_defi_liquidity_crisis_predictor -v
"""

import json
import os
import tempfile
import unittest

from spa_core.analytics.defi_liquidity_crisis_predictor import (
    analyze,
    run_and_log,
    _tvl_trend_risk,
    _utilization_risk,
    _redemption_risk,
    _collateral_risk,
    _market_stress_risk,
    _crisis_probability_label,
    _merge_config,
    LOG_MAX,
)


def _make_protocol(**overrides):
    base = {
        "name": "TestProto",
        "tvl_usd": 10_000_000.0,
        "tvl_7d_ago_usd": 10_000_000.0,
        "utilization_rate_pct": 50.0,
        "pending_redemptions_usd": 1_000_000.0,
        "daily_outflow_usd": 0.0,
        "stablecoin_collateral_pct": 60.0,
        "market_stress_score": 20,
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# _tvl_trend_risk
# ---------------------------------------------------------------------------

class TestTvlTrendRisk(unittest.TestCase):
    def test_drop_below_30_returns_30(self):
        self.assertEqual(_tvl_trend_risk(-31), 30.0)

    def test_drop_exactly_minus30_returns_22(self):
        # -30 is NOT < -30, but IS < -20 → 22
        self.assertEqual(_tvl_trend_risk(-30), 22.0)

    def test_drop_minus29_returns_22(self):
        self.assertEqual(_tvl_trend_risk(-29), 22.0)

    def test_drop_exactly_minus20_returns_15(self):
        # -20 is NOT < -20, but IS < -10 → 15
        self.assertEqual(_tvl_trend_risk(-20), 15.0)

    def test_drop_minus19_returns_15(self):
        self.assertEqual(_tvl_trend_risk(-19), 15.0)

    def test_drop_exactly_minus10_returns_8(self):
        # -10 is NOT < -10, but IS < 0 → 8
        self.assertEqual(_tvl_trend_risk(-10), 8.0)

    def test_drop_minus9_returns_8(self):
        self.assertEqual(_tvl_trend_risk(-9), 8.0)

    def test_drop_minus1_returns_8(self):
        self.assertEqual(_tvl_trend_risk(-0.001), 8.0)

    def test_zero_returns_0(self):
        self.assertEqual(_tvl_trend_risk(0), 0.0)

    def test_positive_returns_0(self):
        self.assertEqual(_tvl_trend_risk(15), 0.0)


# ---------------------------------------------------------------------------
# _utilization_risk
# ---------------------------------------------------------------------------

class TestUtilizationRisk(unittest.TestCase):
    def test_above_95_returns_25(self):
        self.assertEqual(_utilization_risk(96), 25.0)

    def test_exactly_95_returns_25(self):
        self.assertEqual(_utilization_risk(95), 25.0)

    def test_94_returns_20(self):
        self.assertEqual(_utilization_risk(94), 20.0)

    def test_exactly_90_returns_20(self):
        self.assertEqual(_utilization_risk(90), 20.0)

    def test_89_returns_15(self):
        self.assertEqual(_utilization_risk(89), 15.0)

    def test_exactly_80_returns_15(self):
        self.assertEqual(_utilization_risk(80), 15.0)

    def test_79_returns_8(self):
        self.assertEqual(_utilization_risk(79), 8.0)

    def test_exactly_70_returns_8(self):
        self.assertEqual(_utilization_risk(70), 8.0)

    def test_69_returns_0(self):
        self.assertEqual(_utilization_risk(69), 0.0)

    def test_zero_returns_0(self):
        self.assertEqual(_utilization_risk(0), 0.0)


# ---------------------------------------------------------------------------
# _redemption_risk
# ---------------------------------------------------------------------------

class TestRedemptionRisk(unittest.TestCase):
    def test_coverage_below_1_1_returns_25(self):
        self.assertEqual(_redemption_risk(1.0), 25.0)

    def test_coverage_exactly_1_1_is_18(self):
        # 1.1 is NOT < 1.1, so falls to next bracket
        self.assertEqual(_redemption_risk(1.1), 18.0)

    def test_coverage_1_05_returns_25(self):
        self.assertEqual(_redemption_risk(1.05), 25.0)

    def test_coverage_1_4_returns_18(self):
        self.assertEqual(_redemption_risk(1.4), 18.0)

    def test_coverage_exactly_1_5_is_10(self):
        self.assertEqual(_redemption_risk(1.5), 10.0)

    def test_coverage_1_8_returns_10(self):
        self.assertEqual(_redemption_risk(1.8), 10.0)

    def test_coverage_exactly_2_0_is_4(self):
        self.assertEqual(_redemption_risk(2.0), 4.0)

    def test_coverage_4_9_returns_4(self):
        self.assertEqual(_redemption_risk(4.9), 4.0)

    def test_coverage_exactly_5_0_is_0(self):
        self.assertEqual(_redemption_risk(5.0), 0.0)

    def test_coverage_high_returns_0(self):
        self.assertEqual(_redemption_risk(999.0), 0.0)


# ---------------------------------------------------------------------------
# _collateral_risk
# ---------------------------------------------------------------------------

class TestCollateralRisk(unittest.TestCase):
    def test_exactly_10_pct_returns_10(self):
        self.assertEqual(_collateral_risk(10), 10.0)

    def test_below_10_returns_10(self):
        self.assertEqual(_collateral_risk(5), 10.0)

    def test_11_returns_7(self):
        self.assertEqual(_collateral_risk(11), 7.0)

    def test_exactly_30_returns_7(self):
        self.assertEqual(_collateral_risk(30), 7.0)

    def test_31_returns_4(self):
        self.assertEqual(_collateral_risk(31), 4.0)

    def test_exactly_50_returns_4(self):
        self.assertEqual(_collateral_risk(50), 4.0)

    def test_51_returns_0(self):
        self.assertEqual(_collateral_risk(51), 0.0)

    def test_100_returns_0(self):
        self.assertEqual(_collateral_risk(100), 0.0)


# ---------------------------------------------------------------------------
# _market_stress_risk
# ---------------------------------------------------------------------------

class TestMarketStressRisk(unittest.TestCase):
    def test_zero_stress(self):
        self.assertEqual(_market_stress_risk(0), 0.0)

    def test_50_stress_gives_5(self):
        self.assertAlmostEqual(_market_stress_risk(50), 5.0)

    def test_100_stress_gives_10(self):
        self.assertAlmostEqual(_market_stress_risk(100), 10.0)

    def test_capped_at_10(self):
        self.assertEqual(_market_stress_risk(200), 10.0)

    def test_30_gives_3(self):
        self.assertAlmostEqual(_market_stress_risk(30), 3.0)


# ---------------------------------------------------------------------------
# _crisis_probability_label
# ---------------------------------------------------------------------------

class TestCrisisProbabilityLabel(unittest.TestCase):
    def test_75_is_critical(self):
        self.assertEqual(_crisis_probability_label(75), "CRITICAL")

    def test_100_is_critical(self):
        self.assertEqual(_crisis_probability_label(100), "CRITICAL")

    def test_74_is_high(self):
        self.assertEqual(_crisis_probability_label(74), "HIGH")

    def test_50_is_high(self):
        self.assertEqual(_crisis_probability_label(50), "HIGH")

    def test_49_is_moderate(self):
        self.assertEqual(_crisis_probability_label(49), "MODERATE")

    def test_25_is_moderate(self):
        self.assertEqual(_crisis_probability_label(25), "MODERATE")

    def test_24_is_low(self):
        self.assertEqual(_crisis_probability_label(24), "LOW")

    def test_zero_is_low(self):
        self.assertEqual(_crisis_probability_label(0), "LOW")


# ---------------------------------------------------------------------------
# _merge_config
# ---------------------------------------------------------------------------

class TestMergeConfig(unittest.TestCase):
    def test_defaults_applied(self):
        cfg = _merge_config(None)
        self.assertEqual(cfg["crisis_threshold"], 70.0)
        self.assertEqual(cfg["tvl_drop_alert_pct"], 20.0)

    def test_override_threshold(self):
        cfg = _merge_config({"crisis_threshold": 50.0})
        self.assertEqual(cfg["crisis_threshold"], 50.0)
        self.assertEqual(cfg["tvl_drop_alert_pct"], 20.0)

    def test_override_tvl_drop(self):
        cfg = _merge_config({"tvl_drop_alert_pct": 10.0})
        self.assertEqual(cfg["tvl_drop_alert_pct"], 10.0)


# ---------------------------------------------------------------------------
# analyze() — empty input
# ---------------------------------------------------------------------------

class TestAnalyzeEmpty(unittest.TestCase):
    def setUp(self):
        self.result = analyze([])

    def test_protocols_empty(self):
        self.assertEqual(self.result["protocols"], [])

    def test_crisis_count_zero(self):
        self.assertEqual(self.result["crisis_count"], 0)

    def test_at_risk_empty(self):
        self.assertEqual(self.result["at_risk_protocols"], [])

    def test_safest_none(self):
        self.assertIsNone(self.result["safest_protocol"])

    def test_highest_risk_none(self):
        self.assertIsNone(self.result["highest_risk_protocol"])

    def test_portfolio_risk_low(self):
        self.assertEqual(self.result["portfolio_crisis_risk"], "LOW")

    def test_timestamp_present(self):
        self.assertIn("timestamp", self.result)


# ---------------------------------------------------------------------------
# analyze() — single safe protocol
# ---------------------------------------------------------------------------

class TestAnalyzeSafeProtocol(unittest.TestCase):
    def setUp(self):
        p = _make_protocol(
            name="SafeProto",
            tvl_usd=50_000_000,
            tvl_7d_ago_usd=50_000_000,
            utilization_rate_pct=50,
            pending_redemptions_usd=1_000_000,
            daily_outflow_usd=0,
            stablecoin_collateral_pct=80,
            market_stress_score=10,
        )
        self.result = analyze([p])
        self.proto = self.result["protocols"][0]

    def test_crisis_count_zero(self):
        self.assertEqual(self.result["crisis_count"], 0)

    def test_risk_score_low(self):
        # tvl_trend=0, util=0, redemption=0 (coverage=50), collateral=0, stress=1 → 1
        self.assertLess(self.proto["risk_score"], 25)

    def test_crisis_probability_low(self):
        self.assertEqual(self.proto["crisis_probability"], "LOW")

    def test_runway_none_when_outflow_zero(self):
        self.assertIsNone(self.proto["runway_days"])

    def test_recommendation_low(self):
        self.assertIn("no immediate action", self.proto["recommendation"])

    def test_redemption_coverage_correct(self):
        # tvl=50M, pending=1M → coverage=50
        self.assertAlmostEqual(self.proto["redemption_coverage_ratio"], 50.0)

    def test_safest_is_safe_proto(self):
        self.assertEqual(self.result["safest_protocol"], "SafeProto")

    def test_highest_risk_is_safe_proto(self):
        self.assertEqual(self.result["highest_risk_protocol"], "SafeProto")


# ---------------------------------------------------------------------------
# analyze() — critical protocol
# ---------------------------------------------------------------------------

class TestAnalyzeCriticalProtocol(unittest.TestCase):
    def setUp(self):
        p = _make_protocol(
            name="CrisisProto",
            tvl_usd=1_000_000,
            tvl_7d_ago_usd=2_000_000,  # -50% drop
            utilization_rate_pct=97,
            pending_redemptions_usd=950_000,  # coverage ≈ 1.05 < 1.1
            daily_outflow_usd=100_000,         # runway=10 days
            stablecoin_collateral_pct=5,       # < 10
            market_stress_score=90,
        )
        self.result = analyze([p])
        self.proto = self.result["protocols"][0]

    def test_risk_score_high(self):
        self.assertGreaterEqual(self.proto["risk_score"], 75)

    def test_crisis_probability_critical(self):
        self.assertEqual(self.proto["crisis_probability"], "CRITICAL")

    def test_crisis_count_one(self):
        self.assertEqual(self.result["crisis_count"], 1)

    def test_portfolio_crisis_risk_critical(self):
        self.assertEqual(self.result["portfolio_crisis_risk"], "CRITICAL")

    def test_recommendation_exit(self):
        self.assertIn("EXIT", self.proto["recommendation"])

    def test_tvl_change_negative(self):
        self.assertAlmostEqual(self.proto["tvl_change_7d_pct"], -50.0)

    def test_runway_10_days(self):
        self.assertAlmostEqual(self.proto["runway_days"], 10.0)

    def test_key_risks_not_empty(self):
        self.assertGreater(len(self.proto["key_risks"]), 0)

    def test_tvl_drop_key_risk(self):
        risks = self.proto["key_risks"]
        self.assertTrue(any("TVL dropped" in r for r in risks))

    def test_utilization_key_risk(self):
        risks = self.proto["key_risks"]
        self.assertTrue(any("Utilization" in r for r in risks))

    def test_redemption_key_risk(self):
        risks = self.proto["key_risks"]
        self.assertTrue(any("Redemption" in r for r in risks))

    def test_collateral_key_risk(self):
        risks = self.proto["key_risks"]
        self.assertTrue(any("stablecoin" in r.lower() for r in risks))

    def test_runway_key_risk(self):
        risks = self.proto["key_risks"]
        self.assertTrue(any("runway" in r.lower() for r in risks))


# ---------------------------------------------------------------------------
# TVL edge cases
# ---------------------------------------------------------------------------

class TestTvlEdgeCases(unittest.TestCase):
    def test_tvl_7d_zero_gives_zero_change(self):
        p = _make_protocol(tvl_usd=1_000_000, tvl_7d_ago_usd=0)
        r = analyze([p])
        self.assertAlmostEqual(r["protocols"][0]["tvl_change_7d_pct"], 0.0)

    def test_tvl_increased_no_tvl_trend_risk(self):
        p = _make_protocol(tvl_usd=11_000_000, tvl_7d_ago_usd=10_000_000)
        r = analyze([p])
        # tvl_change = +10%, so tvl_trend_risk = 0
        self.assertAlmostEqual(r["protocols"][0]["tvl_change_7d_pct"], 10.0)

    def test_pending_redemptions_zero_gives_high_coverage(self):
        p = _make_protocol(pending_redemptions_usd=0)
        r = analyze([p])
        proto = r["protocols"][0]
        self.assertAlmostEqual(proto["redemption_coverage_ratio"], 999.0)


# ---------------------------------------------------------------------------
# at_risk_protocols threshold
# ---------------------------------------------------------------------------

class TestAtRiskProtocols(unittest.TestCase):
    def test_default_threshold_70(self):
        # Score needs to be > 70
        p_safe = _make_protocol(name="Safe")
        p_risky = _make_protocol(
            name="Risky",
            tvl_usd=1_000_000,
            tvl_7d_ago_usd=2_000_000,
            utilization_rate_pct=97,
            pending_redemptions_usd=950_000,
            stablecoin_collateral_pct=5,
            market_stress_score=90,
        )
        r = analyze([p_safe, p_risky])
        self.assertIn("Risky", r["at_risk_protocols"])
        self.assertNotIn("Safe", r["at_risk_protocols"])

    def test_custom_threshold(self):
        p = _make_protocol(name="Proto", market_stress_score=50)
        # market_stress_risk=5, collateral=0 (>50%), util=0, tvl_trend=0, redemption=0(999) → score=5
        r = analyze([p], config={"crisis_threshold": 1.0})
        self.assertIn("Proto", r["at_risk_protocols"])


# ---------------------------------------------------------------------------
# Multiple protocols — safest / highest risk
# ---------------------------------------------------------------------------

class TestMultipleProtocols(unittest.TestCase):
    def setUp(self):
        p_safe = _make_protocol(name="Safe", market_stress_score=0)
        p_mid = _make_protocol(name="Mid", utilization_rate_pct=82, market_stress_score=40)
        p_risky = _make_protocol(
            name="Risky",
            tvl_usd=1_000_000,
            tvl_7d_ago_usd=2_000_000,
            utilization_rate_pct=97,
            pending_redemptions_usd=900_000,
            stablecoin_collateral_pct=5,
            market_stress_score=90,
        )
        self.result = analyze([p_safe, p_mid, p_risky])

    def test_safest_is_safe(self):
        self.assertEqual(self.result["safest_protocol"], "Safe")

    def test_highest_risk_is_risky(self):
        self.assertEqual(self.result["highest_risk_protocol"], "Risky")

    def test_crisis_count_at_least_one(self):
        self.assertGreaterEqual(self.result["crisis_count"], 1)

    def test_all_protocols_in_result(self):
        names = [p["name"] for p in self.result["protocols"]]
        self.assertIn("Safe", names)
        self.assertIn("Mid", names)
        self.assertIn("Risky", names)


# ---------------------------------------------------------------------------
# run_and_log — ring buffer
# ---------------------------------------------------------------------------

class TestRunAndLog(unittest.TestCase):
    def _temp_log(self):
        d = tempfile.mkdtemp()
        return os.path.join(d, "test_crisis_log.json")

    def test_creates_log_file(self):
        path = self._temp_log()
        run_and_log([], data_file=path)
        self.assertTrue(os.path.exists(path))

    def test_log_is_list(self):
        path = self._temp_log()
        run_and_log([], data_file=path)
        with open(path) as f:
            data = json.load(f)
        self.assertIsInstance(data, list)

    def test_log_appends_multiple(self):
        path = self._temp_log()
        run_and_log([], data_file=path)
        run_and_log([], data_file=path)
        with open(path) as f:
            data = json.load(f)
        self.assertEqual(len(data), 2)

    def test_ring_buffer_max(self):
        path = self._temp_log()
        p = _make_protocol()
        for _ in range(LOG_MAX + 5):
            run_and_log([p], data_file=path)
        with open(path) as f:
            data = json.load(f)
        self.assertEqual(len(data), LOG_MAX)

    def test_log_entry_has_timestamp(self):
        path = self._temp_log()
        run_and_log([], data_file=path)
        with open(path) as f:
            data = json.load(f)
        self.assertIn("timestamp", data[0])


# ---------------------------------------------------------------------------
# Score clamped at 100
# ---------------------------------------------------------------------------

class TestScoreClamp(unittest.TestCase):
    def test_risk_score_never_exceeds_100(self):
        p = _make_protocol(
            tvl_usd=500_000,
            tvl_7d_ago_usd=2_000_000,
            utilization_rate_pct=100,
            pending_redemptions_usd=499_000,
            daily_outflow_usd=200_000,
            stablecoin_collateral_pct=0,
            market_stress_score=100,
        )
        r = analyze([p])
        self.assertLessEqual(r["protocols"][0]["risk_score"], 100.0)

    def test_risk_score_never_below_zero(self):
        p = _make_protocol(
            tvl_usd=10_000_000,
            tvl_7d_ago_usd=10_000_000,
            utilization_rate_pct=0,
            pending_redemptions_usd=0,
            daily_outflow_usd=0,
            stablecoin_collateral_pct=100,
            market_stress_score=0,
        )
        r = analyze([p])
        self.assertGreaterEqual(r["protocols"][0]["risk_score"], 0.0)


# ---------------------------------------------------------------------------
# Recommendation strings
# ---------------------------------------------------------------------------

class TestRecommendations(unittest.TestCase):
    def _get_recommendation(self, score_target):
        """Find a configuration that gets close to the target risk level."""
        if score_target == "LOW":
            p = _make_protocol(market_stress_score=0)
        elif score_target == "MODERATE":
            p = _make_protocol(utilization_rate_pct=82, market_stress_score=30)
        elif score_target == "HIGH":
            p = _make_protocol(
                utilization_rate_pct=91,
                tvl_usd=5_000_000,
                tvl_7d_ago_usd=7_000_000,
                stablecoin_collateral_pct=20,
                market_stress_score=50,
            )
        else:  # CRITICAL
            p = _make_protocol(
                tvl_usd=1_000_000,
                tvl_7d_ago_usd=2_000_000,
                utilization_rate_pct=97,
                pending_redemptions_usd=950_000,
                stablecoin_collateral_pct=5,
                market_stress_score=90,
            )
        return analyze([p])["protocols"][0]["recommendation"]

    def test_critical_recommendation(self):
        self.assertIn("EXIT", self._get_recommendation("CRITICAL"))

    def test_low_recommendation(self):
        self.assertIn("no immediate action", self._get_recommendation("LOW"))


# ---------------------------------------------------------------------------
# TVL drop alert key risk with custom threshold
# ---------------------------------------------------------------------------

class TestCustomTvlDropAlert(unittest.TestCase):
    def test_custom_tvl_drop_threshold(self):
        p = _make_protocol(
            tvl_usd=8_500_000,
            tvl_7d_ago_usd=10_000_000,  # -15% drop
        )
        # Default threshold is 20%, so -15% won't trigger. With 10% it will.
        r_default = analyze([p])
        r_custom = analyze([p], config={"tvl_drop_alert_pct": 10.0})

        risks_default = r_default["protocols"][0]["key_risks"]
        risks_custom = r_custom["protocols"][0]["key_risks"]

        self.assertFalse(any("TVL dropped" in r for r in risks_default))
        self.assertTrue(any("TVL dropped" in r for r in risks_custom))


# ---------------------------------------------------------------------------
# Runway calculation
# ---------------------------------------------------------------------------

class TestRunwayCalculation(unittest.TestCase):
    def test_runway_calculation(self):
        p = _make_protocol(tvl_usd=1_000_000, daily_outflow_usd=10_000)
        r = analyze([p])
        self.assertAlmostEqual(r["protocols"][0]["runway_days"], 100.0)

    def test_runway_none_when_no_outflow(self):
        p = _make_protocol(daily_outflow_usd=0)
        r = analyze([p])
        self.assertIsNone(r["protocols"][0]["runway_days"])

    def test_runway_key_risk_triggered_below_30(self):
        p = _make_protocol(tvl_usd=1_000_000, daily_outflow_usd=50_000)  # 20 days
        r = analyze([p])
        risks = r["protocols"][0]["key_risks"]
        self.assertTrue(any("runway" in ri.lower() for ri in risks))

    def test_runway_no_key_risk_above_30(self):
        p = _make_protocol(tvl_usd=10_000_000, daily_outflow_usd=100_000)  # 100 days
        r = analyze([p])
        risks = r["protocols"][0]["key_risks"]
        self.assertFalse(any("runway" in ri.lower() for ri in risks))


# ---------------------------------------------------------------------------
# High utilization key risk
# ---------------------------------------------------------------------------

class TestUtilizationKeyRisk(unittest.TestCase):
    def test_utilization_91_triggers_key_risk(self):
        p = _make_protocol(utilization_rate_pct=91)
        r = analyze([p])
        risks = r["protocols"][0]["key_risks"]
        self.assertTrue(any("Utilization" in ri for ri in risks))

    def test_utilization_89_no_key_risk(self):
        p = _make_protocol(utilization_rate_pct=89)
        r = analyze([p])
        risks = r["protocols"][0]["key_risks"]
        self.assertFalse(any("Utilization" in ri for ri in risks))


if __name__ == "__main__":
    unittest.main()
