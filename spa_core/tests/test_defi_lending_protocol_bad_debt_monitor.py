"""
Tests for MP-994: DeFiLendingProtocolBadDebtMonitor
Run: python3 -m unittest spa_core.tests.test_defi_lending_protocol_bad_debt_monitor
"""

import json
import os
import tempfile
import unittest
from pathlib import Path

from spa_core.analytics.defi_lending_protocol_bad_debt_monitor import (
    DeFiLendingProtocolBadDebtMonitor,
)


def _make_protocol(
    name="TestProto",
    total_borrowed_usd=1_000_000.0,
    bad_debt_usd=0.0,
    bad_debt_trend_pct_30d=0.0,
    reserve_fund_usd=100_000.0,
    total_tvl_usd=2_000_000.0,
    largest_underwater_position_usd=0.0,
    avg_collateral_ratio_pct=150.0,
    liquidation_count_30d=10,
    failed_liquidation_count_30d=0,
    protocol_covers_bad_debt=False,
    token_inflation_risk=False,
):
    return {
        "name": name,
        "total_borrowed_usd": total_borrowed_usd,
        "bad_debt_usd": bad_debt_usd,
        "bad_debt_trend_pct_30d": bad_debt_trend_pct_30d,
        "reserve_fund_usd": reserve_fund_usd,
        "total_tvl_usd": total_tvl_usd,
        "largest_underwater_position_usd": largest_underwater_position_usd,
        "avg_collateral_ratio_pct": avg_collateral_ratio_pct,
        "liquidation_count_30d": liquidation_count_30d,
        "failed_liquidation_count_30d": failed_liquidation_count_30d,
        "protocol_covers_bad_debt": protocol_covers_bad_debt,
        "token_inflation_risk": token_inflation_risk,
    }


class TestBadDebtRatioPct(unittest.TestCase):
    def setUp(self):
        self.m = DeFiLendingProtocolBadDebtMonitor()

    def test_zero_bad_debt(self):
        p = _make_protocol(total_borrowed_usd=1_000_000.0, bad_debt_usd=0.0)
        self.assertEqual(self.m._bad_debt_ratio_pct(p), 0.0)

    def test_one_percent(self):
        p = _make_protocol(total_borrowed_usd=1_000_000.0, bad_debt_usd=10_000.0)
        self.assertAlmostEqual(self.m._bad_debt_ratio_pct(p), 1.0, places=4)

    def test_half_percent(self):
        p = _make_protocol(total_borrowed_usd=1_000_000.0, bad_debt_usd=5_000.0)
        self.assertAlmostEqual(self.m._bad_debt_ratio_pct(p), 0.5, places=4)

    def test_zero_total_borrowed(self):
        p = _make_protocol(total_borrowed_usd=0.0, bad_debt_usd=1000.0)
        self.assertEqual(self.m._bad_debt_ratio_pct(p), 0.0)

    def test_small_ratio(self):
        p = _make_protocol(total_borrowed_usd=10_000_000.0, bad_debt_usd=500.0)
        self.assertAlmostEqual(self.m._bad_debt_ratio_pct(p), 0.005, places=5)

    def test_two_percent(self):
        p = _make_protocol(total_borrowed_usd=1_000_000.0, bad_debt_usd=20_000.0)
        self.assertAlmostEqual(self.m._bad_debt_ratio_pct(p), 2.0, places=4)


class TestReserveCoverageRatio(unittest.TestCase):
    def setUp(self):
        self.m = DeFiLendingProtocolBadDebtMonitor()

    def test_no_bad_debt_infinite_coverage(self):
        p = _make_protocol(reserve_fund_usd=1_000_000.0, bad_debt_usd=0.0)
        self.assertGreater(self.m._reserve_coverage_ratio(p), 1000.0)

    def test_10x_coverage(self):
        p = _make_protocol(reserve_fund_usd=100_000.0, bad_debt_usd=10_000.0)
        self.assertAlmostEqual(self.m._reserve_coverage_ratio(p), 10.0, places=4)

    def test_1x_coverage(self):
        p = _make_protocol(reserve_fund_usd=50_000.0, bad_debt_usd=50_000.0)
        self.assertAlmostEqual(self.m._reserve_coverage_ratio(p), 1.0, places=4)

    def test_below_1x_coverage(self):
        p = _make_protocol(reserve_fund_usd=10_000.0, bad_debt_usd=50_000.0)
        self.assertAlmostEqual(self.m._reserve_coverage_ratio(p), 0.2, places=4)

    def test_2x_coverage(self):
        p = _make_protocol(reserve_fund_usd=200_000.0, bad_debt_usd=100_000.0)
        self.assertAlmostEqual(self.m._reserve_coverage_ratio(p), 2.0, places=4)


class TestFailedLiqPct(unittest.TestCase):
    def setUp(self):
        self.m = DeFiLendingProtocolBadDebtMonitor()

    def test_no_liquidations(self):
        p = _make_protocol(liquidation_count_30d=0, failed_liquidation_count_30d=0)
        self.assertEqual(self.m._failed_liq_pct(p), 0.0)

    def test_ten_percent_failed(self):
        p = _make_protocol(liquidation_count_30d=100, failed_liquidation_count_30d=10)
        self.assertAlmostEqual(self.m._failed_liq_pct(p), 10.0, places=4)

    def test_all_failed(self):
        p = _make_protocol(liquidation_count_30d=50, failed_liquidation_count_30d=50)
        self.assertAlmostEqual(self.m._failed_liq_pct(p), 100.0, places=4)

    def test_zero_failed(self):
        p = _make_protocol(liquidation_count_30d=100, failed_liquidation_count_30d=0)
        self.assertEqual(self.m._failed_liq_pct(p), 0.0)

    def test_five_percent_failed(self):
        p = _make_protocol(liquidation_count_30d=20, failed_liquidation_count_30d=1)
        self.assertAlmostEqual(self.m._failed_liq_pct(p), 5.0, places=4)


class TestContagionRiskScore(unittest.TestCase):
    def setUp(self):
        self.m = DeFiLendingProtocolBadDebtMonitor()

    def test_zero_risk(self):
        p = _make_protocol(bad_debt_trend_pct_30d=0.0, largest_underwater_position_usd=0.0)
        score = self.m._contagion_risk_score(0.0, 0.0, p)
        self.assertEqual(score, 0.0)

    def test_max_risk(self):
        p = _make_protocol(
            bad_debt_trend_pct_30d=100.0,
            largest_underwater_position_usd=1_000_000.0,
            total_borrowed_usd=1_000_000.0,
        )
        score = self.m._contagion_risk_score(2.0, 100.0, p)
        self.assertEqual(score, 100.0)

    def test_score_bounded_0_100(self):
        p = _make_protocol(bad_debt_trend_pct_30d=500.0, largest_underwater_position_usd=10_000_000.0)
        score = self.m._contagion_risk_score(100.0, 100.0, p)
        self.assertLessEqual(score, 100.0)
        self.assertGreaterEqual(score, 0.0)

    def test_negative_trend_no_contribution(self):
        p = _make_protocol(bad_debt_trend_pct_30d=-30.0, largest_underwater_position_usd=0.0)
        score = self.m._contagion_risk_score(0.0, 0.0, p)
        self.assertEqual(score, 0.0)

    def test_moderate_risk(self):
        p = _make_protocol(
            bad_debt_trend_pct_30d=25.0,
            largest_underwater_position_usd=50_000.0,
            total_borrowed_usd=1_000_000.0,
        )
        score = self.m._contagion_risk_score(0.5, 10.0, p)
        self.assertGreater(score, 0.0)
        self.assertLess(score, 100.0)

    def test_high_bad_debt_ratio(self):
        p = _make_protocol(bad_debt_trend_pct_30d=0.0, largest_underwater_position_usd=0.0)
        score = self.m._contagion_risk_score(2.0, 0.0, p)
        self.assertEqual(score, 25.0)  # only ratio component at full: 2%/2%*25 = 25


class TestSolvencyScore(unittest.TestCase):
    def setUp(self):
        self.m = DeFiLendingProtocolBadDebtMonitor()

    def test_perfect_solvency(self):
        score = self.m._solvency_score(0.0, 9999.0, 0.0)
        self.assertEqual(score, 100.0)

    def test_zero_solvency(self):
        # Max deductions: 50 (bad_debt) + 30 (reserve) + 20 (failed) = 100
        score = self.m._solvency_score(2.0, 0.0, 100.0)
        self.assertEqual(score, 0.0)

    def test_high_bad_debt_ratio(self):
        score = self.m._solvency_score(2.0, 10.0, 0.0)
        self.assertEqual(score, 50.0)  # 100 - 50 (bad_debt deduction at 2%)

    def test_low_reserve_deduction(self):
        score = self.m._solvency_score(0.0, 1.0, 0.0)
        # reserve_deduct = (2 - 1) / 2 * 30 = 15
        self.assertAlmostEqual(score, 85.0, places=2)

    def test_score_bounded_0_100(self):
        for ratio in [0, 0.5, 1, 2, 5, 10]:
            for cov in [0, 0.5, 1, 2, 5]:
                s = self.m._solvency_score(ratio, cov, 50.0)
                self.assertLessEqual(s, 100.0)
                self.assertGreaterEqual(s, 0.0)

    def test_failed_liq_deduction(self):
        score = self.m._solvency_score(0.0, 9999.0, 100.0)
        self.assertAlmostEqual(score, 80.0, places=2)  # 100 - 20


class TestHealthLabel(unittest.TestCase):
    def setUp(self):
        self.m = DeFiLendingProtocolBadDebtMonitor()

    def test_pristine(self):
        label = self.m._health_label(0.001, 15.0)
        self.assertEqual(label, "PRISTINE")

    def test_healthy(self):
        label = self.m._health_label(0.05, 5.0)
        self.assertEqual(label, "HEALTHY")

    def test_watchlist(self):
        label = self.m._health_label(0.2, 5.0)
        self.assertEqual(label, "WATCHLIST")

    def test_stressed_by_ratio(self):
        label = self.m._health_label(0.6, 5.0)
        self.assertEqual(label, "STRESSED")

    def test_stressed_by_coverage(self):
        label = self.m._health_label(0.2, 1.5)
        self.assertEqual(label, "STRESSED")

    def test_insolvent_by_ratio(self):
        label = self.m._health_label(2.5, 5.0)
        self.assertEqual(label, "INSOLVENT")

    def test_insolvent_by_coverage(self):
        label = self.m._health_label(0.3, 0.5)
        self.assertEqual(label, "INSOLVENT")

    def test_insolvent_priority_over_stressed(self):
        # Both conditions true — INSOLVENT wins
        label = self.m._health_label(3.0, 0.5)
        self.assertEqual(label, "INSOLVENT")

    def test_pristine_boundary_ratio(self):
        # 0.01% = boundary: exactly PRISTINE threshold
        label = self.m._health_label(0.009, 12.0)
        self.assertEqual(label, "PRISTINE")

    def test_healthy_not_pristine_low_coverage(self):
        # bad_debt_ratio < 0.01% but coverage < 10 → HEALTHY
        label = self.m._health_label(0.005, 8.0)
        self.assertEqual(label, "HEALTHY")


class TestFlags(unittest.TestCase):
    def setUp(self):
        self.m = DeFiLendingProtocolBadDebtMonitor()

    def test_bad_debt_accelerating(self):
        p = _make_protocol(bad_debt_trend_pct_30d=60.0, bad_debt_usd=1000.0, reserve_fund_usd=10_000.0)
        flags = self.m._compute_flags(p, 0.1, 10.0, 0.0)
        self.assertIn("BAD_DEBT_ACCELERATING", flags)

    def test_no_bad_debt_accelerating_below_threshold(self):
        p = _make_protocol(bad_debt_trend_pct_30d=30.0)
        flags = self.m._compute_flags(p, 0.1, 10.0, 0.0)
        self.assertNotIn("BAD_DEBT_ACCELERATING", flags)

    def test_reserve_depleted(self):
        p = _make_protocol(bad_debt_usd=10_000.0, reserve_fund_usd=10_000.0)
        flags = self.m._compute_flags(p, 1.0, 1.0, 0.0)
        self.assertIn("RESERVE_DEPLETED", flags)

    def test_no_reserve_depleted_when_no_bad_debt(self):
        p = _make_protocol(bad_debt_usd=0.0, reserve_fund_usd=10_000.0)
        flags = self.m._compute_flags(p, 0.0, 9999.0, 0.0)
        self.assertNotIn("RESERVE_DEPLETED", flags)

    def test_large_underwater_position(self):
        p = _make_protocol(total_borrowed_usd=1_000_000.0, largest_underwater_position_usd=150_000.0)
        flags = self.m._compute_flags(p, 0.1, 5.0, 0.0)
        self.assertIn("LARGE_UNDERWATER_POSITION", flags)

    def test_no_large_position_below_threshold(self):
        p = _make_protocol(total_borrowed_usd=1_000_000.0, largest_underwater_position_usd=50_000.0)
        flags = self.m._compute_flags(p, 0.1, 5.0, 0.0)
        self.assertNotIn("LARGE_UNDERWATER_POSITION", flags)

    def test_failed_liquidations_flag(self):
        p = _make_protocol(liquidation_count_30d=100, failed_liquidation_count_30d=10)
        flags = self.m._compute_flags(p, 0.1, 5.0, 10.0)
        self.assertIn("FAILED_LIQUIDATIONS", flags)

    def test_no_failed_liq_below_threshold(self):
        p = _make_protocol(liquidation_count_30d=100, failed_liquidation_count_30d=4)
        flags = self.m._compute_flags(p, 0.1, 5.0, 4.0)
        self.assertNotIn("FAILED_LIQUIDATIONS", flags)

    def test_token_inflation_risk_flag(self):
        p = _make_protocol(token_inflation_risk=True)
        flags = self.m._compute_flags(p, 0.1, 5.0, 0.0)
        self.assertIn("TOKEN_INFLATION_RISK", flags)

    def test_protocol_covered_flag(self):
        p = _make_protocol(protocol_covers_bad_debt=True, bad_debt_usd=1000.0)
        flags = self.m._compute_flags(p, 0.1, 5.0, 0.0)
        self.assertIn("PROTOCOL_COVERED", flags)

    def test_no_flags_pristine_protocol(self):
        p = _make_protocol(
            bad_debt_trend_pct_30d=5.0,
            bad_debt_usd=100.0,
            reserve_fund_usd=100_000.0,
            largest_underwater_position_usd=0.0,
            liquidation_count_30d=10,
            failed_liquidation_count_30d=0,
            token_inflation_risk=False,
            protocol_covers_bad_debt=False,
        )
        flags = self.m._compute_flags(p, 0.001, 1000.0, 0.0)
        self.assertEqual(flags, [])

    def test_multiple_flags(self):
        p = _make_protocol(
            bad_debt_trend_pct_30d=80.0,
            bad_debt_usd=50_000.0,
            reserve_fund_usd=50_000.0,
            largest_underwater_position_usd=200_000.0,
            total_borrowed_usd=1_000_000.0,
            liquidation_count_30d=100,
            failed_liquidation_count_30d=10,
            token_inflation_risk=True,
            protocol_covers_bad_debt=True,
        )
        flags = self.m._compute_flags(p, 5.0, 1.0, 10.0)
        self.assertIn("BAD_DEBT_ACCELERATING", flags)
        self.assertIn("RESERVE_DEPLETED", flags)
        self.assertIn("LARGE_UNDERWATER_POSITION", flags)
        self.assertIn("FAILED_LIQUIDATIONS", flags)
        self.assertIn("TOKEN_INFLATION_RISK", flags)
        self.assertIn("PROTOCOL_COVERED", flags)


class TestMonitorReturnStructure(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.data_file = Path(self.tmp.name) / "bad_debt_log.json"
        self.m = DeFiLendingProtocolBadDebtMonitor(data_file=self.data_file)

    def tearDown(self):
        self.tmp.cleanup()

    def test_return_keys(self):
        result = self.m.monitor([_make_protocol()])
        self.assertIn("protocols", result)
        self.assertIn("aggregates", result)
        self.assertIn("timestamp", result)
        self.assertIn("config", result)

    def test_empty_protocols(self):
        result = self.m.monitor([])
        self.assertEqual(result["protocols"], [])
        self.assertEqual(result["aggregates"]["insolvent_count"], 0)

    def test_single_protocol(self):
        result = self.m.monitor([_make_protocol(name="Aave")])
        self.assertEqual(len(result["protocols"]), 1)
        self.assertEqual(result["protocols"][0]["name"], "Aave")

    def test_multiple_protocols(self):
        result = self.m.monitor([_make_protocol(name="A"), _make_protocol(name="B")])
        self.assertEqual(len(result["protocols"]), 2)

    def test_protocol_result_keys(self):
        result = self.m.monitor([_make_protocol()])
        p = result["protocols"][0]
        required = [
            "name", "bad_debt_ratio_pct", "reserve_coverage_ratio", "failed_liq_pct",
            "contagion_risk_score", "solvency_score", "health_label", "flags",
        ]
        for key in required:
            self.assertIn(key, p)

    def test_aggregates_keys(self):
        result = self.m.monitor([_make_protocol()])
        agg = result["aggregates"]
        required = [
            "healthiest", "most_stressed", "total_bad_debt_usd",
            "insolvent_count", "total_reserve_usd",
        ]
        for key in required:
            self.assertIn(key, agg)

    def test_timestamp_is_float(self):
        result = self.m.monitor([_make_protocol()])
        self.assertIsInstance(result["timestamp"], float)

    def test_config_passthrough(self):
        cfg = {"test_key": 42}
        result = self.m.monitor([_make_protocol()], config=cfg)
        self.assertEqual(result["config"]["test_key"], 42)


class TestMonitorAggregates(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.data_file = Path(self.tmp.name) / "bad_debt_log.json"
        self.m = DeFiLendingProtocolBadDebtMonitor(data_file=self.data_file)

    def tearDown(self):
        self.tmp.cleanup()

    def test_total_bad_debt(self):
        p1 = _make_protocol(bad_debt_usd=10_000.0)
        p2 = _make_protocol(bad_debt_usd=20_000.0)
        result = self.m.monitor([p1, p2])
        self.assertAlmostEqual(result["aggregates"]["total_bad_debt_usd"], 30_000.0, places=2)

    def test_total_reserve(self):
        p1 = _make_protocol(reserve_fund_usd=50_000.0)
        p2 = _make_protocol(reserve_fund_usd=75_000.0)
        result = self.m.monitor([p1, p2])
        self.assertAlmostEqual(result["aggregates"]["total_reserve_usd"], 125_000.0, places=2)

    def test_insolvent_count(self):
        p1 = _make_protocol(
            name="Insolvent", bad_debt_usd=25_000.0, total_borrowed_usd=1_000_000.0,
            reserve_fund_usd=5_000.0
        )  # bad_debt_ratio=2.5% → INSOLVENT
        p2 = _make_protocol(name="Healthy")
        result = self.m.monitor([p1, p2])
        self.assertEqual(result["aggregates"]["insolvent_count"], 1)

    def test_healthiest_by_solvency(self):
        good = _make_protocol(name="Good")
        bad = _make_protocol(
            name="Bad", bad_debt_usd=20_000.0, total_borrowed_usd=1_000_000.0,
            reserve_fund_usd=500.0
        )
        result = self.m.monitor([good, bad])
        self.assertEqual(result["aggregates"]["healthiest"], "Good")

    def test_most_stressed_by_solvency(self):
        good = _make_protocol(name="Good")
        bad = _make_protocol(
            name="Bad", bad_debt_usd=20_000.0, total_borrowed_usd=1_000_000.0,
            reserve_fund_usd=500.0
        )
        result = self.m.monitor([good, bad])
        self.assertEqual(result["aggregates"]["most_stressed"], "Bad")

    def test_all_insolvent_count(self):
        protos = [
            _make_protocol(name=f"P{i}", bad_debt_usd=30_000.0, total_borrowed_usd=1_000_000.0, reserve_fund_usd=1_000.0)
            for i in range(3)
        ]
        result = self.m.monitor(protos)
        self.assertEqual(result["aggregates"]["insolvent_count"], 3)


class TestHealthLabelsInMonitor(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.m = DeFiLendingProtocolBadDebtMonitor(
            data_file=Path(self.tmp.name) / "log.json"
        )

    def tearDown(self):
        self.tmp.cleanup()

    def test_pristine_label(self):
        p = _make_protocol(
            bad_debt_usd=50.0,        # 0.005% ratio → PRISTINE
            total_borrowed_usd=1_000_000.0,
            reserve_fund_usd=1_000_000.0,  # 20000x coverage
        )
        result = self.m.monitor([p])
        self.assertEqual(result["protocols"][0]["health_label"], "PRISTINE")

    def test_healthy_label(self):
        p = _make_protocol(
            bad_debt_usd=500.0,    # 0.05% ratio
            total_borrowed_usd=1_000_000.0,
            reserve_fund_usd=100_000.0,
        )
        result = self.m.monitor([p])
        self.assertEqual(result["protocols"][0]["health_label"], "HEALTHY")

    def test_watchlist_label(self):
        p = _make_protocol(
            bad_debt_usd=2_000.0,  # 0.2% ratio
            total_borrowed_usd=1_000_000.0,
            reserve_fund_usd=100_000.0,
        )
        result = self.m.monitor([p])
        self.assertEqual(result["protocols"][0]["health_label"], "WATCHLIST")

    def test_stressed_label(self):
        p = _make_protocol(
            bad_debt_usd=6_000.0,  # 0.6% ratio → STRESSED
            total_borrowed_usd=1_000_000.0,
            reserve_fund_usd=50_000.0,
        )
        result = self.m.monitor([p])
        self.assertEqual(result["protocols"][0]["health_label"], "STRESSED")

    def test_insolvent_label(self):
        p = _make_protocol(
            bad_debt_usd=25_000.0,  # 2.5% ratio → INSOLVENT
            total_borrowed_usd=1_000_000.0,
            reserve_fund_usd=10_000.0,
        )
        result = self.m.monitor([p])
        self.assertEqual(result["protocols"][0]["health_label"], "INSOLVENT")


class TestAtomicLogWrite(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.data_file = Path(self.tmp.name) / "bad_debt_log.json"
        self.m = DeFiLendingProtocolBadDebtMonitor(data_file=self.data_file)

    def tearDown(self):
        self.tmp.cleanup()

    def test_log_file_created(self):
        self.m.monitor([_make_protocol()])
        self.assertTrue(self.data_file.exists())

    def test_log_is_list(self):
        self.m.monitor([_make_protocol()])
        with open(self.data_file) as fh:
            log = json.load(fh)
        self.assertIsInstance(log, list)

    def test_log_entry_count(self):
        self.m.monitor([_make_protocol()])
        self.m.monitor([_make_protocol()])
        with open(self.data_file) as fh:
            log = json.load(fh)
        self.assertEqual(len(log), 2)

    def test_log_entry_keys(self):
        self.m.monitor([_make_protocol()])
        with open(self.data_file) as fh:
            log = json.load(fh)
        entry = log[0]
        for key in ["timestamp", "protocol_count", "insolvent_count", "total_bad_debt_usd"]:
            self.assertIn(key, entry)

    def test_ring_buffer_cap_100(self):
        for i in range(105):
            self.m.monitor([_make_protocol(name=f"P{i}")])
        with open(self.data_file) as fh:
            log = json.load(fh)
        self.assertEqual(len(log), 100)

    def test_no_tmp_file_left(self):
        self.m.monitor([_make_protocol()])
        tmp_file = str(self.data_file) + ".tmp"
        self.assertFalse(os.path.exists(tmp_file))

    def test_log_summary_contains_health_label(self):
        self.m.monitor([_make_protocol(name="TestP")])
        with open(self.data_file) as fh:
            log = json.load(fh)
        entry = log[0]
        self.assertIn("summary", entry)
        self.assertEqual(entry["summary"][0]["name"], "TestP")
        self.assertIn("health_label", entry["summary"][0])

    def test_corrupted_log_reset(self):
        # Write invalid JSON to data file
        with open(self.data_file, "w") as fh:
            fh.write("not json {{{")
        self.m.monitor([_make_protocol()])
        with open(self.data_file) as fh:
            log = json.load(fh)
        self.assertEqual(len(log), 1)

    def test_non_list_json_reset(self):
        with open(self.data_file, "w") as fh:
            json.dump({"key": "value"}, fh)
        self.m.monitor([_make_protocol()])
        with open(self.data_file) as fh:
            log = json.load(fh)
        self.assertIsInstance(log, list)


class TestPassthroughFields(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.m = DeFiLendingProtocolBadDebtMonitor(
            data_file=Path(self.tmp.name) / "log.json"
        )

    def tearDown(self):
        self.tmp.cleanup()

    def test_tvl_passthrough(self):
        p = _make_protocol(total_tvl_usd=5_000_000.0)
        result = self.m.monitor([p])
        self.assertAlmostEqual(result["protocols"][0]["total_tvl_usd"], 5_000_000.0)

    def test_avg_collateral_ratio_passthrough(self):
        p = _make_protocol(avg_collateral_ratio_pct=175.0)
        result = self.m.monitor([p])
        self.assertAlmostEqual(result["protocols"][0]["avg_collateral_ratio_pct"], 175.0)

    def test_liquidation_count_passthrough(self):
        p = _make_protocol(liquidation_count_30d=42)
        result = self.m.monitor([p])
        self.assertEqual(result["protocols"][0]["liquidation_count_30d"], 42)

    def test_protocol_covers_bad_debt_passthrough(self):
        p = _make_protocol(protocol_covers_bad_debt=True)
        result = self.m.monitor([p])
        self.assertTrue(result["protocols"][0]["protocol_covers_bad_debt"])

    def test_trend_passthrough(self):
        p = _make_protocol(bad_debt_trend_pct_30d=75.0)
        result = self.m.monitor([p])
        self.assertAlmostEqual(result["protocols"][0]["bad_debt_trend_pct_30d"], 75.0)


class TestEdgeCases(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.m = DeFiLendingProtocolBadDebtMonitor(
            data_file=Path(self.tmp.name) / "log.json"
        )

    def tearDown(self):
        self.tmp.cleanup()

    def test_default_name_missing(self):
        result = self.m.monitor([{"total_borrowed_usd": 1_000_000.0, "bad_debt_usd": 0.0}])
        self.assertEqual(result["protocols"][0]["name"], "unknown")

    def test_missing_fields_use_defaults(self):
        # Minimal protocol with only name
        result = self.m.monitor([{"name": "Minimal"}])
        p = result["protocols"][0]
        self.assertEqual(p["bad_debt_ratio_pct"], 0.0)
        self.assertEqual(p["failed_liq_pct"], 0.0)

    def test_solvency_score_is_float(self):
        result = self.m.monitor([_make_protocol()])
        s = result["protocols"][0]["solvency_score"]
        self.assertIsInstance(s, float)

    def test_contagion_score_is_float(self):
        result = self.m.monitor([_make_protocol()])
        s = result["protocols"][0]["contagion_risk_score"]
        self.assertIsInstance(s, float)

    def test_flags_is_list(self):
        result = self.m.monitor([_make_protocol()])
        self.assertIsInstance(result["protocols"][0]["flags"], list)

    def test_solvency_score_range(self):
        # Various protocols — score must always be 0-100
        protocols = [
            _make_protocol(bad_debt_usd=0.0),
            _make_protocol(bad_debt_usd=5_000.0),
            _make_protocol(bad_debt_usd=25_000.0, reserve_fund_usd=1_000.0),
            _make_protocol(bad_debt_usd=100_000.0, reserve_fund_usd=0.0),
        ]
        result = self.m.monitor(protocols)
        for p in result["protocols"]:
            self.assertGreaterEqual(p["solvency_score"], 0.0)
            self.assertLessEqual(p["solvency_score"], 100.0)

    def test_contagion_score_range(self):
        protocols = [
            _make_protocol(bad_debt_trend_pct_30d=0.0),
            _make_protocol(bad_debt_trend_pct_30d=200.0, bad_debt_usd=50_000.0),
        ]
        result = self.m.monitor(protocols)
        for p in result["protocols"]:
            self.assertGreaterEqual(p["contagion_risk_score"], 0.0)
            self.assertLessEqual(p["contagion_risk_score"], 100.0)

    def test_monitor_no_config(self):
        result = self.m.monitor([_make_protocol()])
        self.assertEqual(result["config"], {})

    def test_reserve_depleted_exact_threshold(self):
        # coverage = 1.5 → exactly at threshold, no RESERVE_DEPLETED flag
        p = _make_protocol(bad_debt_usd=10_000.0, reserve_fund_usd=15_000.0)
        result = self.m.monitor([p])
        # coverage = 15000/10000 = 1.5 — exactly at threshold, should not trigger
        self.assertNotIn("RESERVE_DEPLETED", result["protocols"][0]["flags"])

    def test_large_position_boundary(self):
        # 10% exactly is the threshold
        p = _make_protocol(total_borrowed_usd=1_000_000.0, largest_underwater_position_usd=100_000.0)
        result = self.m.monitor([p])
        # 100000/1000000*100 = 10.0, not > 10.0, so no flag
        self.assertNotIn("LARGE_UNDERWATER_POSITION", result["protocols"][0]["flags"])

    def test_large_position_above_boundary(self):
        p = _make_protocol(total_borrowed_usd=1_000_000.0, largest_underwater_position_usd=100_001.0)
        result = self.m.monitor([p])
        self.assertIn("LARGE_UNDERWATER_POSITION", result["protocols"][0]["flags"])


class TestMultipleCallsLog(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.data_file = Path(self.tmp.name) / "bad_debt_log.json"
        self.m = DeFiLendingProtocolBadDebtMonitor(data_file=self.data_file)

    def tearDown(self):
        self.tmp.cleanup()

    def test_five_calls_five_entries(self):
        for _ in range(5):
            self.m.monitor([_make_protocol()])
        with open(self.data_file) as fh:
            log = json.load(fh)
        self.assertEqual(len(log), 5)

    def test_entries_ordered_by_time(self):
        for i in range(3):
            self.m.monitor([_make_protocol(name=f"P{i}", bad_debt_usd=float(i * 1000))])
        with open(self.data_file) as fh:
            log = json.load(fh)
        # timestamps should be non-decreasing
        for i in range(len(log) - 1):
            self.assertLessEqual(log[i]["timestamp"], log[i + 1]["timestamp"])


if __name__ == "__main__":
    unittest.main()
