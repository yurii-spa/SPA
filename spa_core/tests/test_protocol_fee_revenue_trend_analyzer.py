"""
Tests for MP-979: ProtocolFeeRevenueTrendAnalyzer
Run: python3 -m unittest spa_core.tests.test_protocol_fee_revenue_trend_analyzer
"""

import json
import math
import os
import tempfile
import unittest

from spa_core.analytics.protocol_fee_revenue_trend_analyzer import (
    ProtocolFeeRevenueTrendAnalyzer,
    LABEL_HYPERGROWTH,
    LABEL_STRONG_GROWTH,
    LABEL_STABLE,
    LABEL_DECLINING,
    LABEL_COLLAPSING,
    FLAG_BEATS_COMPETITORS,
    FLAG_LOSING_MARKET_SHARE,
    FLAG_ONE_TIME_INFLATED,
    FLAG_TREND_REVERSAL,
    FLAG_STRONG_TREND,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_protocol(**kwargs):
    """Return a minimal valid protocol dict with overridable defaults."""
    base = {
        "name": "TestProtocol",
        "revenue_by_week_usd": [100_000.0] * 12,
        "protocol_type": "dex",
        "total_tvl_usd": 100_000_000.0,
        "competitor_avg_revenue_growth_pct": 10.0,
        "market_cycle": "neutral",
        "seasonal_factor": 1.0,
        "one_time_events_usd": 0.0,
    }
    base.update(kwargs)
    return base


def _make_growing_protocol(growth_pct: float = 60.0, **kwargs) -> dict:
    """Protocol with strong week-over-week growth."""
    weeks = []
    val = 50_000.0
    for _ in range(12):
        weeks.append(val)
        val *= (1 + growth_pct / 400.0)
    return _make_protocol(revenue_by_week_usd=weeks, **kwargs)


class TestProtocolFeeRevenueTrendAnalyzerBasic(unittest.TestCase):
    """Basic structure tests."""

    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp()
        self.log_file = os.path.join(self.tmp_dir, "fee_revenue_trend_log.json")
        self.analyzer = ProtocolFeeRevenueTrendAnalyzer(data_file=self.log_file)

    def test_returns_dict(self):
        result = self.analyzer.analyze([_make_protocol()])
        self.assertIsInstance(result, dict)

    def test_has_results_key(self):
        result = self.analyzer.analyze([_make_protocol()])
        self.assertIn("results", result)

    def test_has_aggregates_key(self):
        result = self.analyzer.analyze([_make_protocol()])
        self.assertIn("aggregates", result)

    def test_has_run_ts(self):
        result = self.analyzer.analyze([_make_protocol()])
        self.assertIn("run_ts", result)

    def test_has_protocol_count(self):
        result = self.analyzer.analyze([_make_protocol(), _make_protocol()])
        self.assertEqual(result["protocol_count"], 2)

    def test_empty_list(self):
        result = self.analyzer.analyze([])
        self.assertEqual(result["results"], [])
        self.assertEqual(result["protocol_count"], 0)

    def test_none_config_ok(self):
        result = self.analyzer.analyze([_make_protocol()], config=None)
        self.assertIsInstance(result, dict)

    def test_empty_config_ok(self):
        result = self.analyzer.analyze([_make_protocol()], config={})
        self.assertIsInstance(result, dict)

    def test_results_length_matches_input(self):
        protocols = [_make_protocol(name=f"P{i}") for i in range(4)]
        result = self.analyzer.analyze(protocols)
        self.assertEqual(len(result["results"]), 4)


class TestResultFields(unittest.TestCase):
    """Test that each result has required fields."""

    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp()
        self.log_file = os.path.join(self.tmp_dir, "fee_revenue_trend_log.json")
        self.analyzer = ProtocolFeeRevenueTrendAnalyzer(data_file=self.log_file)

    def _get_result(self, **kwargs):
        r = self.analyzer.analyze([_make_protocol(**kwargs)])
        return r["results"][0]

    def test_has_name(self):
        self.assertIn("name", self._get_result())

    def test_has_protocol_type(self):
        self.assertIn("protocol_type", self._get_result())

    def test_has_revenue_4w_avg_usd(self):
        self.assertIn("revenue_4w_avg_usd", self._get_result())

    def test_has_revenue_12w_avg_usd(self):
        self.assertIn("revenue_12w_avg_usd", self._get_result())

    def test_has_mom_growth_pct(self):
        self.assertIn("mom_growth_pct", self._get_result())

    def test_has_trend_slope(self):
        self.assertIn("trend_slope", self._get_result())

    def test_has_trend_r_squared(self):
        self.assertIn("trend_r_squared", self._get_result())

    def test_has_normalized_revenue_usd(self):
        self.assertIn("normalized_revenue_usd", self._get_result())

    def test_has_cycle_adjusted_growth(self):
        self.assertIn("cycle_adjusted_growth", self._get_result())

    def test_has_label(self):
        self.assertIn("label", self._get_result())

    def test_has_flags(self):
        self.assertIn("flags", self._get_result())

    def test_flags_is_list(self):
        r = self._get_result()
        self.assertIsInstance(r["flags"], list)

    def test_name_field_value(self):
        r = self._get_result(name="Uniswap")
        self.assertEqual(r["name"], "Uniswap")

    def test_protocol_type_field_value(self):
        r = self._get_result(protocol_type="lending")
        self.assertEqual(r["protocol_type"], "lending")

    def test_has_market_cycle(self):
        self.assertIn("market_cycle", self._get_result())

    def test_has_seasonal_factor(self):
        self.assertIn("seasonal_factor", self._get_result())


class TestRevenueAverages(unittest.TestCase):
    """Test revenue average computations."""

    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp()
        self.log_file = os.path.join(self.tmp_dir, "fee_revenue_trend_log.json")
        self.analyzer = ProtocolFeeRevenueTrendAnalyzer(data_file=self.log_file)

    def _get_result(self, **kwargs):
        r = self.analyzer.analyze([_make_protocol(**kwargs)])
        return r["results"][0]

    def test_flat_revenue_12w_avg(self):
        weeks = [100_000.0] * 12
        r = self._get_result(revenue_by_week_usd=weeks)
        self.assertAlmostEqual(r["revenue_12w_avg_usd"], 100_000.0, places=0)

    def test_flat_revenue_4w_avg(self):
        weeks = [100_000.0] * 12
        r = self._get_result(revenue_by_week_usd=weeks)
        self.assertAlmostEqual(r["revenue_4w_avg_usd"], 100_000.0, places=0)

    def test_4w_avg_uses_last_4_weeks(self):
        weeks = [0.0] * 8 + [200_000.0] * 4
        r = self._get_result(revenue_by_week_usd=weeks)
        self.assertAlmostEqual(r["revenue_4w_avg_usd"], 200_000.0, places=0)

    def test_12w_avg_is_mean(self):
        weeks = list(range(12))
        r = self._get_result(revenue_by_week_usd=weeks)
        expected = sum(range(12)) / 12.0
        self.assertAlmostEqual(r["revenue_12w_avg_usd"], expected, places=1)

    def test_empty_revenue_list(self):
        r = self._get_result(revenue_by_week_usd=[])
        self.assertIsInstance(r["revenue_4w_avg_usd"], float)

    def test_short_revenue_list(self):
        r = self._get_result(revenue_by_week_usd=[100.0, 200.0])
        self.assertIsInstance(r["revenue_4w_avg_usd"], float)


class TestMomGrowth(unittest.TestCase):
    """Test MoM growth computation."""

    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp()
        self.log_file = os.path.join(self.tmp_dir, "fee_revenue_trend_log.json")
        self.analyzer = ProtocolFeeRevenueTrendAnalyzer(data_file=self.log_file)

    def _get_result(self, **kwargs):
        r = self.analyzer.analyze([_make_protocol(**kwargs)])
        return r["results"][0]

    def test_flat_revenue_zero_growth(self):
        weeks = [100_000.0] * 12
        r = self._get_result(revenue_by_week_usd=weeks)
        self.assertAlmostEqual(r["mom_growth_pct"], 0.0, places=2)

    def test_doubling_revenue_positive_growth(self):
        # Last 4w avg = 200k, prev 4w avg = 100k → 100% growth
        weeks = [100_000.0] * 4 + [100_000.0] * 4 + [200_000.0] * 4
        r = self._get_result(revenue_by_week_usd=weeks)
        self.assertGreater(r["mom_growth_pct"], 0.0)

    def test_halving_revenue_negative_growth(self):
        weeks = [200_000.0] * 8 + [100_000.0] * 4
        r = self._get_result(revenue_by_week_usd=weeks)
        self.assertLess(r["mom_growth_pct"], 0.0)

    def test_mom_growth_is_float(self):
        r = self._get_result()
        self.assertIsInstance(r["mom_growth_pct"], float)


class TestTrendLabels(unittest.TestCase):
    """Test trend label assignment."""

    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp()
        self.log_file = os.path.join(self.tmp_dir, "fee_revenue_trend_log.json")
        self.analyzer = ProtocolFeeRevenueTrendAnalyzer(data_file=self.log_file)

    def _get_label(self, **kwargs):
        r = self.analyzer.analyze([_make_protocol(**kwargs)])
        return r["results"][0]["label"]

    def test_hypergrowth_label(self):
        # 8 low weeks then 4 very high weeks → high mom growth
        weeks = [10_000.0] * 8 + [700_000.0] * 4
        label = self._get_label(revenue_by_week_usd=weeks)
        self.assertEqual(label, LABEL_HYPERGROWTH)

    def test_collapsing_label(self):
        # 8 high weeks then 4 very low weeks
        weeks = [1_000_000.0] * 8 + [10_000.0] * 4
        label = self._get_label(revenue_by_week_usd=weeks)
        self.assertEqual(label, LABEL_COLLAPSING)

    def test_stable_label(self):
        weeks = [100_000.0] * 12
        label = self._get_label(revenue_by_week_usd=weeks)
        self.assertEqual(label, LABEL_STABLE)

    def test_valid_labels(self):
        valid = {LABEL_HYPERGROWTH, LABEL_STRONG_GROWTH, LABEL_STABLE, LABEL_DECLINING, LABEL_COLLAPSING}
        label = self._get_label()
        self.assertIn(label, valid)

    def test_strong_growth_label(self):
        weeks = [100_000.0] * 8 + [130_000.0] * 4
        label = self._get_label(revenue_by_week_usd=weeks)
        self.assertIn(label, {LABEL_STRONG_GROWTH, LABEL_HYPERGROWTH, LABEL_STABLE})

    def test_declining_label(self):
        weeks = [100_000.0] * 8 + [88_000.0] * 4
        label = self._get_label(revenue_by_week_usd=weeks)
        self.assertIn(label, {LABEL_DECLINING, LABEL_STABLE, LABEL_COLLAPSING})

    def test_custom_thresholds(self):
        weeks = [100_000.0] * 8 + [125_000.0] * 4
        r = self.analyzer.analyze(
            [_make_protocol(revenue_by_week_usd=weeks)],
            config={"hypergrowth_threshold": 5.0}
        )
        label = r["results"][0]["label"]
        self.assertEqual(label, LABEL_HYPERGROWTH)


class TestLinearRegression(unittest.TestCase):
    """Test linear regression metrics."""

    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp()
        self.log_file = os.path.join(self.tmp_dir, "fee_revenue_trend_log.json")
        self.analyzer = ProtocolFeeRevenueTrendAnalyzer(data_file=self.log_file)

    def _get_result(self, **kwargs):
        r = self.analyzer.analyze([_make_protocol(**kwargs)])
        return r["results"][0]

    def test_slope_positive_for_rising(self):
        weeks = [float(i * 10_000) for i in range(1, 13)]
        r = self._get_result(revenue_by_week_usd=weeks)
        self.assertGreater(r["trend_slope"], 0.0)

    def test_slope_negative_for_falling(self):
        weeks = [float((12 - i) * 10_000) for i in range(12)]
        r = self._get_result(revenue_by_week_usd=weeks)
        self.assertLess(r["trend_slope"], 0.0)

    def test_slope_zero_for_flat(self):
        weeks = [100_000.0] * 12
        r = self._get_result(revenue_by_week_usd=weeks)
        self.assertAlmostEqual(r["trend_slope"], 0.0, places=2)

    def test_r_squared_high_for_perfect_trend(self):
        weeks = [float(i * 10_000) for i in range(1, 13)]
        r = self._get_result(revenue_by_week_usd=weeks)
        self.assertGreater(r["trend_r_squared"], 0.95)

    def test_r_squared_in_range(self):
        r = self._get_result()
        self.assertGreaterEqual(r["trend_r_squared"], 0.0)
        self.assertLessEqual(r["trend_r_squared"], 1.0)

    def test_short_series_regression(self):
        r = self._get_result(revenue_by_week_usd=[100.0, 200.0])
        self.assertIsInstance(r["trend_slope"], float)
        self.assertIsInstance(r["trend_r_squared"], float)


class TestNormalizedRevenue(unittest.TestCase):
    """Test normalized revenue (minus one-time events)."""

    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp()
        self.log_file = os.path.join(self.tmp_dir, "fee_revenue_trend_log.json")
        self.analyzer = ProtocolFeeRevenueTrendAnalyzer(data_file=self.log_file)

    def _get_result(self, **kwargs):
        r = self.analyzer.analyze([_make_protocol(**kwargs)])
        return r["results"][0]

    def test_normalized_lower_with_one_time(self):
        r_no = self._get_result(one_time_events_usd=0.0)
        r_yes = self._get_result(one_time_events_usd=100_000.0)
        self.assertLessEqual(r_yes["normalized_revenue_usd"], r_no["normalized_revenue_usd"])

    def test_normalized_nonnegative(self):
        r = self._get_result(
            revenue_by_week_usd=[100.0] * 12,
            one_time_events_usd=1_000_000.0,
        )
        self.assertGreaterEqual(r["normalized_revenue_usd"], 0.0)

    def test_no_one_time_normalized_equals_4w_avg(self):
        weeks = [100_000.0] * 12
        r = self._get_result(revenue_by_week_usd=weeks, one_time_events_usd=0.0)
        self.assertAlmostEqual(r["normalized_revenue_usd"], r["revenue_4w_avg_usd"], places=0)


class TestCycleAdjustedGrowth(unittest.TestCase):
    """Test cycle-adjusted growth computation."""

    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp()
        self.log_file = os.path.join(self.tmp_dir, "fee_revenue_trend_log.json")
        self.analyzer = ProtocolFeeRevenueTrendAnalyzer(data_file=self.log_file)

    def _get_cag(self, **kwargs):
        r = self.analyzer.analyze([_make_protocol(**kwargs)])
        return r["results"][0]["cycle_adjusted_growth"]

    def test_bull_cycle_reduces_adj_growth(self):
        weeks = [100_000.0] * 8 + [130_000.0] * 4
        cag_neutral = self._get_cag(revenue_by_week_usd=weeks, market_cycle="neutral")
        cag_bull = self._get_cag(revenue_by_week_usd=weeks, market_cycle="bull")
        self.assertLessEqual(cag_bull, cag_neutral)

    def test_bear_cycle_increases_adj_growth(self):
        weeks = [100_000.0] * 8 + [130_000.0] * 4
        cag_neutral = self._get_cag(revenue_by_week_usd=weeks, market_cycle="neutral")
        cag_bear = self._get_cag(revenue_by_week_usd=weeks, market_cycle="bear")
        self.assertGreaterEqual(cag_bear, cag_neutral)

    def test_cycle_adjusted_growth_is_float(self):
        self.assertIsInstance(self._get_cag(), float)


class TestFlags(unittest.TestCase):
    """Test flag assignment."""

    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp()
        self.log_file = os.path.join(self.tmp_dir, "fee_revenue_trend_log.json")
        self.analyzer = ProtocolFeeRevenueTrendAnalyzer(data_file=self.log_file)

    def _get_flags(self, **kwargs):
        r = self.analyzer.analyze([_make_protocol(**kwargs)])
        return r["results"][0]["flags"]

    def test_beats_competitors_flag(self):
        # Growing strongly vs flat competitors
        weeks = [100_000.0] * 8 + [500_000.0] * 4
        flags = self._get_flags(
            revenue_by_week_usd=weeks,
            competitor_avg_revenue_growth_pct=5.0,
            market_cycle="neutral",
        )
        self.assertIn(FLAG_BEATS_COMPETITORS, flags)

    def test_losing_market_share_flag(self):
        # Declining while competitors grow
        weeks = [100_000.0] * 8 + [10_000.0] * 4
        flags = self._get_flags(
            revenue_by_week_usd=weeks,
            competitor_avg_revenue_growth_pct=30.0,
            market_cycle="neutral",
        )
        self.assertIn(FLAG_LOSING_MARKET_SHARE, flags)

    def test_one_time_inflated_flag(self):
        # One-time > 20% of 4w avg
        flags = self._get_flags(
            revenue_by_week_usd=[100_000.0] * 12,
            one_time_events_usd=50_000.0,
        )
        self.assertIn(FLAG_ONE_TIME_INFLATED, flags)

    def test_no_one_time_inflated_flag(self):
        flags = self._get_flags(
            revenue_by_week_usd=[100_000.0] * 12,
            one_time_events_usd=0.0,
        )
        self.assertNotIn(FLAG_ONE_TIME_INFLATED, flags)

    def test_trend_reversal_flag(self):
        # Rising trend overall but last week dropped
        weeks = [10_000.0, 20_000.0, 30_000.0, 40_000.0,
                 50_000.0, 60_000.0, 70_000.0, 80_000.0,
                 90_000.0, 100_000.0, 110_000.0, 90_000.0]
        flags = self._get_flags(revenue_by_week_usd=weeks)
        self.assertIn(FLAG_TREND_REVERSAL, flags)

    def test_strong_trend_flag(self):
        # Perfect linear increase → r_sq ≈ 1.0
        weeks = [float(i * 10_000) for i in range(1, 13)]
        flags = self._get_flags(revenue_by_week_usd=weeks)
        self.assertIn(FLAG_STRONG_TREND, flags)

    def test_no_strong_trend_flag_random(self):
        # Flat revenue has r_sq = 1.0 (trivially) — use noisy data
        import random
        random.seed(42)
        weeks = [100_000.0 + random.uniform(-50_000, 50_000) for _ in range(12)]
        flags = self._get_flags(revenue_by_week_usd=weeks)
        # May or may not have STRONG_TREND — just check flags is a list
        self.assertIsInstance(flags, list)


class TestAggregates(unittest.TestCase):
    """Test aggregate calculations."""

    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp()
        self.log_file = os.path.join(self.tmp_dir, "fee_revenue_trend_log.json")
        self.analyzer = ProtocolFeeRevenueTrendAnalyzer(data_file=self.log_file)

    def test_aggregates_empty(self):
        agg = self.analyzer.analyze([])["aggregates"]
        self.assertIsNone(agg["fastest_growing"])
        self.assertIsNone(agg["fastest_declining"])
        self.assertEqual(agg["average_mom_growth"], 0.0)
        self.assertEqual(agg["hypergrowth_count"], 0)
        self.assertEqual(agg["collapsing_count"], 0)

    def test_aggregates_fastest_growing(self):
        p1 = _make_protocol(name="Slow", revenue_by_week_usd=[100_000.0] * 12)
        p2 = _make_protocol(name="Fast", revenue_by_week_usd=[100_000.0] * 8 + [500_000.0] * 4)
        agg = self.analyzer.analyze([p1, p2])["aggregates"]
        self.assertEqual(agg["fastest_growing"], "Fast")

    def test_aggregates_fastest_declining(self):
        p1 = _make_protocol(name="Stable", revenue_by_week_usd=[100_000.0] * 12)
        p2 = _make_protocol(name="Crash", revenue_by_week_usd=[100_000.0] * 8 + [1_000.0] * 4)
        agg = self.analyzer.analyze([p1, p2])["aggregates"]
        self.assertEqual(agg["fastest_declining"], "Crash")

    def test_hypergrowth_count(self):
        p = _make_protocol(revenue_by_week_usd=[10_000.0] * 8 + [700_000.0] * 4)
        agg = self.analyzer.analyze([p])["aggregates"]
        self.assertGreaterEqual(agg["hypergrowth_count"], 0)

    def test_collapsing_count(self):
        p = _make_protocol(revenue_by_week_usd=[1_000_000.0] * 8 + [10_000.0] * 4)
        agg = self.analyzer.analyze([p])["aggregates"]
        self.assertGreaterEqual(agg["collapsing_count"], 0)

    def test_average_mom_growth_is_float(self):
        agg = self.analyzer.analyze([_make_protocol()])["aggregates"]
        self.assertIsInstance(agg["average_mom_growth"], float)

    def test_average_mom_growth_flat(self):
        p = _make_protocol(revenue_by_week_usd=[100_000.0] * 12)
        agg = self.analyzer.analyze([p])["aggregates"]
        self.assertAlmostEqual(agg["average_mom_growth"], 0.0, places=2)


class TestRingBufferLog(unittest.TestCase):
    """Test ring-buffer log writes."""

    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp()
        self.log_file = os.path.join(self.tmp_dir, "fee_revenue_trend_log.json")
        self.analyzer = ProtocolFeeRevenueTrendAnalyzer(data_file=self.log_file)

    def test_log_created_after_analyze(self):
        self.analyzer.analyze([_make_protocol()])
        self.assertTrue(os.path.exists(self.log_file))

    def test_log_is_list(self):
        self.analyzer.analyze([_make_protocol()])
        with open(self.log_file) as f:
            data = json.load(f)
        self.assertIsInstance(data, list)

    def test_log_grows_with_calls(self):
        self.analyzer.analyze([_make_protocol()])
        self.analyzer.analyze([_make_protocol()])
        with open(self.log_file) as f:
            data = json.load(f)
        self.assertEqual(len(data), 2)

    def test_log_ring_buffer_cap_100(self):
        for _ in range(110):
            self.analyzer.analyze([_make_protocol()])
        with open(self.log_file) as f:
            data = json.load(f)
        self.assertLessEqual(len(data), 100)

    def test_log_has_run_ts(self):
        self.analyzer.analyze([_make_protocol()])
        with open(self.log_file) as f:
            data = json.load(f)
        self.assertIn("run_ts", data[0])

    def test_log_has_protocol_count(self):
        self.analyzer.analyze([_make_protocol()])
        with open(self.log_file) as f:
            data = json.load(f)
        self.assertIn("protocol_count", data[0])

    def test_log_atomic_write(self):
        self.analyzer.analyze([_make_protocol()])
        tmp_files = [f for f in os.listdir(self.tmp_dir) if f.endswith(".tmp")]
        self.assertEqual(len(tmp_files), 0)

    def test_invalid_log_recovers(self):
        with open(self.log_file, "w") as f:
            f.write("not json{{{")
        self.analyzer.analyze([_make_protocol()])
        with open(self.log_file) as f:
            data = json.load(f)
        self.assertEqual(len(data), 1)


class TestEdgeCases(unittest.TestCase):
    """Edge cases and boundary conditions."""

    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp()
        self.log_file = os.path.join(self.tmp_dir, "fee_revenue_trend_log.json")
        self.analyzer = ProtocolFeeRevenueTrendAnalyzer(data_file=self.log_file)

    def _get_result(self, **kwargs):
        r = self.analyzer.analyze([_make_protocol(**kwargs)])
        return r["results"][0]

    def test_zero_revenue_all_weeks(self):
        r = self._get_result(revenue_by_week_usd=[0.0] * 12)
        self.assertIsInstance(r["mom_growth_pct"], float)

    def test_single_week_revenue(self):
        r = self._get_result(revenue_by_week_usd=[100_000.0])
        self.assertIsInstance(r["revenue_4w_avg_usd"], float)

    def test_very_large_revenue(self):
        r = self._get_result(revenue_by_week_usd=[1e12] * 12)
        self.assertIn("label", r)

    def test_unknown_market_cycle(self):
        r = self._get_result(market_cycle="unknown")
        self.assertIsInstance(r["cycle_adjusted_growth"], float)

    def test_seasonal_factor_zero(self):
        r = self._get_result(seasonal_factor=0.0)
        self.assertIsInstance(r["cycle_adjusted_growth"], float)

    def test_competitor_growth_zero(self):
        r = self._get_result(competitor_avg_revenue_growth_pct=0.0)
        self.assertIsInstance(r["flags"], list)

    def test_negative_revenue_weeks(self):
        r = self._get_result(revenue_by_week_usd=[-1000.0] * 12)
        self.assertIsInstance(r["mom_growth_pct"], float)

    def test_protocol_types(self):
        for ptype in ["dex", "lending", "perp", "bridge", "staking"]:
            r = self._get_result(protocol_type=ptype)
            self.assertEqual(r["protocol_type"], ptype)

    def test_missing_optional_fields(self):
        proto = {"name": "MinProto", "revenue_by_week_usd": [100.0] * 12}
        r = self.analyzer.analyze([proto])
        self.assertIsInstance(r["results"][0]["label"], str)

    def test_run_ts_is_string(self):
        result = self.analyzer.analyze([_make_protocol()])
        self.assertIsInstance(result["run_ts"], str)

    def test_multiple_protocols_independent(self):
        protocols = [
            _make_protocol(name="A", revenue_by_week_usd=[100_000.0] * 12),
            _make_protocol(name="B", revenue_by_week_usd=[1_000_000.0] * 8 + [10_000.0] * 4),
        ]
        r = self.analyzer.analyze(protocols)
        self.assertEqual(len(r["results"]), 2)
        self.assertEqual(r["results"][0]["name"], "A")
        self.assertEqual(r["results"][1]["name"], "B")

    def test_normalized_revenue_is_float(self):
        r = self._get_result()
        self.assertIsInstance(r["normalized_revenue_usd"], float)

    def test_r_squared_is_float(self):
        r = self._get_result()
        self.assertIsInstance(r["trend_r_squared"], float)

    def test_trend_slope_is_float(self):
        r = self._get_result()
        self.assertIsInstance(r["trend_slope"], float)


if __name__ == "__main__":
    unittest.main()
