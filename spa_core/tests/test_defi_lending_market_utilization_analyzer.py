"""
MP-964 Tests: DeFiLendingMarketUtilizationAnalyzer
Run: python3 -m unittest spa_core.tests.test_defi_lending_market_utilization_analyzer -v
"""

import json
import os
import tempfile
import unittest

from spa_core.analytics.defi_lending_market_utilization_analyzer import (
    DeFiLendingMarketUtilizationAnalyzer,
)


def make_market(**kwargs):
    """Return a market dict with sensible defaults."""
    defaults = {
        "protocol": "AaveV3",
        "asset": "USDC",
        "total_supply_usd": 100_000_000,
        "total_borrow_usd": 80_000_000,
        "base_rate_pct": 0.0,
        "slope1_pct": 4.0,
        "slope2_pct": 60.0,
        "kink_utilization_pct": 80.0,
        "reserve_factor_pct": 10.0,
        "current_supply_apy_pct": 3.5,
        "current_borrow_apy_pct": 4.8,
        "liquidation_threshold_pct": 85.0,
        "close_factor_pct": 50.0,
    }
    defaults.update(kwargs)
    return defaults


class TestUtilizationRateCalc(unittest.TestCase):
    """Tests for utilization_rate_pct computation."""

    def setUp(self):
        self.az = DeFiLendingMarketUtilizationAnalyzer()

    def test_util_80_percent(self):
        m = make_market(total_supply_usd=100e6, total_borrow_usd=80e6)
        r = self.az.analyze([m])
        self.assertAlmostEqual(r["markets"][0]["utilization_rate_pct"], 80.0, places=3)

    def test_util_zero_borrow(self):
        m = make_market(total_supply_usd=100e6, total_borrow_usd=0)
        r = self.az.analyze([m])
        self.assertAlmostEqual(r["markets"][0]["utilization_rate_pct"], 0.0, places=3)

    def test_util_100_percent(self):
        m = make_market(total_supply_usd=100e6, total_borrow_usd=100e6)
        r = self.az.analyze([m])
        self.assertAlmostEqual(r["markets"][0]["utilization_rate_pct"], 100.0, places=3)

    def test_util_over_100(self):
        # Technically impossible but guard for bad data
        m = make_market(total_supply_usd=100e6, total_borrow_usd=110e6)
        r = self.az.analyze([m])
        self.assertGreater(r["markets"][0]["utilization_rate_pct"], 100.0)

    def test_util_zero_supply_returns_zero(self):
        m = make_market(total_supply_usd=0, total_borrow_usd=50e6)
        r = self.az.analyze([m])
        self.assertEqual(r["markets"][0]["utilization_rate_pct"], 0.0)

    def test_util_50_percent(self):
        m = make_market(total_supply_usd=200e6, total_borrow_usd=100e6)
        r = self.az.analyze([m])
        self.assertAlmostEqual(r["markets"][0]["utilization_rate_pct"], 50.0, places=3)

    def test_util_5_percent(self):
        m = make_market(total_supply_usd=100e6, total_borrow_usd=5e6)
        r = self.az.analyze([m])
        self.assertAlmostEqual(r["markets"][0]["utilization_rate_pct"], 5.0, places=3)

    def test_util_90_percent(self):
        m = make_market(total_supply_usd=100e6, total_borrow_usd=90e6)
        r = self.az.analyze([m])
        self.assertAlmostEqual(r["markets"][0]["utilization_rate_pct"], 90.0, places=3)


class TestBorrowAPYModel(unittest.TestCase):
    """Tests for borrow APY kink model."""

    def setUp(self):
        self.az = DeFiLendingMarketUtilizationAnalyzer()

    def test_borrow_apy_zero_util(self):
        # util=0 → base_rate only
        m = make_market(
            total_borrow_usd=0, base_rate_pct=1.0, slope1_pct=4.0, kink_utilization_pct=80.0
        )
        r = self.az.analyze([m])
        self.assertAlmostEqual(r["markets"][0]["borrow_apy_from_model_pct"], 1.0, places=3)

    def test_borrow_apy_at_kink(self):
        # util=80, kink=80 → base + slope1
        m = make_market(
            total_supply_usd=100e6,
            total_borrow_usd=80e6,
            base_rate_pct=0.0,
            slope1_pct=4.0,
            slope2_pct=60.0,
            kink_utilization_pct=80.0,
        )
        r = self.az.analyze([m])
        # u==kink branch: base + (80/80)*4 = 4.0
        self.assertAlmostEqual(r["markets"][0]["borrow_apy_from_model_pct"], 4.0, places=3)

    def test_borrow_apy_below_kink_half(self):
        # util=40, kink=80 → base + (40/80)*4 = 2.0
        m = make_market(
            total_supply_usd=100e6,
            total_borrow_usd=40e6,
            base_rate_pct=0.0,
            slope1_pct=4.0,
            slope2_pct=60.0,
            kink_utilization_pct=80.0,
        )
        r = self.az.analyze([m])
        self.assertAlmostEqual(r["markets"][0]["borrow_apy_from_model_pct"], 2.0, places=3)

    def test_borrow_apy_above_kink(self):
        # util=90, kink=80 → base + slope1 + (10/20)*slope2 = 0+4+(0.5*60)=34
        m = make_market(
            total_supply_usd=100e6,
            total_borrow_usd=90e6,
            base_rate_pct=0.0,
            slope1_pct=4.0,
            slope2_pct=60.0,
            kink_utilization_pct=80.0,
        )
        r = self.az.analyze([m])
        self.assertAlmostEqual(r["markets"][0]["borrow_apy_from_model_pct"], 34.0, places=3)

    def test_borrow_apy_saturated(self):
        # util=100, kink=80 → base + slope1 + (20/20)*slope2 = 0+4+60=64
        m = make_market(
            total_supply_usd=100e6,
            total_borrow_usd=100e6,
            base_rate_pct=0.0,
            slope1_pct=4.0,
            slope2_pct=60.0,
            kink_utilization_pct=80.0,
        )
        r = self.az.analyze([m])
        self.assertAlmostEqual(r["markets"][0]["borrow_apy_from_model_pct"], 64.0, places=3)

    def test_borrow_apy_with_base_rate(self):
        # base=1, util=kink=80 → 1 + (80/80)*4 = 5
        m = make_market(
            total_supply_usd=100e6,
            total_borrow_usd=80e6,
            base_rate_pct=1.0,
            slope1_pct=4.0,
            kink_utilization_pct=80.0,
        )
        r = self.az.analyze([m])
        self.assertAlmostEqual(r["markets"][0]["borrow_apy_from_model_pct"], 5.0, places=3)

    def test_borrow_apy_kink_60_above(self):
        # kink=60, util=80 → base + slope1 + (20/40)*slope2 = 0+4+0.5*60=34
        m = make_market(
            total_supply_usd=100e6,
            total_borrow_usd=80e6,
            base_rate_pct=0.0,
            slope1_pct=4.0,
            slope2_pct=60.0,
            kink_utilization_pct=60.0,
        )
        r = self.az.analyze([m])
        self.assertAlmostEqual(r["markets"][0]["borrow_apy_from_model_pct"], 34.0, places=3)


class TestSupplyAPYModel(unittest.TestCase):
    """Tests for supply APY model."""

    def setUp(self):
        self.az = DeFiLendingMarketUtilizationAnalyzer()

    def test_supply_apy_at_kink(self):
        # util=80, kink=80, borrow=4%, reserve=10%
        # supply = 4 * 0.8 * 0.9 = 2.88
        m = make_market(
            total_supply_usd=100e6,
            total_borrow_usd=80e6,
            base_rate_pct=0.0,
            slope1_pct=4.0,
            reserve_factor_pct=10.0,
            kink_utilization_pct=80.0,
        )
        r = self.az.analyze([m])
        self.assertAlmostEqual(r["markets"][0]["supply_apy_from_model_pct"], 2.88, places=3)

    def test_supply_apy_zero_util(self):
        m = make_market(total_borrow_usd=0)
        r = self.az.analyze([m])
        self.assertAlmostEqual(r["markets"][0]["supply_apy_from_model_pct"], 0.0, places=3)

    def test_supply_apy_zero_reserve(self):
        # reserve=0 → supply = borrow * util
        m = make_market(
            total_supply_usd=100e6,
            total_borrow_usd=80e6,
            base_rate_pct=0.0,
            slope1_pct=4.0,
            reserve_factor_pct=0.0,
            kink_utilization_pct=80.0,
        )
        r = self.az.analyze([m])
        # borrow=4, util=0.8, reserve=0 → supply=4*0.8*1=3.2
        self.assertAlmostEqual(r["markets"][0]["supply_apy_from_model_pct"], 3.2, places=3)

    def test_supply_apy_high_reserve(self):
        # reserve=50%
        m = make_market(
            total_supply_usd=100e6,
            total_borrow_usd=80e6,
            base_rate_pct=0.0,
            slope1_pct=4.0,
            reserve_factor_pct=50.0,
            kink_utilization_pct=80.0,
        )
        r = self.az.analyze([m])
        # borrow=4, util=0.8, reserve=0.5 → 4*0.8*0.5=1.6
        self.assertAlmostEqual(r["markets"][0]["supply_apy_from_model_pct"], 1.6, places=3)


class TestSpreadAndDistances(unittest.TestCase):
    """Tests for spread_pct, distance_to_kink, distance_to_full."""

    def setUp(self):
        self.az = DeFiLendingMarketUtilizationAnalyzer()

    def test_spread_positive(self):
        m = make_market(
            total_supply_usd=100e6,
            total_borrow_usd=80e6,
            base_rate_pct=0.0,
            slope1_pct=4.0,
            reserve_factor_pct=10.0,
            kink_utilization_pct=80.0,
        )
        r = self.az.analyze([m])
        # borrow=4, supply=2.88, spread=1.12
        self.assertAlmostEqual(r["markets"][0]["spread_pct"], 1.12, places=3)

    def test_spread_zero_util_is_zero(self):
        m = make_market(total_borrow_usd=0)
        r = self.az.analyze([m])
        self.assertAlmostEqual(r["markets"][0]["spread_pct"], 0.0, places=3)

    def test_distance_to_kink_below(self):
        # util=60, kink=80 → distance=20
        m = make_market(total_supply_usd=100e6, total_borrow_usd=60e6, kink_utilization_pct=80.0)
        r = self.az.analyze([m])
        self.assertAlmostEqual(r["markets"][0]["distance_to_kink_pct"], 20.0, places=3)

    def test_distance_to_kink_above(self):
        # util=90, kink=80 → distance=-10
        m = make_market(total_supply_usd=100e6, total_borrow_usd=90e6, kink_utilization_pct=80.0)
        r = self.az.analyze([m])
        self.assertAlmostEqual(r["markets"][0]["distance_to_kink_pct"], -10.0, places=3)

    def test_distance_to_full_80(self):
        m = make_market(total_supply_usd=100e6, total_borrow_usd=80e6)
        r = self.az.analyze([m])
        self.assertAlmostEqual(r["markets"][0]["distance_to_full_pct"], 20.0, places=3)

    def test_distance_to_full_zero_borrow(self):
        m = make_market(total_borrow_usd=0)
        r = self.az.analyze([m])
        self.assertAlmostEqual(r["markets"][0]["distance_to_full_pct"], 100.0, places=3)

    def test_distance_to_full_100_util(self):
        m = make_market(total_supply_usd=100e6, total_borrow_usd=100e6)
        r = self.az.analyze([m])
        self.assertAlmostEqual(r["markets"][0]["distance_to_full_pct"], 0.0, places=3)


class TestUtilizationLabels(unittest.TestCase):
    """Tests for all utilization labels."""

    def setUp(self):
        self.az = DeFiLendingMarketUtilizationAnalyzer()

    def _label(self, borrow_pct, supply=100e6, kink=80.0):
        m = make_market(
            total_supply_usd=supply,
            total_borrow_usd=supply * borrow_pct / 100,
            kink_utilization_pct=kink,
        )
        return self.az.analyze([m])["markets"][0]["utilization_label"]

    def test_label_empty_5pct(self):
        self.assertEqual(self._label(5.0), "EMPTY")

    def test_label_empty_0pct(self):
        self.assertEqual(self._label(0.0), "EMPTY")

    def test_label_empty_9pct(self):
        self.assertEqual(self._label(9.0), "EMPTY")

    def test_label_low_20pct(self):
        self.assertEqual(self._label(20.0), "LOW")

    def test_label_low_30pct(self):
        self.assertEqual(self._label(30.0), "LOW")

    def test_label_low_50pct(self):
        # kink=80, 50 < 80-10=70 → LOW
        self.assertEqual(self._label(50.0, kink=80.0), "LOW")

    def test_label_optimal_at_kink(self):
        self.assertEqual(self._label(80.0, kink=80.0), "OPTIMAL")

    def test_label_optimal_below_kink_5(self):
        # 75 and kink=80: |75-80|=5 ≤ 10 → OPTIMAL
        self.assertEqual(self._label(75.0, kink=80.0), "OPTIMAL")

    def test_label_optimal_above_kink_5(self):
        # 85 and kink=80: |85-80|=5 ≤ 10 → OPTIMAL
        self.assertEqual(self._label(85.0, kink=80.0), "OPTIMAL")

    def test_label_optimal_kink_60(self):
        # util=60, kink=60 → OPTIMAL
        self.assertEqual(self._label(60.0, kink=60.0), "OPTIMAL")

    def test_label_high_above_kink_plus_10(self):
        # kink=60, util=75: 75 > 60+10=70, util<=90 → HIGH
        self.assertEqual(self._label(75.0, kink=60.0), "HIGH")

    def test_label_high_88pct_kink_60(self):
        self.assertEqual(self._label(88.0, kink=60.0), "HIGH")

    def test_label_saturated_92pct(self):
        self.assertEqual(self._label(92.0), "SATURATED")

    def test_label_saturated_99pct(self):
        self.assertEqual(self._label(99.0), "SATURATED")

    def test_label_overutilized(self):
        # Need util > 100
        m = make_market(
            total_supply_usd=100e6,
            total_borrow_usd=110e6,
            kink_utilization_pct=80.0,
        )
        label = self.az.analyze([m])["markets"][0]["utilization_label"]
        self.assertEqual(label, "OVERUTILIZED")

    def test_label_high_takes_priority_over_empty_edge(self):
        # util=91, kink=80 → SATURATED (not HIGH)
        self.assertEqual(self._label(91.0, kink=80.0), "SATURATED")


class TestFlags(unittest.TestCase):
    """Tests for all utilization flags."""

    def setUp(self):
        self.az = DeFiLendingMarketUtilizationAnalyzer()

    def _flags(self, borrow_pct, supply=100e6, kink=80.0, spread_override=None, **kwargs):
        m = make_market(
            total_supply_usd=supply,
            total_borrow_usd=supply * borrow_pct / 100,
            kink_utilization_pct=kink,
            **kwargs,
        )
        return self.az.analyze([m])["markets"][0]["flags"]

    # AT_KINK tests
    def test_at_kink_exact(self):
        self.assertIn("AT_KINK", self._flags(80.0, kink=80.0))

    def test_at_kink_within_5_below(self):
        self.assertIn("AT_KINK", self._flags(76.0, kink=80.0))

    def test_at_kink_within_5_above(self):
        self.assertIn("AT_KINK", self._flags(84.0, kink=80.0))

    def test_no_at_kink_far_from_kink(self):
        self.assertNotIn("AT_KINK", self._flags(50.0, kink=80.0))

    def test_no_at_kink_just_outside(self):
        # |74-80|=6 > 5 → not AT_KINK
        self.assertNotIn("AT_KINK", self._flags(74.0, kink=80.0))

    # RATE_SPIKE_IMMINENT tests
    def test_rate_spike_imminent_above_95pct_kink(self):
        # kink=80, 95%*80=76 → util>76 triggers
        self.assertIn("RATE_SPIKE_IMMINENT", self._flags(77.0, kink=80.0))

    def test_rate_spike_imminent_at_kink(self):
        self.assertIn("RATE_SPIKE_IMMINENT", self._flags(80.0, kink=80.0))

    def test_no_rate_spike_below_95pct_kink(self):
        # kink=80, 95%*80=76, util=70 → no spike
        self.assertNotIn("RATE_SPIKE_IMMINENT", self._flags(70.0, kink=80.0))

    def test_rate_spike_kink_100(self):
        # kink=100, 95%*100=95, util=96 → spike
        self.assertIn("RATE_SPIKE_IMMINENT", self._flags(96.0, kink=100.0))

    # SUPPLY_INCENTIVE_NEEDED tests
    def test_supply_incentive_81pct(self):
        self.assertIn("SUPPLY_INCENTIVE_NEEDED", self._flags(81.0))

    def test_supply_incentive_90pct(self):
        self.assertIn("SUPPLY_INCENTIVE_NEEDED", self._flags(90.0))

    def test_no_supply_incentive_79pct(self):
        self.assertNotIn("SUPPLY_INCENTIVE_NEEDED", self._flags(79.0))

    def test_no_supply_incentive_50pct(self):
        self.assertNotIn("SUPPLY_INCENTIVE_NEEDED", self._flags(50.0))

    # LIQUIDATION_RISK_HIGH tests
    def test_liquidation_risk_91pct(self):
        self.assertIn("LIQUIDATION_RISK_HIGH", self._flags(91.0))

    def test_no_liquidation_risk_89pct(self):
        self.assertNotIn("LIQUIDATION_RISK_HIGH", self._flags(89.0))

    def test_liquidation_risk_overutilized(self):
        m = make_market(total_supply_usd=100e6, total_borrow_usd=110e6)
        flags = self.az.analyze([m])["markets"][0]["flags"]
        self.assertIn("LIQUIDATION_RISK_HIGH", flags)

    # HEALTHY_SPREAD tests
    def test_healthy_spread_3pct(self):
        # Need spread in [2,8]; tune base+slope/reserve to get ~3% spread
        m = make_market(
            total_supply_usd=100e6,
            total_borrow_usd=80e6,
            base_rate_pct=0.0,
            slope1_pct=5.0,
            reserve_factor_pct=20.0,
            kink_utilization_pct=80.0,
        )
        # borrow=5, supply=5*0.8*0.8=3.2, spread=1.8 → not healthy
        # Try: slope1=5, reserve=0% → borrow=5, supply=5*0.8=4, spread=1 → not healthy
        # Try: slope1=10, reserve=30% → borrow=10, supply=10*0.8*0.7=5.6, spread=4.4 → healthy
        m2 = make_market(
            total_supply_usd=100e6,
            total_borrow_usd=80e6,
            base_rate_pct=0.0,
            slope1_pct=10.0,
            reserve_factor_pct=30.0,
            kink_utilization_pct=80.0,
        )
        flags = self.az.analyze([m2])["markets"][0]["flags"]
        self.assertIn("HEALTHY_SPREAD", flags)

    def test_no_healthy_spread_too_low(self):
        # Very low spread: borrow≈supply
        m = make_market(
            total_supply_usd=100e6,
            total_borrow_usd=80e6,
            base_rate_pct=0.0,
            slope1_pct=4.0,
            reserve_factor_pct=0.0,
            kink_utilization_pct=80.0,
        )
        # borrow=4, supply=4*0.8=3.2, spread=0.8 < 2 → not healthy
        flags = self.az.analyze([m])["markets"][0]["flags"]
        self.assertNotIn("HEALTHY_SPREAD", flags)

    def test_no_healthy_spread_too_high(self):
        # Very high spread: util=100, borrow=64, supply≈17.28, spread=46.72 > 8
        m = make_market(
            total_supply_usd=100e6,
            total_borrow_usd=100e6,
            base_rate_pct=0.0,
            slope1_pct=4.0,
            slope2_pct=60.0,
            reserve_factor_pct=30.0,
            kink_utilization_pct=80.0,
        )
        flags = self.az.analyze([m])["markets"][0]["flags"]
        self.assertNotIn("HEALTHY_SPREAD", flags)


class TestMultipleMarkets(unittest.TestCase):
    """Tests for multiple markets in a single analyze() call."""

    def setUp(self):
        self.az = DeFiLendingMarketUtilizationAnalyzer()

    def test_multiple_markets_count(self):
        markets = [
            make_market(protocol="Aave", asset="USDC", total_borrow_usd=80e6),
            make_market(protocol="Compound", asset="ETH", total_borrow_usd=60e6),
            make_market(protocol="Morpho", asset="DAI", total_borrow_usd=92e6),
        ]
        r = self.az.analyze(markets)
        self.assertEqual(len(r["markets"]), 3)

    def test_multiple_markets_protocol_preserved(self):
        markets = [
            make_market(protocol="Aave", total_borrow_usd=80e6),
            make_market(protocol="Compound", total_borrow_usd=40e6),
        ]
        r = self.az.analyze(markets)
        protocols = [m["protocol"] for m in r["markets"]]
        self.assertIn("Aave", protocols)
        self.assertIn("Compound", protocols)

    def test_multiple_markets_different_utils(self):
        markets = [
            make_market(total_borrow_usd=10e6),   # 10%
            make_market(total_borrow_usd=50e6),   # 50%
            make_market(total_borrow_usd=95e6),   # 95%
        ]
        r = self.az.analyze(markets)
        utils = [m["utilization_rate_pct"] for m in r["markets"]]
        self.assertAlmostEqual(utils[0], 10.0, places=2)
        self.assertAlmostEqual(utils[1], 50.0, places=2)
        self.assertAlmostEqual(utils[2], 95.0, places=2)

    def test_empty_market_list(self):
        r = self.az.analyze([])
        self.assertEqual(r["markets"], [])
        self.assertEqual(r["market_count"], 0)

    def test_single_market(self):
        r = self.az.analyze([make_market(total_borrow_usd=80e6)])
        self.assertEqual(len(r["markets"]), 1)
        self.assertEqual(r["market_count"], 1)


class TestAggregates(unittest.TestCase):
    """Tests for aggregate computations."""

    def setUp(self):
        self.az = DeFiLendingMarketUtilizationAnalyzer()

    def test_highest_utilization(self):
        markets = [
            make_market(protocol="A", total_borrow_usd=30e6),  # 30%
            make_market(protocol="B", total_borrow_usd=90e6),  # 90%
            make_market(protocol="C", total_borrow_usd=60e6),  # 60%
        ]
        r = self.az.analyze(markets)
        self.assertEqual(r["aggregates"]["highest_utilization"]["protocol"], "B")
        self.assertAlmostEqual(
            r["aggregates"]["highest_utilization"]["utilization_rate_pct"], 90.0, places=2
        )

    def test_lowest_utilization(self):
        markets = [
            make_market(protocol="A", total_borrow_usd=30e6),  # 30%
            make_market(protocol="B", total_borrow_usd=90e6),  # 90%
            make_market(protocol="C", total_borrow_usd=60e6),  # 60%
        ]
        r = self.az.analyze(markets)
        self.assertEqual(r["aggregates"]["lowest_utilization"]["protocol"], "A")

    def test_average_utilization(self):
        markets = [
            make_market(total_borrow_usd=20e6),  # 20%
            make_market(total_borrow_usd=80e6),  # 80%
        ]
        r = self.az.analyze(markets)
        self.assertAlmostEqual(r["aggregates"]["average_utilization"], 50.0, places=2)

    def test_saturated_count(self):
        markets = [
            make_market(total_borrow_usd=92e6),  # SATURATED
            make_market(total_borrow_usd=80e6),  # OPTIMAL
            make_market(total_borrow_usd=50e6),  # LOW
        ]
        r = self.az.analyze(markets)
        self.assertEqual(r["aggregates"]["saturated_count"], 1)

    def test_overutilized_counts_in_saturated(self):
        markets = [
            make_market(total_supply_usd=100e6, total_borrow_usd=110e6),  # OVERUTILIZED
            make_market(total_borrow_usd=95e6),  # SATURATED
            make_market(total_borrow_usd=50e6),  # LOW
        ]
        r = self.az.analyze(markets)
        self.assertEqual(r["aggregates"]["saturated_count"], 2)

    def test_optimal_count(self):
        markets = [
            make_market(total_borrow_usd=80e6, kink_utilization_pct=80.0),  # OPTIMAL
            make_market(total_borrow_usd=75e6, kink_utilization_pct=80.0),  # OPTIMAL
            make_market(total_borrow_usd=50e6, kink_utilization_pct=80.0),  # LOW
        ]
        r = self.az.analyze(markets)
        self.assertEqual(r["aggregates"]["optimal_count"], 2)

    def test_aggregates_empty_list(self):
        r = self.az.analyze([])
        agg = r["aggregates"]
        self.assertIsNone(agg["highest_utilization"])
        self.assertIsNone(agg["lowest_utilization"])
        self.assertIsNone(agg["average_utilization"])
        self.assertEqual(agg["saturated_count"], 0)
        self.assertEqual(agg["optimal_count"], 0)

    def test_aggregates_single_market(self):
        r = self.az.analyze([make_market(total_borrow_usd=70e6)])
        agg = r["aggregates"]
        self.assertIsNotNone(agg["highest_utilization"])
        self.assertEqual(
            agg["highest_utilization"]["protocol"], agg["lowest_utilization"]["protocol"]
        )

    def test_aggregates_three_markets_average(self):
        markets = [
            make_market(total_borrow_usd=10e6),  # 10%
            make_market(total_borrow_usd=20e6),  # 20%
            make_market(total_borrow_usd=30e6),  # 30%
        ]
        r = self.az.analyze(markets)
        self.assertAlmostEqual(r["aggregates"]["average_utilization"], 20.0, places=2)


class TestOutputStructure(unittest.TestCase):
    """Tests for output structure and field presence."""

    def setUp(self):
        self.az = DeFiLendingMarketUtilizationAnalyzer()

    def test_output_has_markets_key(self):
        r = self.az.analyze([make_market()])
        self.assertIn("markets", r)

    def test_output_has_aggregates_key(self):
        r = self.az.analyze([make_market()])
        self.assertIn("aggregates", r)

    def test_output_has_market_count(self):
        r = self.az.analyze([make_market()])
        self.assertEqual(r["market_count"], 1)

    def test_output_has_timestamp(self):
        r = self.az.analyze([make_market()])
        self.assertIn("timestamp", r)
        self.assertIsInstance(r["timestamp"], str)

    def test_market_result_has_protocol(self):
        r = self.az.analyze([make_market(protocol="TestProto")])
        self.assertEqual(r["markets"][0]["protocol"], "TestProto")

    def test_market_result_has_asset(self):
        r = self.az.analyze([make_market(asset="TestAsset")])
        self.assertEqual(r["markets"][0]["asset"], "TestAsset")

    def test_market_result_has_utilization_rate(self):
        r = self.az.analyze([make_market()])
        self.assertIn("utilization_rate_pct", r["markets"][0])

    def test_market_result_has_borrow_apy(self):
        r = self.az.analyze([make_market()])
        self.assertIn("borrow_apy_from_model_pct", r["markets"][0])

    def test_market_result_has_supply_apy(self):
        r = self.az.analyze([make_market()])
        self.assertIn("supply_apy_from_model_pct", r["markets"][0])

    def test_market_result_has_spread(self):
        r = self.az.analyze([make_market()])
        self.assertIn("spread_pct", r["markets"][0])

    def test_market_result_has_flags_list(self):
        r = self.az.analyze([make_market()])
        self.assertIsInstance(r["markets"][0]["flags"], list)

    def test_market_result_has_label(self):
        r = self.az.analyze([make_market()])
        self.assertIn("utilization_label", r["markets"][0])

    def test_market_result_has_distance_to_kink(self):
        r = self.az.analyze([make_market()])
        self.assertIn("distance_to_kink_pct", r["markets"][0])

    def test_market_result_has_distance_to_full(self):
        r = self.az.analyze([make_market()])
        self.assertIn("distance_to_full_pct", r["markets"][0])

    def test_market_result_preserves_liquidation_threshold(self):
        r = self.az.analyze([make_market(liquidation_threshold_pct=77.0)])
        self.assertEqual(r["markets"][0]["liquidation_threshold_pct"], 77.0)

    def test_market_result_preserves_close_factor(self):
        r = self.az.analyze([make_market(close_factor_pct=60.0)])
        self.assertEqual(r["markets"][0]["close_factor_pct"], 60.0)

    def test_market_result_preserves_current_supply_apy(self):
        r = self.az.analyze([make_market(current_supply_apy_pct=3.14)])
        self.assertAlmostEqual(r["markets"][0]["current_supply_apy_pct"], 3.14, places=3)

    def test_market_result_preserves_current_borrow_apy(self):
        r = self.az.analyze([make_market(current_borrow_apy_pct=5.0)])
        self.assertAlmostEqual(r["markets"][0]["current_borrow_apy_pct"], 5.0, places=3)


class TestLogWriting(unittest.TestCase):
    """Tests for ring-buffer log writing."""

    def setUp(self):
        self.az = DeFiLendingMarketUtilizationAnalyzer()

    def test_write_log_creates_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            m = make_market(total_borrow_usd=80e6)
            self.az.analyze([m], config={"write_log": True, "data_dir": tmp})
            self.assertTrue(os.path.exists(os.path.join(tmp, "lending_utilization_log.json")))

    def test_write_log_content(self):
        with tempfile.TemporaryDirectory() as tmp:
            m = make_market(total_borrow_usd=80e6)
            self.az.analyze([m], config={"write_log": True, "data_dir": tmp})
            with open(os.path.join(tmp, "lending_utilization_log.json")) as f:
                log = json.load(f)
            self.assertEqual(len(log), 1)
            self.assertIn("timestamp", log[0])

    def test_write_log_appends(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = {"write_log": True, "data_dir": tmp}
            m = make_market(total_borrow_usd=80e6)
            self.az.analyze([m], config=cfg)
            self.az.analyze([m], config=cfg)
            with open(os.path.join(tmp, "lending_utilization_log.json")) as f:
                log = json.load(f)
            self.assertEqual(len(log), 2)

    def test_write_log_ring_buffer_cap(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = {"write_log": True, "data_dir": tmp}
            m = make_market(total_borrow_usd=80e6)
            for _ in range(105):
                self.az.analyze([m], config=cfg)
            with open(os.path.join(tmp, "lending_utilization_log.json")) as f:
                log = json.load(f)
            self.assertEqual(len(log), 100)

    def test_no_log_by_default(self):
        with tempfile.TemporaryDirectory() as tmp:
            m = make_market(total_borrow_usd=80e6)
            self.az.analyze([m])
            log_path = os.path.join(tmp, "lending_utilization_log.json")
            self.assertFalse(os.path.exists(log_path))

    def test_write_log_has_market_count(self):
        with tempfile.TemporaryDirectory() as tmp:
            markets = [make_market(), make_market()]
            self.az.analyze(markets, config={"write_log": True, "data_dir": tmp})
            with open(os.path.join(tmp, "lending_utilization_log.json")) as f:
                log = json.load(f)
            self.assertEqual(log[0]["market_count"], 2)

    def test_write_log_has_saturated_count(self):
        with tempfile.TemporaryDirectory() as tmp:
            m = make_market(total_borrow_usd=95e6)
            self.az.analyze([m], config={"write_log": True, "data_dir": tmp})
            with open(os.path.join(tmp, "lending_utilization_log.json")) as f:
                log = json.load(f)
            self.assertEqual(log[0]["saturated_count"], 1)

    def test_write_log_invalid_existing_log(self):
        with tempfile.TemporaryDirectory() as tmp:
            log_path = os.path.join(tmp, "lending_utilization_log.json")
            with open(log_path, "w") as f:
                f.write("INVALID JSON{{{")
            m = make_market(total_borrow_usd=80e6)
            # Should not raise, should start fresh
            self.az.analyze([m], config={"write_log": True, "data_dir": tmp})
            with open(log_path) as f:
                log = json.load(f)
            self.assertEqual(len(log), 1)


class TestEdgeCases(unittest.TestCase):
    """Edge cases and miscellaneous tests."""

    def setUp(self):
        self.az = DeFiLendingMarketUtilizationAnalyzer()

    def test_default_config_none(self):
        m = make_market(total_borrow_usd=80e6)
        r = self.az.analyze([m], config=None)
        self.assertIsInstance(r, dict)

    def test_string_numbers_coerced(self):
        m = make_market(total_supply_usd="100000000", total_borrow_usd="80000000")
        r = self.az.analyze([m])
        self.assertAlmostEqual(r["markets"][0]["utilization_rate_pct"], 80.0, places=2)

    def test_missing_optional_fields_use_defaults(self):
        m = {"protocol": "X", "asset": "Y", "total_supply_usd": 100e6, "total_borrow_usd": 50e6}
        r = self.az.analyze([m])
        self.assertIn("borrow_apy_from_model_pct", r["markets"][0])

    def test_kink_at_100_above_kink_never_triggered(self):
        # kink=100, util=80 → below kink always
        m = make_market(
            total_borrow_usd=80e6,
            kink_utilization_pct=100.0,
            slope1_pct=4.0,
            slope2_pct=60.0,
        )
        r = self.az.analyze([m])
        # util=80 < kink=100 → base + (80/100)*4 = 3.2
        self.assertAlmostEqual(r["markets"][0]["borrow_apy_from_model_pct"], 3.2, places=3)

    def test_very_small_supply(self):
        m = make_market(total_supply_usd=1, total_borrow_usd=0.8)
        r = self.az.analyze([m])
        self.assertAlmostEqual(r["markets"][0]["utilization_rate_pct"], 80.0, places=2)

    def test_analyze_returns_dict(self):
        r = self.az.analyze([make_market()])
        self.assertIsInstance(r, dict)

    def test_borrow_supply_apy_relationship(self):
        # supply_apy should always <= borrow_apy when util in [0,100]
        m = make_market(total_borrow_usd=70e6)
        r = self.az.analyze([m])
        market = r["markets"][0]
        self.assertLessEqual(
            market["supply_apy_from_model_pct"], market["borrow_apy_from_model_pct"] + 1e-9
        )

    def test_flags_flags_can_be_empty(self):
        # util=5%: EMPTY, spread=~0, no flags expected except possibly none
        m = make_market(total_borrow_usd=5e6, base_rate_pct=0.0, slope1_pct=4.0)
        flags = self.az.analyze([m])["markets"][0]["flags"]
        self.assertIsInstance(flags, list)

    def test_multiple_flags_coexist(self):
        # util=77 with kink=80: AT_KINK (|77-80|=3≤5) AND RATE_SPIKE_IMMINENT (77>76)
        m = make_market(total_borrow_usd=77e6, kink_utilization_pct=80.0)
        flags = self.az.analyze([m])["markets"][0]["flags"]
        self.assertIn("AT_KINK", flags)
        self.assertIn("RATE_SPIKE_IMMINENT", flags)

    def test_high_util_has_supply_incentive_and_liquidation(self):
        m = make_market(total_borrow_usd=92e6)
        flags = self.az.analyze([m])["markets"][0]["flags"]
        self.assertIn("SUPPLY_INCENTIVE_NEEDED", flags)
        self.assertIn("LIQUIDATION_RISK_HIGH", flags)


if __name__ == "__main__":
    unittest.main()
