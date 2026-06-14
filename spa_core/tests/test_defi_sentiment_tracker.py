"""
Tests for MP-791: DeFiSentimentTracker
≥65 unittest cases covering signal classification, composite score,
sentiment labels, signal breakdown, log persistence, edge cases.
"""

import json
import os
import tempfile
import time
import unittest

from spa_core.analytics.defi_sentiment_tracker import (
    DeFiSentimentTracker,
    SentimentResult,
    SentimentLabel,
    SignalLabel,
    SignalBreakdown,
    LOG_CAP,
    TVL_BULLISH_THRESHOLD,
    TVL_BEARISH_THRESHOLD,
    NEW_WALLET_BULLISH_RATIO,
    NEW_WALLET_BEARISH_RATIO,
    WD_RATIO_BULLISH,
    WD_RATIO_BEARISH,
    LARGE_EXIT_BULLISH_MAX,
    LARGE_EXIT_BEARISH_MIN,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _all_bullish() -> dict:
    """4/4 bullish signals → score +8."""
    return {
        "protocol": "TestProto",
        "signals": {
            "tvl_change_7d_pct": 10.0,           # bullish (>5%)
            "new_wallet_count_7d": 1500,
            "new_wallet_4w_avg": 1000,            # bullish (1.5x > 1.2)
            "withdraw_to_deposit_ratio": 0.5,     # bullish (<0.8)
            "large_exit_count_7d": 1,             # bullish (≤3)
        },
    }


def _all_bearish() -> dict:
    """4/4 bearish signals → score -8."""
    return {
        "protocol": "TestProto",
        "signals": {
            "tvl_change_7d_pct": -10.0,          # bearish (<-5%)
            "new_wallet_count_7d": 500,
            "new_wallet_4w_avg": 1000,            # bearish (0.5x < 0.8)
            "withdraw_to_deposit_ratio": 1.5,     # bearish (>1.2)
            "large_exit_count_7d": 15,            # bearish (≥10)
        },
    }


def _all_neutral() -> dict:
    """4/4 neutral signals → score 0."""
    return {
        "protocol": "TestProto",
        "signals": {
            "tvl_change_7d_pct": 2.0,            # neutral (between ±5%)
            "new_wallet_count_7d": 1000,
            "new_wallet_4w_avg": 1000,            # neutral (1.0x)
            "withdraw_to_deposit_ratio": 1.0,     # neutral
            "large_exit_count_7d": 6,             # neutral (4-9)
        },
    }


class TestDeFiSentimentTrackerBasic(unittest.TestCase):

    def setUp(self):
        self.tracker = DeFiSentimentTracker()

    # --- Test 1-5: result object ---

    def test_01_result_is_sentiment_result(self):
        r = self.tracker.track(_all_bullish())
        self.assertIsInstance(r, SentimentResult)

    def test_02_timestamp_is_recent(self):
        r = self.tracker.track(_all_bullish())
        self.assertAlmostEqual(r.timestamp, time.time(), delta=5)

    def test_03_protocol_preserved(self):
        data = _all_bullish()
        data["protocol"] = "Morpho"
        r = self.tracker.track(data)
        self.assertEqual(r.protocol, "Morpho")

    def test_04_to_dict_returns_dict(self):
        r = self.tracker.track(_all_bullish())
        self.assertIsInstance(r.to_dict(), dict)

    def test_05_to_dict_json_serialisable(self):
        r = self.tracker.track(_all_bullish())
        s = json.dumps(r.to_dict())
        self.assertIsInstance(s, str)

    # --- Test 6-10: composite score ---

    def test_06_all_bullish_score_plus8(self):
        r = self.tracker.track(_all_bullish())
        self.assertEqual(r.composite_sentiment_score, 8)

    def test_07_all_bearish_score_minus8(self):
        r = self.tracker.track(_all_bearish())
        self.assertEqual(r.composite_sentiment_score, -8)

    def test_08_all_neutral_score_zero(self):
        r = self.tracker.track(_all_neutral())
        self.assertEqual(r.composite_sentiment_score, 0)

    def test_09_mixed_2bullish_2bearish_score_zero(self):
        data = {
            "protocol": "P",
            "signals": {
                "tvl_change_7d_pct": 10.0,        # bullish
                "new_wallet_count_7d": 500,
                "new_wallet_4w_avg": 1000,         # bearish
                "withdraw_to_deposit_ratio": 0.5,  # bullish
                "large_exit_count_7d": 15,         # bearish
            },
        }
        r = self.tracker.track(data)
        self.assertEqual(r.composite_sentiment_score, 0)

    def test_10_score_formula_b2_minus_b2(self):
        # 3 bullish, 1 bearish → 3*2 - 1*2 = 4
        data = {
            "protocol": "P",
            "signals": {
                "tvl_change_7d_pct": 10.0,         # bullish
                "new_wallet_count_7d": 1500,
                "new_wallet_4w_avg": 1000,          # bullish
                "withdraw_to_deposit_ratio": 0.5,   # bullish
                "large_exit_count_7d": 15,          # bearish
            },
        }
        r = self.tracker.track(data)
        self.assertEqual(r.composite_sentiment_score, 4)

    # --- Test 11-15: sentiment label ---

    def test_11_very_bullish_label(self):
        r = self.tracker.track(_all_bullish())
        self.assertEqual(r.sentiment, SentimentLabel.VERY_BULLISH.value)

    def test_12_very_bearish_label(self):
        r = self.tracker.track(_all_bearish())
        self.assertEqual(r.sentiment, SentimentLabel.VERY_BEARISH.value)

    def test_13_neutral_label_all_neutral(self):
        r = self.tracker.track(_all_neutral())
        self.assertEqual(r.sentiment, SentimentLabel.NEUTRAL.value)

    def test_14_bullish_label_score_plus2(self):
        # 2 bullish, 0 bearish, 2 neutral → score = 4 → VERY_BULLISH actually
        # Need exactly score=2 for BULLISH: 1 bullish, 0 bearish, 3 neutral
        data = {
            "protocol": "P",
            "signals": {
                "tvl_change_7d_pct": 10.0,         # bullish
                "new_wallet_count_7d": 1000,
                "new_wallet_4w_avg": 1000,          # neutral
                "withdraw_to_deposit_ratio": 1.0,   # neutral
                "large_exit_count_7d": 6,           # neutral
            },
        }
        r = self.tracker.track(data)
        self.assertEqual(r.composite_sentiment_score, 2)
        self.assertEqual(r.sentiment, SentimentLabel.BULLISH.value)

    def test_15_bearish_label_score_minus2(self):
        data = {
            "protocol": "P",
            "signals": {
                "tvl_change_7d_pct": -10.0,        # bearish
                "new_wallet_count_7d": 1000,
                "new_wallet_4w_avg": 1000,          # neutral
                "withdraw_to_deposit_ratio": 1.0,   # neutral
                "large_exit_count_7d": 6,           # neutral
            },
        }
        r = self.tracker.track(data)
        self.assertEqual(r.composite_sentiment_score, -2)
        self.assertEqual(r.sentiment, SentimentLabel.BEARISH.value)

    # --- Test 16-20: TVL signal ---

    def test_16_tvl_above_threshold_bullish(self):
        data = _all_neutral()
        data["signals"]["tvl_change_7d_pct"] = TVL_BULLISH_THRESHOLD + 0.1
        r = self.tracker.track(data)
        self.assertEqual(r.signal_breakdown["tvl_signal"], SignalLabel.BULLISH.value)

    def test_17_tvl_below_threshold_bearish(self):
        data = _all_neutral()
        data["signals"]["tvl_change_7d_pct"] = TVL_BEARISH_THRESHOLD - 0.1
        r = self.tracker.track(data)
        self.assertEqual(r.signal_breakdown["tvl_signal"], SignalLabel.BEARISH.value)

    def test_18_tvl_at_zero_neutral(self):
        data = _all_neutral()
        data["signals"]["tvl_change_7d_pct"] = 0.0
        r = self.tracker.track(data)
        self.assertEqual(r.signal_breakdown["tvl_signal"], SignalLabel.NEUTRAL.value)

    def test_19_tvl_at_exactly_bullish_threshold_neutral(self):
        # Boundary: >5% is bullish, exactly 5% is neutral
        data = _all_neutral()
        data["signals"]["tvl_change_7d_pct"] = TVL_BULLISH_THRESHOLD
        r = self.tracker.track(data)
        self.assertEqual(r.signal_breakdown["tvl_signal"], SignalLabel.NEUTRAL.value)

    def test_20_tvl_at_exactly_bearish_threshold_neutral(self):
        data = _all_neutral()
        data["signals"]["tvl_change_7d_pct"] = TVL_BEARISH_THRESHOLD
        r = self.tracker.track(data)
        self.assertEqual(r.signal_breakdown["tvl_signal"], SignalLabel.NEUTRAL.value)

    # --- Test 21-25: new wallet signal ---

    def test_21_new_wallet_above_120pct_bullish(self):
        data = _all_neutral()
        data["signals"]["new_wallet_count_7d"] = 1300
        data["signals"]["new_wallet_4w_avg"] = 1000
        r = self.tracker.track(data)
        self.assertEqual(r.signal_breakdown["new_wallet_signal"], SignalLabel.BULLISH.value)

    def test_22_new_wallet_below_80pct_bearish(self):
        data = _all_neutral()
        data["signals"]["new_wallet_count_7d"] = 700
        data["signals"]["new_wallet_4w_avg"] = 1000
        r = self.tracker.track(data)
        self.assertEqual(r.signal_breakdown["new_wallet_signal"], SignalLabel.BEARISH.value)

    def test_23_new_wallet_at_100pct_neutral(self):
        data = _all_neutral()
        data["signals"]["new_wallet_count_7d"] = 1000
        data["signals"]["new_wallet_4w_avg"] = 1000
        r = self.tracker.track(data)
        self.assertEqual(r.signal_breakdown["new_wallet_signal"], SignalLabel.NEUTRAL.value)

    def test_24_new_wallet_no_avg_neutral(self):
        data = _all_neutral()
        data["signals"].pop("new_wallet_4w_avg", None)
        r = self.tracker.track(data)
        self.assertEqual(r.signal_breakdown["new_wallet_signal"], SignalLabel.NEUTRAL.value)

    def test_25_new_wallet_zero_avg_neutral(self):
        data = _all_neutral()
        data["signals"]["new_wallet_count_7d"] = 1000
        data["signals"]["new_wallet_4w_avg"] = 0
        r = self.tracker.track(data)
        self.assertEqual(r.signal_breakdown["new_wallet_signal"], SignalLabel.NEUTRAL.value)

    # --- Test 26-30: withdraw/deposit ratio ---

    def test_26_wd_ratio_below_threshold_bullish(self):
        data = _all_neutral()
        data["signals"]["withdraw_to_deposit_ratio"] = WD_RATIO_BULLISH - 0.1
        r = self.tracker.track(data)
        self.assertEqual(r.signal_breakdown["wd_ratio_signal"], SignalLabel.BULLISH.value)

    def test_27_wd_ratio_above_threshold_bearish(self):
        data = _all_neutral()
        data["signals"]["withdraw_to_deposit_ratio"] = WD_RATIO_BEARISH + 0.1
        r = self.tracker.track(data)
        self.assertEqual(r.signal_breakdown["wd_ratio_signal"], SignalLabel.BEARISH.value)

    def test_28_wd_ratio_exactly_at_bullish_neutral(self):
        data = _all_neutral()
        data["signals"]["withdraw_to_deposit_ratio"] = WD_RATIO_BULLISH  # 0.8 not < 0.8
        r = self.tracker.track(data)
        self.assertEqual(r.signal_breakdown["wd_ratio_signal"], SignalLabel.NEUTRAL.value)

    def test_29_wd_ratio_exactly_at_bearish_neutral(self):
        data = _all_neutral()
        data["signals"]["withdraw_to_deposit_ratio"] = WD_RATIO_BEARISH  # 1.2 not > 1.2
        r = self.tracker.track(data)
        self.assertEqual(r.signal_breakdown["wd_ratio_signal"], SignalLabel.NEUTRAL.value)

    def test_30_wd_ratio_at_1_neutral(self):
        data = _all_neutral()
        data["signals"]["withdraw_to_deposit_ratio"] = 1.0
        r = self.tracker.track(data)
        self.assertEqual(r.signal_breakdown["wd_ratio_signal"], SignalLabel.NEUTRAL.value)

    # --- Test 31-35: large exits ---

    def test_31_large_exit_zero_bullish(self):
        data = _all_neutral()
        data["signals"]["large_exit_count_7d"] = 0
        r = self.tracker.track(data)
        self.assertEqual(r.signal_breakdown["large_exit_signal"], SignalLabel.BULLISH.value)

    def test_32_large_exit_at_max_bullish(self):
        data = _all_neutral()
        data["signals"]["large_exit_count_7d"] = LARGE_EXIT_BULLISH_MAX
        r = self.tracker.track(data)
        self.assertEqual(r.signal_breakdown["large_exit_signal"], SignalLabel.BULLISH.value)

    def test_33_large_exit_above_bearish_min(self):
        data = _all_neutral()
        data["signals"]["large_exit_count_7d"] = LARGE_EXIT_BEARISH_MIN
        r = self.tracker.track(data)
        self.assertEqual(r.signal_breakdown["large_exit_signal"], SignalLabel.BEARISH.value)

    def test_34_large_exit_middle_range_neutral(self):
        data = _all_neutral()
        data["signals"]["large_exit_count_7d"] = (LARGE_EXIT_BULLISH_MAX + LARGE_EXIT_BEARISH_MIN) // 2
        r = self.tracker.track(data)
        self.assertEqual(r.signal_breakdown["large_exit_signal"], SignalLabel.NEUTRAL.value)

    def test_35_large_exit_very_high_bearish(self):
        data = _all_neutral()
        data["signals"]["large_exit_count_7d"] = 50
        r = self.tracker.track(data)
        self.assertEqual(r.signal_breakdown["large_exit_signal"], SignalLabel.BEARISH.value)

    # --- Test 36-40: counts ---

    def test_36_all_bullish_counts(self):
        r = self.tracker.track(_all_bullish())
        self.assertEqual(r.bullish_count, 4)
        self.assertEqual(r.bearish_count, 0)
        self.assertEqual(r.neutral_count, 0)

    def test_37_all_bearish_counts(self):
        r = self.tracker.track(_all_bearish())
        self.assertEqual(r.bullish_count, 0)
        self.assertEqual(r.bearish_count, 4)
        self.assertEqual(r.neutral_count, 0)

    def test_38_all_neutral_counts(self):
        r = self.tracker.track(_all_neutral())
        self.assertEqual(r.bullish_count, 0)
        self.assertEqual(r.bearish_count, 0)
        self.assertEqual(r.neutral_count, 4)

    def test_39_counts_sum_to_4(self):
        for data in (_all_bullish(), _all_bearish(), _all_neutral()):
            r = self.tracker.track(data)
            total = r.bullish_count + r.bearish_count + r.neutral_count
            self.assertEqual(total, 4)

    def test_40_mixed_counts(self):
        # 2 bullish (tvl + wd), 1 bearish (exits), 1 neutral (wallets)
        data = {
            "protocol": "P",
            "signals": {
                "tvl_change_7d_pct": 10.0,
                "new_wallet_count_7d": 1000,
                "new_wallet_4w_avg": 1000,
                "withdraw_to_deposit_ratio": 0.5,
                "large_exit_count_7d": 15,
            },
        }
        r = self.tracker.track(data)
        self.assertEqual(r.bullish_count, 2)
        self.assertEqual(r.bearish_count, 1)
        self.assertEqual(r.neutral_count, 1)

    # --- Test 41-45: signal_breakdown dict ---

    def test_41_breakdown_has_tvl_signal(self):
        r = self.tracker.track(_all_bullish())
        self.assertIn("tvl_signal", r.signal_breakdown)

    def test_42_breakdown_has_new_wallet_signal(self):
        r = self.tracker.track(_all_bullish())
        self.assertIn("new_wallet_signal", r.signal_breakdown)

    def test_43_breakdown_has_wd_ratio_signal(self):
        r = self.tracker.track(_all_bullish())
        self.assertIn("wd_ratio_signal", r.signal_breakdown)

    def test_44_breakdown_has_large_exit_signal(self):
        r = self.tracker.track(_all_bullish())
        self.assertIn("large_exit_signal", r.signal_breakdown)

    def test_45_breakdown_preserves_input_values(self):
        data = _all_bullish()
        data["signals"]["tvl_change_7d_pct"] = 7.7
        r = self.tracker.track(data)
        self.assertAlmostEqual(r.signal_breakdown["tvl_change_7d_pct"], 7.7)

    # --- Test 46-50: get_sentiment / get_signal_breakdown ---

    def test_46_get_sentiment_none_before_track(self):
        t = DeFiSentimentTracker()
        self.assertIsNone(t.get_sentiment())

    def test_47_get_sentiment_after_track(self):
        self.tracker.track(_all_bullish())
        self.assertIsNotNone(self.tracker.get_sentiment())

    def test_48_get_breakdown_none_before_track(self):
        t = DeFiSentimentTracker()
        self.assertIsNone(t.get_signal_breakdown())

    def test_49_get_breakdown_after_track(self):
        self.tracker.track(_all_bullish())
        self.assertIsNotNone(self.tracker.get_signal_breakdown())

    def test_50_get_sentiment_matches_result(self):
        r = self.tracker.track(_all_bullish())
        self.assertEqual(self.tracker.get_sentiment(), r.sentiment)

    # --- Test 51-57: log persistence ---

    def test_51_append_log_creates_file(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "sentiment_log.json")
            t = DeFiSentimentTracker(log_path=path)
            r = t.track(_all_bullish())
            t.append_log(r)
            self.assertTrue(os.path.exists(path))

    def test_52_append_log_valid_json(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "sentiment_log.json")
            t = DeFiSentimentTracker(log_path=path)
            r = t.track(_all_bullish())
            t.append_log(r)
            with open(path) as fh:
                data = json.load(fh)
            self.assertIsInstance(data, list)

    def test_53_append_log_single_entry(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "sentiment_log.json")
            t = DeFiSentimentTracker(log_path=path)
            r = t.track(_all_bullish())
            t.append_log(r)
            with open(path) as fh:
                data = json.load(fh)
            self.assertEqual(len(data), 1)

    def test_54_append_log_accumulates(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "sentiment_log.json")
            t = DeFiSentimentTracker(log_path=path)
            for _ in range(7):
                r = t.track(_all_bullish())
                t.append_log(r)
            with open(path) as fh:
                data = json.load(fh)
            self.assertEqual(len(data), 7)

    def test_55_log_capped_at_100(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "sentiment_log.json")
            t = DeFiSentimentTracker(log_path=path)
            for _ in range(LOG_CAP + 15):
                r = t.track(_all_bullish())
                t.append_log(r)
            with open(path) as fh:
                data = json.load(fh)
            self.assertEqual(len(data), LOG_CAP)

    def test_56_log_entry_has_sentiment(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "sentiment_log.json")
            t = DeFiSentimentTracker(log_path=path)
            r = t.track(_all_bullish())
            t.append_log(r)
            with open(path) as fh:
                data = json.load(fh)
            self.assertIn("sentiment", data[0])

    def test_57_log_overwrites_corrupt_file(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "sentiment_log.json")
            with open(path, "w") as fh:
                fh.write("NOT JSON!!")
            t = DeFiSentimentTracker(log_path=path)
            r = t.track(_all_bullish())
            t.append_log(r)
            with open(path) as fh:
                data = json.load(fh)
            self.assertEqual(len(data), 1)

    # --- Test 58-65: edge cases ---

    def test_58_missing_signals_key_defaults(self):
        data = {"protocol": "Unknown"}
        r = self.tracker.track(data)
        self.assertIsInstance(r, SentimentResult)

    def test_59_empty_signals_dict(self):
        data = {"protocol": "P", "signals": {}}
        r = self.tracker.track(data)
        self.assertIsInstance(r.composite_sentiment_score, int)

    def test_60_protocol_defaults_to_unknown(self):
        r = self.tracker.track({"signals": {}})
        self.assertEqual(r.protocol, "unknown")

    def test_61_score_range_all_bullish(self):
        r = self.tracker.track(_all_bullish())
        self.assertGreaterEqual(r.composite_sentiment_score, -8)
        self.assertLessEqual(r.composite_sentiment_score, 8)

    def test_62_score_range_all_bearish(self):
        r = self.tracker.track(_all_bearish())
        self.assertGreaterEqual(r.composite_sentiment_score, -8)
        self.assertLessEqual(r.composite_sentiment_score, 8)

    def test_63_sentiment_valid_label(self):
        valid = {e.value for e in SentimentLabel}
        for data in (_all_bullish(), _all_bearish(), _all_neutral()):
            r = self.tracker.track(data)
            self.assertIn(r.sentiment, valid)

    def test_64_multiple_tracks_independent(self):
        r1 = self.tracker.track(_all_bullish())
        r2 = self.tracker.track(_all_bearish())
        self.assertEqual(r1.composite_sentiment_score, 8)
        self.assertEqual(r2.composite_sentiment_score, -8)

    def test_65_breakdown_signal_values_valid(self):
        valid = {e.value for e in SignalLabel}
        r = self.tracker.track(_all_bullish())
        for key in ("tvl_signal", "new_wallet_signal", "wd_ratio_signal", "large_exit_signal"):
            self.assertIn(r.signal_breakdown[key], valid)

    # --- Bonus tests 66-68 ---

    def test_66_very_bullish_threshold_boundary(self):
        # score = 4 → not > 4 so not VERY_BULLISH, should be BULLISH
        # but score 5 → should be VERY_BULLISH
        # 3 bullish + 1 neutral → score = 6 → VERY_BULLISH
        data = {
            "protocol": "P",
            "signals": {
                "tvl_change_7d_pct": 10.0,
                "new_wallet_count_7d": 1300,
                "new_wallet_4w_avg": 1000,
                "withdraw_to_deposit_ratio": 0.5,
                "large_exit_count_7d": 6,         # neutral
            },
        }
        r = self.tracker.track(data)
        self.assertEqual(r.composite_sentiment_score, 6)
        self.assertEqual(r.sentiment, SentimentLabel.VERY_BULLISH.value)

    def test_67_very_bearish_threshold_boundary(self):
        # score = -6 → VERY_BEARISH
        data = {
            "protocol": "P",
            "signals": {
                "tvl_change_7d_pct": -10.0,
                "new_wallet_count_7d": 700,
                "new_wallet_4w_avg": 1000,
                "withdraw_to_deposit_ratio": 1.5,
                "large_exit_count_7d": 6,         # neutral
            },
        }
        r = self.tracker.track(data)
        self.assertEqual(r.composite_sentiment_score, -6)
        self.assertEqual(r.sentiment, SentimentLabel.VERY_BEARISH.value)

    def test_68_score_4_is_very_bullish(self):
        # 3 bullish, 1 bearish → score = 6 - 2 = 4 — boundary check
        data = {
            "protocol": "P",
            "signals": {
                "tvl_change_7d_pct": 10.0,
                "new_wallet_count_7d": 1300,
                "new_wallet_4w_avg": 1000,
                "withdraw_to_deposit_ratio": 1.5,   # bearish
                "large_exit_count_7d": 1,            # bullish
            },
        }
        r = self.tracker.track(data)
        self.assertEqual(r.composite_sentiment_score, 4)
        # score = 4, not > 4 → BULLISH (per spec: >4 = VERY_BULLISH)
        self.assertEqual(r.sentiment, SentimentLabel.BULLISH.value)


if __name__ == "__main__":
    unittest.main()
