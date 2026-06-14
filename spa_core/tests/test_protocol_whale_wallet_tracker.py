"""
Tests for MP-915: ProtocolWhaleWalletTracker
Run: python3 -m unittest spa_core.tests.test_protocol_whale_wallet_tracker -v
Target: ≥85 tests
"""

import json
import os
import tempfile
import unittest
from pathlib import Path

from spa_core.analytics.protocol_whale_wallet_tracker import (
    ProtocolWhaleWalletTracker,
    MAX_ENTRIES,
)


def make_wallet(
    address="0xABC",
    protocol="AaveV3",
    position_usd=5_000_000.0,
    entry_price_usd=1.0,
    current_price_usd=1.5,
    unrealized_pnl_usd=2_500_000.0,
    days_held=90,
    transaction_count_30d=12,
    last_action="deposit",
    last_action_days_ago=5,
    wallet_label="whale",
):
    return {
        "address": address,
        "protocol": protocol,
        "position_usd": position_usd,
        "entry_price_usd": entry_price_usd,
        "current_price_usd": current_price_usd,
        "unrealized_pnl_usd": unrealized_pnl_usd,
        "days_held": days_held,
        "transaction_count_30d": transaction_count_30d,
        "last_action": last_action,
        "last_action_days_ago": last_action_days_ago,
        "wallet_label": wallet_label,
    }


class TestTrackerInit(unittest.TestCase):
    def test_default_data_file(self):
        t = ProtocolWhaleWalletTracker()
        self.assertEqual(t.data_file, Path("data/whale_tracker_log.json"))

    def test_custom_data_file(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "log.json"
            t = ProtocolWhaleWalletTracker(data_file=p)
            self.assertEqual(t.data_file, p)

    def test_data_file_stored_as_path(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "log.json"
            t = ProtocolWhaleWalletTracker(data_file=str(p))
            self.assertIsInstance(t.data_file, Path)


class TestPnlPct(unittest.TestCase):
    def setUp(self):
        self.t = ProtocolWhaleWalletTracker.__new__(ProtocolWhaleWalletTracker)

    def test_zero_pnl_same_price(self):
        w = make_wallet(entry_price_usd=1.0, current_price_usd=1.0)
        self.assertAlmostEqual(self.t._compute_pnl_pct(w), 0.0)

    def test_positive_pnl_50pct(self):
        w = make_wallet(entry_price_usd=1.0, current_price_usd=1.5)
        self.assertAlmostEqual(self.t._compute_pnl_pct(w), 50.0)

    def test_positive_pnl_100pct(self):
        w = make_wallet(entry_price_usd=1.0, current_price_usd=2.0)
        self.assertAlmostEqual(self.t._compute_pnl_pct(w), 100.0)

    def test_negative_pnl(self):
        w = make_wallet(entry_price_usd=2.0, current_price_usd=1.0)
        self.assertAlmostEqual(self.t._compute_pnl_pct(w), -50.0)

    def test_zero_entry_price_returns_zero(self):
        w = make_wallet(entry_price_usd=0.0, current_price_usd=2.0)
        self.assertAlmostEqual(self.t._compute_pnl_pct(w), 0.0)

    def test_negative_entry_price_returns_zero(self):
        w = make_wallet(entry_price_usd=-1.0, current_price_usd=2.0)
        self.assertAlmostEqual(self.t._compute_pnl_pct(w), 0.0)

    def test_small_gain(self):
        w = make_wallet(entry_price_usd=100.0, current_price_usd=101.0)
        self.assertAlmostEqual(self.t._compute_pnl_pct(w), 1.0)

    def test_result_rounded(self):
        w = make_wallet(entry_price_usd=3.0, current_price_usd=4.0)
        pnl = self.t._compute_pnl_pct(w)
        # 33.3333... rounded to 4 places
        self.assertAlmostEqual(pnl, 33.3333, places=3)

    def test_large_gain(self):
        w = make_wallet(entry_price_usd=1.0, current_price_usd=10.0)
        self.assertAlmostEqual(self.t._compute_pnl_pct(w), 900.0)

    def test_empty_wallet_dict(self):
        pnl = self.t._compute_pnl_pct({})
        self.assertAlmostEqual(pnl, 0.0)


class TestHoldingStrengthScore(unittest.TestCase):
    def setUp(self):
        self.t = ProtocolWhaleWalletTracker.__new__(ProtocolWhaleWalletTracker)

    def test_returns_float(self):
        w = make_wallet()
        score = self.t._compute_holding_strength_score(w)
        self.assertIsInstance(score, float)

    def test_range_0_100(self):
        for pos in [0, 100_000, 1_000_000, 10_000_000, 50_000_000]:
            w = make_wallet(position_usd=pos)
            score = self.t._compute_holding_strength_score(w)
            self.assertGreaterEqual(score, 0.0)
            self.assertLessEqual(score, 100.0)

    def test_large_long_held_position_high_score(self):
        w = make_wallet(
            position_usd=15_000_000,
            days_held=500,
            transaction_count_30d=25,
            last_action_days_ago=1,
        )
        score = self.t._compute_holding_strength_score(w)
        self.assertGreater(score, 70.0)

    def test_small_new_position_low_score(self):
        w = make_wallet(
            position_usd=100,
            days_held=1,
            transaction_count_30d=0,
            last_action_days_ago=29,
        )
        score = self.t._compute_holding_strength_score(w)
        self.assertLess(score, 30.0)

    def test_larger_position_higher_score(self):
        small = make_wallet(position_usd=100_000, days_held=100, transaction_count_30d=10, last_action_days_ago=5)
        large = make_wallet(position_usd=10_000_000, days_held=100, transaction_count_30d=10, last_action_days_ago=5)
        self.assertGreater(
            self.t._compute_holding_strength_score(large),
            self.t._compute_holding_strength_score(small),
        )

    def test_longer_held_higher_score(self):
        new_w = make_wallet(days_held=1, position_usd=1_000_000, transaction_count_30d=5, last_action_days_ago=5)
        old_w = make_wallet(days_held=365, position_usd=1_000_000, transaction_count_30d=5, last_action_days_ago=5)
        self.assertGreater(
            self.t._compute_holding_strength_score(old_w),
            self.t._compute_holding_strength_score(new_w),
        )

    def test_recent_activity_boosts_score(self):
        active = make_wallet(last_action_days_ago=0, transaction_count_30d=30, position_usd=1_000_000, days_held=100)
        inactive = make_wallet(last_action_days_ago=33, transaction_count_30d=0, position_usd=1_000_000, days_held=100)
        self.assertGreater(
            self.t._compute_holding_strength_score(active),
            self.t._compute_holding_strength_score(inactive),
        )

    def test_deterministic(self):
        w = make_wallet()
        s1 = self.t._compute_holding_strength_score(w)
        s2 = self.t._compute_holding_strength_score(w)
        self.assertEqual(s1, s2)

    def test_zero_position_zero_days(self):
        w = make_wallet(position_usd=0.0, days_held=0, transaction_count_30d=0, last_action_days_ago=0)
        score = self.t._compute_holding_strength_score(w)
        self.assertGreaterEqual(score, 0.0)


class TestExitRiskScore(unittest.TestCase):
    def setUp(self):
        self.t = ProtocolWhaleWalletTracker.__new__(ProtocolWhaleWalletTracker)

    def test_returns_float(self):
        w = make_wallet()
        score = self.t._compute_exit_risk_score(w)
        self.assertIsInstance(score, float)

    def test_range_0_100(self):
        w = make_wallet()
        score = self.t._compute_exit_risk_score(w)
        self.assertGreaterEqual(score, 0.0)
        self.assertLessEqual(score, 100.0)

    def test_large_profit_high_exit_risk(self):
        w = make_wallet(
            entry_price_usd=1.0,
            current_price_usd=3.0,  # 200% gain
            last_action="deposit",
            last_action_days_ago=25,
            transaction_count_30d=0,
        )
        score = self.t._compute_exit_risk_score(w)
        self.assertGreater(score, 40.0)

    def test_no_profit_low_inactivity_low_risk(self):
        w = make_wallet(
            entry_price_usd=1.0,
            current_price_usd=1.0,
            last_action="deposit",
            last_action_days_ago=0,
            transaction_count_30d=25,
        )
        score = self.t._compute_exit_risk_score(w)
        self.assertLess(score, 30.0)

    def test_withdraw_action_increases_risk(self):
        deposit_w = make_wallet(last_action="deposit", entry_price_usd=1.0, current_price_usd=1.1, last_action_days_ago=1)
        withdraw_w = make_wallet(last_action="withdraw", entry_price_usd=1.0, current_price_usd=1.1, last_action_days_ago=1)
        self.assertGreater(
            self.t._compute_exit_risk_score(withdraw_w),
            self.t._compute_exit_risk_score(deposit_w),
        )

    def test_claim_action_increases_risk(self):
        deposit_w = make_wallet(last_action="deposit", entry_price_usd=1.0, current_price_usd=1.0, last_action_days_ago=1)
        claim_w = make_wallet(last_action="claim", entry_price_usd=1.0, current_price_usd=1.0, last_action_days_ago=1)
        self.assertGreater(
            self.t._compute_exit_risk_score(claim_w),
            self.t._compute_exit_risk_score(deposit_w),
        )

    def test_high_inactivity_increases_risk(self):
        active = make_wallet(last_action_days_ago=1, transaction_count_30d=20)
        inactive = make_wallet(last_action_days_ago=27, transaction_count_30d=0)
        self.assertGreater(
            self.t._compute_exit_risk_score(inactive),
            self.t._compute_exit_risk_score(active),
        )

    def test_capped_at_100(self):
        w = make_wallet(
            entry_price_usd=1.0,
            current_price_usd=100.0,
            last_action="withdraw",
            last_action_days_ago=30,
            transaction_count_30d=0,
        )
        score = self.t._compute_exit_risk_score(w)
        self.assertLessEqual(score, 100.0)

    def test_deterministic(self):
        w = make_wallet()
        s1 = self.t._compute_exit_risk_score(w)
        s2 = self.t._compute_exit_risk_score(w)
        self.assertEqual(s1, s2)


class TestActivityLabel(unittest.TestCase):
    def setUp(self):
        self.t = ProtocolWhaleWalletTracker.__new__(ProtocolWhaleWalletTracker)

    def test_inactive_after_30_days(self):
        w = make_wallet(last_action_days_ago=31, last_action="deposit")
        self.assertEqual(self.t._get_activity_label(w), "INACTIVE")

    def test_inactive_at_31_days(self):
        w = make_wallet(last_action_days_ago=35)
        self.assertEqual(self.t._get_activity_label(w), "INACTIVE")

    def test_active_within_30_days_deposit(self):
        w = make_wallet(last_action="deposit", last_action_days_ago=5, transaction_count_30d=15)
        self.assertEqual(self.t._get_activity_label(w), "ACCUMULATING")

    def test_deposit_low_tx_holding(self):
        w = make_wallet(last_action="deposit", last_action_days_ago=5, transaction_count_30d=5)
        self.assertEqual(self.t._get_activity_label(w), "HOLDING")

    def test_withdraw_high_tx_reducing(self):
        w = make_wallet(last_action="withdraw", last_action_days_ago=3, transaction_count_30d=10)
        self.assertEqual(self.t._get_activity_label(w), "REDUCING")

    def test_withdraw_low_tx_exiting(self):
        w = make_wallet(last_action="withdraw", last_action_days_ago=3, transaction_count_30d=2)
        self.assertEqual(self.t._get_activity_label(w), "EXITING")

    def test_borrow_high_tx_accumulating(self):
        w = make_wallet(last_action="borrow", last_action_days_ago=2, transaction_count_30d=15)
        self.assertEqual(self.t._get_activity_label(w), "ACCUMULATING")

    def test_borrow_low_tx_holding(self):
        w = make_wallet(last_action="borrow", last_action_days_ago=2, transaction_count_30d=3)
        self.assertEqual(self.t._get_activity_label(w), "HOLDING")

    def test_claim_returns_holding(self):
        w = make_wallet(last_action="claim", last_action_days_ago=2, transaction_count_30d=5)
        self.assertEqual(self.t._get_activity_label(w), "HOLDING")

    def test_unknown_action_holding(self):
        w = make_wallet(last_action="stake", last_action_days_ago=2, transaction_count_30d=5)
        self.assertEqual(self.t._get_activity_label(w), "HOLDING")

    def test_label_is_string(self):
        w = make_wallet()
        label = self.t._get_activity_label(w)
        self.assertIsInstance(label, str)

    def test_valid_labels(self):
        valid = {"ACCUMULATING", "HOLDING", "REDUCING", "EXITING", "INACTIVE"}
        for action in ["deposit", "withdraw", "borrow", "claim"]:
            for tx in [1, 15]:
                w = make_wallet(last_action=action, transaction_count_30d=tx, last_action_days_ago=3)
                self.assertIn(self.t._get_activity_label(w), valid)


class TestFlags(unittest.TestCase):
    def setUp(self):
        self.t = ProtocolWhaleWalletTracker.__new__(ProtocolWhaleWalletTracker)

    def test_no_flags_normal_wallet(self):
        w = make_wallet(
            position_usd=500_000,
            entry_price_usd=1.0,
            current_price_usd=1.1,
            days_held=30,
            last_action_days_ago=5,
            transaction_count_30d=10,
        )
        flags = self.t._compute_flags(w, 10.0)
        self.assertEqual(flags, [])

    def test_large_unrealized_profit_flag(self):
        flags = self.t._compute_flags(make_wallet(), 51.0)
        self.assertIn("LARGE_UNREALIZED_PROFIT", flags)

    def test_no_large_profit_at_50(self):
        flags = self.t._compute_flags(make_wallet(), 50.0)
        self.assertNotIn("LARGE_UNREALIZED_PROFIT", flags)

    def test_inactive_whale_flag(self):
        w = make_wallet(position_usd=2_000_000, last_action_days_ago=31)
        flags = self.t._compute_flags(w, 10.0)
        self.assertIn("INACTIVE_WHALE", flags)

    def test_no_inactive_whale_small_position(self):
        w = make_wallet(position_usd=500_000, last_action_days_ago=31)
        flags = self.t._compute_flags(w, 10.0)
        self.assertNotIn("INACTIVE_WHALE", flags)

    def test_no_inactive_whale_active(self):
        w = make_wallet(position_usd=2_000_000, last_action_days_ago=10)
        flags = self.t._compute_flags(w, 10.0)
        self.assertNotIn("INACTIVE_WHALE", flags)

    def test_recent_entry_flag(self):
        w = make_wallet(days_held=6)
        flags = self.t._compute_flags(w, 0.0)
        self.assertIn("RECENT_ENTRY", flags)

    def test_no_recent_entry_at_7(self):
        w = make_wallet(days_held=7)
        flags = self.t._compute_flags(w, 0.0)
        self.assertNotIn("RECENT_ENTRY", flags)

    def test_high_churn_flag(self):
        w = make_wallet(transaction_count_30d=51)
        flags = self.t._compute_flags(w, 0.0)
        self.assertIn("HIGH_CHURN", flags)

    def test_no_high_churn_at_50(self):
        w = make_wallet(transaction_count_30d=50)
        flags = self.t._compute_flags(w, 0.0)
        self.assertNotIn("HIGH_CHURN", flags)

    def test_multiple_flags(self):
        w = make_wallet(
            position_usd=2_000_000,
            days_held=3,
            last_action_days_ago=32,
            transaction_count_30d=55,
        )
        flags = self.t._compute_flags(w, 80.0)
        self.assertIn("LARGE_UNREALIZED_PROFIT", flags)
        self.assertIn("INACTIVE_WHALE", flags)
        self.assertIn("RECENT_ENTRY", flags)
        self.assertIn("HIGH_CHURN", flags)

    def test_flags_returns_list(self):
        flags = self.t._compute_flags(make_wallet(), 0.0)
        self.assertIsInstance(flags, list)

    def test_inactive_whale_exactly_31_days(self):
        w = make_wallet(position_usd=1_000_001, last_action_days_ago=31)
        flags = self.t._compute_flags(w, 0.0)
        self.assertIn("INACTIVE_WHALE", flags)

    def test_large_profit_exactly_51(self):
        flags = self.t._compute_flags(make_wallet(), 51.0)
        self.assertIn("LARGE_UNREALIZED_PROFIT", flags)


class TestAnalyzeWallet(unittest.TestCase):
    def setUp(self):
        self.t = ProtocolWhaleWalletTracker.__new__(ProtocolWhaleWalletTracker)

    def test_returns_dict(self):
        w = make_wallet()
        result = self.t._analyze_wallet(w)
        self.assertIsInstance(result, dict)

    def test_has_all_required_keys(self):
        w = make_wallet()
        result = self.t._analyze_wallet(w)
        for key in [
            "address", "protocol", "position_usd", "entry_price_usd",
            "current_price_usd", "unrealized_pnl_usd", "days_held",
            "transaction_count_30d", "last_action", "last_action_days_ago",
            "wallet_label", "pnl_pct", "holding_strength_score",
            "exit_risk_score", "activity_label", "flags",
        ]:
            self.assertIn(key, result)

    def test_address_preserved(self):
        w = make_wallet(address="0xDEAD")
        result = self.t._analyze_wallet(w)
        self.assertEqual(result["address"], "0xDEAD")

    def test_protocol_preserved(self):
        w = make_wallet(protocol="Compound")
        result = self.t._analyze_wallet(w)
        self.assertEqual(result["protocol"], "Compound")

    def test_wallet_label_preserved(self):
        w = make_wallet(wallet_label="shark")
        result = self.t._analyze_wallet(w)
        self.assertEqual(result["wallet_label"], "shark")

    def test_pnl_pct_positive(self):
        w = make_wallet(entry_price_usd=1.0, current_price_usd=2.0)
        result = self.t._analyze_wallet(w)
        self.assertAlmostEqual(result["pnl_pct"], 100.0)

    def test_activity_label_valid(self):
        valid = {"ACCUMULATING", "HOLDING", "REDUCING", "EXITING", "INACTIVE"}
        w = make_wallet()
        result = self.t._analyze_wallet(w)
        self.assertIn(result["activity_label"], valid)


class TestTrackEmpty(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.log_file = Path(self.tmp) / "log.json"
        self.tracker = ProtocolWhaleWalletTracker(data_file=self.log_file)

    def test_empty_wallets_returns_dict(self):
        result = self.tracker.track([], {})
        self.assertIsInstance(result, dict)

    def test_empty_wallet_count_zero(self):
        result = self.tracker.track([], {})
        self.assertEqual(result["wallet_count"], 0)

    def test_empty_wallets_list_empty(self):
        result = self.tracker.track([], {})
        self.assertEqual(result["wallets"], [])

    def test_empty_aggregates_none(self):
        result = self.tracker.track([], {})
        self.assertIsNone(result["aggregates"]["largest_position"])
        self.assertIsNone(result["aggregates"]["highest_exit_risk"])

    def test_empty_total_tvl_zero(self):
        result = self.tracker.track([], {})
        self.assertEqual(result["aggregates"]["total_whale_tvl_usd"], 0.0)

    def test_empty_avg_pnl_zero(self):
        result = self.tracker.track([], {})
        self.assertEqual(result["aggregates"]["average_pnl_pct"], 0.0)

    def test_empty_accumulating_count_zero(self):
        result = self.tracker.track([], {})
        self.assertEqual(result["aggregates"]["accumulating_count"], 0)

    def test_empty_has_timestamp(self):
        result = self.tracker.track([], {})
        self.assertIn("timestamp", result)
        self.assertIsInstance(result["timestamp"], float)


class TestTrackAggregates(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.log_file = Path(self.tmp) / "log.json"
        self.tracker = ProtocolWhaleWalletTracker(data_file=self.log_file)

    def test_wallet_count_correct(self):
        ws = [make_wallet(address=f"0x{i}") for i in range(4)]
        result = self.tracker.track(ws, {})
        self.assertEqual(result["wallet_count"], 4)

    def test_total_tvl_sum(self):
        ws = [
            make_wallet(address="0x1", position_usd=1_000_000),
            make_wallet(address="0x2", position_usd=2_000_000),
        ]
        result = self.tracker.track(ws, {})
        self.assertAlmostEqual(result["aggregates"]["total_whale_tvl_usd"], 3_000_000)

    def test_largest_position_identified(self):
        ws = [
            make_wallet(address="0xBig", position_usd=10_000_000),
            make_wallet(address="0xSmall", position_usd=100_000),
        ]
        result = self.tracker.track(ws, {})
        self.assertEqual(result["aggregates"]["largest_position"], "0xBig")

    def test_highest_exit_risk_identified(self):
        ws = [
            make_wallet(address="0xSafe", entry_price_usd=1.0, current_price_usd=1.0,
                        last_action="deposit", last_action_days_ago=1, transaction_count_30d=20),
            make_wallet(address="0xRisky", entry_price_usd=1.0, current_price_usd=3.0,
                        last_action="withdraw", last_action_days_ago=28, transaction_count_30d=0),
        ]
        result = self.tracker.track(ws, {})
        self.assertEqual(result["aggregates"]["highest_exit_risk"], "0xRisky")

    def test_average_pnl_pct(self):
        ws = [
            make_wallet(address="0x1", entry_price_usd=1.0, current_price_usd=2.0),  # 100%
            make_wallet(address="0x2", entry_price_usd=1.0, current_price_usd=1.0),  # 0%
        ]
        result = self.tracker.track(ws, {})
        self.assertAlmostEqual(result["aggregates"]["average_pnl_pct"], 50.0)

    def test_accumulating_count(self):
        ws = [
            make_wallet(address="0x1", last_action="deposit", transaction_count_30d=15, last_action_days_ago=2),
            make_wallet(address="0x2", last_action="deposit", transaction_count_30d=15, last_action_days_ago=2),
            make_wallet(address="0x3", last_action="withdraw", transaction_count_30d=1, last_action_days_ago=2),
        ]
        result = self.tracker.track(ws, {})
        self.assertEqual(result["aggregates"]["accumulating_count"], 2)

    def test_single_wallet_largest_is_itself(self):
        ws = [make_wallet(address="0xOnly")]
        result = self.tracker.track(ws, {})
        self.assertEqual(result["aggregates"]["largest_position"], "0xOnly")

    def test_wallets_list_length(self):
        ws = [make_wallet(address=f"0x{i}") for i in range(5)]
        result = self.tracker.track(ws, {})
        self.assertEqual(len(result["wallets"]), 5)

    def test_result_has_timestamp(self):
        result = self.tracker.track([make_wallet()], {})
        self.assertIn("timestamp", result)

    def test_wallets_contain_pnl_pct(self):
        result = self.tracker.track([make_wallet()], {})
        self.assertIn("pnl_pct", result["wallets"][0])

    def test_wallets_contain_activity_label(self):
        result = self.tracker.track([make_wallet()], {})
        self.assertIn("activity_label", result["wallets"][0])

    def test_wallets_contain_flags(self):
        result = self.tracker.track([make_wallet()], {})
        self.assertIsInstance(result["wallets"][0]["flags"], list)

    def test_config_ignored_gracefully(self):
        result = self.tracker.track([make_wallet()], {"extra": 42})
        self.assertIsInstance(result, dict)


class TestLogRingBuffer(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.log_file = Path(self.tmp) / "log.json"
        self.tracker = ProtocolWhaleWalletTracker(data_file=self.log_file)

    def test_log_created_after_track(self):
        self.tracker.track([make_wallet()], {})
        self.assertTrue(self.log_file.exists())

    def test_log_is_valid_json(self):
        self.tracker.track([make_wallet()], {})
        with open(self.log_file) as f:
            data = json.load(f)
        self.assertIsInstance(data, list)

    def test_log_grows_with_calls(self):
        self.tracker.track([make_wallet()], {})
        self.tracker.track([make_wallet()], {})
        with open(self.log_file) as f:
            data = json.load(f)
        self.assertEqual(len(data), 2)

    def test_log_entry_has_timestamp(self):
        self.tracker.track([make_wallet()], {})
        with open(self.log_file) as f:
            data = json.load(f)
        self.assertIn("timestamp", data[0])

    def test_log_entry_has_aggregates(self):
        self.tracker.track([make_wallet()], {})
        with open(self.log_file) as f:
            data = json.load(f)
        self.assertIn("aggregates", data[0])

    def test_ring_buffer_capped_at_100(self):
        for i in range(110):
            self.tracker.track([make_wallet(address=f"0x{i}")], {})
        with open(self.log_file) as f:
            data = json.load(f)
        self.assertLessEqual(len(data), MAX_ENTRIES)

    def test_ring_buffer_keeps_exactly_100(self):
        for i in range(105):
            self.tracker.track([make_wallet(address=f"0x{i}")], {})
        with open(self.log_file) as f:
            data = json.load(f)
        self.assertEqual(len(data), 100)

    def test_log_persists_across_instances(self):
        self.tracker.track([make_wallet()], {})
        tracker2 = ProtocolWhaleWalletTracker(data_file=self.log_file)
        tracker2.track([make_wallet()], {})
        with open(self.log_file) as f:
            data = json.load(f)
        self.assertEqual(len(data), 2)

    def test_corrupted_log_recovers(self):
        self.log_file.parent.mkdir(parents=True, exist_ok=True)
        with open(self.log_file, "w") as f:
            f.write("{{{{ invalid json")
        self.tracker.track([make_wallet()], {})
        with open(self.log_file) as f:
            data = json.load(f)
        self.assertEqual(len(data), 1)

    def test_log_entry_has_wallet_count(self):
        ws = [make_wallet(address=f"0x{i}") for i in range(3)]
        self.tracker.track(ws, {})
        with open(self.log_file) as f:
            data = json.load(f)
        self.assertEqual(data[0]["wallet_count"], 3)


class TestAtomicWrite(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.log_file = Path(self.tmp) / "log.json"
        self.tracker = ProtocolWhaleWalletTracker(data_file=self.log_file)

    def test_no_tmp_file_left_after_write(self):
        self.tracker.track([make_wallet()], {})
        tmp_path = str(self.log_file) + ".tmp"
        self.assertFalse(os.path.exists(tmp_path))

    def test_log_file_is_valid_after_write(self):
        self.tracker.track([make_wallet()], {})
        with open(self.log_file) as f:
            data = json.load(f)
        self.assertIsInstance(data, list)

    def test_parent_dirs_created_automatically(self):
        deep_path = Path(self.tmp) / "deep" / "nested" / "log.json"
        tracker = ProtocolWhaleWalletTracker(data_file=deep_path)
        tracker.track([make_wallet()], {})
        self.assertTrue(deep_path.exists())


class TestEdgeCases(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.log_file = Path(self.tmp) / "log.json"
        self.tracker = ProtocolWhaleWalletTracker(data_file=self.log_file)

    def test_wallet_with_zero_position(self):
        w = make_wallet(position_usd=0.0)
        result = self.tracker.track([w], {})
        self.assertEqual(result["wallet_count"], 1)

    def test_wallet_with_negative_pnl(self):
        w = make_wallet(entry_price_usd=2.0, current_price_usd=1.0)
        result = self.tracker.track([w], {})
        self.assertLess(result["wallets"][0]["pnl_pct"], 0)

    def test_empty_wallet_dict(self):
        result = self.tracker.track([{}], {})
        self.assertEqual(result["wallet_count"], 1)

    def test_holding_strength_never_negative(self):
        w = make_wallet(position_usd=0, days_held=0, transaction_count_30d=0, last_action_days_ago=100)
        score = ProtocolWhaleWalletTracker.__new__(ProtocolWhaleWalletTracker)._compute_holding_strength_score(w)
        self.assertGreaterEqual(score, 0.0)

    def test_exit_risk_never_negative(self):
        w = make_wallet(entry_price_usd=1.0, current_price_usd=0.5, last_action_days_ago=0, transaction_count_30d=30)
        t = ProtocolWhaleWalletTracker.__new__(ProtocolWhaleWalletTracker)
        score = t._compute_exit_risk_score(w)
        self.assertGreaterEqual(score, 0.0)

    def test_dolphins_tracked(self):
        w = make_wallet(wallet_label="dolphin", position_usd=50_000)
        result = self.tracker.track([w], {})
        self.assertEqual(result["wallets"][0]["wallet_label"], "dolphin")

    def test_sharks_tracked(self):
        w = make_wallet(wallet_label="shark", position_usd=500_000)
        result = self.tracker.track([w], {})
        self.assertEqual(result["wallets"][0]["wallet_label"], "shark")

    def test_many_wallets_aggregates_consistent(self):
        ws = [make_wallet(address=f"0x{i}", position_usd=float(i * 100_000)) for i in range(1, 11)]
        result = self.tracker.track(ws, {})
        self.assertEqual(result["wallet_count"], 10)
        total = sum(i * 100_000 for i in range(1, 11))
        self.assertAlmostEqual(result["aggregates"]["total_whale_tvl_usd"], float(total))


if __name__ == "__main__":
    unittest.main()
