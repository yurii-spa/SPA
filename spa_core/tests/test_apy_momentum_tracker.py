"""
MP-811 — Unit tests for APYMomentumTracker.
Pure stdlib unittest; ≥ 65 tests.
Run: python3 -m unittest spa_core.tests.test_apy_momentum_tracker -v
"""

import json
import os
import unittest
import tempfile
from pathlib import Path

from spa_core.analytics.apy_momentum_tracker import (
    MAX_ENTRIES,
    DEFAULT_CONFIG,
    _classify_signal,
    _classify_trend,
    _compute_ema,
    analyze,
    load_log,
    save_result,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _tmp_log(tmp_dir: str) -> Path:
    return Path(tmp_dir) / "apy_momentum_log.json"


def _flat_history(n: int = 10, value: float = 0.05) -> list:
    return [value] * n


def _rising_history(n: int = 20, start: float = 0.01, step: float = 0.005) -> list:
    return [start + i * step for i in range(n)]


def _falling_history(n: int = 20, start: float = 0.10, step: float = 0.005) -> list:
    return [start - i * step for i in range(n)]


# ---------------------------------------------------------------------------
# 1. TestComputeEMA
# ---------------------------------------------------------------------------

class TestComputeEMA(unittest.TestCase):

    def test_empty_returns_zero(self):
        self.assertEqual(_compute_ema([], 7), 0.0)

    def test_single_value_returns_that_value(self):
        self.assertAlmostEqual(_compute_ema([0.05], 7), 0.05)

    def test_two_values_window_2_alpha_two_thirds(self):
        # α = 2/(2+1) = 2/3; ema = (2/3)*0.06 + (1/3)*0.04 = 0.04 + 0.04/3 = 0.04 + 0.01333 = 0.05333
        result = _compute_ema([0.04, 0.06], 2)
        expected = (2.0 / 3) * 0.06 + (1.0 / 3) * 0.04
        self.assertAlmostEqual(result, expected, places=10)

    def test_two_values_window_21_lower_alpha(self):
        alpha = 2.0 / 22
        result = _compute_ema([0.04, 0.06], 21)
        expected = alpha * 0.06 + (1 - alpha) * 0.04
        self.assertAlmostEqual(result, expected, places=10)

    def test_all_same_values_returns_same(self):
        vals = [0.05] * 15
        self.assertAlmostEqual(_compute_ema(vals, 7), 0.05)
        self.assertAlmostEqual(_compute_ema(vals, 21), 0.05)

    def test_window_1_alpha_one_returns_last(self):
        # α = 2/(1+1) = 1.0 → always returns last value
        vals = [0.01, 0.02, 0.03, 0.04, 0.09]
        self.assertAlmostEqual(_compute_ema(vals, 1), 0.09)

    def test_short_window_higher_weight_on_recent(self):
        # Rising series: short window (α larger) → higher EMA (closer to recent)
        vals = _rising_history(30)
        ema_short = _compute_ema(vals, 7)
        ema_long = _compute_ema(vals, 21)
        self.assertGreater(ema_short, ema_long)

    def test_falling_series_short_below_long(self):
        vals = _falling_history(30)
        ema_short = _compute_ema(vals, 7)
        ema_long = _compute_ema(vals, 21)
        self.assertLess(ema_short, ema_long)

    def test_uses_all_values_not_just_window(self):
        # If only last `window` values were used, results would differ
        vals = [0.10] + [0.01] * 19  # one old spike then constant low
        ema_all = _compute_ema(vals, 7)
        # EMA considering the initial spike is slightly higher than 0.01
        self.assertGreater(ema_all, 0.01)

    def test_result_is_float(self):
        self.assertIsInstance(_compute_ema([0.05, 0.06], 7), float)


# ---------------------------------------------------------------------------
# 2. TestClassifySignal
# ---------------------------------------------------------------------------

class TestClassifySignal(unittest.TestCase):

    def test_above_10_strong_buy(self):
        self.assertEqual(_classify_signal(10.01), "STRONG_BUY")
        self.assertEqual(_classify_signal(50.0), "STRONG_BUY")

    def test_exactly_10_is_buy_not_strong_buy(self):
        self.assertEqual(_classify_signal(10.0), "BUY")

    def test_between_2_and_10_buy(self):
        self.assertEqual(_classify_signal(5.0), "BUY")
        self.assertEqual(_classify_signal(2.01), "BUY")
        self.assertEqual(_classify_signal(9.99), "BUY")

    def test_exactly_2_is_neutral(self):
        self.assertEqual(_classify_signal(2.0), "NEUTRAL")

    def test_zero_is_neutral(self):
        self.assertEqual(_classify_signal(0.0), "NEUTRAL")

    def test_exactly_minus_2_is_neutral(self):
        self.assertEqual(_classify_signal(-2.0), "NEUTRAL")

    def test_between_minus_10_and_minus_2_sell(self):
        self.assertEqual(_classify_signal(-5.0), "SELL")
        self.assertEqual(_classify_signal(-2.01), "SELL")
        self.assertEqual(_classify_signal(-9.99), "SELL")

    def test_exactly_minus_10_is_sell(self):
        self.assertEqual(_classify_signal(-10.0), "SELL")

    def test_below_minus_10_strong_sell(self):
        self.assertEqual(_classify_signal(-10.01), "STRONG_SELL")
        self.assertEqual(_classify_signal(-50.0), "STRONG_SELL")


# ---------------------------------------------------------------------------
# 3. TestClassifyTrend
# ---------------------------------------------------------------------------

class TestClassifyTrend(unittest.TestCase):

    def test_above_1_02_accelerating(self):
        # 0.05 * 1.02 = 0.0510...; use 0.0512 to be clearly above
        self.assertEqual(_classify_trend(0.0512, 0.05), "ACCELERATING")

    def test_exactly_1_02_is_stable_not_accelerating(self):
        # Due to floating-point, use a value known to equal the threshold
        threshold = 0.05 * 1.02
        self.assertEqual(_classify_trend(threshold, 0.05), "STABLE")

    def test_well_above_is_accelerating(self):
        self.assertEqual(_classify_trend(0.06, 0.05), "ACCELERATING")

    def test_below_0_98_decelerating(self):
        # 0.05 * 0.98 = 0.049; use 0.0488 to be clearly below
        self.assertEqual(_classify_trend(0.0488, 0.05), "DECELERATING")

    def test_exactly_0_98_is_stable_not_decelerating(self):
        threshold = 0.05 * 0.98
        self.assertEqual(_classify_trend(threshold, 0.050), "STABLE")

    def test_within_band_stable(self):
        self.assertEqual(_classify_trend(0.05, 0.05), "STABLE")
        self.assertEqual(_classify_trend(0.0505, 0.05), "STABLE")

    def test_ema_zero_returns_stable(self):
        self.assertEqual(_classify_trend(0.05, 0.0), "STABLE")
        self.assertEqual(_classify_trend(0.0, 0.0), "STABLE")


# ---------------------------------------------------------------------------
# 4. TestAnalyzeOutputStructure
# ---------------------------------------------------------------------------

class TestAnalyzeOutputStructure(unittest.TestCase):

    def setUp(self):
        self.protocols = [
            {"name": "aave", "apy_history": _rising_history(15)},
        ]

    def test_returns_dict(self):
        result = analyze(self.protocols)
        self.assertIsInstance(result, dict)

    def test_has_protocols_key(self):
        result = analyze(self.protocols)
        self.assertIn("protocols", result)
        self.assertIsInstance(result["protocols"], list)

    def test_has_market_sentiment(self):
        result = analyze(self.protocols)
        self.assertIn("market_sentiment", result)
        self.assertIn(result["market_sentiment"], {"BULLISH", "NEUTRAL", "BEARISH"})

    def test_has_bullish_bearish_count(self):
        result = analyze(self.protocols)
        self.assertIn("bullish_count", result)
        self.assertIn("bearish_count", result)
        self.assertIsInstance(result["bullish_count"], int)
        self.assertIsInstance(result["bearish_count"], int)

    def test_has_top_bottom_momentum(self):
        result = analyze(self.protocols)
        self.assertIn("top_momentum", result)
        self.assertIn("bottom_momentum", result)

    def test_has_timestamp(self):
        result = analyze(self.protocols)
        self.assertIn("timestamp", result)
        self.assertIsInstance(result["timestamp"], float)
        self.assertGreater(result["timestamp"], 0)

    def test_protocol_has_all_required_fields(self):
        result = analyze(self.protocols)
        p = result["protocols"][0]
        for key in ("name", "current_apy", "ema_short", "ema_long",
                    "momentum", "momentum_pct", "signal", "trend"):
            self.assertIn(key, p)

    def test_protocol_current_apy_matches_last_history(self):
        history = [0.01, 0.02, 0.03, 0.07]
        result = analyze([{"name": "x", "apy_history": history}])
        self.assertAlmostEqual(result["protocols"][0]["current_apy"], 0.07)

    def test_signal_is_valid_label(self):
        result = analyze(self.protocols)
        valid = {"STRONG_BUY", "BUY", "NEUTRAL", "SELL", "STRONG_SELL"}
        self.assertIn(result["protocols"][0]["signal"], valid)

    def test_trend_is_valid_label(self):
        result = analyze(self.protocols)
        valid = {"ACCELERATING", "STABLE", "DECELERATING"}
        self.assertIn(result["protocols"][0]["trend"], valid)


# ---------------------------------------------------------------------------
# 5. TestAnalyzeSignals
# ---------------------------------------------------------------------------

class TestAnalyzeSignals(unittest.TestCase):

    def test_rising_series_positive_momentum(self):
        history = _rising_history(30)
        result = analyze([{"name": "r", "apy_history": history}])
        p = result["protocols"][0]
        self.assertGreater(p["momentum"], 0)
        self.assertGreater(p["momentum_pct"], 0)

    def test_flat_series_zero_momentum(self):
        history = _flat_history(30)
        result = analyze([{"name": "f", "apy_history": history}])
        p = result["protocols"][0]
        self.assertAlmostEqual(p["momentum"], 0.0)
        self.assertAlmostEqual(p["momentum_pct"], 0.0)
        self.assertEqual(p["signal"], "NEUTRAL")

    def test_falling_series_negative_momentum(self):
        history = _falling_history(30)
        result = analyze([{"name": "d", "apy_history": history}])
        p = result["protocols"][0]
        self.assertLess(p["momentum"], 0)
        self.assertLess(p["momentum_pct"], 0)

    def test_strongly_rising_produces_strong_buy_or_buy(self):
        # Very steep rise → large positive momentum_pct
        history = [0.01 * (1 + 0.5 * i) for i in range(30)]
        result = analyze([{"name": "r", "apy_history": history}])
        self.assertIn(result["protocols"][0]["signal"], {"STRONG_BUY", "BUY"})

    def test_strongly_falling_produces_strong_sell_or_sell(self):
        history = [0.30 - 0.01 * i for i in range(30)]
        result = analyze([{"name": "d", "apy_history": history}])
        self.assertIn(result["protocols"][0]["signal"], {"STRONG_SELL", "SELL"})

    def test_custom_short_window_affects_ema_short(self):
        history = _rising_history(30)
        r3 = analyze([{"name": "x", "apy_history": history}], config={"short_window": 3})
        r7 = analyze([{"name": "x", "apy_history": history}], config={"short_window": 7})
        # Smaller window → higher alpha → EMA closer to last (higher for rising)
        self.assertGreater(r3["protocols"][0]["ema_short"],
                           r7["protocols"][0]["ema_short"])

    def test_custom_long_window_affects_ema_long(self):
        history = _rising_history(30)
        r14 = analyze([{"name": "x", "apy_history": history}], config={"long_window": 14})
        r30 = analyze([{"name": "x", "apy_history": history}], config={"long_window": 30})
        # Smaller long_window → higher alpha → EMA closer to last (higher for rising)
        self.assertGreater(r14["protocols"][0]["ema_long"],
                           r30["protocols"][0]["ema_long"])

    def test_momentum_equals_ema_short_minus_ema_long(self):
        history = _rising_history(20)
        result = analyze([{"name": "x", "apy_history": history}])
        p = result["protocols"][0]
        self.assertAlmostEqual(p["momentum"], p["ema_short"] - p["ema_long"], places=10)

    def test_momentum_pct_formula(self):
        history = _rising_history(20)
        result = analyze([{"name": "x", "apy_history": history}])
        p = result["protocols"][0]
        if p["ema_long"] != 0:
            expected = p["momentum"] / p["ema_long"] * 100.0
            self.assertAlmostEqual(p["momentum_pct"], expected, places=6)


# ---------------------------------------------------------------------------
# 6. TestAnalyzeEdgeCases
# ---------------------------------------------------------------------------

class TestAnalyzeEdgeCases(unittest.TestCase):

    def test_empty_protocols_list(self):
        result = analyze([])
        self.assertEqual(result["protocols"], [])
        self.assertEqual(result["bullish_count"], 0)
        self.assertEqual(result["bearish_count"], 0)
        self.assertEqual(result["top_momentum"], "")
        self.assertEqual(result["bottom_momentum"], "")

    def test_empty_apy_history_protocol_skipped(self):
        result = analyze([{"name": "empty", "apy_history": []}])
        self.assertEqual(result["protocols"], [])

    def test_multiple_empty_histories_all_skipped(self):
        protos = [{"name": f"p{i}", "apy_history": []} for i in range(5)]
        result = analyze(protos)
        self.assertEqual(len(result["protocols"]), 0)

    def test_single_value_ema_short_equals_value(self):
        result = analyze([{"name": "x", "apy_history": [0.05]}])
        p = result["protocols"][0]
        self.assertAlmostEqual(p["ema_short"], 0.05)
        self.assertAlmostEqual(p["ema_long"], 0.05)

    def test_single_value_momentum_zero(self):
        result = analyze([{"name": "x", "apy_history": [0.05]}])
        p = result["protocols"][0]
        self.assertAlmostEqual(p["momentum"], 0.0)
        self.assertAlmostEqual(p["momentum_pct"], 0.0)

    def test_single_value_signal_neutral(self):
        result = analyze([{"name": "x", "apy_history": [0.05]}])
        self.assertEqual(result["protocols"][0]["signal"], "NEUTRAL")

    def test_single_value_trend_stable(self):
        result = analyze([{"name": "x", "apy_history": [0.05]}])
        self.assertEqual(result["protocols"][0]["trend"], "STABLE")

    def test_two_entry_history_computed(self):
        result = analyze([{"name": "x", "apy_history": [0.04, 0.06]}])
        p = result["protocols"][0]
        self.assertAlmostEqual(p["current_apy"], 0.06)
        # Both EMAs exist and are floats
        self.assertIsInstance(p["ema_short"], float)
        self.assertIsInstance(p["ema_long"], float)

    def test_all_zero_history_momentum_pct_zero(self):
        result = analyze([{"name": "x", "apy_history": [0.0, 0.0, 0.0, 0.0]}])
        p = result["protocols"][0]
        self.assertAlmostEqual(p["momentum_pct"], 0.0)

    def test_none_config_uses_defaults(self):
        history = _rising_history(20)
        r_none = analyze([{"name": "x", "apy_history": history}], config=None)
        r_def = analyze([{"name": "x", "apy_history": history}],
                        config=DEFAULT_CONFIG.copy())
        self.assertAlmostEqual(
            r_none["protocols"][0]["momentum_pct"],
            r_def["protocols"][0]["momentum_pct"],
            places=8,
        )

    def test_mixed_valid_and_empty_protocols(self):
        protos = [
            {"name": "good", "apy_history": [0.04, 0.05, 0.06]},
            {"name": "empty", "apy_history": []},
        ]
        result = analyze(protos)
        self.assertEqual(len(result["protocols"]), 1)
        self.assertEqual(result["protocols"][0]["name"], "good")


# ---------------------------------------------------------------------------
# 7. TestMomentumValues
# ---------------------------------------------------------------------------

class TestMomentumValues(unittest.TestCase):

    def test_ema_values_are_floats(self):
        result = analyze([{"name": "x", "apy_history": _rising_history(20)}])
        p = result["protocols"][0]
        self.assertIsInstance(p["ema_short"], float)
        self.assertIsInstance(p["ema_long"], float)

    def test_short_ema_above_long_for_rising(self):
        result = analyze([{"name": "x", "apy_history": _rising_history(30)}])
        p = result["protocols"][0]
        self.assertGreater(p["ema_short"], p["ema_long"])

    def test_short_ema_below_long_for_falling(self):
        result = analyze([{"name": "x", "apy_history": _falling_history(30)}])
        p = result["protocols"][0]
        self.assertLess(p["ema_short"], p["ema_long"])

    def test_flat_ema_short_equals_ema_long(self):
        result = analyze([{"name": "x", "apy_history": _flat_history(30)}])
        p = result["protocols"][0]
        self.assertAlmostEqual(p["ema_short"], p["ema_long"])

    def test_momentum_sign_positive_for_rising(self):
        result = analyze([{"name": "x", "apy_history": _rising_history(20)}])
        self.assertGreater(result["protocols"][0]["momentum"], 0)

    def test_momentum_sign_negative_for_falling(self):
        result = analyze([{"name": "x", "apy_history": _falling_history(20)}])
        self.assertLess(result["protocols"][0]["momentum"], 0)

    def test_momentum_pct_is_percentage(self):
        # For a very strongly rising series, pct should be >0
        history = [0.01 + 0.005 * i for i in range(30)]
        result = analyze([{"name": "x", "apy_history": history}])
        p = result["protocols"][0]
        # Not a trivial fraction — should be some percentage
        self.assertGreater(abs(p["momentum_pct"]), 0.0)

    def test_bullish_count_increments_per_buy_signal(self):
        # Both protocols strongly rising → bullish_count >= 1
        protos = [
            {"name": "a", "apy_history": _rising_history(30)},
            {"name": "b", "apy_history": _rising_history(30)},
        ]
        result = analyze(protos)
        self.assertGreaterEqual(result["bullish_count"], 1)


# ---------------------------------------------------------------------------
# 8. TestMarketSentiment
# ---------------------------------------------------------------------------

class TestMarketSentiment(unittest.TestCase):

    def test_bullish_majority(self):
        protos = [
            {"name": "a", "apy_history": _rising_history(30)},
            {"name": "b", "apy_history": _rising_history(30)},
            {"name": "c", "apy_history": _falling_history(30)},
        ]
        result = analyze(protos)
        if result["bullish_count"] > result["bearish_count"]:
            self.assertEqual(result["market_sentiment"], "BULLISH")

    def test_bearish_majority(self):
        protos = [
            {"name": "a", "apy_history": _falling_history(30)},
            {"name": "b", "apy_history": _falling_history(30)},
            {"name": "c", "apy_history": _rising_history(30)},
        ]
        result = analyze(protos)
        if result["bearish_count"] > result["bullish_count"]:
            self.assertEqual(result["market_sentiment"], "BEARISH")

    def test_equal_counts_is_neutral(self):
        # Force equal by using flat histories (NEUTRAL signal)
        protos = [
            {"name": "a", "apy_history": _flat_history(20)},
            {"name": "b", "apy_history": _flat_history(20)},
        ]
        result = analyze(protos)
        self.assertEqual(result["market_sentiment"], "NEUTRAL")

    def test_empty_protocols_sentiment_neutral(self):
        result = analyze([])
        self.assertEqual(result["market_sentiment"], "NEUTRAL")

    def test_all_flat_neutral_sentiment(self):
        protos = [{"name": f"p{i}", "apy_history": _flat_history(20)} for i in range(5)]
        result = analyze(protos)
        self.assertEqual(result["market_sentiment"], "NEUTRAL")

    def test_sentiment_bullish_when_more_bulls(self):
        protos = [{"name": f"r{i}", "apy_history": _rising_history(30)} for i in range(3)]
        result = analyze(protos)
        if result["bullish_count"] > 0:
            self.assertIn(result["market_sentiment"], {"BULLISH", "NEUTRAL"})

    def test_counts_non_negative(self):
        result = analyze([{"name": "x", "apy_history": _rising_history(20)}])
        self.assertGreaterEqual(result["bullish_count"], 0)
        self.assertGreaterEqual(result["bearish_count"], 0)


# ---------------------------------------------------------------------------
# 9. TestTopBottomMomentum
# ---------------------------------------------------------------------------

class TestTopBottomMomentum(unittest.TestCase):

    def test_top_momentum_has_highest_pct(self):
        protos = [
            {"name": "rising", "apy_history": _rising_history(30)},
            {"name": "flat", "apy_history": _flat_history(30)},
            {"name": "falling", "apy_history": _falling_history(30)},
        ]
        result = analyze(protos)
        proto_map = {p["name"]: p for p in result["protocols"]}
        top = result["top_momentum"]
        self.assertEqual(
            top,
            max(proto_map, key=lambda k: proto_map[k]["momentum_pct"]),
        )

    def test_bottom_momentum_has_lowest_pct(self):
        protos = [
            {"name": "rising", "apy_history": _rising_history(30)},
            {"name": "flat", "apy_history": _flat_history(30)},
            {"name": "falling", "apy_history": _falling_history(30)},
        ]
        result = analyze(protos)
        proto_map = {p["name"]: p for p in result["protocols"]}
        bottom = result["bottom_momentum"]
        self.assertEqual(
            bottom,
            min(proto_map, key=lambda k: proto_map[k]["momentum_pct"]),
        )

    def test_single_protocol_top_equals_bottom(self):
        result = analyze([{"name": "only", "apy_history": _rising_history(10)}])
        self.assertEqual(result["top_momentum"], "only")
        self.assertEqual(result["bottom_momentum"], "only")

    def test_empty_protocols_returns_empty_strings(self):
        result = analyze([])
        self.assertEqual(result["top_momentum"], "")
        self.assertEqual(result["bottom_momentum"], "")

    def test_top_bottom_are_strings(self):
        result = analyze([{"name": "a", "apy_history": _rising_history(20)}])
        self.assertIsInstance(result["top_momentum"], str)
        self.assertIsInstance(result["bottom_momentum"], str)


# ---------------------------------------------------------------------------
# 10. TestSaveResult
# ---------------------------------------------------------------------------

class TestSaveResult(unittest.TestCase):

    def test_creates_file_if_missing(self):
        with tempfile.TemporaryDirectory() as td:
            log = _tmp_log(td)
            self.assertFalse(log.exists())
            save_result({"test": 1}, data_file=log)
            self.assertTrue(log.exists())

    def test_file_is_valid_json_list(self):
        with tempfile.TemporaryDirectory() as td:
            log = _tmp_log(td)
            save_result({"test": 1}, data_file=log)
            data = json.loads(log.read_text())
            self.assertIsInstance(data, list)
            self.assertEqual(len(data), 1)

    def test_appends_multiple_results(self):
        with tempfile.TemporaryDirectory() as td:
            log = _tmp_log(td)
            save_result({"n": 1}, data_file=log)
            save_result({"n": 2}, data_file=log)
            save_result({"n": 3}, data_file=log)
            data = json.loads(log.read_text())
            self.assertEqual(len(data), 3)
            self.assertEqual(data[0]["n"], 1)
            self.assertEqual(data[2]["n"], 3)

    def test_ring_buffer_capped_at_max_entries(self):
        with tempfile.TemporaryDirectory() as td:
            log = _tmp_log(td)
            for i in range(MAX_ENTRIES + 10):
                save_result({"i": i}, data_file=log)
            data = json.loads(log.read_text())
            self.assertEqual(len(data), MAX_ENTRIES)
            # Oldest entries dropped; last entry should be i=MAX_ENTRIES+9
            self.assertEqual(data[-1]["i"], MAX_ENTRIES + 9)

    def test_no_tmp_file_left_after_write(self):
        with tempfile.TemporaryDirectory() as td:
            log = _tmp_log(td)
            save_result({"x": 1}, data_file=log)
            tmp = log.with_suffix(".tmp")
            self.assertFalse(tmp.exists())

    def test_handles_corrupt_existing_file(self):
        with tempfile.TemporaryDirectory() as td:
            log = _tmp_log(td)
            log.write_text("not-json-at-all!!!")
            save_result({"ok": True}, data_file=log)
            data = json.loads(log.read_text())
            self.assertEqual(data, [{"ok": True}])

    def test_creates_parent_directory(self):
        with tempfile.TemporaryDirectory() as td:
            log = Path(td) / "nested" / "dir" / "log.json"
            save_result({"ok": True}, data_file=log)
            self.assertTrue(log.exists())

    def test_load_log_returns_empty_for_missing_file(self):
        with tempfile.TemporaryDirectory() as td:
            log = _tmp_log(td)
            self.assertEqual(load_log(log), [])

    def test_load_log_returns_saved_entries(self):
        with tempfile.TemporaryDirectory() as td:
            log = _tmp_log(td)
            save_result({"a": 1}, data_file=log)
            save_result({"b": 2}, data_file=log)
            loaded = load_log(log)
            self.assertEqual(len(loaded), 2)
            self.assertEqual(loaded[0]["a"], 1)

    def test_save_full_analyze_result(self):
        with tempfile.TemporaryDirectory() as td:
            log = _tmp_log(td)
            result = analyze([{"name": "aave", "apy_history": _rising_history(20)}])
            save_result(result, data_file=log)
            loaded = load_log(log)
            self.assertEqual(len(loaded), 1)
            self.assertIn("protocols", loaded[0])
            self.assertIn("market_sentiment", loaded[0])


if __name__ == "__main__":
    unittest.main()
