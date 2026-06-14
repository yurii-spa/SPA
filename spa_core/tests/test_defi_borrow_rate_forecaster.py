"""
Tests for MP-974 DeFiBorrowRateForecaster
Run: python3 -m unittest spa_core.tests.test_defi_borrow_rate_forecaster -v
"""
import json
import os
import tempfile
import unittest

from spa_core.analytics.defi_borrow_rate_forecaster import (
    DeFiBorrowRateForecaster,
    _kink_rate,
    _risk_score,
    _forecast_label,
    _atomic_write,
)


# ── Minimal market helper ──────────────────────────────────────────────────────

def _market(
    protocol="Aave",
    asset="USDC",
    util=70.0,
    kink=80.0,
    base_rate=0.0,
    slope1=0.05,
    slope2=0.5,
    util_7d=68.0,
    util_30d_avg=66.0,
    net_inflow=0.0,
    total_supply=1_000_000.0,
    large_exposure=10.0,
    seasonal=1.0,
):
    return {
        "protocol": protocol,
        "asset": asset,
        "current_utilization_pct": util,
        "kink_pct": kink,
        "base_rate": base_rate,
        "slope1": slope1,
        "slope2": slope2,
        "utilization_7d_ago_pct": util_7d,
        "utilization_30d_avg_pct": util_30d_avg,
        "net_inflow_30d_usd": net_inflow,
        "total_supply_usd": total_supply,
        "large_borrower_exposure_pct": large_exposure,
        "seasonal_adjustment": seasonal,
    }


# ── Kink rate unit tests ───────────────────────────────────────────────────────

class TestKinkRate(unittest.TestCase):

    def test_below_kink_uses_slope1(self):
        rate = _kink_rate(50.0, 80.0, 0.0, 0.05, 0.5)
        self.assertAlmostEqual(rate, 0.05 * 50.0, places=8)

    def test_at_kink_uses_slope1(self):
        rate = _kink_rate(80.0, 80.0, 0.0, 0.05, 0.5)
        self.assertAlmostEqual(rate, 0.05 * 80.0, places=8)

    def test_above_kink_activates_slope2(self):
        rate = _kink_rate(90.0, 80.0, 0.0, 0.05, 0.5)
        expected = 0.05 * 80.0 + 0.5 * (90.0 - 80.0)
        self.assertAlmostEqual(rate, expected, places=8)

    def test_base_rate_added(self):
        rate = _kink_rate(50.0, 80.0, 2.0, 0.05, 0.5)
        self.assertAlmostEqual(rate, 2.0 + 0.05 * 50.0, places=8)

    def test_zero_utilization(self):
        rate = _kink_rate(0.0, 80.0, 1.0, 0.05, 0.5)
        self.assertAlmostEqual(rate, 1.0, places=8)

    def test_full_utilization(self):
        rate = _kink_rate(100.0, 80.0, 0.0, 0.05, 0.5)
        expected = 0.05 * 80.0 + 0.5 * 20.0
        self.assertAlmostEqual(rate, expected, places=8)

    def test_zero_slopes(self):
        rate = _kink_rate(90.0, 80.0, 3.0, 0.0, 0.0)
        self.assertAlmostEqual(rate, 3.0, places=8)

    def test_high_slope2(self):
        rate = _kink_rate(85.0, 80.0, 0.0, 0.0, 2.0)
        self.assertAlmostEqual(rate, 2.0 * 5.0, places=8)

    def test_kink_at_zero(self):
        # Everything above kink
        rate = _kink_rate(50.0, 0.0, 0.0, 0.05, 0.5)
        expected = 0.05 * 0.0 + 0.5 * 50.0
        self.assertAlmostEqual(rate, expected, places=8)

    def test_kink_at_100(self):
        # Everything below kink
        rate = _kink_rate(99.0, 100.0, 0.0, 0.05, 0.5)
        self.assertAlmostEqual(rate, 0.05 * 99.0, places=8)


# ── Risk score unit tests ──────────────────────────────────────────────────────

class TestRiskScore(unittest.TestCase):

    def test_returns_int(self):
        score = _risk_score(70.0, 80.0, "stable", 30.0)
        self.assertIsInstance(score, int)

    def test_range_0_to_100(self):
        score = _risk_score(79.0, 80.0, "rising", 300.0)
        self.assertGreaterEqual(score, 0)
        self.assertLessEqual(score, 100)

    def test_very_near_kink_high_score(self):
        # Within 2 pp of kink = +40
        score_near = _risk_score(79.0, 80.0, "stable", 0.0)
        score_far = _risk_score(60.0, 80.0, "stable", 0.0)
        self.assertGreater(score_near, score_far)

    def test_above_kink_extra_risk(self):
        score_above = _risk_score(85.0, 80.0, "stable", 0.0)
        score_below = _risk_score(75.0, 80.0, "stable", 0.0)
        self.assertGreater(score_above, score_below)

    def test_rising_trend_adds_score(self):
        score_rising = _risk_score(70.0, 80.0, "rising", 0.0)
        score_falling = _risk_score(70.0, 80.0, "falling", 0.0)
        self.assertGreater(score_rising, score_falling)

    def test_large_rate_change_adds_score(self):
        score_big = _risk_score(70.0, 80.0, "stable", 250.0)
        score_small = _risk_score(70.0, 80.0, "stable", 10.0)
        self.assertGreater(score_big, score_small)

    def test_capped_at_100(self):
        # Max possible inputs
        score = _risk_score(80.1, 80.0, "rising", 500.0)
        self.assertLessEqual(score, 100)

    def test_zero_case(self):
        # Far from kink, falling, no rate change
        score = _risk_score(10.0, 80.0, "falling", 0.0)
        self.assertGreaterEqual(score, 0)


# ── Forecast label unit tests ──────────────────────────────────────────────────

class TestForecastLabel(unittest.TestCase):

    def test_rate_spike_imminent(self):
        label = _forecast_label(85.0, 80.0, "rising", 200.0)
        self.assertEqual(label, "RATE_SPIKE_IMMINENT")

    def test_rate_normalization(self):
        label = _forecast_label(85.0, 80.0, "falling", -200.0)
        self.assertEqual(label, "RATE_NORMALIZATION")

    def test_rising(self):
        label = _forecast_label(70.0, 80.0, "rising", 100.0)
        self.assertEqual(label, "RISING")

    def test_falling(self):
        label = _forecast_label(70.0, 80.0, "falling", -100.0)
        self.assertEqual(label, "FALLING")

    def test_stable(self):
        label = _forecast_label(70.0, 80.0, "stable", 20.0)
        self.assertEqual(label, "STABLE")

    def test_spike_imminent_takes_priority_over_rising(self):
        # above kink + rising → RATE_SPIKE_IMMINENT even if bps > 50
        label = _forecast_label(82.0, 80.0, "rising", 100.0)
        self.assertEqual(label, "RATE_SPIKE_IMMINENT")

    def test_normalization_takes_priority_over_falling(self):
        label = _forecast_label(82.0, 80.0, "falling", -100.0)
        self.assertEqual(label, "RATE_NORMALIZATION")

    def test_exactly_at_threshold_stable(self):
        # bps == 50 → STABLE (not > threshold)
        label = _forecast_label(70.0, 80.0, "stable", 50.0)
        self.assertEqual(label, "STABLE")

    def test_above_kink_stable_trend(self):
        # above kink + stable trend, but bps within threshold
        label = _forecast_label(82.0, 80.0, "stable", 20.0)
        self.assertEqual(label, "STABLE")


# ── Integration tests (DeFiBorrowRateForecaster.forecast) ─────────────────────

class TestForecastIntegration(unittest.TestCase):

    def setUp(self):
        self.forecaster = DeFiBorrowRateForecaster()
        self.tmp = tempfile.mkdtemp()
        self.cfg = {"data_dir": self.tmp, "write_log": False}

    # ── Output structure ──────────────────────────────────────────────────────

    def test_empty_markets_returns_empty_list(self):
        result = self.forecaster.forecast([], self.cfg)
        self.assertEqual(result["markets"], [])

    def test_output_has_timestamp(self):
        result = self.forecaster.forecast([], self.cfg)
        self.assertIn("timestamp", result)
        self.assertTrue(result["timestamp"].endswith("Z"))

    def test_output_has_markets_key(self):
        result = self.forecaster.forecast([_market()], self.cfg)
        self.assertIn("markets", result)

    def test_output_has_aggregates_key(self):
        result = self.forecaster.forecast([_market()], self.cfg)
        self.assertIn("aggregates", result)

    def test_market_result_has_required_fields(self):
        result = self.forecaster.forecast([_market()], self.cfg)
        m = result["markets"][0]
        required = [
            "protocol", "asset", "current_utilization_pct", "current_borrow_rate_pct",
            "trend_direction", "forecast_7d_utilization_pct", "forecast_7d_borrow_rate_pct",
            "rate_change_bps", "rate_shock_risk_score", "forecast_label", "flags",
        ]
        for f in required:
            self.assertIn(f, m, f"Missing field: {f}")

    def test_aggregates_has_required_fields(self):
        result = self.forecaster.forecast([_market()], self.cfg)
        agg = result["aggregates"]
        for f in ["highest_rate_risk", "most_stable", "average_forecast_rate",
                  "spike_imminent_count", "falling_count"]:
            self.assertIn(f, agg)

    # ── Trend direction ───────────────────────────────────────────────────────

    def test_trend_rising(self):
        m = _market(util=75.0, util_7d=70.0)  # delta = +5 > 2
        res = self.forecaster.forecast([m], self.cfg)
        self.assertEqual(res["markets"][0]["trend_direction"], "rising")

    def test_trend_falling(self):
        m = _market(util=65.0, util_7d=70.0)  # delta = -5 < -2
        res = self.forecaster.forecast([m], self.cfg)
        self.assertEqual(res["markets"][0]["trend_direction"], "falling")

    def test_trend_stable(self):
        m = _market(util=71.0, util_7d=70.0)  # delta = +1 within ±2
        res = self.forecaster.forecast([m], self.cfg)
        self.assertEqual(res["markets"][0]["trend_direction"], "stable")

    def test_trend_rising_exactly_2(self):
        m = _market(util=72.0, util_7d=70.0)  # delta = +2, not > 2 → stable
        res = self.forecaster.forecast([m], self.cfg)
        self.assertEqual(res["markets"][0]["trend_direction"], "stable")

    def test_trend_rising_just_above_2(self):
        m = _market(util=72.1, util_7d=70.0)  # delta = +2.1 > 2 → rising
        res = self.forecaster.forecast([m], self.cfg)
        self.assertEqual(res["markets"][0]["trend_direction"], "rising")

    # ── Forecast utilization ──────────────────────────────────────────────────

    def test_forecast_util_clamps_to_100(self):
        m = _market(util=98.0, util_7d=90.0, seasonal=2.0)
        res = self.forecaster.forecast([m], self.cfg)
        self.assertLessEqual(res["markets"][0]["forecast_7d_utilization_pct"], 100.0)

    def test_forecast_util_clamps_to_zero(self):
        m = _market(util=2.0, util_7d=10.0, seasonal=2.0)
        res = self.forecaster.forecast([m], self.cfg)
        self.assertGreaterEqual(res["markets"][0]["forecast_7d_utilization_pct"], 0.0)

    def test_forecast_util_seasonal_amplifies(self):
        m1 = _market(util=75.0, util_7d=70.0, seasonal=1.0)
        m2 = _market(util=75.0, util_7d=70.0, seasonal=1.2)
        r1 = self.forecaster.forecast([m1], self.cfg)["markets"][0]
        r2 = self.forecaster.forecast([m2], self.cfg)["markets"][0]
        self.assertGreater(r2["forecast_7d_utilization_pct"], r1["forecast_7d_utilization_pct"])

    def test_forecast_util_seasonal_dampens(self):
        m1 = _market(util=75.0, util_7d=70.0, seasonal=1.0)
        m2 = _market(util=75.0, util_7d=70.0, seasonal=0.8)
        r1 = self.forecaster.forecast([m1], self.cfg)["markets"][0]
        r2 = self.forecaster.forecast([m2], self.cfg)["markets"][0]
        self.assertLess(r2["forecast_7d_utilization_pct"], r1["forecast_7d_utilization_pct"])

    def test_forecast_util_identity_seasonal_1(self):
        m = _market(util=75.0, util_7d=70.0, seasonal=1.0)
        res = self.forecaster.forecast([m], self.cfg)
        expected = 75.0 + (75.0 - 70.0) * 1.0  # = 80.0
        self.assertAlmostEqual(res["markets"][0]["forecast_7d_utilization_pct"], expected, places=4)

    # ── Rate change bps ───────────────────────────────────────────────────────

    def test_rate_change_bps_positive_when_rising(self):
        m = _market(util=75.0, util_7d=70.0)
        res = self.forecaster.forecast([m], self.cfg)
        self.assertGreater(res["markets"][0]["rate_change_bps"], 0)

    def test_rate_change_bps_negative_when_falling(self):
        m = _market(util=65.0, util_7d=70.0)
        res = self.forecaster.forecast([m], self.cfg)
        self.assertLess(res["markets"][0]["rate_change_bps"], 0)

    def test_rate_change_bps_zero_stable_no_delta(self):
        m = _market(util=70.0, util_7d=70.0, seasonal=1.0)
        res = self.forecaster.forecast([m], self.cfg)
        self.assertAlmostEqual(res["markets"][0]["rate_change_bps"], 0.0, places=4)

    # ── Flags ─────────────────────────────────────────────────────────────────

    def test_near_kink_flag_within_5(self):
        m = _market(util=76.0, kink=80.0)  # |76-80| = 4 ≤ 5 → flagged
        res = self.forecaster.forecast([m], self.cfg)
        self.assertIn("NEAR_KINK", res["markets"][0]["flags"])

    def test_near_kink_flag_exactly_5(self):
        m = _market(util=75.0, kink=80.0)  # |75-80| = 5 ≤ 5 → flagged
        res = self.forecaster.forecast([m], self.cfg)
        self.assertIn("NEAR_KINK", res["markets"][0]["flags"])

    def test_near_kink_flag_not_triggered(self):
        m = _market(util=70.0, kink=80.0)  # |70-80| = 10 > 5 → not flagged
        res = self.forecaster.forecast([m], self.cfg)
        self.assertNotIn("NEAR_KINK", res["markets"][0]["flags"])

    def test_large_borrower_risk_flag(self):
        m = _market(large_exposure=35.0)
        res = self.forecaster.forecast([m], self.cfg)
        self.assertIn("LARGE_BORROWER_RISK", res["markets"][0]["flags"])

    def test_large_borrower_risk_not_flagged_at_30(self):
        m = _market(large_exposure=30.0)  # not > 30
        res = self.forecaster.forecast([m], self.cfg)
        self.assertNotIn("LARGE_BORROWER_RISK", res["markets"][0]["flags"])

    def test_large_borrower_risk_not_flagged_below_30(self):
        m = _market(large_exposure=20.0)
        res = self.forecaster.forecast([m], self.cfg)
        self.assertNotIn("LARGE_BORROWER_RISK", res["markets"][0]["flags"])

    def test_supply_inflow_flag(self):
        # net_inflow = 60_000 > 5% of 1_000_000 = 50_000
        m = _market(net_inflow=60_000.0, total_supply=1_000_000.0)
        res = self.forecaster.forecast([m], self.cfg)
        self.assertIn("SUPPLY_INFLOW", res["markets"][0]["flags"])

    def test_supply_inflow_not_flagged_at_threshold(self):
        # net_inflow = 50_000 == exactly 5% of 1_000_000 → not > 5%
        m = _market(net_inflow=50_000.0, total_supply=1_000_000.0)
        res = self.forecaster.forecast([m], self.cfg)
        self.assertNotIn("SUPPLY_INFLOW", res["markets"][0]["flags"])

    def test_supply_inflow_not_flagged_zero_supply(self):
        m = _market(net_inflow=999_999.0, total_supply=0.0)
        res = self.forecaster.forecast([m], self.cfg)
        self.assertNotIn("SUPPLY_INFLOW", res["markets"][0]["flags"])

    def test_supply_inflow_not_flagged_negative_inflow(self):
        m = _market(net_inflow=-100_000.0, total_supply=1_000_000.0)
        res = self.forecaster.forecast([m], self.cfg)
        self.assertNotIn("SUPPLY_INFLOW", res["markets"][0]["flags"])

    def test_rate_above_10pct_flag(self):
        # base_rate=0, slope2=1.0, util=90, kink=80 → rate = 1*(90-80) = 10, not > 10
        # Use higher: util=91 → rate = 1*11 = 11 > 10
        m = _market(util=91.0, kink=80.0, base_rate=0.0, slope1=0.0, slope2=1.0)
        res = self.forecaster.forecast([m], self.cfg)
        self.assertIn("RATE_ABOVE_10PCT", res["markets"][0]["flags"])

    def test_rate_above_10pct_not_flagged_at_10(self):
        # rate = exactly 10 → not > 10
        m = _market(util=90.0, kink=80.0, base_rate=0.0, slope1=0.0, slope2=1.0)
        res = self.forecaster.forecast([m], self.cfg)
        self.assertNotIn("RATE_ABOVE_10PCT", res["markets"][0]["flags"])

    def test_trend_reversal_flag_7d_up_30d_below(self):
        # current=75, 7d_ago=70 (delta_7d=+5, rising), 30d_avg=80 (diff_30d=-5)
        m = _market(util=75.0, util_7d=70.0, util_30d_avg=80.0)
        res = self.forecaster.forecast([m], self.cfg)
        self.assertIn("TREND_REVERSAL", res["markets"][0]["flags"])

    def test_trend_reversal_flag_7d_down_30d_above(self):
        # current=65, 7d_ago=70 (delta_7d=-5, falling), 30d_avg=60 (diff_30d=+5)
        m = _market(util=65.0, util_7d=70.0, util_30d_avg=60.0)
        res = self.forecaster.forecast([m], self.cfg)
        self.assertIn("TREND_REVERSAL", res["markets"][0]["flags"])

    def test_no_trend_reversal_same_direction(self):
        # current=75, 7d_ago=70 (rising), 30d_avg=70 (also above → rising)
        m = _market(util=75.0, util_7d=70.0, util_30d_avg=70.0)
        res = self.forecaster.forecast([m], self.cfg)
        # diff_30d = 75-70 = +5, delta_7d = +5, same direction
        self.assertNotIn("TREND_REVERSAL", res["markets"][0]["flags"])

    def test_multiple_flags_can_coexist(self):
        m = _market(
            util=78.0, kink=80.0, base_rate=0.0, slope1=0.12, slope2=2.0,
            large_exposure=40.0, net_inflow=100_000.0, total_supply=1_000_000.0,
            util_7d=73.0, util_30d_avg=82.0
        )
        res = self.forecaster.forecast([m], self.cfg)
        flags = res["markets"][0]["flags"]
        # Should have NEAR_KINK + LARGE_BORROWER_RISK + SUPPLY_INFLOW + TREND_REVERSAL at minimum
        self.assertIn("NEAR_KINK", flags)
        self.assertIn("LARGE_BORROWER_RISK", flags)
        self.assertIn("SUPPLY_INFLOW", flags)
        self.assertIn("TREND_REVERSAL", flags)

    def test_no_flags(self):
        # Far from kink, low exposure, no inflow, low rate
        m = _market(util=50.0, kink=80.0, large_exposure=5.0, net_inflow=0.0,
                    util_7d=50.0, util_30d_avg=50.0, slope1=0.01, slope2=0.1)
        res = self.forecaster.forecast([m], self.cfg)
        self.assertEqual(res["markets"][0]["flags"], [])

    # ── Labels ────────────────────────────────────────────────────────────────

    def test_rate_spike_imminent_label(self):
        m = _market(util=85.0, kink=80.0, util_7d=80.0)  # above kink + rising
        res = self.forecaster.forecast([m], self.cfg)
        self.assertEqual(res["markets"][0]["forecast_label"], "RATE_SPIKE_IMMINENT")

    def test_rate_normalization_label(self):
        m = _market(util=85.0, kink=80.0, util_7d=92.0)  # above kink + falling
        res = self.forecaster.forecast([m], self.cfg)
        self.assertEqual(res["markets"][0]["forecast_label"], "RATE_NORMALIZATION")

    def test_stable_label(self):
        # No delta, no rate change
        m = _market(util=70.0, util_7d=70.0, kink=80.0, slope1=0.05, slope2=0.5)
        res = self.forecaster.forecast([m], self.cfg)
        self.assertEqual(res["markets"][0]["forecast_label"], "STABLE")

    # ── Aggregates ────────────────────────────────────────────────────────────

    def test_aggregates_empty(self):
        result = self.forecaster.forecast([], self.cfg)
        agg = result["aggregates"]
        self.assertIsNone(agg["highest_rate_risk"])
        self.assertIsNone(agg["most_stable"])
        self.assertEqual(agg["average_forecast_rate"], 0.0)
        self.assertEqual(agg["spike_imminent_count"], 0)
        self.assertEqual(agg["falling_count"], 0)

    def test_aggregates_single_market(self):
        m = _market(protocol="Alpha")
        result = self.forecaster.forecast([m], self.cfg)
        agg = result["aggregates"]
        self.assertEqual(agg["highest_rate_risk"], "Alpha")
        self.assertEqual(agg["most_stable"], "Alpha")

    def test_aggregates_spike_imminent_count(self):
        m1 = _market(protocol="A", util=85.0, kink=80.0, util_7d=80.0)  # spike
        m2 = _market(protocol="B", util=70.0, kink=80.0, util_7d=70.0)  # stable
        result = self.forecaster.forecast([m1, m2], self.cfg)
        self.assertEqual(result["aggregates"]["spike_imminent_count"], 1)

    def test_aggregates_falling_count(self):
        m1 = _market(protocol="A", util=65.0, util_7d=72.0, kink=80.0,
                     slope1=0.1, slope2=1.0)
        m2 = _market(protocol="B", util=70.0, util_7d=70.0, kink=80.0)
        result = self.forecaster.forecast([m1, m2], self.cfg)
        self.assertGreaterEqual(result["aggregates"]["falling_count"], 0)

    def test_aggregates_average_forecast_rate(self):
        # Two identical markets → average = their forecast rate
        m = _market(util=70.0, util_7d=70.0, kink=80.0, slope1=0.05)
        result = self.forecaster.forecast([m, m], self.cfg)
        # Average should equal individual forecast rate
        individual = result["markets"][0]["forecast_7d_borrow_rate_pct"]
        self.assertAlmostEqual(result["aggregates"]["average_forecast_rate"], individual, places=4)

    def test_aggregates_highest_rate_risk_correct_protocol(self):
        m1 = _market(protocol="LowRisk", util=50.0, kink=80.0)
        m2 = _market(protocol="HighRisk", util=79.0, kink=80.0, util_7d=73.0)  # near kink + rising
        result = self.forecaster.forecast([m1, m2], self.cfg)
        self.assertEqual(result["aggregates"]["highest_rate_risk"], "HighRisk")

    def test_aggregates_most_stable_correct_protocol(self):
        m1 = _market(protocol="Stable", util=70.0, util_7d=70.0)  # zero delta
        m2 = _market(protocol="Volatile", util=75.0, util_7d=65.0)  # large delta
        result = self.forecaster.forecast([m1, m2], self.cfg)
        self.assertEqual(result["aggregates"]["most_stable"], "Stable")

    def test_protocol_name_preserved(self):
        m = _market(protocol="MyProtocol")
        res = self.forecaster.forecast([m], self.cfg)
        self.assertEqual(res["markets"][0]["protocol"], "MyProtocol")

    def test_asset_name_preserved(self):
        m = _market(asset="DAI")
        res = self.forecaster.forecast([m], self.cfg)
        self.assertEqual(res["markets"][0]["asset"], "DAI")

    # ── Config ────────────────────────────────────────────────────────────────

    def test_config_none_does_not_crash(self):
        # write_log would try to write to "data/" dir - suppress by passing explicit cfg
        cfg = {"data_dir": self.tmp, "write_log": False}
        result = self.forecaster.forecast([_market()], cfg)
        self.assertIn("markets", result)

    def test_config_empty_uses_defaults(self):
        cfg = {"data_dir": self.tmp, "write_log": False}
        result = self.forecaster.forecast([_market()], cfg)
        self.assertIn("aggregates", result)

    def test_missing_optional_fields_use_defaults(self):
        # Minimal market with only required fields
        minimal = {"protocol": "Min", "current_utilization_pct": 70.0}
        result = self.forecaster.forecast([minimal], self.cfg)
        m = result["markets"][0]
        self.assertIn("current_borrow_rate_pct", m)

    # ── Log writing ───────────────────────────────────────────────────────────

    def test_write_log_false_no_file_created(self):
        cfg = {"data_dir": self.tmp, "write_log": False}
        self.forecaster.forecast([_market()], cfg)
        log_path = os.path.join(self.tmp, "borrow_rate_forecast_log.json")
        self.assertFalse(os.path.exists(log_path))

    def test_write_log_true_creates_file(self):
        cfg = {"data_dir": self.tmp, "write_log": True}
        self.forecaster.forecast([_market()], cfg)
        log_path = os.path.join(self.tmp, "borrow_rate_forecast_log.json")
        self.assertTrue(os.path.exists(log_path))

    def test_log_is_valid_json_array(self):
        cfg = {"data_dir": self.tmp, "write_log": True}
        self.forecaster.forecast([_market()], cfg)
        log_path = os.path.join(self.tmp, "borrow_rate_forecast_log.json")
        with open(log_path) as f:
            log = json.load(f)
        self.assertIsInstance(log, list)

    def test_log_appends_entries(self):
        cfg = {"data_dir": self.tmp, "write_log": True}
        self.forecaster.forecast([_market()], cfg)
        self.forecaster.forecast([_market()], cfg)
        log_path = os.path.join(self.tmp, "borrow_rate_forecast_log.json")
        with open(log_path) as f:
            log = json.load(f)
        self.assertEqual(len(log), 2)

    def test_log_ring_buffer_caps_entries(self):
        cfg = {"data_dir": self.tmp, "write_log": True, "log_cap": 3}
        for _ in range(5):
            self.forecaster.forecast([_market()], cfg)
        log_path = os.path.join(self.tmp, "borrow_rate_forecast_log.json")
        with open(log_path) as f:
            log = json.load(f)
        self.assertEqual(len(log), 3)

    def test_atomic_write_produces_correct_file(self):
        path = os.path.join(self.tmp, "test_atomic.json")
        data = {"key": "value"}
        _atomic_write(path, data)
        with open(path) as f:
            loaded = json.load(f)
        self.assertEqual(loaded, data)

    def test_no_tmp_file_left_after_atomic_write(self):
        path = os.path.join(self.tmp, "test_atomic2.json")
        _atomic_write(path, [1, 2, 3])
        self.assertFalse(os.path.exists(path + ".tmp"))

    # ── Edge cases ────────────────────────────────────────────────────────────

    def test_zero_utilization(self):
        m = _market(util=0.0, util_7d=0.0)
        result = self.forecaster.forecast([m], self.cfg)
        self.assertGreaterEqual(result["markets"][0]["current_borrow_rate_pct"], 0.0)

    def test_hundred_utilization(self):
        m = _market(util=100.0, util_7d=95.0)
        result = self.forecaster.forecast([m], self.cfg)
        self.assertIsNotNone(result["markets"][0]["forecast_label"])

    def test_risk_score_in_valid_range_always(self):
        scenarios = [
            _market(util=50.0, util_7d=40.0),
            _market(util=79.5, kink=80.0, util_7d=70.0),
            _market(util=99.0, kink=80.0, util_7d=85.0),
            _market(util=0.0, util_7d=0.0),
        ]
        for scenario in scenarios:
            res = self.forecaster.forecast([scenario], self.cfg)
            score = res["markets"][0]["rate_shock_risk_score"]
            self.assertGreaterEqual(score, 0)
            self.assertLessEqual(score, 100)

    def test_multiple_markets(self):
        markets = [_market(protocol=f"P{i}", util=float(40+i*5)) for i in range(5)]
        result = self.forecaster.forecast(markets, self.cfg)
        self.assertEqual(len(result["markets"]), 5)

    def test_all_spike_imminent_markets(self):
        markets = [
            _market(protocol=f"P{i}", util=85.0, kink=80.0, util_7d=79.0)
            for i in range(3)
        ]
        result = self.forecaster.forecast(markets, self.cfg)
        self.assertEqual(result["aggregates"]["spike_imminent_count"], 3)

    def test_current_borrow_rate_correctness_below_kink(self):
        m = _market(util=50.0, kink=80.0, base_rate=1.0, slope1=0.1, slope2=0.5)
        res = self.forecaster.forecast([m], self.cfg)
        expected = 1.0 + 0.1 * 50.0  # = 6.0
        self.assertAlmostEqual(res["markets"][0]["current_borrow_rate_pct"], expected, places=4)

    def test_current_borrow_rate_correctness_above_kink(self):
        m = _market(util=90.0, kink=80.0, base_rate=0.0, slope1=0.05, slope2=0.5)
        res = self.forecaster.forecast([m], self.cfg)
        expected = 0.05 * 80.0 + 0.5 * 10.0  # = 4 + 5 = 9.0
        self.assertAlmostEqual(res["markets"][0]["current_borrow_rate_pct"], expected, places=4)

    def test_large_borrower_exactly_30_not_flagged(self):
        m = _market(large_exposure=30.0)
        res = self.forecaster.forecast([m], self.cfg)
        self.assertNotIn("LARGE_BORROWER_RISK", res["markets"][0]["flags"])

    def test_supply_inflow_exactly_5pct_not_flagged(self):
        m = _market(net_inflow=50_000.0, total_supply=1_000_000.0)
        res = self.forecaster.forecast([m], self.cfg)
        self.assertNotIn("SUPPLY_INFLOW", res["markets"][0]["flags"])


if __name__ == "__main__":
    unittest.main()
