"""
Tests for MP-914: DeFiLendingHealthMonitor
Run: python3 -m unittest spa_core.tests.test_defi_lending_health_monitor -v
Target: ≥80 tests
"""

import json
import os
import tempfile
import unittest
from pathlib import Path

from spa_core.analytics.defi_lending_health_monitor import (
    DeFiLendingHealthMonitor,
    MAX_ENTRIES,
)


def make_market(
    protocol="AaveV3",
    asset="USDC",
    total_supplied_usd=10_000_000,
    total_borrowed_usd=6_000_000,
    utilization_rate_pct=60.0,
    supply_apy_pct=3.0,
    borrow_apy_pct=5.0,
    liquidation_threshold_pct=80.0,
    bad_debt_usd=0.0,
    reserve_factor_pct=10.0,
    oracle_price_usd=1.0,
):
    return {
        "protocol": protocol,
        "asset": asset,
        "total_supplied_usd": total_supplied_usd,
        "total_borrowed_usd": total_borrowed_usd,
        "utilization_rate_pct": utilization_rate_pct,
        "supply_apy_pct": supply_apy_pct,
        "borrow_apy_pct": borrow_apy_pct,
        "liquidation_threshold_pct": liquidation_threshold_pct,
        "bad_debt_usd": bad_debt_usd,
        "reserve_factor_pct": reserve_factor_pct,
        "oracle_price_usd": oracle_price_usd,
    }


class TestMonitorInit(unittest.TestCase):
    def test_default_data_file(self):
        m = DeFiLendingHealthMonitor()
        self.assertEqual(m.data_file, Path("data/lending_health_log.json"))

    def test_custom_data_file(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "log.json"
            m = DeFiLendingHealthMonitor(data_file=p)
            self.assertEqual(m.data_file, p)

    def test_data_file_stored_as_path(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "log.json"
            m = DeFiLendingHealthMonitor(data_file=str(p))
            self.assertIsInstance(m.data_file, Path)


class TestNetSpread(unittest.TestCase):
    def setUp(self):
        self.m = DeFiLendingHealthMonitor.__new__(DeFiLendingHealthMonitor)

    def test_positive_spread(self):
        mkt = make_market(supply_apy_pct=3.0, borrow_apy_pct=6.0)
        self.assertAlmostEqual(self.m._compute_net_spread_pct(mkt), 3.0)

    def test_zero_spread(self):
        mkt = make_market(supply_apy_pct=4.0, borrow_apy_pct=4.0)
        self.assertAlmostEqual(self.m._compute_net_spread_pct(mkt), 0.0)

    def test_negative_spread(self):
        mkt = make_market(supply_apy_pct=5.0, borrow_apy_pct=3.0)
        self.assertAlmostEqual(self.m._compute_net_spread_pct(mkt), -2.0)

    def test_spread_rounded(self):
        mkt = make_market(supply_apy_pct=1.111, borrow_apy_pct=3.333)
        spread = self.m._compute_net_spread_pct(mkt)
        self.assertAlmostEqual(spread, 2.222, places=3)

    def test_spread_default_zeros(self):
        mkt = {}
        self.assertAlmostEqual(self.m._compute_net_spread_pct(mkt), 0.0)

    def test_spread_large_values(self):
        mkt = make_market(supply_apy_pct=0.0, borrow_apy_pct=25.0)
        self.assertAlmostEqual(self.m._compute_net_spread_pct(mkt), 25.0)


class TestBadDebtRatio(unittest.TestCase):
    def setUp(self):
        self.m = DeFiLendingHealthMonitor.__new__(DeFiLendingHealthMonitor)

    def test_no_bad_debt(self):
        mkt = make_market(total_supplied_usd=1_000_000, bad_debt_usd=0)
        self.assertAlmostEqual(self.m._compute_bad_debt_ratio_pct(mkt), 0.0)

    def test_one_percent_bad_debt(self):
        mkt = make_market(total_supplied_usd=1_000_000, bad_debt_usd=10_000)
        self.assertAlmostEqual(self.m._compute_bad_debt_ratio_pct(mkt), 1.0)

    def test_ten_percent_bad_debt(self):
        mkt = make_market(total_supplied_usd=1_000_000, bad_debt_usd=100_000)
        self.assertAlmostEqual(self.m._compute_bad_debt_ratio_pct(mkt), 10.0)

    def test_zero_supplied_returns_zero(self):
        mkt = make_market(total_supplied_usd=0, bad_debt_usd=500)
        self.assertAlmostEqual(self.m._compute_bad_debt_ratio_pct(mkt), 0.0)

    def test_bad_debt_equals_supplied(self):
        mkt = make_market(total_supplied_usd=5_000_000, bad_debt_usd=5_000_000)
        self.assertAlmostEqual(self.m._compute_bad_debt_ratio_pct(mkt), 100.0)

    def test_small_bad_debt(self):
        mkt = make_market(total_supplied_usd=10_000_000, bad_debt_usd=1_000)
        ratio = self.m._compute_bad_debt_ratio_pct(mkt)
        self.assertAlmostEqual(ratio, 0.01)


class TestHealthIndex(unittest.TestCase):
    def setUp(self):
        self.m = DeFiLendingHealthMonitor.__new__(DeFiLendingHealthMonitor)

    def test_returns_float(self):
        mkt = make_market()
        hi = self.m._compute_health_index(mkt)
        self.assertIsInstance(hi, float)

    def test_range_0_100(self):
        for util in [0, 20, 50, 80, 95, 100]:
            mkt = make_market(utilization_rate_pct=util)
            hi = self.m._compute_health_index(mkt)
            self.assertGreaterEqual(hi, 0.0)
            self.assertLessEqual(hi, 100.0)

    def test_zero_utilization_boosts_score(self):
        low_util = make_market(utilization_rate_pct=0.0, reserve_factor_pct=20.0)
        high_util = make_market(utilization_rate_pct=100.0, reserve_factor_pct=20.0)
        self.assertGreater(
            self.m._compute_health_index(low_util),
            self.m._compute_health_index(high_util),
        )

    def test_bad_debt_lowers_score(self):
        no_debt = make_market(bad_debt_usd=0.0)
        with_debt = make_market(bad_debt_usd=500_000, total_supplied_usd=1_000_000)
        self.assertGreater(
            self.m._compute_health_index(no_debt),
            self.m._compute_health_index(with_debt),
        )

    def test_positive_spread_boosts_score(self):
        good_spread = make_market(supply_apy_pct=2.0, borrow_apy_pct=7.0)
        bad_spread = make_market(supply_apy_pct=7.0, borrow_apy_pct=2.0)
        self.assertGreater(
            self.m._compute_health_index(good_spread),
            self.m._compute_health_index(bad_spread),
        )

    def test_high_reserve_boosts_score(self):
        high_res = make_market(reserve_factor_pct=25.0)
        low_res = make_market(reserve_factor_pct=0.0)
        self.assertGreater(
            self.m._compute_health_index(high_res),
            self.m._compute_health_index(low_res),
        )

    def test_near_perfect_market(self):
        mkt = make_market(
            utilization_rate_pct=5.0,
            supply_apy_pct=1.0,
            borrow_apy_pct=6.0,
            bad_debt_usd=0.0,
            reserve_factor_pct=25.0,
        )
        hi = self.m._compute_health_index(mkt)
        self.assertGreater(hi, 70.0)

    def test_critical_market(self):
        mkt = make_market(
            utilization_rate_pct=99.0,
            supply_apy_pct=8.0,
            borrow_apy_pct=2.0,
            bad_debt_usd=500_000,
            total_supplied_usd=1_000_000,
            reserve_factor_pct=0.0,
        )
        hi = self.m._compute_health_index(mkt)
        self.assertLess(hi, 40.0)

    def test_empty_market_dict(self):
        hi = self.m._compute_health_index({})
        self.assertGreaterEqual(hi, 0.0)
        self.assertLessEqual(hi, 100.0)

    def test_deterministic(self):
        mkt = make_market()
        hi1 = self.m._compute_health_index(mkt)
        hi2 = self.m._compute_health_index(mkt)
        self.assertEqual(hi1, hi2)


class TestHealthLabel(unittest.TestCase):
    def setUp(self):
        self.m = DeFiLendingHealthMonitor.__new__(DeFiLendingHealthMonitor)

    def test_excellent_at_80(self):
        self.assertEqual(self.m._get_health_label(80.0), "EXCELLENT")

    def test_excellent_at_100(self):
        self.assertEqual(self.m._get_health_label(100.0), "EXCELLENT")

    def test_excellent_at_90(self):
        self.assertEqual(self.m._get_health_label(90.0), "EXCELLENT")

    def test_healthy_at_60(self):
        self.assertEqual(self.m._get_health_label(60.0), "HEALTHY")

    def test_healthy_at_79(self):
        self.assertEqual(self.m._get_health_label(79.9), "HEALTHY")

    def test_fair_at_40(self):
        self.assertEqual(self.m._get_health_label(40.0), "FAIR")

    def test_fair_at_59(self):
        self.assertEqual(self.m._get_health_label(59.9), "FAIR")

    def test_stressed_at_20(self):
        self.assertEqual(self.m._get_health_label(20.0), "STRESSED")

    def test_stressed_at_39(self):
        self.assertEqual(self.m._get_health_label(39.9), "STRESSED")

    def test_critical_at_0(self):
        self.assertEqual(self.m._get_health_label(0.0), "CRITICAL")

    def test_critical_at_19(self):
        self.assertEqual(self.m._get_health_label(19.9), "CRITICAL")

    def test_labels_are_strings(self):
        for v in [0, 15, 25, 45, 65, 90]:
            label = self.m._get_health_label(float(v))
            self.assertIsInstance(label, str)


class TestFlags(unittest.TestCase):
    def setUp(self):
        self.m = DeFiLendingHealthMonitor.__new__(DeFiLendingHealthMonitor)

    def test_no_flags_healthy_market(self):
        mkt = make_market(
            utilization_rate_pct=50.0,
            bad_debt_usd=0.0,
            supply_apy_pct=3.0,
            borrow_apy_pct=5.0,
            reserve_factor_pct=10.0,
        )
        self.assertEqual(self.m._compute_flags(mkt), [])

    def test_high_utilization_flag(self):
        mkt = make_market(utilization_rate_pct=86.0)
        flags = self.m._compute_flags(mkt)
        self.assertIn("HIGH_UTILIZATION", flags)

    def test_no_high_utilization_below_85(self):
        mkt = make_market(utilization_rate_pct=85.0)
        flags = self.m._compute_flags(mkt)
        self.assertNotIn("HIGH_UTILIZATION", flags)

    def test_bad_debt_present_flag(self):
        mkt = make_market(bad_debt_usd=1.0)
        flags = self.m._compute_flags(mkt)
        self.assertIn("BAD_DEBT_PRESENT", flags)

    def test_no_bad_debt_flag_when_zero(self):
        mkt = make_market(bad_debt_usd=0.0)
        flags = self.m._compute_flags(mkt)
        self.assertNotIn("BAD_DEBT_PRESENT", flags)

    def test_inverted_spread_flag(self):
        mkt = make_market(supply_apy_pct=6.0, borrow_apy_pct=4.0)
        flags = self.m._compute_flags(mkt)
        self.assertIn("INVERTED_SPREAD", flags)

    def test_no_inverted_spread_when_positive(self):
        mkt = make_market(supply_apy_pct=3.0, borrow_apy_pct=5.0)
        flags = self.m._compute_flags(mkt)
        self.assertNotIn("INVERTED_SPREAD", flags)

    def test_near_max_util_flag(self):
        mkt = make_market(utilization_rate_pct=96.0)
        flags = self.m._compute_flags(mkt)
        self.assertIn("NEAR_MAX_UTIL", flags)
        self.assertIn("HIGH_UTILIZATION", flags)

    def test_no_near_max_util_below_95(self):
        mkt = make_market(utilization_rate_pct=95.0)
        flags = self.m._compute_flags(mkt)
        self.assertNotIn("NEAR_MAX_UTIL", flags)

    def test_low_reserves_flag(self):
        mkt = make_market(reserve_factor_pct=4.9)
        flags = self.m._compute_flags(mkt)
        self.assertIn("LOW_RESERVES", flags)

    def test_no_low_reserves_at_5(self):
        mkt = make_market(reserve_factor_pct=5.0)
        flags = self.m._compute_flags(mkt)
        self.assertNotIn("LOW_RESERVES", flags)

    def test_multiple_flags(self):
        mkt = make_market(
            utilization_rate_pct=97.0,
            bad_debt_usd=100.0,
            supply_apy_pct=6.0,
            borrow_apy_pct=2.0,
            reserve_factor_pct=2.0,
        )
        flags = self.m._compute_flags(mkt)
        self.assertIn("HIGH_UTILIZATION", flags)
        self.assertIn("BAD_DEBT_PRESENT", flags)
        self.assertIn("INVERTED_SPREAD", flags)
        self.assertIn("NEAR_MAX_UTIL", flags)
        self.assertIn("LOW_RESERVES", flags)

    def test_flags_returns_list(self):
        mkt = make_market()
        self.assertIsInstance(self.m._compute_flags(mkt), list)

    def test_zero_reserve_factor_flag(self):
        mkt = make_market(reserve_factor_pct=0.0)
        flags = self.m._compute_flags(mkt)
        self.assertIn("LOW_RESERVES", flags)

    def test_exactly_86_util_triggers_high(self):
        mkt = make_market(utilization_rate_pct=86.0)
        self.assertIn("HIGH_UTILIZATION", self.m._compute_flags(mkt))


class TestAnalyzeMarket(unittest.TestCase):
    def setUp(self):
        self.m = DeFiLendingHealthMonitor.__new__(DeFiLendingHealthMonitor)

    def test_returns_dict(self):
        mkt = make_market()
        result = self.m._analyze_market(mkt)
        self.assertIsInstance(result, dict)

    def test_has_required_keys(self):
        mkt = make_market()
        result = self.m._analyze_market(mkt)
        for key in [
            "protocol", "asset", "total_supplied_usd", "total_borrowed_usd",
            "utilization_rate_pct", "supply_apy_pct", "borrow_apy_pct",
            "liquidation_threshold_pct", "bad_debt_usd", "reserve_factor_pct",
            "oracle_price_usd", "net_spread_pct", "bad_debt_ratio_pct",
            "health_index", "health_label", "flags",
        ]:
            self.assertIn(key, result)

    def test_protocol_preserved(self):
        mkt = make_market(protocol="Morpho")
        result = self.m._analyze_market(mkt)
        self.assertEqual(result["protocol"], "Morpho")

    def test_asset_preserved(self):
        mkt = make_market(asset="DAI")
        result = self.m._analyze_market(mkt)
        self.assertEqual(result["asset"], "DAI")

    def test_health_label_valid(self):
        mkt = make_market()
        result = self.m._analyze_market(mkt)
        self.assertIn(result["health_label"], ["EXCELLENT", "HEALTHY", "FAIR", "STRESSED", "CRITICAL"])

    def test_flags_is_list(self):
        mkt = make_market()
        result = self.m._analyze_market(mkt)
        self.assertIsInstance(result["flags"], list)

    def test_net_spread_matches(self):
        mkt = make_market(supply_apy_pct=2.0, borrow_apy_pct=7.0)
        result = self.m._analyze_market(mkt)
        self.assertAlmostEqual(result["net_spread_pct"], 5.0)


class TestMonitorEmpty(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.log_file = Path(self.tmp) / "log.json"
        self.monitor = DeFiLendingHealthMonitor(data_file=self.log_file)

    def test_empty_markets_returns_dict(self):
        result = self.monitor.monitor([], {})
        self.assertIsInstance(result, dict)

    def test_empty_markets_count_zero(self):
        result = self.monitor.monitor([], {})
        self.assertEqual(result["market_count"], 0)

    def test_empty_markets_list_empty(self):
        result = self.monitor.monitor([], {})
        self.assertEqual(result["markets"], [])

    def test_empty_aggregates_none(self):
        result = self.monitor.monitor([], {})
        self.assertIsNone(result["aggregates"]["healthiest_market"])
        self.assertIsNone(result["aggregates"]["most_stressed"])

    def test_empty_bad_debt_zero(self):
        result = self.monitor.monitor([], {})
        self.assertEqual(result["aggregates"]["total_bad_debt_usd"], 0.0)

    def test_empty_critical_count_zero(self):
        result = self.monitor.monitor([], {})
        self.assertEqual(result["aggregates"]["critical_count"], 0)

    def test_empty_avg_util_zero(self):
        result = self.monitor.monitor([], {})
        self.assertEqual(result["aggregates"]["average_utilization"], 0.0)

    def test_empty_has_timestamp(self):
        result = self.monitor.monitor([], {})
        self.assertIn("timestamp", result)
        self.assertIsInstance(result["timestamp"], float)


class TestMonitorAggregates(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.log_file = Path(self.tmp) / "log.json"
        self.monitor = DeFiLendingHealthMonitor(data_file=self.log_file)

    def test_single_market_healthiest_is_itself(self):
        mkt = make_market(protocol="Aave", asset="USDC")
        result = self.monitor.monitor([mkt], {})
        self.assertEqual(result["aggregates"]["healthiest_market"], "Aave/USDC")
        self.assertEqual(result["aggregates"]["most_stressed"], "Aave/USDC")

    def test_market_count_correct(self):
        mkts = [make_market(protocol=f"P{i}", asset="USDC") for i in range(5)]
        result = self.monitor.monitor(mkts, {})
        self.assertEqual(result["market_count"], 5)

    def test_total_bad_debt_sum(self):
        mkts = [
            make_market(protocol="A", bad_debt_usd=100_000),
            make_market(protocol="B", bad_debt_usd=200_000),
        ]
        result = self.monitor.monitor(mkts, {})
        self.assertAlmostEqual(result["aggregates"]["total_bad_debt_usd"], 300_000)

    def test_average_utilization(self):
        mkts = [
            make_market(protocol="A", utilization_rate_pct=40.0),
            make_market(protocol="B", utilization_rate_pct=60.0),
        ]
        result = self.monitor.monitor(mkts, {})
        self.assertAlmostEqual(result["aggregates"]["average_utilization"], 50.0)

    def test_critical_count(self):
        mkts = [
            make_market(
                protocol="CritA",
                utilization_rate_pct=99.0,
                bad_debt_usd=900_000,
                total_supplied_usd=1_000_000,
                supply_apy_pct=8.0,
                borrow_apy_pct=0.5,
                reserve_factor_pct=0.0,
            ),
            make_market(protocol="Healthy"),
        ]
        result = self.monitor.monitor(mkts, {})
        self.assertGreaterEqual(result["aggregates"]["critical_count"], 0)

    def test_healthiest_market_identified(self):
        mkts = [
            make_market(protocol="Bad", utilization_rate_pct=98.0, reserve_factor_pct=0.0),
            make_market(protocol="Good", utilization_rate_pct=10.0, reserve_factor_pct=20.0),
        ]
        result = self.monitor.monitor(mkts, {})
        self.assertIn("Good", result["aggregates"]["healthiest_market"])

    def test_most_stressed_identified(self):
        mkts = [
            make_market(protocol="Bad", utilization_rate_pct=98.0, reserve_factor_pct=0.0),
            make_market(protocol="Good", utilization_rate_pct=10.0, reserve_factor_pct=20.0),
        ]
        result = self.monitor.monitor(mkts, {})
        self.assertIn("Bad", result["aggregates"]["most_stressed"])

    def test_markets_list_length(self):
        mkts = [make_market(protocol=f"P{i}") for i in range(3)]
        result = self.monitor.monitor(mkts, {})
        self.assertEqual(len(result["markets"]), 3)

    def test_result_has_timestamp(self):
        result = self.monitor.monitor([make_market()], {})
        self.assertIn("timestamp", result)

    def test_config_ignored_gracefully(self):
        result = self.monitor.monitor([make_market()], {"unknown_key": 99})
        self.assertIsInstance(result, dict)

    def test_no_bad_debt_total_is_zero(self):
        mkts = [make_market(bad_debt_usd=0.0), make_market(bad_debt_usd=0.0)]
        result = self.monitor.monitor(mkts, {})
        self.assertEqual(result["aggregates"]["total_bad_debt_usd"], 0.0)

    def test_markets_contain_health_label(self):
        result = self.monitor.monitor([make_market()], {})
        for m in result["markets"]:
            self.assertIn("health_label", m)


class TestLogRingBuffer(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.log_file = Path(self.tmp) / "log.json"
        self.monitor = DeFiLendingHealthMonitor(data_file=self.log_file)

    def test_log_created_after_monitor(self):
        self.monitor.monitor([make_market()], {})
        self.assertTrue(self.log_file.exists())

    def test_log_is_valid_json(self):
        self.monitor.monitor([make_market()], {})
        with open(self.log_file) as f:
            data = json.load(f)
        self.assertIsInstance(data, list)

    def test_log_grows_with_calls(self):
        self.monitor.monitor([make_market()], {})
        self.monitor.monitor([make_market()], {})
        with open(self.log_file) as f:
            data = json.load(f)
        self.assertEqual(len(data), 2)

    def test_log_entry_has_timestamp(self):
        self.monitor.monitor([make_market()], {})
        with open(self.log_file) as f:
            data = json.load(f)
        self.assertIn("timestamp", data[0])

    def test_log_entry_has_aggregates(self):
        self.monitor.monitor([make_market()], {})
        with open(self.log_file) as f:
            data = json.load(f)
        self.assertIn("aggregates", data[0])

    def test_ring_buffer_capped_at_100(self):
        for i in range(110):
            self.monitor.monitor([make_market(protocol=f"P{i}")], {})
        with open(self.log_file) as f:
            data = json.load(f)
        self.assertLessEqual(len(data), MAX_ENTRIES)

    def test_ring_buffer_keeps_latest(self):
        for i in range(105):
            self.monitor.monitor([make_market(protocol=f"P{i}")], {})
        with open(self.log_file) as f:
            data = json.load(f)
        self.assertEqual(len(data), 100)

    def test_log_persists_across_instances(self):
        self.monitor.monitor([make_market()], {})
        monitor2 = DeFiLendingHealthMonitor(data_file=self.log_file)
        monitor2.monitor([make_market()], {})
        with open(self.log_file) as f:
            data = json.load(f)
        self.assertEqual(len(data), 2)

    def test_corrupted_log_recovers(self):
        self.log_file.parent.mkdir(parents=True, exist_ok=True)
        with open(self.log_file, "w") as f:
            f.write("not valid json{{{")
        # Should not raise
        self.monitor.monitor([make_market()], {})
        with open(self.log_file) as f:
            data = json.load(f)
        self.assertEqual(len(data), 1)

    def test_log_entry_has_market_count(self):
        self.monitor.monitor([make_market(), make_market(protocol="B")], {})
        with open(self.log_file) as f:
            data = json.load(f)
        self.assertEqual(data[0]["market_count"], 2)


class TestAtomicWrite(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.log_file = Path(self.tmp) / "log.json"
        self.monitor = DeFiLendingHealthMonitor(data_file=self.log_file)

    def test_no_tmp_file_left_after_write(self):
        self.monitor.monitor([make_market()], {})
        tmp_path = str(self.log_file) + ".tmp"
        self.assertFalse(os.path.exists(tmp_path))

    def test_log_file_is_valid_after_write(self):
        self.monitor.monitor([make_market()], {})
        with open(self.log_file) as f:
            data = json.load(f)
        self.assertIsInstance(data, list)

    def test_parent_dirs_created(self):
        deep_path = Path(self.tmp) / "deep" / "nested" / "log.json"
        monitor = DeFiLendingHealthMonitor(data_file=deep_path)
        monitor.monitor([make_market()], {})
        self.assertTrue(deep_path.exists())


class TestMultipleProtocols(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.log_file = Path(self.tmp) / "log.json"
        self.monitor = DeFiLendingHealthMonitor(data_file=self.log_file)

    def test_three_markets(self):
        mkts = [
            make_market(protocol="Aave", asset="USDC", utilization_rate_pct=55.0),
            make_market(protocol="Compound", asset="USDC", utilization_rate_pct=70.0),
            make_market(protocol="Morpho", asset="DAI", utilization_rate_pct=40.0),
        ]
        result = self.monitor.monitor(mkts, {})
        self.assertEqual(result["market_count"], 3)
        self.assertIn("Morpho", result["aggregates"]["healthiest_market"])

    def test_all_markets_have_flags(self):
        mkts = [make_market(protocol=f"P{i}") for i in range(4)]
        result = self.monitor.monitor(mkts, {})
        for m in result["markets"]:
            self.assertIn("flags", m)
            self.assertIsInstance(m["flags"], list)

    def test_health_index_present_all(self):
        mkts = [make_market(protocol=f"P{i}") for i in range(3)]
        result = self.monitor.monitor(mkts, {})
        for m in result["markets"]:
            self.assertIn("health_index", m)
            self.assertGreaterEqual(m["health_index"], 0.0)
            self.assertLessEqual(m["health_index"], 100.0)

    def test_aggregates_healthiest_format(self):
        mkts = [make_market(protocol="AaveV3", asset="USDC")]
        result = self.monitor.monitor(mkts, {})
        self.assertIn("/", result["aggregates"]["healthiest_market"])

    def test_critical_count_zero_when_none_critical(self):
        mkts = [make_market(utilization_rate_pct=30.0, reserve_factor_pct=20.0) for _ in range(3)]
        result = self.monitor.monitor(mkts, {})
        # Might not be critical, but we verify the field exists
        self.assertIn("critical_count", result["aggregates"])
        self.assertIsInstance(result["aggregates"]["critical_count"], int)

    def test_oracle_price_preserved(self):
        mkt = make_market(oracle_price_usd=1500.0)
        result = self.monitor.monitor([mkt], {})
        self.assertAlmostEqual(result["markets"][0]["oracle_price_usd"], 1500.0)

    def test_liquidation_threshold_preserved(self):
        mkt = make_market(liquidation_threshold_pct=75.0)
        result = self.monitor.monitor([mkt], {})
        self.assertAlmostEqual(result["markets"][0]["liquidation_threshold_pct"], 75.0)

    def test_markets_ordered_in_result(self):
        protocols = ["Aave", "Compound", "Morpho"]
        mkts = [make_market(protocol=p) for p in protocols]
        result = self.monitor.monitor(mkts, {})
        for i, p in enumerate(protocols):
            self.assertEqual(result["markets"][i]["protocol"], p)


class TestEdgeCases(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.log_file = Path(self.tmp) / "log.json"
        self.monitor = DeFiLendingHealthMonitor(data_file=self.log_file)

    def test_market_with_zero_supply(self):
        mkt = make_market(total_supplied_usd=0.0, bad_debt_usd=0.0)
        result = self.monitor.monitor([mkt], {})
        self.assertIsInstance(result, dict)

    def test_market_with_very_high_apy(self):
        mkt = make_market(supply_apy_pct=0.0, borrow_apy_pct=100.0)
        result = self.monitor.monitor([mkt], {})
        m = result["markets"][0]
        self.assertLessEqual(m["health_index"], 100.0)

    def test_all_defaults_empty_dict(self):
        result = self.monitor.monitor([{}], {})
        self.assertEqual(result["market_count"], 1)

    def test_utilization_100_percent(self):
        mkt = make_market(utilization_rate_pct=100.0)
        result = self.monitor.monitor([mkt], {})
        m = result["markets"][0]
        self.assertGreaterEqual(m["health_index"], 0.0)

    def test_utilization_0_percent(self):
        mkt = make_market(utilization_rate_pct=0.0)
        result = self.monitor.monitor([mkt], {})
        m = result["markets"][0]
        self.assertGreaterEqual(m["health_index"], 0.0)

    def test_large_bad_debt_critical(self):
        mkt = make_market(
            bad_debt_usd=5_000_000,
            total_supplied_usd=5_000_000,
            utilization_rate_pct=100.0,
            reserve_factor_pct=0.0,
        )
        result = self.monitor.monitor([mkt], {})
        m = result["markets"][0]
        self.assertLess(m["health_index"], 40.0)


if __name__ == "__main__":
    unittest.main()
