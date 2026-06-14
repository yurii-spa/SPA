"""
Tests for MP-1102: DeFiProtocolStakingWithdrawalQueueAnalyzer
Run with: python3 -m unittest spa_core/tests/test_defi_protocol_staking_withdrawal_queue_analyzer.py
Target: ≥ 110 tests, all green.
"""

import json
import os
import sys
import tempfile
import unittest

# Ensure project root on path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from spa_core.analytics.defi_protocol_staking_withdrawal_queue_analyzer import (
    DeFiProtocolStakingWithdrawalQueueAnalyzer,
    _clamp,
    _epochs_per_day,
    _compute_estimated_wait_days,
    _compute_queue_depth_ratio,
    _withdrawal_label,
    _compute_withdrawal_risk_score,
    _wait_vs_sell_decision,
    _atomic_write,
    _append_log,
    ETH_PER_VALIDATOR,
    SECONDS_PER_DAY,
    DEFAULT_CHURN_LIMIT,
    DEFAULT_SECONDS_PER_EPOCH,
    LOG_CAP,
)


def _make_analyzer():
    return DeFiProtocolStakingWithdrawalQueueAnalyzer()


def _base_data(**overrides):
    d = {
        "validators_in_exit_queue": 1000,
        "churn_limit_per_epoch": 8,
        "seconds_per_epoch": 384,
        "total_staked_eth": 32_000_000.0,  # 1M validators
        "my_stake_eth": 100.0,
        "current_eth_price_usd": 3000.0,
        "lst_discount_pct": 0.2,
        "protocol_name": "Lido",
    }
    d.update(overrides)
    return d


class TestConstants(unittest.TestCase):
    def test_eth_per_validator(self):
        self.assertEqual(ETH_PER_VALIDATOR, 32.0)

    def test_seconds_per_day(self):
        self.assertEqual(SECONDS_PER_DAY, 86_400)

    def test_default_churn_limit(self):
        self.assertEqual(DEFAULT_CHURN_LIMIT, 8)

    def test_default_seconds_per_epoch(self):
        self.assertEqual(DEFAULT_SECONDS_PER_EPOCH, 384)

    def test_log_cap(self):
        self.assertEqual(LOG_CAP, 100)


class TestClamp(unittest.TestCase):
    def test_clamp_within(self):
        self.assertEqual(_clamp(50.0), 50.0)

    def test_clamp_below(self):
        self.assertEqual(_clamp(-5.0), 0.0)

    def test_clamp_above(self):
        self.assertEqual(_clamp(200.0), 100.0)

    def test_clamp_at_lo(self):
        self.assertEqual(_clamp(0.0), 0.0)

    def test_clamp_at_hi(self):
        self.assertEqual(_clamp(100.0), 100.0)

    def test_clamp_custom_bounds(self):
        self.assertEqual(_clamp(5.0, 0.0, 10.0), 5.0)

    def test_clamp_custom_below(self):
        self.assertEqual(_clamp(-1.0, 0.0, 10.0), 0.0)

    def test_clamp_custom_above(self):
        self.assertEqual(_clamp(15.0, 0.0, 10.0), 10.0)


class TestEpochsPerDay(unittest.TestCase):
    def test_mainnet_epoch(self):
        # 86400 / 384 = 225
        self.assertAlmostEqual(_epochs_per_day(384), 225.0, places=5)

    def test_faster_epoch(self):
        # 86400 / 100 = 864
        self.assertAlmostEqual(_epochs_per_day(100), 864.0, places=5)

    def test_slow_epoch(self):
        # 86400 / 1000 = 86.4
        self.assertAlmostEqual(_epochs_per_day(1000), 86.4, places=5)

    def test_zero_epoch_raises(self):
        with self.assertRaises(ValueError):
            _epochs_per_day(0)

    def test_negative_epoch_raises(self):
        with self.assertRaises(ValueError):
            _epochs_per_day(-1)


class TestEstimatedWaitDays(unittest.TestCase):
    def test_empty_queue_returns_zero(self):
        self.assertEqual(_compute_estimated_wait_days(0, 8, 384), 0.0)

    def test_negative_queue_returns_zero(self):
        self.assertEqual(_compute_estimated_wait_days(-100, 8, 384), 0.0)

    def test_zero_churn_raises(self):
        with self.assertRaises(ValueError):
            _compute_estimated_wait_days(1000, 0, 384)

    def test_basic_calculation(self):
        # 1 validator, churn=8, epoch=384 s
        # exit_epochs = 1/8 = 0.125
        # epd = 86400/384 = 225
        # days = 0.125/225 ≈ 0.000556
        result = _compute_estimated_wait_days(1, 8, 384)
        self.assertAlmostEqual(result, 1 / 8 / 225, places=6)

    def test_large_queue(self):
        # 1000 validators, churn=8, epoch=384 => ~4.44 days
        result = _compute_estimated_wait_days(1000, 8, 384)
        self.assertAlmostEqual(result, 1000 / 8 / 225, places=4)

    def test_high_churn_reduces_wait(self):
        r_low = _compute_estimated_wait_days(1000, 4, 384)
        r_high = _compute_estimated_wait_days(1000, 16, 384)
        self.assertGreater(r_low, r_high)

    def test_shorter_epoch_increases_epd_reduces_wait(self):
        r_long = _compute_estimated_wait_days(1000, 8, 768)
        r_short = _compute_estimated_wait_days(1000, 8, 192)
        self.assertGreater(r_long, r_short)

    def test_zero_seconds_per_epoch_raises(self):
        with self.assertRaises(ValueError):
            _compute_estimated_wait_days(100, 8, 0)

    def test_exact_one_day(self):
        # 1 day = 225 epochs; queue=churn*225=225*8=1800 validators
        result = _compute_estimated_wait_days(1800, 8, 384)
        self.assertAlmostEqual(result, 1.0, places=5)

    def test_exact_seven_days(self):
        # 7 days = 7*225=1575 epochs; 1575*8=12600 validators
        result = _compute_estimated_wait_days(12600, 8, 384)
        self.assertAlmostEqual(result, 7.0, places=5)

    def test_exact_thirty_days(self):
        # 30*225=6750 epochs; 6750*8=54000 validators
        result = _compute_estimated_wait_days(54000, 8, 384)
        self.assertAlmostEqual(result, 30.0, places=5)


class TestQueueDepthRatio(unittest.TestCase):
    def test_zero_staked_eth(self):
        self.assertEqual(_compute_queue_depth_ratio(1000, 0.0), 0.0)

    def test_negative_staked_eth(self):
        self.assertEqual(_compute_queue_depth_ratio(1000, -100.0), 0.0)

    def test_zero_queue(self):
        self.assertEqual(_compute_queue_depth_ratio(0, 1_000_000.0), 0.0)

    def test_basic_ratio(self):
        # 1000 queued / (1_000_000 / 32) = 1000 / 31250 ≈ 0.032
        result = _compute_queue_depth_ratio(1000, 1_000_000.0)
        self.assertAlmostEqual(result, 1000 / (1_000_000 / 32), places=6)

    def test_cap_at_one(self):
        # More validators queued than total → cap at 1.0
        result = _compute_queue_depth_ratio(1_000_000, 32_000.0)
        self.assertEqual(result, 1.0)

    def test_proportional(self):
        r1 = _compute_queue_depth_ratio(1000, 32_000_000.0)
        r2 = _compute_queue_depth_ratio(2000, 32_000_000.0)
        self.assertAlmostEqual(r2, 2 * r1, places=6)

    def test_exact_ratio(self):
        # 320 validators in queue, 32*10000 eth => 10000 total validators
        result = _compute_queue_depth_ratio(320, 32.0 * 10000)
        self.assertAlmostEqual(result, 0.032, places=6)


class TestWithdrawalLabel(unittest.TestCase):
    def test_no_queue(self):
        self.assertEqual(_withdrawal_label(0.0), "NO_QUEUE")

    def test_negative_zero_is_no_queue(self):
        self.assertEqual(_withdrawal_label(-0.0), "NO_QUEUE")

    def test_short_wait_just_above_zero(self):
        self.assertEqual(_withdrawal_label(0.001), "SHORT_WAIT")

    def test_short_wait_boundary(self):
        # strictly less than 2
        self.assertEqual(_withdrawal_label(1.999), "SHORT_WAIT")

    def test_exactly_two_days_moderate(self):
        self.assertEqual(_withdrawal_label(2.0), "MODERATE_WAIT")

    def test_moderate_wait_middle(self):
        self.assertEqual(_withdrawal_label(4.5), "MODERATE_WAIT")

    def test_moderate_wait_upper_boundary(self):
        # strictly less than 7
        self.assertEqual(_withdrawal_label(6.999), "MODERATE_WAIT")

    def test_exactly_seven_days_long(self):
        self.assertEqual(_withdrawal_label(7.0), "LONG_WAIT")

    def test_long_wait_middle(self):
        self.assertEqual(_withdrawal_label(15.0), "LONG_WAIT")

    def test_long_wait_upper_boundary(self):
        self.assertEqual(_withdrawal_label(30.0), "LONG_WAIT")

    def test_severe_congestion_just_above_30(self):
        self.assertEqual(_withdrawal_label(30.001), "SEVERE_CONGESTION")

    def test_severe_congestion_large(self):
        self.assertEqual(_withdrawal_label(365.0), "SEVERE_CONGESTION")


class TestWithdrawalRiskScore(unittest.TestCase):
    def test_no_queue_zero_risk(self):
        self.assertEqual(_compute_withdrawal_risk_score(0.0, 0.0), 0)

    def test_zero_depth_ratio(self):
        score = _compute_withdrawal_risk_score(10.0, 0.0)
        expected = min(100, int(10.0 / 45.0 * 100))
        self.assertEqual(score, expected)

    def test_score_increases_with_wait(self):
        s1 = _compute_withdrawal_risk_score(5.0, 0.0)
        s2 = _compute_withdrawal_risk_score(20.0, 0.0)
        self.assertGreater(s2, s1)

    def test_score_increases_with_depth(self):
        s1 = _compute_withdrawal_risk_score(10.0, 0.0)
        s2 = _compute_withdrawal_risk_score(10.0, 0.5)
        self.assertGreaterEqual(s2, s1)

    def test_max_score_is_100(self):
        self.assertEqual(_compute_withdrawal_risk_score(1000.0, 1.0), 100)

    def test_score_is_int(self):
        self.assertIsInstance(_compute_withdrawal_risk_score(10.0, 0.0), int)

    def test_45_days_near_100(self):
        score = _compute_withdrawal_risk_score(45.0, 0.0)
        self.assertGreaterEqual(score, 95)

    def test_depth_bonus_bounded(self):
        # depth_ratio=1.0 adds at most 10 to the score
        s_no_depth = _compute_withdrawal_risk_score(20.0, 0.0)
        s_full_depth = _compute_withdrawal_risk_score(20.0, 1.0)
        self.assertLessEqual(s_full_depth - s_no_depth, 10)

    def test_score_non_negative(self):
        self.assertGreaterEqual(_compute_withdrawal_risk_score(0.0, 0.0), 0)


class TestWaitVsSellDecision(unittest.TestCase):
    def test_zero_days_wait(self):
        self.assertEqual(_wait_vs_sell_decision(0.0, 0.5), "WAIT_FOR_WITHDRAWAL")

    def test_two_days_boundary_wait(self):
        self.assertEqual(_wait_vs_sell_decision(2.0, 0.5), "WAIT_FOR_WITHDRAWAL")

    def test_short_wait_high_discount_still_wait(self):
        # ≤2 days always → WAIT regardless of discount
        self.assertEqual(_wait_vs_sell_decision(1.0, 5.0), "WAIT_FOR_WITHDRAWAL")

    def test_very_long_wait_high_discount_sell(self):
        self.assertEqual(_wait_vs_sell_decision(31.0, 1.0), "SELL_ON_MARKET")

    def test_very_high_discount_sells(self):
        # 2.0% discount → SELL regardless of wait length
        self.assertEqual(_wait_vs_sell_decision(5.0, 2.0), "SELL_ON_MARKET")

    def test_very_long_wait_low_discount_sells(self):
        # >30 days → SELL even if discount is 0
        self.assertEqual(_wait_vs_sell_decision(31.0, 0.0), "SELL_ON_MARKET")

    def test_moderate_wait_low_discount_wait(self):
        self.assertEqual(_wait_vs_sell_decision(5.0, 0.3), "WAIT_FOR_WITHDRAWAL")

    def test_moderate_wait_moderate_discount_borderline(self):
        # 5 days, 0.8% discount → BORDERLINE
        self.assertEqual(_wait_vs_sell_decision(10.0, 0.8), "BORDERLINE")

    def test_borderline_case(self):
        result = _wait_vs_sell_decision(15.0, 1.5)
        # 1.5% discount is < 2% but >1%; 15 days < 30 → BORDERLINE
        self.assertIn(result, ("SELL_ON_MARKET", "BORDERLINE"))

    def test_returns_string(self):
        self.assertIsInstance(_wait_vs_sell_decision(5.0, 0.5), str)

    def test_valid_decision_values(self):
        valid = {"WAIT_FOR_WITHDRAWAL", "SELL_ON_MARKET", "BORDERLINE"}
        for wait in [0.0, 1.0, 2.0, 5.0, 10.0, 20.0, 31.0]:
            for disc in [0.0, 0.3, 0.5, 1.0, 2.0, 3.0]:
                result = _wait_vs_sell_decision(wait, disc)
                self.assertIn(result, valid, f"wait={wait} disc={disc}")


class TestAnalyzerReturnShape(unittest.TestCase):
    def setUp(self):
        self.analyzer = _make_analyzer()
        self.tmp = tempfile.mkdtemp()
        self.log_path = os.path.join(self.tmp, "test_queue_log.json")
        self.cfg = {"write_log": False, "log_path": self.log_path}

    def test_returns_dict(self):
        result = self.analyzer.analyze(_base_data(), self.cfg)
        self.assertIsInstance(result, dict)

    def test_required_keys(self):
        result = self.analyzer.analyze(_base_data(), self.cfg)
        expected_keys = {
            "ts", "protocol_name", "estimated_wait_days",
            "my_position_usd", "queue_depth_ratio", "lst_discount_usd",
            "wait_vs_sell_decision", "withdrawal_risk_score", "withdrawal_label",
        }
        self.assertEqual(set(result.keys()), expected_keys)

    def test_protocol_name_preserved(self):
        result = self.analyzer.analyze(_base_data(protocol_name="Rocket Pool"), self.cfg)
        self.assertEqual(result["protocol_name"], "Rocket Pool")

    def test_ts_present_and_string(self):
        result = self.analyzer.analyze(_base_data(), self.cfg)
        self.assertIsInstance(result["ts"], str)
        self.assertGreater(len(result["ts"]), 0)

    def test_estimated_wait_days_float(self):
        result = self.analyzer.analyze(_base_data(), self.cfg)
        self.assertIsInstance(result["estimated_wait_days"], float)

    def test_withdrawal_risk_score_int(self):
        result = self.analyzer.analyze(_base_data(), self.cfg)
        self.assertIsInstance(result["withdrawal_risk_score"], int)

    def test_withdrawal_label_string(self):
        result = self.analyzer.analyze(_base_data(), self.cfg)
        self.assertIsInstance(result["withdrawal_label"], str)

    def test_wait_vs_sell_decision_string(self):
        result = self.analyzer.analyze(_base_data(), self.cfg)
        self.assertIsInstance(result["wait_vs_sell_decision"], str)

    def test_type_error_non_dict(self):
        with self.assertRaises(TypeError):
            self.analyzer.analyze([1, 2, 3], self.cfg)

    def test_type_error_string(self):
        with self.assertRaises(TypeError):
            self.analyzer.analyze("bad input", self.cfg)


class TestAnalyzerNOQueueScenario(unittest.TestCase):
    def setUp(self):
        self.analyzer = _make_analyzer()
        self.cfg = {"write_log": False}

    def test_no_queue_label(self):
        result = self.analyzer.analyze(_base_data(validators_in_exit_queue=0), self.cfg)
        self.assertEqual(result["withdrawal_label"], "NO_QUEUE")

    def test_no_queue_wait_is_zero(self):
        result = self.analyzer.analyze(_base_data(validators_in_exit_queue=0), self.cfg)
        self.assertEqual(result["estimated_wait_days"], 0.0)

    def test_no_queue_risk_score_zero(self):
        result = self.analyzer.analyze(_base_data(validators_in_exit_queue=0), self.cfg)
        self.assertEqual(result["withdrawal_risk_score"], 0)

    def test_no_queue_decision_is_wait(self):
        result = self.analyzer.analyze(_base_data(validators_in_exit_queue=0), self.cfg)
        self.assertEqual(result["wait_vs_sell_decision"], "WAIT_FOR_WITHDRAWAL")


class TestAnalyzerShortWaitScenario(unittest.TestCase):
    def setUp(self):
        self.analyzer = _make_analyzer()
        self.cfg = {"write_log": False}

    def test_short_wait_label(self):
        # ~0.5 days wait: 900 validators, churn=8, epoch=384 => 900/8/225 ≈ 0.5 days
        result = self.analyzer.analyze(
            _base_data(validators_in_exit_queue=900, churn_limit_per_epoch=8),
            self.cfg,
        )
        self.assertEqual(result["withdrawal_label"], "SHORT_WAIT")

    def test_short_wait_decision(self):
        result = self.analyzer.analyze(
            _base_data(validators_in_exit_queue=900), self.cfg
        )
        self.assertIn(
            result["wait_vs_sell_decision"],
            ("WAIT_FOR_WITHDRAWAL", "BORDERLINE"),
        )

    def test_short_wait_low_risk_score(self):
        result = self.analyzer.analyze(
            _base_data(validators_in_exit_queue=900), self.cfg
        )
        self.assertLess(result["withdrawal_risk_score"], 30)


class TestAnalyzerModerateWaitScenario(unittest.TestCase):
    def setUp(self):
        self.analyzer = _make_analyzer()
        self.cfg = {"write_log": False}

    def _moderate_data(self):
        # ~4.44 days
        return _base_data(validators_in_exit_queue=8000)

    def test_moderate_label(self):
        result = self.analyzer.analyze(self._moderate_data(), self.cfg)
        self.assertEqual(result["withdrawal_label"], "MODERATE_WAIT")

    def test_moderate_wait_days_range(self):
        result = self.analyzer.analyze(self._moderate_data(), self.cfg)
        self.assertGreaterEqual(result["estimated_wait_days"], 2.0)
        self.assertLess(result["estimated_wait_days"], 7.0)

    def test_moderate_risk_score_range(self):
        result = self.analyzer.analyze(self._moderate_data(), self.cfg)
        self.assertGreater(result["withdrawal_risk_score"], 0)
        self.assertLess(result["withdrawal_risk_score"], 60)


class TestAnalyzerLongWaitScenario(unittest.TestCase):
    def setUp(self):
        self.analyzer = _make_analyzer()
        self.cfg = {"write_log": False}

    def _long_data(self):
        # ~10 days: 10*225*8 = 18000 validators
        return _base_data(validators_in_exit_queue=18000)

    def test_long_wait_label(self):
        result = self.analyzer.analyze(self._long_data(), self.cfg)
        self.assertEqual(result["withdrawal_label"], "LONG_WAIT")

    def test_long_wait_days_range(self):
        result = self.analyzer.analyze(self._long_data(), self.cfg)
        self.assertGreaterEqual(result["estimated_wait_days"], 7.0)
        self.assertLessEqual(result["estimated_wait_days"], 30.0)

    def test_long_risk_score_elevated(self):
        result = self.analyzer.analyze(self._long_data(), self.cfg)
        self.assertGreater(result["withdrawal_risk_score"], 15)


class TestAnalyzerSevereCongestionScenario(unittest.TestCase):
    def setUp(self):
        self.analyzer = _make_analyzer()
        self.cfg = {"write_log": False}

    def _severe_data(self):
        # ~90 days: 90*225*8 = 162000 validators
        return _base_data(validators_in_exit_queue=162000, lst_discount_pct=1.5)

    def test_severe_label(self):
        result = self.analyzer.analyze(self._severe_data(), self.cfg)
        self.assertEqual(result["withdrawal_label"], "SEVERE_CONGESTION")

    def test_severe_wait_days_over_30(self):
        result = self.analyzer.analyze(self._severe_data(), self.cfg)
        self.assertGreater(result["estimated_wait_days"], 30.0)

    def test_severe_decision_sell(self):
        result = self.analyzer.analyze(self._severe_data(), self.cfg)
        self.assertEqual(result["wait_vs_sell_decision"], "SELL_ON_MARKET")

    def test_severe_risk_score_high(self):
        result = self.analyzer.analyze(self._severe_data(), self.cfg)
        self.assertGreater(result["withdrawal_risk_score"], 60)


class TestAnalyzerPositionCalcs(unittest.TestCase):
    def setUp(self):
        self.analyzer = _make_analyzer()
        self.cfg = {"write_log": False}

    def test_my_position_usd(self):
        result = self.analyzer.analyze(
            _base_data(my_stake_eth=100.0, current_eth_price_usd=3000.0), self.cfg
        )
        self.assertAlmostEqual(result["my_position_usd"], 300_000.0, places=2)

    def test_my_position_usd_zero_eth(self):
        result = self.analyzer.analyze(
            _base_data(my_stake_eth=0.0, current_eth_price_usd=3000.0), self.cfg
        )
        self.assertEqual(result["my_position_usd"], 0.0)

    def test_my_position_usd_zero_price(self):
        result = self.analyzer.analyze(
            _base_data(my_stake_eth=100.0, current_eth_price_usd=0.0), self.cfg
        )
        self.assertEqual(result["my_position_usd"], 0.0)

    def test_lst_discount_usd(self):
        result = self.analyzer.analyze(
            _base_data(
                my_stake_eth=100.0,
                current_eth_price_usd=3000.0,
                lst_discount_pct=0.5,
            ),
            self.cfg,
        )
        # 300000 * 0.5 / 100 = 1500
        self.assertAlmostEqual(result["lst_discount_usd"], 1500.0, places=2)

    def test_lst_discount_zero(self):
        result = self.analyzer.analyze(
            _base_data(lst_discount_pct=0.0), self.cfg
        )
        self.assertEqual(result["lst_discount_usd"], 0.0)

    def test_queue_depth_ratio_range(self):
        result = self.analyzer.analyze(_base_data(), self.cfg)
        self.assertGreaterEqual(result["queue_depth_ratio"], 0.0)
        self.assertLessEqual(result["queue_depth_ratio"], 1.0)


class TestAnalyzerDefaultInputs(unittest.TestCase):
    def setUp(self):
        self.analyzer = _make_analyzer()
        self.cfg = {"write_log": False}

    def test_defaults_applied(self):
        # Provide only minimal fields; defaults should kick in
        result = self.analyzer.analyze(
            {
                "validators_in_exit_queue": 100,
                "total_staked_eth": 32_000_000.0,
                "my_stake_eth": 32.0,
                "current_eth_price_usd": 2500.0,
                "lst_discount_pct": 0.0,
            },
            self.cfg,
        )
        self.assertIn("estimated_wait_days", result)
        self.assertGreater(result["estimated_wait_days"], 0.0)

    def test_protocol_name_defaults_to_unknown(self):
        result = self.analyzer.analyze(
            {"validators_in_exit_queue": 0, "total_staked_eth": 1e6}, self.cfg
        )
        self.assertEqual(result["protocol_name"], "unknown")


class TestAnalyzerRiskScoreBounds(unittest.TestCase):
    def setUp(self):
        self.analyzer = _make_analyzer()
        self.cfg = {"write_log": False}

    def test_risk_score_min_is_zero(self):
        result = self.analyzer.analyze(_base_data(validators_in_exit_queue=0), self.cfg)
        self.assertGreaterEqual(result["withdrawal_risk_score"], 0)

    def test_risk_score_max_is_100(self):
        result = self.analyzer.analyze(
            _base_data(validators_in_exit_queue=10_000_000), self.cfg
        )
        self.assertLessEqual(result["withdrawal_risk_score"], 100)

    def test_risk_increases_with_queue_size(self):
        r1 = self.analyzer.analyze(
            _base_data(validators_in_exit_queue=1000), self.cfg
        )["withdrawal_risk_score"]
        r2 = self.analyzer.analyze(
            _base_data(validators_in_exit_queue=50000), self.cfg
        )["withdrawal_risk_score"]
        self.assertGreaterEqual(r2, r1)


class TestAnalyzerLabelConsistency(unittest.TestCase):
    def setUp(self):
        self.analyzer = _make_analyzer()
        self.cfg = {"write_log": False}

    def _result(self, queue):
        return self.analyzer.analyze(_base_data(validators_in_exit_queue=queue), self.cfg)

    def test_label_progression(self):
        labels = [
            self._result(0)["withdrawal_label"],
            self._result(100)["withdrawal_label"],
            self._result(4000)["withdrawal_label"],
            self._result(20000)["withdrawal_label"],
            self._result(200000)["withdrawal_label"],
        ]
        expected = [
            "NO_QUEUE",
            "SHORT_WAIT",
            "MODERATE_WAIT",
            "LONG_WAIT",
            "SEVERE_CONGESTION",
        ]
        self.assertEqual(labels, expected)


class TestLogging(unittest.TestCase):
    def setUp(self):
        self.analyzer = _make_analyzer()
        self.tmp = tempfile.mkdtemp()
        self.log_path = os.path.join(self.tmp, "test_queue_log.json")

    def test_log_created_on_write(self):
        self.analyzer.analyze(
            _base_data(), {"write_log": True, "log_path": self.log_path}
        )
        self.assertTrue(os.path.exists(self.log_path))

    def test_log_is_json_list(self):
        self.analyzer.analyze(
            _base_data(), {"write_log": True, "log_path": self.log_path}
        )
        with open(self.log_path) as f:
            data = json.load(f)
        self.assertIsInstance(data, list)

    def test_log_entry_has_required_fields(self):
        self.analyzer.analyze(
            _base_data(), {"write_log": True, "log_path": self.log_path}
        )
        with open(self.log_path) as f:
            entry = json.load(f)[0]
        self.assertIn("ts", entry)
        self.assertIn("protocol_name", entry)
        self.assertIn("estimated_wait_days", entry)
        self.assertIn("withdrawal_label", entry)
        self.assertIn("withdrawal_risk_score", entry)
        self.assertIn("wait_vs_sell_decision", entry)

    def test_log_appends_multiple_entries(self):
        for _ in range(5):
            self.analyzer.analyze(
                _base_data(), {"write_log": True, "log_path": self.log_path}
            )
        with open(self.log_path) as f:
            data = json.load(f)
        self.assertEqual(len(data), 5)

    def test_log_ring_buffer_cap(self):
        for _ in range(LOG_CAP + 20):
            self.analyzer.analyze(
                _base_data(), {"write_log": True, "log_path": self.log_path}
            )
        with open(self.log_path) as f:
            data = json.load(f)
        self.assertEqual(len(data), LOG_CAP)

    def test_no_log_when_write_log_false(self):
        self.analyzer.analyze(
            _base_data(), {"write_log": False, "log_path": self.log_path}
        )
        self.assertFalse(os.path.exists(self.log_path))

    def test_corrupt_log_recovered(self):
        with open(self.log_path, "w") as f:
            f.write("not json{{{")
        # Should not raise — recovers gracefully
        self.analyzer.analyze(
            _base_data(), {"write_log": True, "log_path": self.log_path}
        )
        with open(self.log_path) as f:
            data = json.load(f)
        self.assertEqual(len(data), 1)


class TestAtomicWrite(unittest.TestCase):
    def test_writes_json(self):
        tmp = tempfile.mkdtemp()
        path = os.path.join(tmp, "out.json")
        _atomic_write(path, [{"key": "value"}])
        with open(path) as f:
            data = json.load(f)
        self.assertEqual(data, [{"key": "value"}])

    def test_overwrites_existing(self):
        tmp = tempfile.mkdtemp()
        path = os.path.join(tmp, "out.json")
        _atomic_write(path, [1])
        _atomic_write(path, [2, 3])
        with open(path) as f:
            data = json.load(f)
        self.assertEqual(data, [2, 3])

    def test_creates_directory(self):
        tmp = tempfile.mkdtemp()
        path = os.path.join(tmp, "subdir", "out.json")
        _atomic_write(path, {"a": 1})
        self.assertTrue(os.path.exists(path))


class TestAppendLog(unittest.TestCase):
    def test_basic_append(self):
        tmp = tempfile.mkdtemp()
        path = os.path.join(tmp, "log.json")
        entry = {
            "ts": "2026-01-01T00:00:00+00:00",
            "protocol_name": "Lido",
            "estimated_wait_days": 3.0,
            "withdrawal_label": "MODERATE_WAIT",
            "withdrawal_risk_score": 20,
            "wait_vs_sell_decision": "WAIT_FOR_WITHDRAWAL",
            "my_position_usd": 300000.0,
        }
        _append_log(entry, path)
        with open(path) as f:
            data = json.load(f)
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]["protocol_name"], "Lido")

    def test_ring_buffer_enforced(self):
        tmp = tempfile.mkdtemp()
        path = os.path.join(tmp, "log.json")
        base_entry = {
            "ts": "2026-01-01T00:00:00+00:00",
            "protocol_name": "Test",
            "estimated_wait_days": 1.0,
            "withdrawal_label": "SHORT_WAIT",
            "withdrawal_risk_score": 5,
            "wait_vs_sell_decision": "WAIT_FOR_WITHDRAWAL",
            "my_position_usd": 1000.0,
        }
        for _ in range(LOG_CAP + 15):
            _append_log(base_entry, path)
        with open(path) as f:
            data = json.load(f)
        self.assertEqual(len(data), LOG_CAP)


class TestAnalyzerEdgeCases(unittest.TestCase):
    def setUp(self):
        self.analyzer = _make_analyzer()
        self.cfg = {"write_log": False}

    def test_very_small_stake(self):
        result = self.analyzer.analyze(
            _base_data(my_stake_eth=0.001, current_eth_price_usd=3000.0), self.cfg
        )
        self.assertAlmostEqual(result["my_position_usd"], 3.0, places=4)

    def test_very_large_queue(self):
        result = self.analyzer.analyze(
            _base_data(validators_in_exit_queue=1_000_000), self.cfg
        )
        self.assertEqual(result["withdrawal_label"], "SEVERE_CONGESTION")
        self.assertEqual(result["withdrawal_risk_score"], 100)

    def test_zero_lst_discount(self):
        result = self.analyzer.analyze(_base_data(lst_discount_pct=0.0), self.cfg)
        self.assertEqual(result["lst_discount_usd"], 0.0)

    def test_high_lst_discount(self):
        result = self.analyzer.analyze(
            _base_data(
                validators_in_exit_queue=100000,
                lst_discount_pct=5.0,
                my_stake_eth=100.0,
                current_eth_price_usd=3000.0,
            ),
            self.cfg,
        )
        # 300000 * 5/100 = 15000
        self.assertAlmostEqual(result["lst_discount_usd"], 15000.0, places=2)

    def test_single_validator_queue(self):
        result = self.analyzer.analyze(
            _base_data(validators_in_exit_queue=1), self.cfg
        )
        self.assertGreater(result["estimated_wait_days"], 0)
        self.assertEqual(result["withdrawal_label"], "SHORT_WAIT")

    def test_very_high_churn(self):
        result = self.analyzer.analyze(
            _base_data(
                validators_in_exit_queue=1000,
                churn_limit_per_epoch=1000,
            ),
            self.cfg,
        )
        # 1 epoch to drain → 1/225 days ≈ 0.0044 days → SHORT_WAIT
        self.assertEqual(result["withdrawal_label"], "SHORT_WAIT")

    def test_protocol_name_passed_through(self):
        result = self.analyzer.analyze(
            _base_data(protocol_name="EtherFi"), self.cfg
        )
        self.assertEqual(result["protocol_name"], "EtherFi")

    def test_float_position_precision(self):
        result = self.analyzer.analyze(
            _base_data(my_stake_eth=1.123456789, current_eth_price_usd=2000.0),
            self.cfg,
        )
        self.assertAlmostEqual(result["my_position_usd"], 1.123456789 * 2000.0, places=2)

    def test_decision_valid_values(self):
        valid = {"WAIT_FOR_WITHDRAWAL", "SELL_ON_MARKET", "BORDERLINE"}
        for queue in [0, 100, 8000, 18000, 54000, 200000]:
            for disc in [0.0, 0.5, 1.0, 2.0]:
                result = self.analyzer.analyze(
                    _base_data(validators_in_exit_queue=queue, lst_discount_pct=disc),
                    self.cfg,
                )
                self.assertIn(result["wait_vs_sell_decision"], valid)

    def test_label_valid_values(self):
        valid = {
            "NO_QUEUE", "SHORT_WAIT", "MODERATE_WAIT",
            "LONG_WAIT", "SEVERE_CONGESTION",
        }
        for queue in [0, 50, 1000, 10000, 100000]:
            result = self.analyzer.analyze(
                _base_data(validators_in_exit_queue=queue), self.cfg
            )
            self.assertIn(result["withdrawal_label"], valid)


class TestAnalyzerChurnVariants(unittest.TestCase):
    def setUp(self):
        self.analyzer = _make_analyzer()
        self.cfg = {"write_log": False}

    def test_churn_4_doubles_wait_vs_churn_8(self):
        r8 = self.analyzer.analyze(
            _base_data(validators_in_exit_queue=1000, churn_limit_per_epoch=8),
            self.cfg,
        )["estimated_wait_days"]
        r4 = self.analyzer.analyze(
            _base_data(validators_in_exit_queue=1000, churn_limit_per_epoch=4),
            self.cfg,
        )["estimated_wait_days"]
        self.assertAlmostEqual(r4, 2 * r8, places=5)

    def test_epoch_speed_halved_doubles_wait(self):
        r_fast = self.analyzer.analyze(
            _base_data(
                validators_in_exit_queue=1000,
                churn_limit_per_epoch=8,
                seconds_per_epoch=192,
            ),
            self.cfg,
        )["estimated_wait_days"]
        r_slow = self.analyzer.analyze(
            _base_data(
                validators_in_exit_queue=1000,
                churn_limit_per_epoch=8,
                seconds_per_epoch=384,
            ),
            self.cfg,
        )["estimated_wait_days"]
        self.assertAlmostEqual(r_slow, 2 * r_fast, places=5)


class TestAnalyzerNoLogMode(unittest.TestCase):
    def test_no_side_effects_without_write(self):
        tmp = tempfile.mkdtemp()
        log_path = os.path.join(tmp, "should_not_exist.json")
        analyzer = _make_analyzer()
        result = analyzer.analyze(
            _base_data(), {"write_log": False, "log_path": log_path}
        )
        self.assertFalse(os.path.exists(log_path))
        self.assertIn("withdrawal_label", result)


class TestAnalyzerIntegration(unittest.TestCase):
    """End-to-end integration with several protocols."""

    def setUp(self):
        self.analyzer = _make_analyzer()
        self.tmp = tempfile.mkdtemp()
        self.log_path = os.path.join(self.tmp, "integration_log.json")

    def _run(self, queue, churn=8, disc=0.3, price=3000.0):
        return self.analyzer.analyze(
            _base_data(
                validators_in_exit_queue=queue,
                churn_limit_per_epoch=churn,
                lst_discount_pct=disc,
                current_eth_price_usd=price,
            ),
            {"write_log": True, "log_path": self.log_path},
        )

    def test_integration_no_queue(self):
        r = self._run(0)
        self.assertEqual(r["withdrawal_label"], "NO_QUEUE")
        self.assertEqual(r["wait_vs_sell_decision"], "WAIT_FOR_WITHDRAWAL")
        self.assertEqual(r["withdrawal_risk_score"], 0)

    def test_integration_short_congestion(self):
        r = self._run(450)  # ~0.25 days
        self.assertEqual(r["withdrawal_label"], "SHORT_WAIT")

    def test_integration_moderate_congestion(self):
        r = self._run(8000)  # ~4.44 days
        self.assertEqual(r["withdrawal_label"], "MODERATE_WAIT")

    def test_integration_long_congestion(self):
        r = self._run(18000)  # ~10 days
        self.assertEqual(r["withdrawal_label"], "LONG_WAIT")

    def test_integration_severe_congestion(self):
        r = self._run(200000)  # ~111 days
        self.assertEqual(r["withdrawal_label"], "SEVERE_CONGESTION")
        self.assertEqual(r["wait_vs_sell_decision"], "SELL_ON_MARKET")

    def test_integration_log_grows(self):
        for _ in range(3):
            self._run(1000)
        with open(self.log_path) as f:
            data = json.load(f)
        self.assertEqual(len(data), 3)

    def test_high_price_increases_position_usd(self):
        r_low = self._run(0, price=1000.0)
        r_high = self._run(0, price=5000.0)
        self.assertGreater(r_high["my_position_usd"], r_low["my_position_usd"])

    def test_discount_scales_with_position(self):
        r = self._run(0, disc=1.0)
        expected = r["my_position_usd"] * 1.0 / 100.0
        self.assertAlmostEqual(r["lst_discount_usd"], expected, places=4)


if __name__ == "__main__":
    unittest.main()
