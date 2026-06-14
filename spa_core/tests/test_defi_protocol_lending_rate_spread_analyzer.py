"""
Tests for MP-1010 DeFiProtocolLendingRateSpreadAnalyzer
Run: python3 -m unittest spa_core.tests.test_defi_protocol_lending_rate_spread_analyzer
"""

import json
import os
import sys
import tempfile
import time
import unittest

# ---------------------------------------------------------------------------
# Path setup — allow running from repo root
# ---------------------------------------------------------------------------
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from spa_core.analytics.defi_protocol_lending_rate_spread_analyzer import (
    DeFiProtocolLendingRateSpreadAnalyzer,
    LABEL_TIGHT_SPREAD,
    LABEL_EFFICIENT,
    LABEL_NORMAL,
    LABEL_WIDE_SPREAD,
    LABEL_INEFFICIENT,
    FLAG_HIGH_UTILIZATION_RISK,
    FLAG_WIDE_SPREAD_OPPORTUNITY,
    FLAG_LOW_RESERVE_FACTOR,
    FLAG_PREMIUM_YIELD,
    FLAG_LIQUIDATION_PROXIMITY,
    FLAG_TIGHT_EFFICIENT_MARKET,
    _spread_efficiency_score,
    _classify_market,
    _compute_flags,
)


def _make_market(**kwargs):
    base = {
        "name": "Test-Market",
        "protocol": "TestProtocol",
        "asset": "USDC",
        "supply_apy_pct": 3.5,
        "borrow_apy_pct": 5.8,
        "utilization_rate_pct": 72.0,
        "total_supplied_usd": 100_000_000.0,
        "total_borrowed_usd": 72_000_000.0,
        "reserve_factor_pct": 10.0,
        "spread_benchmark_pct": 2.0,
        "liquidation_threshold_pct": 80.0,
        "liquidation_bonus_pct": 5.0,
        "protocol_fee_pct": 0.3,
    }
    base.update(kwargs)
    return base


class TestSpreadEfficiencyScore(unittest.TestCase):
    """Tests for _spread_efficiency_score helper."""

    def test_tight_spread_good_util_high_score(self):
        score = _spread_efficiency_score(1.0, 75.0)
        self.assertGreater(score, 70.0)

    def test_wide_spread_low_score(self):
        score = _spread_efficiency_score(9.0, 50.0)
        self.assertLess(score, 30.0)

    def test_very_tight_spread_any_util(self):
        score = _spread_efficiency_score(0.3, 70.0)
        self.assertGreater(score, 80.0)

    def test_score_in_range_0_100(self):
        for spread in [0.0, 1.0, 3.0, 6.0, 10.0, 20.0]:
            for util in [10.0, 50.0, 75.0, 92.0, 99.0]:
                score = _spread_efficiency_score(spread, util)
                self.assertGreaterEqual(score, 0.0)
                self.assertLessEqual(score, 100.0)

    def test_extreme_utilization_reduces_score(self):
        score_normal = _spread_efficiency_score(2.0, 75.0)
        score_extreme = _spread_efficiency_score(2.0, 98.0)
        self.assertGreater(score_normal, score_extreme)

    def test_increasing_spread_decreases_score(self):
        s1 = _spread_efficiency_score(0.5, 70.0)
        s2 = _spread_efficiency_score(3.0, 70.0)
        s3 = _spread_efficiency_score(8.0, 70.0)
        self.assertGreater(s1, s2)
        self.assertGreater(s2, s3)

    def test_optimal_util_band_boosts_score(self):
        score_opt = _spread_efficiency_score(2.0, 70.0)
        score_low_util = _spread_efficiency_score(2.0, 20.0)
        self.assertGreater(score_opt, score_low_util)

    def test_medium_spread_medium_util(self):
        score = _spread_efficiency_score(3.0, 60.0)
        self.assertGreater(score, 0.0)
        self.assertLess(score, 100.0)


class TestClassifyMarket(unittest.TestCase):
    """Tests for _classify_market helper."""

    def test_tight_spread_correct_util(self):
        label = _classify_market(1.0, 0.8, 70.0)
        self.assertEqual(label, LABEL_TIGHT_SPREAD)

    def test_wide_spread_label(self):
        label = _classify_market(6.0, 5.0, 70.0)
        self.assertEqual(label, LABEL_WIDE_SPREAD)

    def test_inefficient_due_to_high_spread(self):
        label = _classify_market(9.0, 8.5, 70.0)
        self.assertEqual(label, LABEL_INEFFICIENT)

    def test_inefficient_due_to_high_utilization(self):
        label = _classify_market(2.0, 1.5, 96.0)
        self.assertEqual(label, LABEL_INEFFICIENT)

    def test_efficient_label(self):
        label = _classify_market(2.5, 2.0, 55.0)
        self.assertEqual(label, LABEL_EFFICIENT)

    def test_normal_label(self):
        label = _classify_market(4.0, 3.5, 65.0)
        self.assertEqual(label, LABEL_NORMAL)

    def test_tight_spread_wrong_util_not_tight(self):
        # spread < 1.5 but util outside 60-80 band → EFFICIENT (spread<3)
        label = _classify_market(1.0, 0.8, 40.0)
        self.assertEqual(label, LABEL_EFFICIENT)

    def test_spread_just_below_wide_threshold(self):
        # 4.9 is between 3 and 5 → NORMAL (not yet WIDE_SPREAD, not EFFICIENT)
        label = _classify_market(4.9, 4.0, 60.0)
        self.assertEqual(label, LABEL_NORMAL)

    def test_spread_exactly_at_inefficient_threshold(self):
        # exactly 8% → INEFFICIENT boundary
        label = _classify_market(8.1, 7.5, 60.0)
        self.assertEqual(label, LABEL_INEFFICIENT)


class TestComputeFlags(unittest.TestCase):
    """Tests for _compute_flags helper."""

    def test_high_utilization_flag(self):
        flags = _compute_flags(3.0, 10.0, 92.0, 1.0, 5.0)
        self.assertIn(FLAG_HIGH_UTILIZATION_RISK, flags)

    def test_no_high_util_below_90(self):
        flags = _compute_flags(3.0, 10.0, 89.0, 1.0, 5.0)
        self.assertNotIn(FLAG_HIGH_UTILIZATION_RISK, flags)

    def test_wide_spread_opportunity(self):
        flags = _compute_flags(7.0, 10.0, 70.0, 1.0, 5.0)
        self.assertIn(FLAG_WIDE_SPREAD_OPPORTUNITY, flags)

    def test_low_reserve_factor(self):
        flags = _compute_flags(3.0, 3.0, 70.0, 1.0, 5.0)
        self.assertIn(FLAG_LOW_RESERVE_FACTOR, flags)

    def test_premium_yield_flag(self):
        flags = _compute_flags(3.0, 10.0, 70.0, 4.0, 5.0)
        self.assertIn(FLAG_PREMIUM_YIELD, flags)

    def test_liquidation_proximity_flag(self):
        flags = _compute_flags(3.0, 10.0, 88.0, 1.0, 8.0)
        self.assertIn(FLAG_LIQUIDATION_PROXIMITY, flags)

    def test_tight_efficient_market_flag(self):
        flags = _compute_flags(1.5, 10.0, 75.0, 1.0, 12.0)
        self.assertIn(FLAG_TIGHT_EFFICIENT_MARKET, flags)

    def test_no_flags_normal_market(self):
        flags = _compute_flags(3.0, 10.0, 70.0, 1.0, 12.0)
        self.assertEqual(flags, [])

    def test_multiple_flags(self):
        flags = _compute_flags(7.0, 3.0, 92.0, 4.0, 8.0)
        self.assertIn(FLAG_HIGH_UTILIZATION_RISK, flags)
        self.assertIn(FLAG_WIDE_SPREAD_OPPORTUNITY, flags)
        self.assertIn(FLAG_LOW_RESERVE_FACTOR, flags)
        self.assertIn(FLAG_PREMIUM_YIELD, flags)
        self.assertIn(FLAG_LIQUIDATION_PROXIMITY, flags)

    def test_liquidation_proximity_requires_low_bonus(self):
        # util > 85 but bonus >= 10 → no flag
        flags = _compute_flags(3.0, 10.0, 88.0, 1.0, 10.0)
        self.assertNotIn(FLAG_LIQUIDATION_PROXIMITY, flags)


class TestAnalyzer(unittest.TestCase):
    """Integration tests for DeFiProtocolLendingRateSpreadAnalyzer.analyze()."""

    def setUp(self):
        self.analyzer = DeFiProtocolLendingRateSpreadAnalyzer()
        self.config = {
            "risk_free_rate_pct": 4.5,
            "benchmark_borrow_rate_pct": 6.0,
        }

    def test_returns_dict(self):
        result = self.analyzer.analyze([_make_market()], self.config)
        self.assertIsInstance(result, dict)

    def test_status_ok_with_data(self):
        result = self.analyzer.analyze([_make_market()], self.config)
        self.assertEqual(result["status"], "ok")

    def test_status_no_data_empty_list(self):
        result = self.analyzer.analyze([], {})
        self.assertEqual(result["status"], "no_data")

    def test_status_no_data_non_list(self):
        result = self.analyzer.analyze(None, {})
        self.assertEqual(result["status"], "no_data")

    def test_markets_list_present(self):
        result = self.analyzer.analyze([_make_market()], self.config)
        self.assertIn("markets", result)
        self.assertIsInstance(result["markets"], list)
        self.assertEqual(len(result["markets"]), 1)

    def test_aggregates_present(self):
        result = self.analyzer.analyze([_make_market()], self.config)
        self.assertIn("aggregates", result)

    def test_timestamp_present(self):
        result = self.analyzer.analyze([_make_market()], self.config)
        self.assertIn("timestamp", result)
        self.assertIsInstance(result["timestamp"], float)

    def test_gross_spread_computed(self):
        mkt = _make_market(supply_apy_pct=3.5, borrow_apy_pct=6.5)
        result = self.analyzer.analyze([mkt], self.config)
        market = result["markets"][0]
        self.assertAlmostEqual(market["gross_spread_pct"], 3.0, places=3)

    def test_effective_spread_computed(self):
        # effective = gross - (reserve/100 * borrow)
        # gross = 6.5 - 3.5 = 3.0
        # effective = 3.0 - (10/100 * 6.5) = 3.0 - 0.65 = 2.35
        mkt = _make_market(
            supply_apy_pct=3.5,
            borrow_apy_pct=6.5,
            reserve_factor_pct=10.0,
        )
        result = self.analyzer.analyze([mkt], self.config)
        market = result["markets"][0]
        self.assertAlmostEqual(market["effective_spread_pct"], 2.35, places=3)

    def test_implied_protocol_revenue(self):
        # implied = (10/100) * (72/100) * 3.5 = 0.1 * 0.72 * 3.5 = 0.252
        mkt = _make_market(
            supply_apy_pct=3.5,
            reserve_factor_pct=10.0,
            utilization_rate_pct=72.0,
        )
        result = self.analyzer.analyze([mkt], self.config)
        market = result["markets"][0]
        self.assertAlmostEqual(market["implied_protocol_revenue_pct"], 0.252, places=3)

    def test_lender_yield_premium(self):
        # supply_apy - risk_free = 3.5 - 4.5 = -1.0
        mkt = _make_market(supply_apy_pct=3.5)
        result = self.analyzer.analyze([mkt], self.config)
        market = result["markets"][0]
        self.assertAlmostEqual(market["lender_yield_premium_pct"], -1.0, places=3)

    def test_lender_premium_positive_when_supply_above_risk_free(self):
        mkt = _make_market(supply_apy_pct=7.0)
        result = self.analyzer.analyze([mkt], self.config)
        market = result["markets"][0]
        self.assertGreater(market["lender_yield_premium_pct"], 0.0)

    def test_borrower_cost_premium(self):
        # borrow_apy - benchmark = 5.8 - 6.0 = -0.2
        mkt = _make_market(borrow_apy_pct=5.8)
        result = self.analyzer.analyze([mkt], self.config)
        market = result["markets"][0]
        self.assertAlmostEqual(market["borrower_cost_premium_pct"], -0.2, places=3)

    def test_spread_vs_benchmark(self):
        # gross = 6.5 - 3.5 = 3.0; benchmark = 2.0; vs_benchmark = 1.0
        mkt = _make_market(
            supply_apy_pct=3.5,
            borrow_apy_pct=6.5,
            spread_benchmark_pct=2.0,
        )
        result = self.analyzer.analyze([mkt], self.config)
        market = result["markets"][0]
        self.assertAlmostEqual(market["spread_vs_benchmark_pct"], 1.0, places=3)

    def test_label_field_present(self):
        result = self.analyzer.analyze([_make_market()], self.config)
        market = result["markets"][0]
        self.assertIn("label", market)

    def test_flags_field_is_list(self):
        result = self.analyzer.analyze([_make_market()], self.config)
        market = result["markets"][0]
        self.assertIsInstance(market["flags"], list)

    def test_efficiency_score_in_range(self):
        result = self.analyzer.analyze([_make_market()], self.config)
        market = result["markets"][0]
        self.assertGreaterEqual(market["spread_efficiency_score"], 0.0)
        self.assertLessEqual(market["spread_efficiency_score"], 100.0)

    def test_tight_spread_label_assigned(self):
        mkt = _make_market(
            supply_apy_pct=4.0,
            borrow_apy_pct=5.2,  # gross = 1.2 < 1.5
            utilization_rate_pct=70.0,
        )
        result = self.analyzer.analyze([mkt], self.config)
        market = result["markets"][0]
        self.assertEqual(market["label"], LABEL_TIGHT_SPREAD)

    def test_inefficient_label_high_spread(self):
        mkt = _make_market(
            supply_apy_pct=2.0,
            borrow_apy_pct=12.0,  # gross = 10.0 > 8
            utilization_rate_pct=60.0,
        )
        result = self.analyzer.analyze([mkt], self.config)
        market = result["markets"][0]
        self.assertEqual(market["label"], LABEL_INEFFICIENT)

    def test_inefficient_label_high_util(self):
        mkt = _make_market(
            supply_apy_pct=3.0,
            borrow_apy_pct=5.0,  # gross = 2.0
            utilization_rate_pct=97.0,
        )
        result = self.analyzer.analyze([mkt], self.config)
        market = result["markets"][0]
        self.assertEqual(market["label"], LABEL_INEFFICIENT)

    def test_wide_spread_label(self):
        mkt = _make_market(
            supply_apy_pct=2.0,
            borrow_apy_pct=8.0,  # gross = 6.0 > 5
            utilization_rate_pct=60.0,
        )
        result = self.analyzer.analyze([mkt], self.config)
        market = result["markets"][0]
        self.assertEqual(market["label"], LABEL_WIDE_SPREAD)

    def test_efficient_label(self):
        mkt = _make_market(
            supply_apy_pct=4.0,
            borrow_apy_pct=6.5,  # gross = 2.5 < 3
            utilization_rate_pct=55.0,
        )
        result = self.analyzer.analyze([mkt], self.config)
        market = result["markets"][0]
        self.assertEqual(market["label"], LABEL_EFFICIENT)

    def test_normal_label(self):
        mkt = _make_market(
            supply_apy_pct=3.0,
            borrow_apy_pct=7.0,  # gross = 4.0
            utilization_rate_pct=65.0,
        )
        result = self.analyzer.analyze([mkt], self.config)
        market = result["markets"][0]
        self.assertEqual(market["label"], LABEL_NORMAL)

    def test_high_utilization_flag(self):
        mkt = _make_market(utilization_rate_pct=93.0)
        result = self.analyzer.analyze([mkt], self.config)
        market = result["markets"][0]
        self.assertIn(FLAG_HIGH_UTILIZATION_RISK, market["flags"])

    def test_wide_spread_flag(self):
        mkt = _make_market(
            supply_apy_pct=1.0,
            borrow_apy_pct=8.0,  # spread = 7.0 > 6
        )
        result = self.analyzer.analyze([mkt], self.config)
        market = result["markets"][0]
        self.assertIn(FLAG_WIDE_SPREAD_OPPORTUNITY, market["flags"])

    def test_low_reserve_factor_flag(self):
        mkt = _make_market(reserve_factor_pct=3.0)
        result = self.analyzer.analyze([mkt], self.config)
        market = result["markets"][0]
        self.assertIn(FLAG_LOW_RESERVE_FACTOR, market["flags"])

    def test_premium_yield_flag(self):
        mkt = _make_market(supply_apy_pct=8.5)  # premium = 8.5 - 4.5 = 4.0 > 3
        result = self.analyzer.analyze([mkt], self.config)
        market = result["markets"][0]
        self.assertIn(FLAG_PREMIUM_YIELD, market["flags"])

    def test_liquidation_proximity_flag(self):
        mkt = _make_market(
            utilization_rate_pct=88.0,
            liquidation_bonus_pct=7.0,
        )
        result = self.analyzer.analyze([mkt], self.config)
        market = result["markets"][0]
        self.assertIn(FLAG_LIQUIDATION_PROXIMITY, market["flags"])

    def test_tight_efficient_market_flag(self):
        mkt = _make_market(
            supply_apy_pct=4.0,
            borrow_apy_pct=5.5,  # gross = 1.5 < 2
            utilization_rate_pct=75.0,
        )
        result = self.analyzer.analyze([mkt], self.config)
        market = result["markets"][0]
        self.assertIn(FLAG_TIGHT_EFFICIENT_MARKET, market["flags"])

    def test_multiple_markets_analyzed(self):
        markets = [_make_market(name=f"M{i}") for i in range(5)]
        result = self.analyzer.analyze(markets, self.config)
        self.assertEqual(len(result["markets"]), 5)

    def test_implied_borrowed_usd_computed(self):
        mkt = _make_market(
            total_supplied_usd=1_000_000.0,
            utilization_rate_pct=75.0,
        )
        result = self.analyzer.analyze([mkt], self.config)
        market = result["markets"][0]
        self.assertAlmostEqual(market["implied_borrowed_usd"], 750_000.0, places=0)

    def test_name_protocol_asset_preserved(self):
        mkt = _make_market(name="Aave-USDC", protocol="Aave", asset="USDC")
        result = self.analyzer.analyze([mkt], self.config)
        market = result["markets"][0]
        self.assertEqual(market["name"], "Aave-USDC")
        self.assertEqual(market["protocol"], "Aave")
        self.assertEqual(market["asset"], "USDC")

    def test_default_config_values_work(self):
        result = self.analyzer.analyze([_make_market()], {})
        self.assertEqual(result["status"], "ok")

    def test_zero_utilization_market(self):
        mkt = _make_market(utilization_rate_pct=0.0, total_borrowed_usd=0.0)
        result = self.analyzer.analyze([mkt], self.config)
        self.assertEqual(result["status"], "ok")

    def test_full_utilization_market(self):
        mkt = _make_market(
            utilization_rate_pct=99.9,
            supply_apy_pct=2.0,
            borrow_apy_pct=30.0,
        )
        result = self.analyzer.analyze([mkt], self.config)
        self.assertEqual(result["status"], "ok")
        market = result["markets"][0]
        self.assertEqual(market["label"], LABEL_INEFFICIENT)

    def test_zero_reserve_factor(self):
        mkt = _make_market(reserve_factor_pct=0.0)
        result = self.analyzer.analyze([mkt], self.config)
        market = result["markets"][0]
        self.assertAlmostEqual(market["effective_spread_pct"], market["gross_spread_pct"], places=4)
        self.assertIn(FLAG_LOW_RESERVE_FACTOR, market["flags"])

    def test_high_reserve_factor_reduces_effective_spread(self):
        mkt_low_res = _make_market(
            supply_apy_pct=3.0,
            borrow_apy_pct=6.0,
            reserve_factor_pct=5.0,
        )
        mkt_high_res = _make_market(
            supply_apy_pct=3.0,
            borrow_apy_pct=6.0,
            reserve_factor_pct=30.0,
        )
        r1 = self.analyzer.analyze([mkt_low_res], self.config)["markets"][0]
        r2 = self.analyzer.analyze([mkt_high_res], self.config)["markets"][0]
        self.assertGreater(r1["effective_spread_pct"], r2["effective_spread_pct"])


class TestAggregates(unittest.TestCase):
    """Tests for aggregate computation."""

    def setUp(self):
        self.analyzer = DeFiProtocolLendingRateSpreadAnalyzer()
        self.config = {}

    def test_aggregates_market_count(self):
        markets = [_make_market(name=f"M{i}") for i in range(4)]
        result = self.analyzer.analyze(markets, self.config)
        self.assertEqual(result["aggregates"]["market_count"], 4)

    def test_tightest_spread_aggregate(self):
        markets = [
            _make_market(name="Tight", supply_apy_pct=4.0, borrow_apy_pct=5.0),
            _make_market(name="Wide", supply_apy_pct=1.0, borrow_apy_pct=10.0),
        ]
        result = self.analyzer.analyze(markets, self.config)
        agg = result["aggregates"]
        self.assertEqual(agg["tightest_spread"]["name"], "Tight")

    def test_widest_spread_aggregate(self):
        markets = [
            _make_market(name="Tight", supply_apy_pct=4.0, borrow_apy_pct=5.0),
            _make_market(name="Wide", supply_apy_pct=1.0, borrow_apy_pct=10.0),
        ]
        result = self.analyzer.analyze(markets, self.config)
        agg = result["aggregates"]
        self.assertEqual(agg["widest_spread"]["name"], "Wide")

    def test_avg_spread_computed(self):
        markets = [
            _make_market(name="M1", supply_apy_pct=3.0, borrow_apy_pct=5.0),   # spread=2
            _make_market(name="M2", supply_apy_pct=2.0, borrow_apy_pct=6.0),   # spread=4
        ]
        result = self.analyzer.analyze(markets, self.config)
        agg = result["aggregates"]
        self.assertAlmostEqual(agg["avg_spread_pct"], 3.0, places=3)

    def test_inefficient_count(self):
        markets = [
            _make_market(name="Good", supply_apy_pct=3.0, borrow_apy_pct=5.5, utilization_rate_pct=70.0),
            _make_market(name="Bad1", supply_apy_pct=2.0, borrow_apy_pct=12.0, utilization_rate_pct=60.0),
            _make_market(name="Bad2", supply_apy_pct=3.0, borrow_apy_pct=5.0, utilization_rate_pct=97.0),
        ]
        result = self.analyzer.analyze(markets, self.config)
        agg = result["aggregates"]
        self.assertEqual(agg["inefficient_count"], 2)

    def test_tight_count(self):
        markets = [
            _make_market(name="T1", supply_apy_pct=4.0, borrow_apy_pct=5.2, utilization_rate_pct=70.0),  # TIGHT
            _make_market(name="T2", supply_apy_pct=4.0, borrow_apy_pct=6.0, utilization_rate_pct=55.0),  # EFFICIENT
            _make_market(name="N1", supply_apy_pct=3.0, borrow_apy_pct=7.0, utilization_rate_pct=65.0),  # NORMAL
        ]
        result = self.analyzer.analyze(markets, self.config)
        agg = result["aggregates"]
        self.assertEqual(agg["tight_count"], 2)

    def test_high_util_risk_count(self):
        markets = [
            _make_market(name="H1", utilization_rate_pct=92.0),
            _make_market(name="H2", utilization_rate_pct=95.0),
            _make_market(name="OK", utilization_rate_pct=70.0),
        ]
        result = self.analyzer.analyze(markets, self.config)
        agg = result["aggregates"]
        self.assertEqual(agg["high_utilization_risk_count"], 2)

    def test_single_market_aggregates(self):
        result = self.analyzer.analyze([_make_market()], self.config)
        agg = result["aggregates"]
        self.assertEqual(agg["tightest_spread"]["name"], agg["widest_spread"]["name"])

    def test_most_efficient_market_in_aggregates(self):
        markets = [
            _make_market(name="Eff", supply_apy_pct=4.0, borrow_apy_pct=5.2, utilization_rate_pct=75.0),
            _make_market(name="Ineff", supply_apy_pct=2.0, borrow_apy_pct=12.0, utilization_rate_pct=50.0),
        ]
        result = self.analyzer.analyze(markets, self.config)
        agg = result["aggregates"]
        self.assertEqual(agg["most_efficient_market"]["name"], "Eff")


class TestRingBufferLog(unittest.TestCase):
    """Tests for the ring-buffer log write."""

    def setUp(self):
        self.analyzer = DeFiProtocolLendingRateSpreadAnalyzer()
        self.tmpdir = tempfile.mkdtemp()
        self.orig_log = __import__(
            "spa_core.analytics.defi_protocol_lending_rate_spread_analyzer",
            fromlist=["defi_protocol_lending_rate_spread_analyzer"]
        )

    def _patch_log_path(self, path):
        import spa_core.analytics.defi_protocol_lending_rate_spread_analyzer as mod
        mod._LOG_PATH = path

    def _restore_log_path(self):
        import spa_core.analytics.defi_protocol_lending_rate_spread_analyzer as mod
        mod._LOG_PATH = os.path.join(
            os.path.dirname(mod.__file__), "..", "..", "data", "lending_rate_spread_log.json"
        )

    def test_log_file_created(self):
        log_path = os.path.join(self.tmpdir, "test_spread_log.json")
        self._patch_log_path(log_path)
        try:
            self.analyzer.analyze([_make_market()], {})
            self.assertTrue(os.path.exists(log_path))
        finally:
            self._restore_log_path()

    def test_log_is_list(self):
        log_path = os.path.join(self.tmpdir, "test_spread_log2.json")
        self._patch_log_path(log_path)
        try:
            self.analyzer.analyze([_make_market()], {})
            with open(log_path) as f:
                data = json.load(f)
            self.assertIsInstance(data, list)
        finally:
            self._restore_log_path()

    def test_log_grows_on_multiple_calls(self):
        log_path = os.path.join(self.tmpdir, "test_spread_log3.json")
        self._patch_log_path(log_path)
        try:
            for _ in range(3):
                self.analyzer.analyze([_make_market()], {})
            with open(log_path) as f:
                data = json.load(f)
            self.assertEqual(len(data), 3)
        finally:
            self._restore_log_path()

    def test_ring_buffer_cap(self):
        import spa_core.analytics.defi_protocol_lending_rate_spread_analyzer as mod
        orig_cap = mod._LOG_CAP
        mod._LOG_CAP = 3
        log_path = os.path.join(self.tmpdir, "test_spread_cap.json")
        self._patch_log_path(log_path)
        try:
            for _ in range(6):
                self.analyzer.analyze([_make_market()], {})
            with open(log_path) as f:
                data = json.load(f)
            self.assertLessEqual(len(data), 3)
        finally:
            mod._LOG_CAP = orig_cap
            self._restore_log_path()

    def test_log_record_has_ts(self):
        log_path = os.path.join(self.tmpdir, "test_spread_ts.json")
        self._patch_log_path(log_path)
        try:
            self.analyzer.analyze([_make_market()], {})
            with open(log_path) as f:
                data = json.load(f)
            self.assertIn("ts", data[0])
        finally:
            self._restore_log_path()

    def test_log_record_has_market_count(self):
        log_path = os.path.join(self.tmpdir, "test_spread_mc.json")
        self._patch_log_path(log_path)
        try:
            self.analyzer.analyze([_make_market(), _make_market(name="M2")], {})
            with open(log_path) as f:
                data = json.load(f)
            self.assertEqual(data[0]["market_count"], 2)
        finally:
            self._restore_log_path()

    def test_log_record_has_aggregates(self):
        log_path = os.path.join(self.tmpdir, "test_spread_agg.json")
        self._patch_log_path(log_path)
        try:
            self.analyzer.analyze([_make_market()], {})
            with open(log_path) as f:
                data = json.load(f)
            self.assertIn("aggregates", data[0])
        finally:
            self._restore_log_path()

    def test_atomic_write_no_tmp_file_left(self):
        log_path = os.path.join(self.tmpdir, "test_spread_atom.json")
        self._patch_log_path(log_path)
        try:
            self.analyzer.analyze([_make_market()], {})
            self.assertFalse(os.path.exists(log_path + ".tmp"))
        finally:
            self._restore_log_path()

    def test_corrupt_log_recovery(self):
        log_path = os.path.join(self.tmpdir, "test_spread_corrupt.json")
        with open(log_path, "w") as f:
            f.write("NOT JSON{{{{")
        self._patch_log_path(log_path)
        try:
            self.analyzer.analyze([_make_market()], {})
            with open(log_path) as f:
                data = json.load(f)
            self.assertEqual(len(data), 1)
        finally:
            self._restore_log_path()


class TestEdgeCases(unittest.TestCase):
    """Edge case and boundary tests."""

    def setUp(self):
        self.analyzer = DeFiProtocolLendingRateSpreadAnalyzer()
        self.config = {}

    def test_borrow_below_supply_negative_spread(self):
        # Edge case: borrow < supply → negative gross spread
        mkt = _make_market(supply_apy_pct=5.0, borrow_apy_pct=3.0)
        result = self.analyzer.analyze([mkt], self.config)
        self.assertEqual(result["status"], "ok")
        market = result["markets"][0]
        self.assertLess(market["gross_spread_pct"], 0.0)

    def test_zero_supply_apy(self):
        mkt = _make_market(supply_apy_pct=0.0, borrow_apy_pct=5.0)
        result = self.analyzer.analyze([mkt], self.config)
        self.assertEqual(result["status"], "ok")

    def test_very_large_values(self):
        mkt = _make_market(
            total_supplied_usd=10_000_000_000.0,
            total_borrowed_usd=7_000_000_000.0,
            supply_apy_pct=3.5,
            borrow_apy_pct=5.8,
        )
        result = self.analyzer.analyze([mkt], self.config)
        self.assertEqual(result["status"], "ok")

    def test_missing_optional_fields_use_defaults(self):
        minimal = {
            "name": "Minimal",
            "supply_apy_pct": 3.0,
            "borrow_apy_pct": 5.0,
            "utilization_rate_pct": 70.0,
        }
        result = self.analyzer.analyze([minimal], self.config)
        self.assertEqual(result["status"], "ok")

    def test_many_markets(self):
        markets = [_make_market(name=f"M{i}", borrow_apy_pct=5.0 + i * 0.5) for i in range(20)]
        result = self.analyzer.analyze(markets, self.config)
        self.assertEqual(len(result["markets"]), 20)

    def test_custom_config_risk_free_rate(self):
        config = {"risk_free_rate_pct": 2.0, "benchmark_borrow_rate_pct": 4.0}
        mkt = _make_market(supply_apy_pct=3.0, borrow_apy_pct=5.0)
        result = self.analyzer.analyze([mkt], config)
        market = result["markets"][0]
        # lender_premium = supply - risk_free = 3.0 - 2.0 = 1.0
        self.assertAlmostEqual(market["lender_yield_premium_pct"], 1.0, places=3)

    def test_custom_config_benchmark_borrow(self):
        config = {"risk_free_rate_pct": 4.5, "benchmark_borrow_rate_pct": 3.0}
        mkt = _make_market(borrow_apy_pct=5.0)
        result = self.analyzer.analyze([mkt], config)
        market = result["markets"][0]
        # borrower_premium = borrow - benchmark = 5.0 - 3.0 = 2.0
        self.assertAlmostEqual(market["borrower_cost_premium_pct"], 2.0, places=3)

    def test_liquidation_threshold_preserved(self):
        mkt = _make_market(liquidation_threshold_pct=75.0)
        result = self.analyzer.analyze([mkt], self.config)
        market = result["markets"][0]
        self.assertAlmostEqual(market["liquidation_threshold_pct"], 75.0, places=2)

    def test_protocol_fee_preserved(self):
        mkt = _make_market(protocol_fee_pct=0.5)
        result = self.analyzer.analyze([mkt], self.config)
        market = result["markets"][0]
        self.assertAlmostEqual(market["protocol_fee_pct"], 0.5, places=2)

    def test_spread_benchmark_preserved(self):
        mkt = _make_market(spread_benchmark_pct=3.0)
        result = self.analyzer.analyze([mkt], self.config)
        market = result["markets"][0]
        self.assertAlmostEqual(market["spread_benchmark_pct"], 3.0, places=2)


if __name__ == "__main__":
    unittest.main()
