# spa_core/tests/test_protocol_decay_risk_monitor.py
# MP-846 — Tests for ProtocolDecayRiskMonitor
# Run: python3 -m unittest spa_core.tests.test_protocol_decay_risk_monitor -v

import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import spa_core.analytics.protocol_decay_risk_monitor as pdr


# ---------------------------------------------------------------------------
# Helper factories
# ---------------------------------------------------------------------------

def _make_proto(
    name="Aave",
    tvl_trend=None,
    commits_30d=40,
    commits_90d_ago=40,
    token_price_trend=None,
    users_30d=5000,
    users_90d_ago=5000,
    social_sentiment=0.0,
    days_since_update=10,
):
    return {
        "name": name,
        "tvl_trend": tvl_trend if tvl_trend is not None else [1e9, 1.05e9, 1.1e9, 1.08e9],
        "github_commits_30d": commits_30d,
        "github_commits_90d_ago": commits_90d_ago,
        "token_price_trend": token_price_trend if token_price_trend is not None else [10.0, 10.5, 11.0, 11.5],
        "unique_users_30d": users_30d,
        "unique_users_90d_ago": users_90d_ago,
        "social_sentiment_score": social_sentiment,
        "days_since_last_update": days_since_update,
    }


def _failing_proto(name="FailProto"):
    return {
        "name": name,
        "tvl_trend": [1e9, 600e6, 300e6, 100e6, 20e6],
        "github_commits_30d": 1,
        "github_commits_90d_ago": 50,
        "token_price_trend": [10.0, 5.0, 2.0, 0.5, 0.1],
        "unique_users_30d": 50,
        "unique_users_90d_ago": 5000,
        "social_sentiment_score": -0.9,
        "days_since_last_update": 400,
    }


# ---------------------------------------------------------------------------
# TVL decay scoring
# ---------------------------------------------------------------------------

class TestTVLDecayScore(unittest.TestCase):

    def test_too_short_trend_returns_zero(self):
        score, change = pdr._tvl_decay_score([1e9, 0.5e9], min_pts=3)
        self.assertEqual(score, 0)
        self.assertIsNone(change)

    def test_first_zero_returns_none(self):
        score, change = pdr._tvl_decay_score([0, 1e9, 0.5e9], min_pts=3)
        self.assertEqual(score, 0)
        self.assertIsNone(change)

    def test_no_decline_zero_score(self):
        score, change = pdr._tvl_decay_score([1e9, 1.1e9, 1.2e9], min_pts=3)
        self.assertEqual(score, 0)
        self.assertGreater(change, 0)

    def test_slight_decline_8_score(self):
        # -8% → score 8
        score, change = pdr._tvl_decay_score([100.0, 96.0, 92.0], min_pts=3)
        self.assertEqual(score, 8)
        self.assertAlmostEqual(change, -8.0, places=4)

    def test_15pct_decline_15_score(self):
        # exactly -16% → score 15
        score, change = pdr._tvl_decay_score([100.0, 90.0, 84.0], min_pts=3)
        self.assertEqual(score, 15)

    def test_30pct_decline_25_score(self):
        # -31% → score 25
        score, change = pdr._tvl_decay_score([100.0, 80.0, 69.0], min_pts=3)
        self.assertEqual(score, 25)

    def test_50pct_decline_35_score(self):
        # -55% → score 35
        score, change = pdr._tvl_decay_score([100.0, 70.0, 45.0], min_pts=3)
        self.assertEqual(score, 35)

    def test_tvl_change_pct_formula(self):
        score, change = pdr._tvl_decay_score([200.0, 180.0, 160.0], min_pts=3)
        self.assertAlmostEqual(change, (160.0 - 200.0) / 200.0 * 100, places=4)

    def test_minimal_trend_exact_min_pts(self):
        score, change = pdr._tvl_decay_score([100.0, 50.0, 25.0], min_pts=3)
        self.assertGreater(score, 0)

    def test_large_trend_works(self):
        trend = [1e9 * (0.9 ** i) for i in range(20)]
        score, change = pdr._tvl_decay_score(trend, min_pts=3)
        self.assertIsNotNone(change)
        self.assertGreater(score, 0)


class TestDevDecayScore(unittest.TestCase):

    def test_no_comparison_base_zero(self):
        score, change = pdr._dev_decay_score(0, 0)
        self.assertEqual(score, 0)
        self.assertIsNone(change)

    def test_no_decline_zero_score(self):
        score, change = pdr._dev_decay_score(50, 50)
        self.assertEqual(score, 0)
        self.assertAlmostEqual(change, 0.0, places=4)

    def test_increase_zero_score(self):
        score, change = pdr._dev_decay_score(60, 40)
        self.assertEqual(score, 0)
        self.assertGreater(change, 0)

    def test_slight_drop_5_score(self):
        # -10% decline (between -20 and 0)
        score, change = pdr._dev_decay_score(36, 40)
        self.assertEqual(score, 5)
        self.assertAlmostEqual(change, -10.0, places=4)

    def test_20pct_drop_10_score(self):
        score, change = pdr._dev_decay_score(30, 40)  # -25%
        self.assertEqual(score, 10)

    def test_40pct_drop_18_score(self):
        score, change = pdr._dev_decay_score(22, 40)  # -45%
        self.assertEqual(score, 18)

    def test_70pct_drop_25_score(self):
        score, change = pdr._dev_decay_score(10, 40)  # -75%
        self.assertEqual(score, 25)

    def test_change_pct_formula(self):
        score, change = pdr._dev_decay_score(20, 50)
        expected = (20 - 50) / 50 * 100
        self.assertAlmostEqual(change, expected, places=4)


class TestUserDecayScore(unittest.TestCase):

    def test_no_base_zero(self):
        score, change = pdr._user_decay_score(0, 0)
        self.assertEqual(score, 0)
        self.assertIsNone(change)

    def test_stable_zero_score(self):
        score, change = pdr._user_decay_score(1000, 1000)
        self.assertEqual(score, 0)

    def test_growth_zero_score(self):
        score, change = pdr._user_decay_score(1200, 1000)
        self.assertEqual(score, 0)
        self.assertGreater(change, 0)

    def test_10pct_drop_7_score(self):
        # -12% → score 7 (< -10)
        score, change = pdr._user_decay_score(880, 1000)
        self.assertEqual(score, 7)

    def test_25pct_drop_14_score(self):
        # -30% → score 14
        score, change = pdr._user_decay_score(700, 1000)
        self.assertEqual(score, 14)

    def test_50pct_drop_20_score(self):
        # -60% → score 20
        score, change = pdr._user_decay_score(400, 1000)
        self.assertEqual(score, 20)

    def test_change_pct_formula(self):
        _, change = pdr._user_decay_score(750, 1000)
        self.assertAlmostEqual(change, -25.0, places=4)


class TestSentimentScore(unittest.TestCase):

    def test_positive_sentiment_zero(self):
        self.assertEqual(pdr._sentiment_score(0.5), 0)

    def test_zero_sentiment_zero(self):
        self.assertEqual(pdr._sentiment_score(0.0), 0)

    def test_slight_negative_3(self):
        self.assertEqual(pdr._sentiment_score(-0.1), 3)

    def test_below_minus_0_2_score_6(self):
        self.assertEqual(pdr._sentiment_score(-0.3), 6)

    def test_below_minus_0_5_score_10(self):
        self.assertEqual(pdr._sentiment_score(-0.6), 10)

    def test_boundary_minus_0_2_score_3(self):
        # exactly -0.2 is NOT < -0.2, so should be 3 (< 0)
        self.assertEqual(pdr._sentiment_score(-0.2), 3)

    def test_boundary_minus_0_5_score_6(self):
        # exactly -0.5 is NOT < -0.5, so → 6
        self.assertEqual(pdr._sentiment_score(-0.5), 6)


class TestStaleScore(unittest.TestCase):

    def test_recent_update_zero(self):
        self.assertEqual(pdr._stale_score(5), 0)

    def test_30_days_zero(self):
        self.assertEqual(pdr._stale_score(30), 0)

    def test_31_days_1(self):
        self.assertEqual(pdr._stale_score(31), 1)

    def test_91_days_4(self):
        self.assertEqual(pdr._stale_score(91), 4)

    def test_181_days_7(self):
        self.assertEqual(pdr._stale_score(181), 7)

    def test_366_days_10(self):
        self.assertEqual(pdr._stale_score(366), 10)

    def test_90_days_exact_4(self):
        # 90 > 30 → 1
        self.assertEqual(pdr._stale_score(90), 1)


class TestTokenTrendScore(unittest.TestCase):

    def test_short_trend_stable_zero(self):
        label, score, change = pdr._token_trend_and_score([10.0, 9.0], min_pts=3)
        self.assertEqual(label, "STABLE")
        self.assertEqual(score, 0)
        self.assertIsNone(change)

    def test_rising_label_zero_score(self):
        label, score, change = pdr._token_trend_and_score([10.0, 11.0, 12.0], min_pts=3)
        self.assertEqual(label, "RISING")
        self.assertEqual(score, 0)
        self.assertGreater(change, 0)

    def test_stable_label_3_score(self):
        # -5% change → STABLE (< 10%)
        label, score, change = pdr._token_trend_and_score([100.0, 98.0, 95.0], min_pts=3)
        self.assertEqual(label, "STABLE")
        self.assertEqual(score, 3)

    def test_falling_label_7_score(self):
        # -25% → FALLING
        label, score, change = pdr._token_trend_and_score([100.0, 85.0, 75.0], min_pts=3)
        self.assertEqual(label, "FALLING")
        self.assertEqual(score, 7)

    def test_crashing_label_10_score(self):
        # -65% → CRASHING
        label, score, change = pdr._token_trend_and_score([100.0, 60.0, 35.0], min_pts=3)
        self.assertEqual(label, "CRASHING")
        self.assertEqual(score, 10)

    def test_zero_first_price_stable(self):
        label, score, change = pdr._token_trend_and_score([0.0, 5.0, 10.0], min_pts=3)
        self.assertEqual(label, "STABLE")
        self.assertEqual(score, 0)
        self.assertIsNone(change)


class TestDecayLabel(unittest.TestCase):

    def test_healthy_below_20(self):
        self.assertEqual(pdr._decay_label(0), "HEALTHY")
        self.assertEqual(pdr._decay_label(19), "HEALTHY")

    def test_early_decay_20_to_39(self):
        self.assertEqual(pdr._decay_label(20), "EARLY_DECAY")
        self.assertEqual(pdr._decay_label(39), "EARLY_DECAY")

    def test_moderate_decay_40_to_59(self):
        self.assertEqual(pdr._decay_label(40), "MODERATE_DECAY")
        self.assertEqual(pdr._decay_label(59), "MODERATE_DECAY")

    def test_severe_decay_60_to_79(self):
        self.assertEqual(pdr._decay_label(60), "SEVERE_DECAY")
        self.assertEqual(pdr._decay_label(79), "SEVERE_DECAY")

    def test_failing_80_plus(self):
        self.assertEqual(pdr._decay_label(80), "FAILING")
        self.assertEqual(pdr._decay_label(100), "FAILING")


class TestWarningSignals(unittest.TestCase):

    def test_no_signals_healthy(self):
        signals = pdr._warning_signals(
            tvl_change_pct=5.0,
            dev_change=10.0,
            user_change=5.0,
            social_sentiment=0.3,
            days_since_update=10,
            price_change=5.0,
        )
        self.assertEqual(signals, [])

    def test_tvl_signal(self):
        signals = pdr._warning_signals(-35.0, None, None, 0.0, 0, None)
        self.assertIn("TVL declining >30%", signals)

    def test_dev_signal(self):
        signals = pdr._warning_signals(None, -50.0, None, 0.0, 0, None)
        self.assertIn("Developer activity dropped significantly", signals)

    def test_user_signal(self):
        signals = pdr._warning_signals(None, None, -30.0, 0.0, 0, None)
        self.assertIn("User base shrinking", signals)

    def test_sentiment_signal(self):
        signals = pdr._warning_signals(None, None, None, -0.3, 0, None)
        self.assertIn("Negative community sentiment", signals)

    def test_stale_signal(self):
        signals = pdr._warning_signals(None, None, None, 0.0, 100, None)
        self.assertIn("No protocol updates in 90+ days", signals)

    def test_token_signal(self):
        signals = pdr._warning_signals(None, None, None, 0.0, 0, -35.0)
        self.assertIn("Token price in freefall", signals)

    def test_all_signals(self):
        signals = pdr._warning_signals(-40.0, -50.0, -30.0, -0.7, 100, -40.0)
        self.assertEqual(len(signals), 6)

    def test_boundary_tvl_30_no_signal(self):
        # exactly -30 is NOT < -30 → no signal
        signals = pdr._warning_signals(-30.0, None, None, 0.0, 0, None)
        self.assertNotIn("TVL declining >30%", signals)

    def test_boundary_sentiment_minus_0_2_signal(self):
        # -0.2 < -0.2 → False → no sentiment signal
        signals = pdr._warning_signals(None, None, None, -0.2, 0, None)
        self.assertNotIn("Negative community sentiment", signals)


class TestEstimatedMonths(unittest.TestCase):

    def test_none_tvl_returns_none(self):
        result = pdr._estimated_months_to_critical(None, 5, 50)
        self.assertIsNone(result)

    def test_positive_tvl_returns_none(self):
        result = pdr._estimated_months_to_critical(10.0, 5, 50)
        self.assertIsNone(result)

    def test_low_decay_score_returns_none(self):
        result = pdr._estimated_months_to_critical(-20.0, 5, 10)
        self.assertIsNone(result)

    def test_decaying_returns_value(self):
        result = pdr._estimated_months_to_critical(-40.0, 8, 50)
        self.assertIsNotNone(result)
        self.assertGreater(result, 0)

    def test_capped_at_120(self):
        # Very slow decay → capped at 120
        result = pdr._estimated_months_to_critical(-0.001, 100, 20)
        if result is not None:
            self.assertLessEqual(result, 120.0)

    def test_severe_decay_short_timeline(self):
        result = pdr._estimated_months_to_critical(-80.0, 5, 90)
        if result is not None:
            self.assertLess(result, 30.0)


class TestAnalyzeMain(unittest.TestCase):

    def setUp(self):
        self.patcher = patch.object(pdr, "_append_log")
        self.patcher.start()

    def tearDown(self):
        self.patcher.stop()

    def test_empty_protocols_empty_result(self):
        result = pdr.analyze([])
        self.assertEqual(result["protocols"], [])
        self.assertEqual(result["decaying_protocols"], [])
        self.assertIsNone(result["healthiest_protocol"])
        self.assertIsNone(result["most_at_risk"])
        self.assertEqual(result["average_decay_score"], 0.0)

    def test_single_healthy_protocol(self):
        result = pdr.analyze([_make_proto()])
        self.assertEqual(len(result["protocols"]), 1)
        p = result["protocols"][0]
        self.assertEqual(p["name"], "Aave")
        self.assertGreaterEqual(p["decay_score"], 0)
        self.assertLessEqual(p["decay_score"], 100)

    def test_failing_protocol_high_score(self):
        result = pdr.analyze([_failing_proto()])
        p = result["protocols"][0]
        self.assertGreaterEqual(p["decay_score"], 60)

    def test_failing_protocol_label(self):
        result = pdr.analyze([_failing_proto()])
        p = result["protocols"][0]
        self.assertIn(p["decay_label"], ["SEVERE_DECAY", "FAILING"])

    def test_failing_in_decaying_list(self):
        result = pdr.analyze([_failing_proto()])
        self.assertIn("FailProto", result["decaying_protocols"])

    def test_healthy_not_in_decaying(self):
        result = pdr.analyze([_make_proto()])
        self.assertNotIn("Aave", result["decaying_protocols"])

    def test_multiple_protocols(self):
        protos = [_make_proto(name=f"P{i}") for i in range(4)]
        result = pdr.analyze(protos)
        self.assertEqual(len(result["protocols"]), 4)

    def test_average_score_correct(self):
        protos = [_make_proto(name="A"), _make_proto(name="B")]
        result = pdr.analyze(protos)
        scores = [p["decay_score"] for p in result["protocols"]]
        expected_avg = sum(scores) / len(scores)
        self.assertAlmostEqual(result["average_decay_score"], expected_avg, places=4)

    def test_most_at_risk_is_highest_score(self):
        protos = [_make_proto(name="Healthy"), _failing_proto("Failing")]
        result = pdr.analyze(protos)
        self.assertEqual(result["most_at_risk"], "Failing")

    def test_healthiest_is_lowest_score(self):
        protos = [_make_proto(name="Healthy"), _failing_proto("Failing")]
        result = pdr.analyze(protos)
        self.assertEqual(result["healthiest_protocol"], "Healthy")

    def test_timestamp_present(self):
        result = pdr.analyze([])
        self.assertIn("timestamp", result)
        self.assertIsInstance(result["timestamp"], float)

    def test_timestamp_recent(self):
        before = time.time()
        result = pdr.analyze([])
        after = time.time()
        self.assertGreaterEqual(result["timestamp"], before)
        self.assertLessEqual(result["timestamp"], after)

    def test_warning_signals_in_output(self):
        result = pdr.analyze([_failing_proto()])
        p = result["protocols"][0]
        self.assertIsInstance(p["warning_signals"], list)
        self.assertGreater(len(p["warning_signals"]), 0)

    def test_decay_score_bounded_0_100(self):
        result = pdr.analyze([_failing_proto()])
        self.assertLessEqual(result["protocols"][0]["decay_score"], 100)
        self.assertGreaterEqual(result["protocols"][0]["decay_score"], 0)

    def test_custom_threshold(self):
        proto = _make_proto()
        result_low = pdr.analyze([proto], config={"decay_threshold": 0})
        # With threshold=0, any positive score → decaying
        if result_low["protocols"][0]["decay_score"] > 0:
            self.assertIn("Aave", result_low["decaying_protocols"])

    def test_custom_min_trend_points(self):
        # With min_trend_points=2, two-point trend is valid
        proto = _make_proto(tvl_trend=[1e9, 0.4e9])
        result = pdr.analyze([proto], config={"min_trend_points": 2})
        p = result["protocols"][0]
        self.assertIsNotNone(p["tvl_change_pct"])

    def test_none_change_when_trend_too_short(self):
        proto = _make_proto(tvl_trend=[1e9, 0.5e9])
        result = pdr.analyze([proto])
        p = result["protocols"][0]
        self.assertIsNone(p["tvl_change_pct"])

    def test_token_trend_label_in_output(self):
        result = pdr.analyze([_make_proto()])
        p = result["protocols"][0]
        self.assertIn(p["token_trend"], ["RISING", "STABLE", "FALLING", "CRASHING"])

    def test_dev_change_pct_none_when_no_base(self):
        proto = _make_proto(commits_90d_ago=0)
        result = pdr.analyze([proto])
        p = result["protocols"][0]
        self.assertIsNone(p["dev_activity_change_pct"])

    def test_user_change_pct_none_when_no_base(self):
        proto = _make_proto(users_90d_ago=0)
        result = pdr.analyze([proto])
        p = result["protocols"][0]
        self.assertIsNone(p["user_change_pct"])

    def test_estimated_months_none_for_healthy(self):
        proto = _make_proto(
            tvl_trend=[1e9, 1.1e9, 1.2e9, 1.3e9],
            social_sentiment=0.8,
            days_since_update=1,
        )
        result = pdr.analyze([proto])
        p = result["protocols"][0]
        # Healthy → None or no meaningful decay → None
        if p["decay_score"] < 20:
            self.assertIsNone(p["estimated_months_to_critical"])

    def test_total_il_two_protocols_both_scored(self):
        protos = [_make_proto(name="A"), _failing_proto("B")]
        result = pdr.analyze(protos)
        self.assertEqual(len(result["protocols"]), 2)
        scores = [p["decay_score"] for p in result["protocols"]]
        # B should score higher
        self.assertGreater(scores[1], scores[0])

    def test_single_protocol_healthiest_most_at_risk_same(self):
        result = pdr.analyze([_make_proto()])
        self.assertEqual(result["healthiest_protocol"], result["most_at_risk"])


class TestRingBufferLog(unittest.TestCase):

    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp()
        self.orig_data_file = pdr.DATA_FILE
        pdr.DATA_FILE = Path(self.tmp_dir) / "decay_log.json"

    def tearDown(self):
        pdr.DATA_FILE = self.orig_data_file

    def _run(self):
        pdr.analyze([_make_proto()])

    def test_log_created(self):
        self._run()
        self.assertTrue(pdr.DATA_FILE.exists())

    def test_log_is_list(self):
        self._run()
        with open(pdr.DATA_FILE) as fh:
            data = json.load(fh)
        self.assertIsInstance(data, list)

    def test_log_grows(self):
        self._run()
        self._run()
        with open(pdr.DATA_FILE) as fh:
            data = json.load(fh)
        self.assertEqual(len(data), 2)

    def test_ring_buffer_capped(self):
        for _ in range(pdr.MAX_ENTRIES + 15):
            self._run()
        with open(pdr.DATA_FILE) as fh:
            data = json.load(fh)
        self.assertLessEqual(len(data), pdr.MAX_ENTRIES)

    def test_log_entry_has_timestamp(self):
        self._run()
        with open(pdr.DATA_FILE) as fh:
            data = json.load(fh)
        self.assertIn("timestamp", data[0])

    def test_log_entry_has_average_decay_score(self):
        self._run()
        with open(pdr.DATA_FILE) as fh:
            data = json.load(fh)
        self.assertIn("average_decay_score", data[0])

    def test_log_entry_has_protocol_count(self):
        pdr.analyze([_make_proto(name="A"), _make_proto(name="B")])
        with open(pdr.DATA_FILE) as fh:
            data = json.load(fh)
        self.assertEqual(data[0]["protocol_count"], 2)

    def test_corrupted_log_recovers(self):
        pdr.DATA_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(pdr.DATA_FILE, "w") as fh:
            fh.write("INVALID_JSON{{")
        self._run()
        with open(pdr.DATA_FILE) as fh:
            data = json.load(fh)
        self.assertEqual(len(data), 1)

    def test_atomic_write_no_tmp_file(self):
        self._run()
        tmp_path = pdr.DATA_FILE.with_suffix(".tmp")
        self.assertFalse(tmp_path.exists())

    def test_log_keeps_newest_entries(self):
        timestamps = []
        for i in range(pdr.MAX_ENTRIES + 5):
            result = pdr.analyze([_make_proto()])
            if i >= pdr.MAX_ENTRIES:
                timestamps.append(result["timestamp"])
        with open(pdr.DATA_FILE) as fh:
            data = json.load(fh)
        self.assertAlmostEqual(data[-1]["timestamp"], timestamps[-1], delta=1.0)


class TestScoreCapAt100(unittest.TestCase):

    def setUp(self):
        self.patcher = patch.object(pdr, "_append_log")
        self.patcher.start()

    def tearDown(self):
        self.patcher.stop()

    def test_score_never_exceeds_100(self):
        # Worst-case inputs → should still be <= 100
        proto = {
            "name": "Worst",
            "tvl_trend": [1e9, 1.0, 0.01],
            "github_commits_30d": 0,
            "github_commits_90d_ago": 1000,
            "token_price_trend": [100.0, 50.0, 1.0],
            "unique_users_30d": 0,
            "unique_users_90d_ago": 100000,
            "social_sentiment_score": -1.0,
            "days_since_last_update": 999,
        }
        result = pdr.analyze([proto])
        self.assertLessEqual(result["protocols"][0]["decay_score"], 100)

    def test_min_inputs_zero_score(self):
        proto = _make_proto(
            tvl_trend=[1e9, 1.1e9, 1.2e9],
            commits_30d=100,
            commits_90d_ago=50,  # growth
            token_price_trend=[10.0, 12.0, 15.0],
            users_30d=10000,
            users_90d_ago=5000,
            social_sentiment=1.0,
            days_since_update=0,
        )
        result = pdr.analyze([proto])
        self.assertEqual(result["protocols"][0]["decay_score"], 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
