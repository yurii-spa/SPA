"""
Tests for MP-880 ProtocolFeeRevenueProjector
Run: python3 -m unittest spa_core.tests.test_protocol_fee_revenue_projector -v
"""

import json
import math
import os
import tempfile
import time
import unittest

from spa_core.analytics.protocol_fee_revenue_projector import (
    analyze,
    analyze_and_log,
    init_log,
    _cycle_multiplier,
    _combined_monthly_growth,
    _monthly_fee,
    _growth_trajectory,
    _sustainability_outlook,
    _projection_confidence,
    _compute_protocol,
    _LOG_FILE,
    _RING_BUFFER_MAX,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _protocol(name="ProtoA", fee=100_000.0, cycle="BULL", **overrides):
    base = {
        "name": name,
        "current_monthly_fee_usd": fee,
        "tvl_usd": 500_000_000.0,
        "tvl_growth_rate_30d_pct": 5.0,
        "fee_rate_bps": 30.0,
        "user_growth_rate_30d_pct": 3.0,
        "market_cycle_position": cycle,
    }
    base.update(overrides)
    return base


def _stable_bull(**overrides):
    return _protocol(
        tvl_growth_rate_30d_pct=2.0,
        user_growth_rate_30d_pct=1.0,
        market_cycle_position="BULL",
        **overrides,
    )


# ---------------------------------------------------------------------------
# 1. Empty input
# ---------------------------------------------------------------------------

class TestEmptyInput(unittest.TestCase):
    def test_empty_protocols_list(self):
        result = analyze([])
        self.assertEqual(result["protocols"], [])
        self.assertIsNone(result["highest_revenue_protocol"])
        self.assertIsNone(result["fastest_growing"])
        self.assertEqual(result["total_projected_annual_usd"], 0.0)
        self.assertEqual(result["average_revenue_cagr_pct"], 0.0)

    def test_empty_has_timestamp(self):
        before = time.time()
        result = analyze([])
        after = time.time()
        self.assertGreaterEqual(result["timestamp"], before)
        self.assertLessEqual(result["timestamp"], after)

    def test_empty_none_config(self):
        result = analyze([], config=None)
        self.assertEqual(result["protocols"], [])

    def test_empty_explicit_config(self):
        result = analyze([], config={"bear_multiplier": 0.3, "bull_multiplier": 2.0})
        self.assertEqual(result["total_projected_annual_usd"], 0.0)


# ---------------------------------------------------------------------------
# 2. Cycle multipliers
# ---------------------------------------------------------------------------

class TestCycleMultipliers(unittest.TestCase):
    def test_bear_default_0_5(self):
        self.assertAlmostEqual(_cycle_multiplier("BEAR", 0.5, 1.5), 0.5)

    def test_accumulation_fixed_0_8(self):
        self.assertAlmostEqual(_cycle_multiplier("ACCUMULATION", 0.5, 1.5), 0.8)

    def test_bull_default_1_5(self):
        self.assertAlmostEqual(_cycle_multiplier("BULL", 0.5, 1.5), 1.5)

    def test_peak_fixed_1_2(self):
        self.assertAlmostEqual(_cycle_multiplier("PEAK", 0.5, 1.5), 1.2)

    def test_bear_custom_multiplier(self):
        self.assertAlmostEqual(_cycle_multiplier("BEAR", 0.3, 1.5), 0.3)

    def test_bull_custom_multiplier(self):
        self.assertAlmostEqual(_cycle_multiplier("BULL", 0.5, 2.0), 2.0)

    def test_case_insensitive(self):
        self.assertAlmostEqual(_cycle_multiplier("bear", 0.4, 1.5), 0.4)
        self.assertAlmostEqual(_cycle_multiplier("Bull", 0.5, 1.8), 1.8)

    def test_unknown_cycle_neutral(self):
        m = _cycle_multiplier("UNKNOWN", 0.5, 1.5)
        self.assertAlmostEqual(m, 1.0)


# ---------------------------------------------------------------------------
# 3. Combined monthly growth
# ---------------------------------------------------------------------------

class TestCombinedMonthlyGrowth(unittest.TestCase):
    def test_both_zero_growth_zero(self):
        g = _combined_monthly_growth(0.0, 0.0)
        self.assertAlmostEqual(g, 0.0)

    def test_only_tvl_growth(self):
        g = _combined_monthly_growth(10.0, 0.0)
        self.assertAlmostEqual(g, 0.10)

    def test_only_user_growth(self):
        g = _combined_monthly_growth(0.0, 5.0)
        self.assertAlmostEqual(g, 0.05)

    def test_multiplicative_combination(self):
        # (1.05 * 1.03) - 1 = 0.0815
        g = _combined_monthly_growth(5.0, 3.0)
        self.assertAlmostEqual(g, (1.05 * 1.03) - 1.0, places=10)

    def test_negative_tvl_growth(self):
        g = _combined_monthly_growth(-10.0, 0.0)
        self.assertAlmostEqual(g, -0.10)

    def test_both_negative(self):
        g = _combined_monthly_growth(-5.0, -5.0)
        self.assertAlmostEqual(g, (0.95 * 0.95) - 1.0, places=10)


# ---------------------------------------------------------------------------
# 4. Monthly fee formula
# ---------------------------------------------------------------------------

class TestMonthlyFeeFormula(unittest.TestCase):
    def test_month_1_no_growth_equals_base_times_cycle(self):
        fee = _monthly_fee(100_000.0, 0.0, 1.5, 1)
        # (1 + 0)^1 * 1.5 * 100_000 = 150_000
        self.assertAlmostEqual(fee, 150_000.0, places=2)

    def test_month_3_with_growth(self):
        g = (1.05 * 1.03) - 1.0
        fee = _monthly_fee(100_000.0, g, 1.5, 3)
        expected = 100_000.0 * ((1.0 + g) ** 3) * 1.5
        self.assertAlmostEqual(fee, expected, places=2)

    def test_month_12_compounding(self):
        g = 0.05
        fee = _monthly_fee(50_000.0, g, 1.2, 12)
        expected = 50_000.0 * (1.05 ** 12) * 1.2
        self.assertAlmostEqual(fee, expected, places=2)

    def test_zero_fee_always_zero(self):
        fee = _monthly_fee(0.0, 0.05, 1.5, 6)
        self.assertAlmostEqual(fee, 0.0)

    def test_declining_growth_less_than_base(self):
        fee = _monthly_fee(100_000.0, -0.05, 1.0, 1)
        self.assertLess(fee, 100_000.0)


# ---------------------------------------------------------------------------
# 5. Growth trajectory
# ---------------------------------------------------------------------------

class TestGrowthTrajectory(unittest.TestCase):
    def test_volatile_positive(self):
        self.assertEqual(_growth_trajectory(0.16), "VOLATILE")

    def test_volatile_negative(self):
        self.assertEqual(_growth_trajectory(-0.16), "VOLATILE")

    def test_volatile_exact_boundary(self):
        self.assertEqual(_growth_trajectory(0.16), "VOLATILE")

    def test_accelerating(self):
        self.assertEqual(_growth_trajectory(0.10), "ACCELERATING")

    def test_accelerating_boundary(self):
        self.assertEqual(_growth_trajectory(0.051), "ACCELERATING")

    def test_steady_zero(self):
        self.assertEqual(_growth_trajectory(0.0), "STEADY")

    def test_steady_small_positive(self):
        self.assertEqual(_growth_trajectory(0.03), "STEADY")

    def test_steady_small_negative(self):
        self.assertEqual(_growth_trajectory(-0.02), "STEADY")

    def test_declining(self):
        self.assertEqual(_growth_trajectory(-0.05), "DECLINING")

    def test_declining_large(self):
        self.assertEqual(_growth_trajectory(-0.10), "DECLINING")

    def test_not_volatile_at_0_15(self):
        # abs(0.15) is NOT > 0.15, so not VOLATILE
        self.assertNotEqual(_growth_trajectory(0.15), "VOLATILE")


# ---------------------------------------------------------------------------
# 6. Sustainability outlook
# ---------------------------------------------------------------------------

class TestSustainabilityOutlook(unittest.TestCase):
    def test_strong_bull_high_cagr(self):
        self.assertEqual(_sustainability_outlook(60.0, "BULL"), "STRONG")

    def test_strong_accumulation_high_cagr(self):
        self.assertEqual(_sustainability_outlook(50.0, "ACCUMULATION"), "STRONG")

    def test_not_strong_in_peak_even_high_cagr(self):
        result = _sustainability_outlook(60.0, "PEAK")
        self.assertNotEqual(result, "STRONG")

    def test_positive_25_cagr(self):
        self.assertEqual(_sustainability_outlook(25.0, "BEAR"), "POSITIVE")

    def test_positive_exact_20(self):
        self.assertEqual(_sustainability_outlook(20.0, "BEAR"), "POSITIVE")

    def test_neutral_0(self):
        self.assertEqual(_sustainability_outlook(0.0, "PEAK"), "NEUTRAL")

    def test_neutral_negative_small(self):
        self.assertEqual(_sustainability_outlook(-5.0, "PEAK"), "NEUTRAL")

    def test_neutral_exact_minus_10(self):
        self.assertEqual(_sustainability_outlook(-10.0, "PEAK"), "NEUTRAL")

    def test_concerning_minus_20(self):
        self.assertEqual(_sustainability_outlook(-20.0, "PEAK"), "CONCERNING")

    def test_concerning_exact_minus_30(self):
        self.assertEqual(_sustainability_outlook(-30.0, "PEAK"), "CONCERNING")

    def test_at_risk_minus_31(self):
        self.assertEqual(_sustainability_outlook(-31.0, "PEAK"), "AT_RISK")

    def test_at_risk_very_negative(self):
        self.assertEqual(_sustainability_outlook(-80.0, "BEAR"), "AT_RISK")


# ---------------------------------------------------------------------------
# 7. Projection confidence
# ---------------------------------------------------------------------------

class TestProjectionConfidence(unittest.TestCase):
    def test_high_steady_accumulation(self):
        self.assertEqual(_projection_confidence("STEADY", "ACCUMULATION"), "HIGH")

    def test_high_steady_bull(self):
        self.assertEqual(_projection_confidence("STEADY", "BULL"), "HIGH")

    def test_low_volatile(self):
        self.assertEqual(_projection_confidence("VOLATILE", "BULL"), "LOW")

    def test_low_bear(self):
        self.assertEqual(_projection_confidence("STEADY", "BEAR"), "LOW")

    def test_medium_accelerating_bull(self):
        self.assertEqual(_projection_confidence("ACCELERATING", "BULL"), "MEDIUM")

    def test_medium_steady_peak(self):
        self.assertEqual(_projection_confidence("STEADY", "PEAK"), "MEDIUM")

    def test_medium_declining_accumulation(self):
        self.assertEqual(_projection_confidence("DECLINING", "ACCUMULATION"), "MEDIUM")


# ---------------------------------------------------------------------------
# 8. Single protocol — full computation
# ---------------------------------------------------------------------------

class TestSingleProtocol(unittest.TestCase):
    def setUp(self):
        self.p = _protocol(name="UniswapV4", fee=200_000.0, cycle="BULL",
                           tvl_growth_rate_30d_pct=5.0, user_growth_rate_30d_pct=3.0)
        self.result = analyze([self.p])
        self.proto = self.result["protocols"][0]

    def test_name_preserved(self):
        self.assertEqual(self.proto["name"], "UniswapV4")

    def test_current_fee_preserved(self):
        self.assertAlmostEqual(self.proto["current_monthly_fee_usd"], 200_000.0)

    def test_cycle_multiplier_bull(self):
        self.assertAlmostEqual(self.proto["cycle_adjusted_multiplier"], 1.5)

    def test_3m_less_than_12m(self):
        # With positive growth, 3m < 12m
        self.assertLess(
            self.proto["projected_monthly_fee_3m_usd"],
            self.proto["projected_monthly_fee_12m_usd"],
        )

    def test_projected_annual_sum_of_12_months(self):
        g = _combined_monthly_growth(5.0, 3.0)
        cycle_m = 1.5
        monthly = [_monthly_fee(200_000.0, g, cycle_m, m) for m in range(1, 13)]
        expected = sum(monthly)
        self.assertAlmostEqual(self.proto["projected_annual_fee_usd"], expected, places=2)

    def test_cagr_positive_growth(self):
        self.assertGreater(self.proto["revenue_cagr_pct"], 0.0)

    def test_single_protocol_highest_revenue_is_itself(self):
        self.assertEqual(self.result["highest_revenue_protocol"], "UniswapV4")

    def test_single_protocol_fastest_growing_is_itself(self):
        self.assertEqual(self.result["fastest_growing"], "UniswapV4")

    def test_total_annual_equals_single_protocol(self):
        self.assertAlmostEqual(
            self.result["total_projected_annual_usd"],
            self.proto["projected_annual_fee_usd"],
            places=2,
        )

    def test_average_cagr_equals_single_protocol(self):
        self.assertAlmostEqual(
            self.result["average_revenue_cagr_pct"],
            self.proto["revenue_cagr_pct"],
            places=6,
        )


# ---------------------------------------------------------------------------
# 9. Zero current_fee
# ---------------------------------------------------------------------------

class TestZeroFee(unittest.TestCase):
    def setUp(self):
        self.p = _protocol(fee=0.0)
        self.result = analyze([self.p])
        self.proto = self.result["protocols"][0]

    def test_all_projections_zero(self):
        self.assertAlmostEqual(self.proto["projected_monthly_fee_3m_usd"], 0.0)
        self.assertAlmostEqual(self.proto["projected_monthly_fee_6m_usd"], 0.0)
        self.assertAlmostEqual(self.proto["projected_monthly_fee_12m_usd"], 0.0)

    def test_annual_zero(self):
        self.assertAlmostEqual(self.proto["projected_annual_fee_usd"], 0.0)

    def test_cagr_zero(self):
        self.assertAlmostEqual(self.proto["revenue_cagr_pct"], 0.0)


# ---------------------------------------------------------------------------
# 10. All four market cycles
# ---------------------------------------------------------------------------

class TestMarketCycles(unittest.TestCase):
    def _run(self, cycle):
        p = _protocol(cycle=cycle)
        return analyze([p])["protocols"][0]

    def test_bear_multiplier_applied(self):
        proto = self._run("BEAR")
        self.assertAlmostEqual(proto["cycle_adjusted_multiplier"], 0.5)

    def test_accumulation_multiplier_applied(self):
        proto = self._run("ACCUMULATION")
        self.assertAlmostEqual(proto["cycle_adjusted_multiplier"], 0.8)

    def test_bull_multiplier_applied(self):
        proto = self._run("BULL")
        self.assertAlmostEqual(proto["cycle_adjusted_multiplier"], 1.5)

    def test_peak_multiplier_applied(self):
        proto = self._run("PEAK")
        self.assertAlmostEqual(proto["cycle_adjusted_multiplier"], 1.2)

    def test_bull_fee_higher_than_bear(self):
        bull = self._run("BULL")
        bear = self._run("BEAR")
        self.assertGreater(bull["projected_annual_fee_usd"], bear["projected_annual_fee_usd"])

    def test_bear_confidence_low(self):
        proto = self._run("BEAR")
        self.assertEqual(proto["projection_confidence"], "LOW")


# ---------------------------------------------------------------------------
# 11. Growth trajectories in full analyze
# ---------------------------------------------------------------------------

class TestGrowthTrajectories(unittest.TestCase):
    def _run(self, tvl_g, user_g):
        p = _protocol(tvl_growth_rate_30d_pct=tvl_g, user_growth_rate_30d_pct=user_g)
        return analyze([p])["protocols"][0]["growth_trajectory"]

    def test_volatile_large_tvl(self):
        self.assertEqual(self._run(20.0, 0.0), "VOLATILE")

    def test_volatile_large_negative(self):
        self.assertEqual(self._run(-20.0, 0.0), "VOLATILE")

    def test_accelerating(self):
        self.assertEqual(self._run(4.0, 2.0), "ACCELERATING")

    def test_steady(self):
        self.assertEqual(self._run(1.0, 0.5), "STEADY")

    def test_declining(self):
        self.assertEqual(self._run(-3.0, 0.0), "DECLINING")


# ---------------------------------------------------------------------------
# 12. Multiple protocols — aggregates
# ---------------------------------------------------------------------------

class TestMultipleProtocols(unittest.TestCase):
    def setUp(self):
        self.protocols = [
            _protocol(name="Big", fee=1_000_000.0, cycle="BULL",
                      tvl_growth_rate_30d_pct=5.0, user_growth_rate_30d_pct=3.0),
            _protocol(name="Small", fee=100_000.0, cycle="BEAR",
                      tvl_growth_rate_30d_pct=1.0, user_growth_rate_30d_pct=0.5),
            _protocol(name="Medium", fee=500_000.0, cycle="ACCUMULATION",
                      tvl_growth_rate_30d_pct=3.0, user_growth_rate_30d_pct=2.0),
        ]
        self.result = analyze(self.protocols)

    def test_three_protocols_returned(self):
        self.assertEqual(len(self.result["protocols"]), 3)

    def test_highest_revenue_is_big(self):
        self.assertEqual(self.result["highest_revenue_protocol"], "Big")

    def test_fastest_growing_exists(self):
        self.assertIn(self.result["fastest_growing"], ["Big", "Small", "Medium"])

    def test_total_annual_is_sum(self):
        expected = sum(p["projected_annual_fee_usd"] for p in self.result["protocols"])
        self.assertAlmostEqual(self.result["total_projected_annual_usd"], expected, places=2)

    def test_average_cagr_is_mean(self):
        cagrs = [p["revenue_cagr_pct"] for p in self.result["protocols"]]
        expected = sum(cagrs) / 3
        self.assertAlmostEqual(self.result["average_revenue_cagr_pct"], expected, places=6)

    def test_timestamp_present(self):
        self.assertIn("timestamp", self.result)

    def test_all_names_unique_in_output(self):
        names = [p["name"] for p in self.result["protocols"]]
        self.assertEqual(len(set(names)), 3)


# ---------------------------------------------------------------------------
# 13. CAGR formula verification
# ---------------------------------------------------------------------------

class TestCAGRFormula(unittest.TestCase):
    def test_cagr_zero_growth_minus_one_cycle(self):
        """Zero combined growth + cycle_mult=1.0 → projected_12m = current → CAGR=0."""
        p = _protocol(
            cycle="ACCUMULATION",  # mult=0.8
            tvl_growth_rate_30d_pct=0.0,
            user_growth_rate_30d_pct=0.0,
        )
        proto = analyze([p])["protocols"][0]
        # With 0 growth and cycle mult 0.8: fee_12m = current * 0.8 → cagr negative
        expected_cagr = (proto["projected_monthly_fee_12m_usd"] / p["current_monthly_fee_usd"] - 1) * 100
        self.assertAlmostEqual(proto["revenue_cagr_pct"], expected_cagr, places=6)

    def test_cagr_matches_12m_vs_current(self):
        p = _stable_bull(fee=80_000.0)
        proto = analyze([p])["protocols"][0]
        expected = (proto["projected_monthly_fee_12m_usd"] / p["current_monthly_fee_usd"] - 1) * 100
        self.assertAlmostEqual(proto["revenue_cagr_pct"], expected, places=6)


# ---------------------------------------------------------------------------
# 14. Custom config
# ---------------------------------------------------------------------------

class TestCustomConfig(unittest.TestCase):
    def test_custom_bear_multiplier(self):
        p = _protocol(cycle="BEAR")
        result = analyze([p], config={"bear_multiplier": 0.3})
        self.assertAlmostEqual(result["protocols"][0]["cycle_adjusted_multiplier"], 0.3)

    def test_custom_bull_multiplier(self):
        p = _protocol(cycle="BULL")
        result = analyze([p], config={"bull_multiplier": 2.5})
        self.assertAlmostEqual(result["protocols"][0]["cycle_adjusted_multiplier"], 2.5)

    def test_projection_months_in_config_ignored_gracefully(self):
        p = _protocol()
        # projection_months in config should not raise
        result = analyze([p], config={"projection_months": 12, "bull_multiplier": 1.5})
        self.assertIn("protocols", result)


# ---------------------------------------------------------------------------
# 15. Return structure completeness
# ---------------------------------------------------------------------------

class TestReturnStructure(unittest.TestCase):
    TOP_KEYS = {
        "protocols", "highest_revenue_protocol", "fastest_growing",
        "total_projected_annual_usd", "average_revenue_cagr_pct", "timestamp",
    }
    PROTO_KEYS = {
        "name", "current_monthly_fee_usd", "projected_monthly_fee_3m_usd",
        "projected_monthly_fee_6m_usd", "projected_monthly_fee_12m_usd",
        "projected_annual_fee_usd", "growth_trajectory", "cycle_adjusted_multiplier",
        "revenue_cagr_pct", "sustainability_outlook", "projection_confidence",
    }

    def test_top_level_keys(self):
        result = analyze([_protocol()])
        self.assertEqual(set(result.keys()), self.TOP_KEYS)

    def test_protocol_keys(self):
        result = analyze([_protocol()])
        proto = result["protocols"][0]
        for k in self.PROTO_KEYS:
            self.assertIn(k, proto, msg=f"Missing key: {k}")

    def test_timestamp_is_float(self):
        result = analyze([_protocol()])
        self.assertIsInstance(result["timestamp"], float)

    def test_total_annual_is_float(self):
        result = analyze([_protocol()])
        self.assertIsInstance(result["total_projected_annual_usd"], float)

    def test_average_cagr_is_float(self):
        result = analyze([_protocol()])
        self.assertIsInstance(result["average_revenue_cagr_pct"], float)

    def test_cycle_multiplier_is_float(self):
        result = analyze([_protocol()])
        self.assertIsInstance(result["protocols"][0]["cycle_adjusted_multiplier"], float)


# ---------------------------------------------------------------------------
# 16. Log file operations
# ---------------------------------------------------------------------------

class TestLogFile(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_init_log_creates_empty_file(self):
        init_log(data_dir=self.tmpdir)
        log_path = os.path.join(self.tmpdir, _LOG_FILE)
        self.assertTrue(os.path.exists(log_path))
        with open(log_path) as f:
            data = json.load(f)
        self.assertEqual(data, [])

    def test_init_log_does_not_overwrite_existing(self):
        log_path = os.path.join(self.tmpdir, _LOG_FILE)
        with open(log_path, "w") as f:
            json.dump([{"sentinel": 42}], f)
        init_log(data_dir=self.tmpdir)
        with open(log_path) as f:
            data = json.load(f)
        self.assertEqual(data[0]["sentinel"], 42)

    def test_analyze_and_log_creates_file(self):
        analyze_and_log([_protocol()], data_dir=self.tmpdir)
        log_path = os.path.join(self.tmpdir, _LOG_FILE)
        self.assertTrue(os.path.exists(log_path))

    def test_analyze_and_log_appends(self):
        for _ in range(5):
            analyze_and_log([_protocol()], data_dir=self.tmpdir)
        log_path = os.path.join(self.tmpdir, _LOG_FILE)
        with open(log_path) as f:
            data = json.load(f)
        self.assertEqual(len(data), 5)

    def test_ring_buffer_caps_at_100(self):
        for _ in range(_RING_BUFFER_MAX + 10):
            analyze_and_log([_protocol()], data_dir=self.tmpdir)
        log_path = os.path.join(self.tmpdir, _LOG_FILE)
        with open(log_path) as f:
            data = json.load(f)
        self.assertEqual(len(data), _RING_BUFFER_MAX)

    def test_log_entry_has_timestamp(self):
        analyze_and_log([_protocol()], data_dir=self.tmpdir)
        log_path = os.path.join(self.tmpdir, _LOG_FILE)
        with open(log_path) as f:
            data = json.load(f)
        self.assertIn("timestamp", data[0])

    def test_log_entry_has_protocols(self):
        analyze_and_log([_protocol()], data_dir=self.tmpdir)
        log_path = os.path.join(self.tmpdir, _LOG_FILE)
        with open(log_path) as f:
            data = json.load(f)
        self.assertIn("protocols", data[0])

    def test_log_recovery_from_corrupt_file(self):
        log_path = os.path.join(self.tmpdir, _LOG_FILE)
        with open(log_path, "w") as f:
            f.write("{bad json here")
        analyze_and_log([_protocol()], data_dir=self.tmpdir)
        with open(log_path) as f:
            data = json.load(f)
        self.assertEqual(len(data), 1)


# ---------------------------------------------------------------------------
# 17. Sustainability outlooks coverage
# ---------------------------------------------------------------------------

class TestSustainabilityOutlookCoverage(unittest.TestCase):
    def test_at_risk_bear_declining(self):
        p = _protocol(
            cycle="BEAR",
            tvl_growth_rate_30d_pct=-20.0,
            user_growth_rate_30d_pct=-10.0,
        )
        proto = analyze([p])["protocols"][0]
        self.assertEqual(proto["sustainability_outlook"], "AT_RISK")

    def test_strong_bull_high_growth(self):
        p = _protocol(
            cycle="BULL",
            tvl_growth_rate_30d_pct=10.0,
            user_growth_rate_30d_pct=8.0,
        )
        proto = analyze([p])["protocols"][0]
        self.assertIn(proto["sustainability_outlook"], ("STRONG", "POSITIVE"))

    def test_neutral_modest_growth_peak(self):
        p = _protocol(
            cycle="PEAK",
            tvl_growth_rate_30d_pct=1.0,
            user_growth_rate_30d_pct=0.5,
        )
        proto = analyze([p])["protocols"][0]
        # cagr should be around (1.0+g)^12 * 1.2 / 1 - 1
        self.assertIn(proto["sustainability_outlook"], ("POSITIVE", "NEUTRAL", "STRONG"))


# ---------------------------------------------------------------------------
# 18. Monotonicity & consistency
# ---------------------------------------------------------------------------

class TestMonotonicity(unittest.TestCase):
    def test_bull_greater_than_accumulation_greater_than_bear(self):
        """Same growth rate, different cycles → fee projections reflect multiplier order."""
        common = dict(tvl_growth_rate_30d_pct=3.0, user_growth_rate_30d_pct=2.0, fee=100_000.0)
        bull_proto = analyze([_protocol(cycle="BULL", **common)])["protocols"][0]
        acc_proto = analyze([_protocol(cycle="ACCUMULATION", **common)])["protocols"][0]
        bear_proto = analyze([_protocol(cycle="BEAR", **common)])["protocols"][0]
        self.assertGreater(bull_proto["projected_annual_fee_usd"], acc_proto["projected_annual_fee_usd"])
        self.assertGreater(acc_proto["projected_annual_fee_usd"], bear_proto["projected_annual_fee_usd"])

    def test_3m_6m_12m_increasing_with_positive_growth(self):
        p = _protocol(tvl_growth_rate_30d_pct=5.0, user_growth_rate_30d_pct=3.0, cycle="BULL")
        proto = analyze([p])["protocols"][0]
        self.assertLess(proto["projected_monthly_fee_3m_usd"], proto["projected_monthly_fee_6m_usd"])
        self.assertLess(proto["projected_monthly_fee_6m_usd"], proto["projected_monthly_fee_12m_usd"])

    def test_3m_6m_12m_decreasing_with_negative_growth_bear(self):
        p = _protocol(
            tvl_growth_rate_30d_pct=-5.0,
            user_growth_rate_30d_pct=-3.0,
            cycle="BEAR",
        )
        proto = analyze([p])["protocols"][0]
        self.assertGreater(proto["projected_monthly_fee_3m_usd"], proto["projected_monthly_fee_6m_usd"])
        self.assertGreater(proto["projected_monthly_fee_6m_usd"], proto["projected_monthly_fee_12m_usd"])


if __name__ == "__main__":
    unittest.main()
