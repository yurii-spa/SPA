"""
Tests for MP-1027: ProtocolDeFiProtocolRevenueSustainabilityAnalyzer
Run: python3 -m unittest spa_core.tests.test_protocol_defi_protocol_revenue_sustainability_analyzer
"""

import json
import math
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))))

from spa_core.analytics.protocol_defi_protocol_revenue_sustainability_analyzer import (
    ProtocolDeFiProtocolRevenueSustainabilityAnalyzer,
    _safe_mean,
    _safe_stdev,
    _revenue_volatility_pct,
    _diversification_score,
    _market_cycle_resilience,
    _burn_multiple_score,
    _trend_score,
    _sustainability_score,
    _sustainability_label,
    _compute_flags,
    _analyze_single,
    _compute_aggregates,
    _atomic_write,
    _append_log,
    LOG_CAP,
    REVENUE_NEAR_ZERO_THRESHOLD_USD,
)


# ── fixtures ──────────────────────────────────────────────────────────────────

def make_protocol(**overrides):
    """Create a baseline protocol dict."""
    base = {
        "name": "TestProtocol",
        "category": "lending",
        "weekly_revenue_usd": [100_000.0, 110_000.0, 105_000.0, 108_000.0],
        "weekly_costs_usd": [80_000.0, 85_000.0, 82_000.0, 83_000.0],
        "revenue_sources": {
            "trading_fees": 40.0,
            "lending_interest": 35.0,
            "liquidations": 15.0,
            "other": 10.0,
        },
        "token_price_usd": 5.0,
        "token_emissions_weekly_usd": 10_000.0,
        "team_size": 20,
        "treasury_runway_months": 24.0,
        "revenue_trend_pct": 3.0,
        "market_dependent_revenue_pct": 30.0,
    }
    base.update(overrides)
    return base


def make_profitable_protocol(**overrides):
    p = make_protocol(
        weekly_revenue_usd=[500_000.0, 520_000.0, 510_000.0, 515_000.0],
        weekly_costs_usd=[200_000.0, 210_000.0, 205_000.0, 208_000.0],
        revenue_trend_pct=10.0,
        market_dependent_revenue_pct=20.0,
        treasury_runway_months=36.0,
        token_emissions_weekly_usd=10_000.0,
    )
    p.update(overrides)
    return p


def make_zombie_protocol(**overrides):
    p = make_protocol(
        name="ZombieProtocol",
        weekly_revenue_usd=[500.0, 300.0, 400.0, 200.0],
        weekly_costs_usd=[50_000.0, 55_000.0, 52_000.0, 53_000.0],
        token_emissions_weekly_usd=40_000.0,
        treasury_runway_months=3.0,
        revenue_trend_pct=-20.0,
    )
    p.update(overrides)
    return p


def make_unsustainable_protocol(**overrides):
    p = make_protocol(
        name="UnsustainableProtocol",
        weekly_revenue_usd=[10_000.0, 9_000.0, 8_000.0, 7_000.0],
        weekly_costs_usd=[50_000.0, 55_000.0, 52_000.0, 53_000.0],
        treasury_runway_months=6.0,
        revenue_trend_pct=-15.0,
        token_emissions_weekly_usd=20_000.0,
    )
    p.update(overrides)
    return p


# ── safe_mean / safe_stdev ────────────────────────────────────────────────────

class TestSafeMeanStdev(unittest.TestCase):

    def test_mean_basic(self):
        self.assertAlmostEqual(_safe_mean([1.0, 2.0, 3.0]), 2.0)

    def test_mean_empty_returns_zero(self):
        self.assertEqual(_safe_mean([]), 0.0)

    def test_mean_single_element(self):
        self.assertEqual(_safe_mean([42.0]), 42.0)

    def test_stdev_empty_returns_zero(self):
        self.assertEqual(_safe_stdev([]), 0.0)

    def test_stdev_single_returns_zero(self):
        self.assertEqual(_safe_stdev([5.0]), 0.0)

    def test_stdev_known_value(self):
        # statistics.stdev uses sample (n-1) denominator.
        # [0, 2]: mean=1, sum_sq_dev=2, sample_var=2/1=2, stdev=sqrt(2)
        vals = [0.0, 2.0]
        self.assertAlmostEqual(_safe_stdev(vals), 2 ** 0.5, places=4)


# ── revenue volatility ────────────────────────────────────────────────────────

class TestRevenueVolatility(unittest.TestCase):

    def test_stable_revenue_low_vol(self):
        vol = _revenue_volatility_pct([100.0, 100.0, 100.0, 100.0])
        self.assertEqual(vol, 0.0)

    def test_volatile_revenue_high_vol(self):
        vol = _revenue_volatility_pct([10.0, 100.0, 10.0, 100.0])
        self.assertGreater(vol, 50.0)

    def test_zero_mean_returns_zero(self):
        vol = _revenue_volatility_pct([0.0, 0.0, 0.0])
        self.assertEqual(vol, 0.0)

    def test_returns_float(self):
        vol = _revenue_volatility_pct([100.0, 110.0, 90.0])
        self.assertIsInstance(vol, float)

    def test_empty_list_returns_zero(self):
        vol = _revenue_volatility_pct([])
        self.assertEqual(vol, 0.0)

    def test_negative_mean_clamped(self):
        # Negative revenues are unusual but shouldn't crash
        vol = _revenue_volatility_pct([-100.0, -90.0, -110.0])
        self.assertIsInstance(vol, float)


# ── diversification score ─────────────────────────────────────────────────────

class TestDiversificationScore(unittest.TestCase):

    def test_uniform_distribution_max_score(self):
        sources = {"a": 25.0, "b": 25.0, "c": 25.0, "d": 25.0}
        score = _diversification_score(sources)
        self.assertGreater(score, 90.0)

    def test_single_source_low_score(self):
        sources = {"a": 100.0}
        score = _diversification_score(sources)
        self.assertEqual(score, 0.0)

    def test_empty_sources_zero(self):
        score = _diversification_score({})
        self.assertEqual(score, 0.0)

    def test_two_equal_sources(self):
        sources = {"a": 50.0, "b": 50.0}
        score = _diversification_score(sources)
        self.assertGreater(score, 50.0)

    def test_dominated_source_low_score(self):
        sources = {"a": 90.0, "b": 5.0, "c": 5.0}
        score = _diversification_score(sources)
        self.assertLess(score, 30.0)

    def test_score_between_0_and_100(self):
        sources = {"a": 60.0, "b": 30.0, "c": 10.0}
        score = _diversification_score(sources)
        self.assertGreaterEqual(score, 0.0)
        self.assertLessEqual(score, 100.0)

    def test_zero_total_returns_zero(self):
        sources = {"a": 0.0, "b": 0.0}
        score = _diversification_score(sources)
        self.assertEqual(score, 0.0)

    def test_returns_float(self):
        sources = {"a": 50.0, "b": 50.0}
        self.assertIsInstance(_diversification_score(sources), float)


# ── market cycle resilience ───────────────────────────────────────────────────

class TestMarketCycleResilience(unittest.TestCase):

    def test_zero_market_dep_full_resilience(self):
        self.assertEqual(_market_cycle_resilience(0.0), 100.0)

    def test_100_market_dep_no_resilience(self):
        self.assertEqual(_market_cycle_resilience(100.0), 0.0)

    def test_50_gives_50(self):
        self.assertAlmostEqual(_market_cycle_resilience(50.0), 50.0)

    def test_clamped_at_zero(self):
        self.assertGreaterEqual(_market_cycle_resilience(150.0), 0.0)

    def test_returns_float(self):
        self.assertIsInstance(_market_cycle_resilience(30.0), float)


# ── burn multiple score ───────────────────────────────────────────────────────

class TestBurnMultipleScore(unittest.TestCase):

    def test_zero_burn_gives_high_score(self):
        score = _burn_multiple_score(0.0)
        self.assertGreater(score, 80.0)

    def test_high_burn_gives_low_score(self):
        score = _burn_multiple_score(10.0)
        self.assertLess(score, 30.0)

    def test_score_clamped_0_100(self):
        for bm in [0, 0.5, 1.0, 2.0, 5.0, 100.0]:
            score = _burn_multiple_score(float(bm))
            self.assertGreaterEqual(score, 0.0)
            self.assertLessEqual(score, 100.0)

    def test_lower_burn_higher_score(self):
        s1 = _burn_multiple_score(0.3)
        s2 = _burn_multiple_score(0.8)
        s3 = _burn_multiple_score(2.0)
        self.assertGreater(s1, s2)
        self.assertGreater(s2, s3)


# ── trend score ────────────────────────────────────────────────────────────────

class TestTrendScore(unittest.TestCase):

    def test_zero_trend_gives_50(self):
        self.assertAlmostEqual(_trend_score(0.0), 50.0)

    def test_positive_trend_above_50(self):
        self.assertGreater(_trend_score(10.0), 50.0)

    def test_negative_trend_below_50(self):
        self.assertLess(_trend_score(-10.0), 50.0)

    def test_clamped_0_100(self):
        for t in [-100, -50, 0, 50, 100]:
            score = _trend_score(float(t))
            self.assertGreaterEqual(score, 0.0)
            self.assertLessEqual(score, 100.0)

    def test_returns_float(self):
        self.assertIsInstance(_trend_score(5.0), float)


# ── sustainability score ──────────────────────────────────────────────────────

class TestSustainabilityScore(unittest.TestCase):

    def test_profitable_protocol_high_score(self):
        score = _sustainability_score(0.4, 80.0, 90.0, 15.0)
        self.assertGreater(score, 60.0)

    def test_unsustainable_protocol_low_score(self):
        score = _sustainability_score(3.0, 10.0, 10.0, -20.0)
        self.assertLess(score, 40.0)

    def test_score_in_0_100_range(self):
        for bm in [0.3, 1.0, 2.0, 5.0]:
            for div in [0.0, 50.0, 100.0]:
                score = _sustainability_score(bm, div, 50.0, 0.0)
                self.assertGreaterEqual(score, 0.0)
                self.assertLessEqual(score, 100.0)


# ── sustainability label ──────────────────────────────────────────────────────

class TestSustainabilityLabel(unittest.TestCase):

    def _label_for(self, protocol, burn_mult, avg_rev, div_score, resilience):
        sus_score = _sustainability_score(burn_mult, div_score, resilience,
                                          protocol.get("revenue_trend_pct", 0.0))
        return _sustainability_label(protocol, burn_mult, avg_rev,
                                     div_score, resilience, sus_score)

    def test_highly_sustainable(self):
        p = make_protocol(revenue_trend_pct=8.0, treasury_runway_months=36.0,
                          token_emissions_weekly_usd=1000.0)
        label = self._label_for(p, 0.4, 500_000.0, 75.0, 80.0)
        self.assertEqual(label, "HIGHLY_SUSTAINABLE")

    def test_sustainable_profitable(self):
        p = make_protocol(revenue_trend_pct=3.0, treasury_runway_months=24.0)
        label = self._label_for(p, 0.7, 200_000.0, 50.0, 60.0)
        self.assertEqual(label, "SUSTAINABLE")

    def test_break_even(self):
        p = make_protocol(revenue_trend_pct=0.0, treasury_runway_months=18.0)
        label = self._label_for(p, 1.0, 100_000.0, 40.0, 50.0)
        self.assertEqual(label, "BREAK_EVEN")

    def test_subsidized(self):
        p = make_protocol(revenue_trend_pct=-2.0, treasury_runway_months=24.0)
        label = self._label_for(p, 1.5, 100_000.0, 30.0, 40.0)
        self.assertEqual(label, "SUBSIDIZED")

    def test_unsustainable(self):
        p = make_protocol(treasury_runway_months=8.0, revenue_trend_pct=-10.0,
                          token_emissions_weekly_usd=30_000.0)
        label = self._label_for(p, 3.0, 10_000.0, 10.0, 20.0)
        self.assertEqual(label, "UNSUSTAINABLE")

    def test_zombie(self):
        p = make_protocol(token_emissions_weekly_usd=50_000.0,
                          treasury_runway_months=2.0)
        label = self._label_for(p, 99.0, 500.0, 5.0, 20.0)
        self.assertEqual(label, "ZOMBIE")

    def test_returns_string(self):
        p = make_protocol()
        label = self._label_for(p, 0.8, 100_000.0, 50.0, 70.0)
        self.assertIsInstance(label, str)


# ── compute flags ─────────────────────────────────────────────────────────────

class TestComputeFlags(unittest.TestCase):

    def test_profitable_flag(self):
        p = make_protocol(weekly_revenue_usd=[100_000.0] * 4)
        flags = _compute_flags(p, 0.7, 100_000.0,
                               {"trading_fees": 50.0, "other": 50.0})
        self.assertIn("PROFITABLE", flags)

    def test_not_profitable_no_flag(self):
        p = make_protocol()
        flags = _compute_flags(p, 1.5, 100_000.0,
                               {"trading_fees": 50.0, "other": 50.0})
        self.assertNotIn("PROFITABLE", flags)

    def test_emission_subsidized_flag(self):
        p = make_protocol(token_emissions_weekly_usd=200_000.0)
        flags = _compute_flags(p, 1.5, 100_000.0,
                               {"trading_fees": 50.0, "other": 50.0})
        self.assertIn("EMISSION_SUBSIDIZED", flags)

    def test_low_diversification_flag(self):
        p = make_protocol()
        flags = _compute_flags(p, 0.8, 100_000.0, {"trading_fees": 80.0, "other": 20.0})
        self.assertIn("LOW_REVENUE_DIVERSIFICATION", flags)

    def test_well_diversified_no_flag(self):
        p = make_protocol()
        flags = _compute_flags(p, 0.8, 100_000.0,
                               {"a": 30.0, "b": 30.0, "c": 25.0, "d": 15.0})
        self.assertNotIn("LOW_REVENUE_DIVERSIFICATION", flags)

    def test_market_dependent_flag(self):
        p = make_protocol(market_dependent_revenue_pct=70.0)
        flags = _compute_flags(p, 0.8, 100_000.0,
                               {"trading_fees": 50.0, "other": 50.0})
        self.assertIn("MARKET_DEPENDENT", flags)

    def test_not_market_dependent(self):
        p = make_protocol(market_dependent_revenue_pct=20.0)
        flags = _compute_flags(p, 0.8, 100_000.0,
                               {"trading_fees": 50.0, "other": 50.0})
        self.assertNotIn("MARKET_DEPENDENT", flags)

    def test_revenue_growing_flag(self):
        p = make_protocol(revenue_trend_pct=10.0)
        flags = _compute_flags(p, 0.8, 100_000.0,
                               {"trading_fees": 50.0, "other": 50.0})
        self.assertIn("REVENUE_GROWING", flags)

    def test_no_growth_no_flag(self):
        p = make_protocol(revenue_trend_pct=2.0)
        flags = _compute_flags(p, 0.8, 100_000.0,
                               {"trading_fees": 50.0, "other": 50.0})
        self.assertNotIn("REVENUE_GROWING", flags)

    def test_runway_critical_flag(self):
        p = make_protocol(treasury_runway_months=3.0)
        flags = _compute_flags(p, 0.8, 100_000.0,
                               {"trading_fees": 50.0, "other": 50.0})
        self.assertIn("RUNWAY_CRITICAL", flags)

    def test_no_runway_critical_if_long(self):
        p = make_protocol(treasury_runway_months=24.0)
        flags = _compute_flags(p, 0.8, 100_000.0,
                               {"trading_fees": 50.0, "other": 50.0})
        self.assertNotIn("RUNWAY_CRITICAL", flags)

    def test_returns_list(self):
        p = make_protocol()
        flags = _compute_flags(p, 0.8, 100_000.0, {"a": 50.0, "b": 50.0})
        self.assertIsInstance(flags, list)


# ── analyze_single ─────────────────────────────────────────────────────────────

class TestAnalyzeSingle(unittest.TestCase):

    def test_returns_dict(self):
        p = make_protocol()
        result = _analyze_single(p)
        self.assertIsInstance(result, dict)

    def test_required_keys_present(self):
        p = make_protocol()
        result = _analyze_single(p)
        for key in ["name", "category", "avg_weekly_revenue_usd",
                    "avg_weekly_costs_usd", "weekly_profit_loss_usd",
                    "burn_multiple", "revenue_volatility_pct",
                    "diversification_score", "market_cycle_resilience",
                    "sustainability_score", "sustainability_label", "flags"]:
            self.assertIn(key, result)

    def test_name_preserved(self):
        p = make_protocol(name="Aave")
        result = _analyze_single(p)
        self.assertEqual(result["name"], "Aave")

    def test_category_preserved(self):
        p = make_protocol(category="dex")
        result = _analyze_single(p)
        self.assertEqual(result["category"], "dex")

    def test_avg_revenue_correct(self):
        p = make_protocol(weekly_revenue_usd=[100.0, 200.0, 300.0, 400.0])
        result = _analyze_single(p)
        self.assertAlmostEqual(result["avg_weekly_revenue_usd"], 250.0, places=1)

    def test_burn_multiple_correct(self):
        p = make_protocol(
            weekly_revenue_usd=[100.0, 100.0, 100.0, 100.0],
            weekly_costs_usd=[50.0, 50.0, 50.0, 50.0]
        )
        result = _analyze_single(p)
        self.assertAlmostEqual(result["burn_multiple"], 0.5, places=4)

    def test_profitable_when_revenue_exceeds_costs(self):
        p = make_profitable_protocol()
        result = _analyze_single(p)
        self.assertIn("PROFITABLE", result["flags"])

    def test_weekly_pnl_positive_when_profitable(self):
        p = make_profitable_protocol()
        result = _analyze_single(p)
        self.assertGreater(result["weekly_profit_loss_usd"], 0.0)

    def test_sustainability_score_range(self):
        p = make_protocol()
        result = _analyze_single(p)
        self.assertGreaterEqual(result["sustainability_score"], 0.0)
        self.assertLessEqual(result["sustainability_score"], 100.0)

    def test_empty_revenue_handled(self):
        p = make_protocol(weekly_revenue_usd=[], weekly_costs_usd=[])
        result = _analyze_single(p)
        self.assertIsNotNone(result["sustainability_label"])

    def test_zero_revenue_high_burn(self):
        p = make_protocol(weekly_revenue_usd=[0.0, 0.0, 0.0, 0.0],
                          weekly_costs_usd=[10_000.0, 10_000.0, 10_000.0, 10_000.0])
        result = _analyze_single(p)
        # burn_multiple should be sentinel (9999)
        self.assertEqual(result["burn_multiple"], 9999.0)


# ── compute aggregates ────────────────────────────────────────────────────────

class TestComputeAggregates(unittest.TestCase):

    def test_empty_returns_defaults(self):
        agg = _compute_aggregates([])
        self.assertIsNone(agg["most_sustainable"])
        self.assertIsNone(agg["least_sustainable"])
        self.assertEqual(agg["avg_sustainability_score"], 0.0)
        self.assertEqual(agg["profitable_count"], 0)
        self.assertEqual(agg["zombie_count"], 0)

    def test_single_item(self):
        analyzed = [_analyze_single(make_protocol(name="P1"))]
        agg = _compute_aggregates(analyzed)
        self.assertEqual(agg["most_sustainable"]["name"], "P1")
        self.assertEqual(agg["least_sustainable"]["name"], "P1")

    def test_avg_score_correct(self):
        a1 = {"sustainability_score": 60.0, "sustainability_label": "SUSTAINABLE",
               "name": "A", "flags": ["PROFITABLE"]}
        a2 = {"sustainability_score": 40.0, "sustainability_label": "SUBSIDIZED",
               "name": "B", "flags": []}
        agg = _compute_aggregates([a1, a2])
        self.assertAlmostEqual(agg["avg_sustainability_score"], 50.0, places=2)

    def test_profitable_count(self):
        a1 = {"sustainability_score": 70.0, "sustainability_label": "SUSTAINABLE",
               "name": "A", "flags": ["PROFITABLE"]}
        a2 = {"sustainability_score": 30.0, "sustainability_label": "UNSUSTAINABLE",
               "name": "B", "flags": []}
        agg = _compute_aggregates([a1, a2])
        self.assertEqual(agg["profitable_count"], 1)

    def test_zombie_count(self):
        a1 = {"sustainability_score": 5.0, "sustainability_label": "ZOMBIE",
               "name": "A", "flags": []}
        a2 = {"sustainability_score": 10.0, "sustainability_label": "ZOMBIE",
               "name": "B", "flags": []}
        agg = _compute_aggregates([a1, a2])
        self.assertEqual(agg["zombie_count"], 2)

    def test_most_sustainable_highest_score(self):
        a1 = {"sustainability_score": 80.0, "sustainability_label": "HIGHLY_SUSTAINABLE",
               "name": "Best", "flags": ["PROFITABLE"]}
        a2 = {"sustainability_score": 20.0, "sustainability_label": "ZOMBIE",
               "name": "Worst", "flags": []}
        agg = _compute_aggregates([a1, a2])
        self.assertEqual(agg["most_sustainable"]["name"], "Best")
        self.assertEqual(agg["least_sustainable"]["name"], "Worst")


# ── main analyzer class ───────────────────────────────────────────────────────

class TestProtocolDeFiProtocolRevenueSustainabilityAnalyzer(unittest.TestCase):

    def setUp(self):
        self.analyzer = ProtocolDeFiProtocolRevenueSustainabilityAnalyzer()
        self.tmpdir = tempfile.mkdtemp()
        self.log_path = os.path.join(self.tmpdir, "test_sustainability_log.json")

    def _cfg(self):
        return {"log_path": self.log_path, "write_log": True}

    def test_returns_dict(self):
        result = self.analyzer.analyze([make_protocol()], self._cfg())
        self.assertIsInstance(result, dict)

    def test_has_required_keys(self):
        result = self.analyzer.analyze([make_protocol()], self._cfg())
        for key in ["ts", "protocol_count", "analyzed_protocols", "aggregates"]:
            self.assertIn(key, result)

    def test_empty_list_allowed(self):
        result = self.analyzer.analyze([], {"log_path": self.log_path, "write_log": False})
        self.assertEqual(result["protocol_count"], 0)
        self.assertEqual(result["analyzed_protocols"], [])

    def test_protocol_count_matches_input(self):
        protocols = [make_protocol(name=f"P{i}") for i in range(4)]
        result = self.analyzer.analyze(protocols, self._cfg())
        self.assertEqual(result["protocol_count"], 4)

    def test_non_list_raises_type_error(self):
        with self.assertRaises(TypeError):
            self.analyzer.analyze({"invalid": True}, self._cfg())

    def test_log_written(self):
        self.analyzer.analyze([make_protocol()], self._cfg())
        self.assertTrue(os.path.exists(self.log_path))

    def test_log_is_json_list(self):
        self.analyzer.analyze([make_protocol()], self._cfg())
        with open(self.log_path) as f:
            data = json.load(f)
        self.assertIsInstance(data, list)

    def test_log_entry_has_ts(self):
        self.analyzer.analyze([make_protocol()], self._cfg())
        with open(self.log_path) as f:
            data = json.load(f)
        self.assertIn("ts", data[-1])

    def test_log_ring_buffer_cap(self):
        for _ in range(LOG_CAP + 5):
            self.analyzer.analyze([make_protocol()], self._cfg())
        with open(self.log_path) as f:
            data = json.load(f)
        self.assertLessEqual(len(data), LOG_CAP)

    def test_write_log_false_no_file(self):
        cfg = {"log_path": self.log_path, "write_log": False}
        self.analyzer.analyze([make_protocol()], cfg)
        self.assertFalse(os.path.exists(self.log_path))

    def test_ts_is_string(self):
        result = self.analyzer.analyze([make_protocol()], self._cfg())
        self.assertIsInstance(result["ts"], str)

    def test_profitable_protocol_labeled_correctly(self):
        result = self.analyzer.analyze([make_profitable_protocol()], self._cfg())
        label = result["analyzed_protocols"][0]["sustainability_label"]
        self.assertIn(label, ["HIGHLY_SUSTAINABLE", "SUSTAINABLE"])

    def test_zombie_protocol_labeled_zombie(self):
        result = self.analyzer.analyze([make_zombie_protocol()], self._cfg())
        label = result["analyzed_protocols"][0]["sustainability_label"]
        self.assertEqual(label, "ZOMBIE")

    def test_unsustainable_protocol_labeled(self):
        result = self.analyzer.analyze([make_unsustainable_protocol()], self._cfg())
        label = result["analyzed_protocols"][0]["sustainability_label"]
        self.assertIn(label, ["UNSUSTAINABLE", "SUBSIDIZED", "BREAK_EVEN"])

    def test_profitable_flag_in_output(self):
        result = self.analyzer.analyze([make_profitable_protocol()], self._cfg())
        flags = result["analyzed_protocols"][0]["flags"]
        self.assertIn("PROFITABLE", flags)

    def test_emission_subsidized_flag(self):
        p = make_protocol(
            weekly_revenue_usd=[5_000.0] * 4,
            token_emissions_weekly_usd=50_000.0,
        )
        result = self.analyzer.analyze([p], self._cfg())
        flags = result["analyzed_protocols"][0]["flags"]
        self.assertIn("EMISSION_SUBSIDIZED", flags)

    def test_low_diversification_flag(self):
        p = make_protocol(revenue_sources={"trading_fees": 85.0, "other": 15.0})
        result = self.analyzer.analyze([p], self._cfg())
        flags = result["analyzed_protocols"][0]["flags"]
        self.assertIn("LOW_REVENUE_DIVERSIFICATION", flags)

    def test_market_dependent_flag(self):
        p = make_protocol(market_dependent_revenue_pct=75.0)
        result = self.analyzer.analyze([p], self._cfg())
        flags = result["analyzed_protocols"][0]["flags"]
        self.assertIn("MARKET_DEPENDENT", flags)

    def test_revenue_growing_flag(self):
        p = make_protocol(revenue_trend_pct=20.0)
        result = self.analyzer.analyze([p], self._cfg())
        flags = result["analyzed_protocols"][0]["flags"]
        self.assertIn("REVENUE_GROWING", flags)

    def test_runway_critical_flag(self):
        p = make_protocol(treasury_runway_months=4.0)
        result = self.analyzer.analyze([p], self._cfg())
        flags = result["analyzed_protocols"][0]["flags"]
        self.assertIn("RUNWAY_CRITICAL", flags)

    def test_aggregates_present(self):
        result = self.analyzer.analyze([make_protocol()], self._cfg())
        agg = result["aggregates"]
        self.assertIn("most_sustainable", agg)
        self.assertIn("least_sustainable", agg)
        self.assertIn("avg_sustainability_score", agg)
        self.assertIn("profitable_count", agg)
        self.assertIn("zombie_count", agg)

    def test_multiple_protocols_aggregated(self):
        protocols = [
            make_profitable_protocol(name="Good"),
            make_zombie_protocol(name="Bad"),
        ]
        result = self.analyzer.analyze(protocols, self._cfg())
        agg = result["aggregates"]
        self.assertEqual(agg["most_sustainable"]["name"], "Good")
        self.assertEqual(agg["least_sustainable"]["name"], "Bad")

    def test_avg_sustainability_positive(self):
        protocols = [make_protocol(name=f"P{i}") for i in range(3)]
        result = self.analyzer.analyze(protocols, self._cfg())
        self.assertGreater(result["aggregates"]["avg_sustainability_score"], 0.0)

    def test_all_categories_allowed(self):
        cats = ["lending", "dex", "derivatives", "yield-aggregator", "stablecoin"]
        for cat in cats:
            p = make_protocol(category=cat)
            result = self.analyzer.analyze([p],
                                           {"log_path": self.log_path, "write_log": False})
            self.assertEqual(result["analyzed_protocols"][0]["category"], cat)

    def test_diversification_score_range(self):
        result = self.analyzer.analyze([make_protocol()], self._cfg())
        div = result["analyzed_protocols"][0]["diversification_score"]
        self.assertGreaterEqual(div, 0.0)
        self.assertLessEqual(div, 100.0)

    def test_market_resilience_range(self):
        result = self.analyzer.analyze([make_protocol()], self._cfg())
        res = result["analyzed_protocols"][0]["market_cycle_resilience"]
        self.assertGreaterEqual(res, 0.0)
        self.assertLessEqual(res, 100.0)

    def test_burn_multiple_above_1_not_profitable(self):
        p = make_protocol(
            weekly_revenue_usd=[50_000.0] * 4,
            weekly_costs_usd=[100_000.0] * 4,
        )
        result = self.analyzer.analyze([p], self._cfg())
        flags = result["analyzed_protocols"][0]["flags"]
        self.assertNotIn("PROFITABLE", flags)

    def test_burn_multiple_computed_correctly(self):
        p = make_protocol(
            weekly_revenue_usd=[200_000.0] * 4,
            weekly_costs_usd=[100_000.0] * 4,
        )
        result = self.analyzer.analyze([p], self._cfg())
        bm = result["analyzed_protocols"][0]["burn_multiple"]
        self.assertAlmostEqual(bm, 0.5, places=3)


# ── atomic write ──────────────────────────────────────────────────────────────

class TestAtomicWrite(unittest.TestCase):

    def test_file_created(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "test.json")
            _atomic_write(path, {"x": 1})
            self.assertTrue(os.path.exists(path))

    def test_content_correct(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "test.json")
            _atomic_write(path, [10, 20, 30])
            with open(path) as f:
                self.assertEqual(json.load(f), [10, 20, 30])

    def test_overwrites_existing(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "test.json")
            _atomic_write(path, {"v": 1})
            _atomic_write(path, {"v": 99})
            with open(path) as f:
                self.assertEqual(json.load(f)["v"], 99)


# ── append log ────────────────────────────────────────────────────────────────

class TestAppendLog(unittest.TestCase):

    def _entry(self):
        return {
            "protocol_count": 2,
            "aggregates": {
                "avg_sustainability_score": 60.0,
                "profitable_count": 1,
                "zombie_count": 0,
            }
        }

    def test_log_created(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "log.json")
            _append_log(self._entry(), path)
            self.assertTrue(os.path.exists(path))

    def test_log_grows(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "log.json")
            for _ in range(3):
                _append_log(self._entry(), path)
            with open(path) as f:
                data = json.load(f)
            self.assertEqual(len(data), 3)

    def test_ring_buffer_capped(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "log.json")
            for _ in range(LOG_CAP + 15):
                _append_log(self._entry(), path)
            with open(path) as f:
                data = json.load(f)
            self.assertLessEqual(len(data), LOG_CAP)

    def test_entry_has_ts_key(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "log.json")
            _append_log(self._entry(), path)
            with open(path) as f:
                data = json.load(f)
            self.assertIn("ts", data[0])

    def test_corrupted_log_recovered(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "log.json")
            with open(path, "w") as f:
                f.write("NOT VALID JSON")
            # Should not raise
            _append_log(self._entry(), path)
            with open(path) as f:
                data = json.load(f)
            self.assertEqual(len(data), 1)


if __name__ == "__main__":
    unittest.main()
