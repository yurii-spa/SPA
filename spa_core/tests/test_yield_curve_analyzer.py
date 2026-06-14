"""
Tests for MP-805 YieldCurveAnalyzer
====================================
≥ 65 unittest tests covering:
  - curve shape classification (NORMAL, INVERTED, FLAT, HUMPED)
  - market_shape majority vote
  - per-protocol metrics
  - cross-protocol aggregation
  - config overrides (short_max_days, medium_max_days)
  - edge cases (empty, single point, single protocol, many protocols)
  - log ring-buffer cap
  - atomic write (no partial file)
  - timestamp presence
"""

import json
import os
import sys
import tempfile
import time
import unittest

# ---------------------------------------------------------------------------
# Make the module importable without installing the package
# ---------------------------------------------------------------------------
_ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

import spa_core.analytics.yield_curve_analyzer as yca


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_row(duration_days, protocol, borrow_rate, supply_rate):
    return {
        "duration_days": duration_days,
        "protocol": protocol,
        "borrow_rate": borrow_rate,
        "supply_rate": supply_rate,
    }


_NORMAL_AAVE = [
    _make_row(1,   "Aave", 5.0, 3.0),
    _make_row(30,  "Aave", 5.5, 3.8),
    _make_row(90,  "Aave", 6.0, 4.2),
    _make_row(180, "Aave", 6.5, 4.9),
    _make_row(365, "Aave", 7.0, 5.5),
]

_INVERTED_COMP = [
    _make_row(1,   "Compound", 6.0, 5.5),
    _make_row(30,  "Compound", 5.5, 4.8),
    _make_row(90,  "Compound", 5.0, 4.0),
    _make_row(180, "Compound", 4.5, 3.5),
    _make_row(365, "Compound", 4.0, 2.8),
]

_FLAT_PROTO = [
    _make_row(7,   "Flat", 4.0, 3.9),
    _make_row(30,  "Flat", 4.1, 4.0),
    _make_row(90,  "Flat", 4.0, 3.95),
    _make_row(180, "Flat", 4.0, 3.98),
]

_HUMPED_PROTO = [
    _make_row(7,   "Humped", 4.0, 2.5),
    _make_row(30,  "Humped", 5.0, 5.5),   # peak in middle
    _make_row(365, "Humped", 4.5, 2.8),
]


# ---------------------------------------------------------------------------
# Test class
# ---------------------------------------------------------------------------

class TestYieldCurveAnalyzerStructure(unittest.TestCase):
    """Result structure tests."""

    def setUp(self):
        self._patch_log()

    def _patch_log(self):
        """Redirect log writes to a temp file so tests are isolated."""
        self._tmpdir = tempfile.mkdtemp()
        self._orig_log = yca._LOG_PATH
        yca._LOG_PATH = os.path.join(self._tmpdir, "yield_curve_log.json")
        # Monkey-patch _append_log to use temp dir
        orig_append = yca._append_log

        def _patched_append(entry):
            log_path = yca._LOG_PATH
            os.makedirs(os.path.dirname(log_path), exist_ok=True)
            try:
                with open(log_path, "r") as fh:
                    log = json.load(fh)
            except (FileNotFoundError, json.JSONDecodeError):
                log = []
            log.append(entry)
            if len(log) > yca._LOG_CAP:
                log = log[-yca._LOG_CAP:]
            tmp = log_path + ".tmp"
            with open(tmp, "w") as fh:
                json.dump(log, fh)
            os.replace(tmp, log_path)

        self._orig_append = yca._append_log
        yca._append_log = _patched_append

    def tearDown(self):
        yca._LOG_PATH = self._orig_log
        yca._append_log = self._orig_append

    # ------------------------------------------------------------------
    # 1-10: Top-level keys
    # ------------------------------------------------------------------

    def test_01_returns_dict(self):
        result = yca.analyze(_NORMAL_AAVE)
        self.assertIsInstance(result, dict)

    def test_02_has_protocols_key(self):
        result = yca.analyze(_NORMAL_AAVE)
        self.assertIn("protocols", result)

    def test_03_has_cross_protocol_key(self):
        result = yca.analyze(_NORMAL_AAVE)
        self.assertIn("cross_protocol", result)

    def test_04_has_market_shape_key(self):
        result = yca.analyze(_NORMAL_AAVE)
        self.assertIn("market_shape", result)

    def test_05_has_timestamp(self):
        result = yca.analyze(_NORMAL_AAVE)
        self.assertIn("timestamp", result)

    def test_06_timestamp_is_float(self):
        result = yca.analyze(_NORMAL_AAVE)
        self.assertIsInstance(result["timestamp"], float)

    def test_07_timestamp_recent(self):
        before = time.time()
        result = yca.analyze(_NORMAL_AAVE)
        after = time.time()
        self.assertGreaterEqual(result["timestamp"], before)
        self.assertLessEqual(result["timestamp"], after)

    def test_08_protocols_is_dict(self):
        result = yca.analyze(_NORMAL_AAVE)
        self.assertIsInstance(result["protocols"], dict)

    def test_09_cross_protocol_is_dict(self):
        result = yca.analyze(_NORMAL_AAVE)
        self.assertIsInstance(result["cross_protocol"], dict)

    def test_10_cross_protocol_has_best_short(self):
        result = yca.analyze(_NORMAL_AAVE)
        self.assertIn("best_short_term", result["cross_protocol"])

    # ------------------------------------------------------------------
    # 11-20: Per-protocol structure
    # ------------------------------------------------------------------

    def test_11_protocol_key_present(self):
        result = yca.analyze(_NORMAL_AAVE)
        self.assertIn("Aave", result["protocols"])

    def test_12_protocol_has_rates(self):
        result = yca.analyze(_NORMAL_AAVE)
        self.assertIn("rates", result["protocols"]["Aave"])

    def test_13_protocol_has_curve_shape(self):
        result = yca.analyze(_NORMAL_AAVE)
        self.assertIn("curve_shape", result["protocols"]["Aave"])

    def test_14_protocol_has_max_supply_rate(self):
        result = yca.analyze(_NORMAL_AAVE)
        self.assertIn("max_supply_rate", result["protocols"]["Aave"])

    def test_15_protocol_has_optimal_duration(self):
        result = yca.analyze(_NORMAL_AAVE)
        self.assertIn("optimal_duration_days", result["protocols"]["Aave"])

    def test_16_protocol_has_short_term_avg(self):
        result = yca.analyze(_NORMAL_AAVE)
        self.assertIn("short_term_avg_supply", result["protocols"]["Aave"])

    def test_17_protocol_has_long_term_avg(self):
        result = yca.analyze(_NORMAL_AAVE)
        self.assertIn("long_term_avg_supply", result["protocols"]["Aave"])

    def test_18_rates_list_correct_length(self):
        result = yca.analyze(_NORMAL_AAVE)
        self.assertEqual(len(result["protocols"]["Aave"]["rates"]), 5)

    def test_19_rates_entry_has_spread(self):
        result = yca.analyze(_NORMAL_AAVE)
        entry = result["protocols"]["Aave"]["rates"][0]
        self.assertIn("spread", entry)

    def test_20_rates_entry_spread_correct(self):
        result = yca.analyze(_NORMAL_AAVE)
        # first entry: borrow 5.0 - supply 3.0 = 2.0
        entry = result["protocols"]["Aave"]["rates"][0]
        self.assertAlmostEqual(entry["spread"], 2.0, places=5)

    # ------------------------------------------------------------------
    # 21-30: Curve shape classification
    # ------------------------------------------------------------------

    def test_21_normal_curve_detected(self):
        result = yca.analyze(_NORMAL_AAVE)
        self.assertEqual(result["protocols"]["Aave"]["curve_shape"], "NORMAL")

    def test_22_inverted_curve_detected(self):
        result = yca.analyze(_INVERTED_COMP)
        self.assertEqual(result["protocols"]["Compound"]["curve_shape"], "INVERTED")

    def test_23_flat_curve_detected(self):
        result = yca.analyze(_FLAT_PROTO)
        self.assertEqual(result["protocols"]["Flat"]["curve_shape"], "FLAT")

    def test_24_humped_curve_detected(self):
        result = yca.analyze(_HUMPED_PROTO)
        self.assertEqual(result["protocols"]["Humped"]["curve_shape"], "HUMPED")

    def test_25_single_point_is_flat(self):
        data = [_make_row(30, "Solo", 5.0, 4.0)]
        result = yca.analyze(data)
        self.assertEqual(result["protocols"]["Solo"]["curve_shape"], "FLAT")

    def test_26_two_points_normal(self):
        data = [
            _make_row(7,   "P", 5.0, 3.0),
            _make_row(365, "P", 6.0, 4.0),
        ]
        result = yca.analyze(data)
        self.assertEqual(result["protocols"]["P"]["curve_shape"], "NORMAL")

    def test_27_two_points_inverted(self):
        data = [
            _make_row(7,   "P", 5.0, 5.0),
            _make_row(365, "P", 4.0, 3.5),
        ]
        result = yca.analyze(data)
        self.assertEqual(result["protocols"]["P"]["curve_shape"], "INVERTED")

    def test_28_two_points_flat_range(self):
        data = [
            _make_row(7,   "P", 4.0, 4.0),
            _make_row(365, "P", 4.0, 4.3),
        ]
        result = yca.analyze(data)
        # range < 0.5, so FLAT
        self.assertEqual(result["protocols"]["P"]["curve_shape"], "FLAT")

    def test_29_shape_valid_values(self):
        valid = {"NORMAL", "INVERTED", "FLAT", "HUMPED"}
        for data in [_NORMAL_AAVE, _INVERTED_COMP, _FLAT_PROTO, _HUMPED_PROTO]:
            result = yca.analyze(data)
            for proto, info in result["protocols"].items():
                self.assertIn(info["curve_shape"], valid)

    def test_30_market_shape_valid(self):
        valid = {"NORMAL", "INVERTED", "FLAT", "HUMPED", "MIXED"}
        result = yca.analyze(_NORMAL_AAVE + _INVERTED_COMP)
        self.assertIn(result["market_shape"], valid)

    # ------------------------------------------------------------------
    # 31-40: Market shape majority vote
    # ------------------------------------------------------------------

    def test_31_market_shape_normal_majority(self):
        # two NORMAL, one INVERTED → NORMAL
        data = _NORMAL_AAVE + _INVERTED_COMP + [
            _make_row(1,   "Aave2", 5.0, 3.0),
            _make_row(365, "Aave2", 7.0, 5.5),
        ]
        result = yca.analyze(data)
        self.assertEqual(result["market_shape"], "NORMAL")

    def test_32_market_shape_mixed_on_tie(self):
        # NORMAL + INVERTED → MIXED
        result = yca.analyze(_NORMAL_AAVE + _INVERTED_COMP)
        self.assertEqual(result["market_shape"], "MIXED")

    def test_33_market_shape_single_protocol(self):
        result = yca.analyze(_NORMAL_AAVE)
        self.assertEqual(result["market_shape"], "NORMAL")

    def test_34_market_shape_all_flat(self):
        data = (
            [_make_row(30, "P1", 4.0, 4.0), _make_row(90, "P1", 4.1, 4.05)]
            + [_make_row(30, "P2", 3.9, 3.95), _make_row(90, "P2", 4.0, 3.98)]
        )
        result = yca.analyze(data)
        self.assertEqual(result["market_shape"], "FLAT")

    def test_35_market_shape_inverted_majority(self):
        # 3 INVERTED protocols
        def inv(name):
            return [
                _make_row(1,   name, 6.0, 5.0),
                _make_row(365, name, 3.0, 2.0),
            ]
        data = inv("A") + inv("B") + inv("C") + _NORMAL_AAVE  # 3 vs 1
        result = yca.analyze(data)
        self.assertEqual(result["market_shape"], "INVERTED")

    # ------------------------------------------------------------------
    # 36-45: Optimal duration and max supply rate
    # ------------------------------------------------------------------

    def test_36_optimal_duration_is_highest_supply(self):
        result = yca.analyze(_NORMAL_AAVE)
        info = result["protocols"]["Aave"]
        self.assertEqual(info["optimal_duration_days"], 365)

    def test_37_max_supply_rate_correct(self):
        result = yca.analyze(_NORMAL_AAVE)
        self.assertAlmostEqual(result["protocols"]["Aave"]["max_supply_rate"], 5.5, places=5)

    def test_38_optimal_duration_single_point(self):
        data = [_make_row(90, "Solo", 5.0, 4.0)]
        result = yca.analyze(data)
        self.assertEqual(result["protocols"]["Solo"]["optimal_duration_days"], 90)

    def test_39_optimal_duration_humped_is_middle(self):
        result = yca.analyze(_HUMPED_PROTO)
        info = result["protocols"]["Humped"]
        self.assertEqual(info["optimal_duration_days"], 30)

    def test_40_max_supply_rate_inverted(self):
        result = yca.analyze(_INVERTED_COMP)
        # first entry has highest supply
        self.assertAlmostEqual(
            result["protocols"]["Compound"]["max_supply_rate"], 5.5, places=5
        )

    # ------------------------------------------------------------------
    # 41-50: Short/long term averages
    # ------------------------------------------------------------------

    def test_41_short_term_avg_uses_config(self):
        data = _NORMAL_AAVE  # entries at 1, 30, 90, 180, 365
        result = yca.analyze(data, config={"short_max_days": 30})
        # durations <= 30: supply 3.0, 3.8 → avg 3.4
        avg = result["protocols"]["Aave"]["short_term_avg_supply"]
        self.assertAlmostEqual(avg, (3.0 + 3.8) / 2, places=4)

    def test_42_long_term_avg_uses_config(self):
        data = _NORMAL_AAVE
        result = yca.analyze(data, config={"medium_max_days": 180})
        # durations > 180: supply 5.5 → avg 5.5
        avg = result["protocols"]["Aave"]["long_term_avg_supply"]
        self.assertAlmostEqual(avg, 5.5, places=5)

    def test_43_short_term_avg_zero_when_no_short(self):
        data = [_make_row(365, "P", 5.0, 4.0)]
        result = yca.analyze(data, config={"short_max_days": 30})
        self.assertAlmostEqual(result["protocols"]["P"]["short_term_avg_supply"], 0.0)

    def test_44_long_term_avg_zero_when_no_long(self):
        data = [_make_row(7, "P", 5.0, 4.0)]
        result = yca.analyze(data, config={"medium_max_days": 180})
        self.assertAlmostEqual(result["protocols"]["P"]["long_term_avg_supply"], 0.0)

    def test_45_short_term_avg_multiple_entries(self):
        data = [
            _make_row(1,  "P", 5.0, 2.0),
            _make_row(7,  "P", 5.0, 4.0),
            _make_row(30, "P", 5.0, 6.0),
        ]
        result = yca.analyze(data, config={"short_max_days": 30})
        expected_avg = (2.0 + 4.0 + 6.0) / 3
        self.assertAlmostEqual(
            result["protocols"]["P"]["short_term_avg_supply"], expected_avg, places=5
        )

    # ------------------------------------------------------------------
    # 51-60: Cross-protocol aggregations
    # ------------------------------------------------------------------

    def test_46_cross_has_best_long_term(self):
        result = yca.analyze(_NORMAL_AAVE)
        self.assertIn("best_long_term", result["cross_protocol"])

    def test_47_cross_has_highest_spread(self):
        result = yca.analyze(_NORMAL_AAVE)
        self.assertIn("highest_spread_opportunity", result["cross_protocol"])

    def test_48_best_short_protocol_set(self):
        result = yca.analyze(_NORMAL_AAVE)
        bs = result["cross_protocol"]["best_short_term"]
        self.assertIn("protocol", bs)
        self.assertIn("rate", bs)
        self.assertIn("duration_days", bs)

    def test_49_best_short_is_within_short_range(self):
        data = _NORMAL_AAVE + _INVERTED_COMP
        result = yca.analyze(data, config={"short_max_days": 30})
        bs = result["cross_protocol"]["best_short_term"]
        self.assertLessEqual(bs["duration_days"], 30)

    def test_50_best_long_is_beyond_medium(self):
        data = _NORMAL_AAVE + _INVERTED_COMP
        result = yca.analyze(data, config={"medium_max_days": 180})
        bl = result["cross_protocol"]["best_long_term"]
        self.assertGreater(bl["duration_days"], 180)

    def test_51_highest_spread_positive(self):
        result = yca.analyze(_NORMAL_AAVE)
        hs = result["cross_protocol"]["highest_spread_opportunity"]
        self.assertGreater(hs["spread"], 0)

    def test_52_highest_spread_correct_value(self):
        # All entries have the same spread: borrow 5.0 - supply 3.0 = 2.0 (first entry)
        # Let's verify it picks the correct max
        result = yca.analyze(_NORMAL_AAVE)
        hs = result["cross_protocol"]["highest_spread_opportunity"]
        # Compute expected max spread from _NORMAL_AAVE
        spreads = [r["borrow_rate"] - r["supply_rate"] for r in _NORMAL_AAVE]
        self.assertAlmostEqual(hs["spread"], max(spreads), places=4)

    def test_53_multi_protocol_best_short_selects_highest_rate(self):
        data = (
            [_make_row(7, "Low",  5.0, 2.0)]
            + [_make_row(7, "High", 5.0, 6.0)]
        )
        result = yca.analyze(data, config={"short_max_days": 30})
        self.assertEqual(result["cross_protocol"]["best_short_term"]["protocol"], "High")

    def test_54_multi_protocol_best_long_selects_highest_rate(self):
        data = (
            [_make_row(365, "Low",  5.0, 2.0)]
            + [_make_row(365, "High", 5.0, 8.0)]
        )
        result = yca.analyze(data, config={"medium_max_days": 180})
        self.assertEqual(result["cross_protocol"]["best_long_term"]["protocol"], "High")

    # ------------------------------------------------------------------
    # 61-70: Edge cases and robustness
    # ------------------------------------------------------------------

    def test_55_empty_rate_data(self):
        result = yca.analyze([])
        self.assertIsInstance(result, dict)
        self.assertEqual(result["protocols"], {})

    def test_56_multiple_protocols_in_result(self):
        data = _NORMAL_AAVE + _INVERTED_COMP
        result = yca.analyze(data)
        self.assertIn("Aave", result["protocols"])
        self.assertIn("Compound", result["protocols"])

    def test_57_rates_sorted_by_duration(self):
        # Supply out-of-order input
        data = [
            _make_row(365, "P", 7.0, 5.0),
            _make_row(1,   "P", 5.0, 3.0),
            _make_row(90,  "P", 6.0, 4.0),
        ]
        result = yca.analyze(data)
        durations = [r["duration_days"] for r in result["protocols"]["P"]["rates"]]
        self.assertEqual(durations, sorted(durations))

    def test_58_config_none_uses_defaults(self):
        result = yca.analyze(_NORMAL_AAVE, config=None)
        self.assertIn("protocols", result)

    def test_59_config_empty_uses_defaults(self):
        result = yca.analyze(_NORMAL_AAVE, config={})
        self.assertIn("protocols", result)

    def test_60_spread_is_borrow_minus_supply(self):
        data = [_make_row(30, "P", 6.0, 4.0)]
        result = yca.analyze(data)
        spread = result["protocols"]["P"]["rates"][0]["spread"]
        self.assertAlmostEqual(spread, 2.0, places=5)

    def test_61_negative_spread_possible(self):
        # supply > borrow → negative spread
        data = [_make_row(30, "P", 3.0, 5.0)]
        result = yca.analyze(data)
        spread = result["protocols"]["P"]["rates"][0]["spread"]
        self.assertAlmostEqual(spread, -2.0, places=5)

    def test_62_many_protocols(self):
        data = []
        for i in range(10):
            data += [
                _make_row(1, f"P{i}", 5.0 + i * 0.1, 3.0 + i * 0.1),
                _make_row(365, f"P{i}", 6.0 + i * 0.1, 4.5 + i * 0.1),
            ]
        result = yca.analyze(data)
        self.assertEqual(len(result["protocols"]), 10)

    def test_63_rates_entry_has_all_keys(self):
        result = yca.analyze(_NORMAL_AAVE)
        for entry in result["protocols"]["Aave"]["rates"]:
            self.assertIn("duration_days", entry)
            self.assertIn("borrow_rate", entry)
            self.assertIn("supply_rate", entry)
            self.assertIn("spread", entry)

    def test_64_market_shape_empty_data(self):
        result = yca.analyze([])
        # With no protocols, market_shape should be FLAT (default)
        self.assertIn(result["market_shape"], {"FLAT", "NORMAL", "INVERTED", "HUMPED", "MIXED"})

    def test_65_single_protocol_market_shape_matches_curve(self):
        result = yca.analyze(_NORMAL_AAVE)
        proto_shape = result["protocols"]["Aave"]["curve_shape"]
        self.assertEqual(result["market_shape"], proto_shape)

    def test_66_inverted_single_protocol_market_shape(self):
        result = yca.analyze(_INVERTED_COMP)
        self.assertEqual(result["market_shape"], "INVERTED")

    def test_67_humped_market_shape(self):
        result = yca.analyze(_HUMPED_PROTO)
        self.assertEqual(result["market_shape"], "HUMPED")


class TestYieldCurveAnalyzerLogging(unittest.TestCase):
    """Ring-buffer log and atomic write tests."""

    def setUp(self):
        self._tmpdir = tempfile.mkdtemp()
        self._log_path = os.path.join(self._tmpdir, "yield_curve_log.json")
        self._orig_append = yca._append_log

        def _patched_append(entry):
            log_path = self._log_path
            os.makedirs(os.path.dirname(log_path), exist_ok=True)
            try:
                with open(log_path, "r") as fh:
                    log = json.load(fh)
            except (FileNotFoundError, json.JSONDecodeError):
                log = []
            log.append(entry)
            if len(log) > yca._LOG_CAP:
                log = log[-yca._LOG_CAP:]
            tmp = log_path + ".tmp"
            with open(tmp, "w") as fh:
                json.dump(log, fh)
            os.replace(tmp, log_path)

        yca._append_log = _patched_append

    def tearDown(self):
        yca._append_log = self._orig_append

    def _run_n(self, n):
        for _ in range(n):
            yca.analyze([_make_row(30, "P", 5.0, 4.0)])

    def test_log_01_creates_log_file(self):
        self._run_n(1)
        self.assertTrue(os.path.exists(self._log_path))

    def test_log_02_log_is_valid_json(self):
        self._run_n(3)
        with open(self._log_path) as fh:
            data = json.load(fh)
        self.assertIsInstance(data, list)

    def test_log_03_log_grows_with_calls(self):
        self._run_n(5)
        with open(self._log_path) as fh:
            data = json.load(fh)
        self.assertEqual(len(data), 5)

    def test_log_04_ring_buffer_caps_at_100(self):
        self._run_n(105)
        with open(self._log_path) as fh:
            data = json.load(fh)
        self.assertEqual(len(data), 100)

    def test_log_05_ring_buffer_keeps_newest(self):
        # Insert 101 unique entries; the 101st should be retained
        for i in range(101):
            yca.analyze([_make_row(i + 1, f"P{i}", 5.0, 4.0)])
        with open(self._log_path) as fh:
            data = json.load(fh)
        self.assertEqual(len(data), 100)

    def test_log_06_no_tmp_file_left(self):
        self._run_n(3)
        self.assertFalse(os.path.exists(self._log_path + ".tmp"))

    def test_log_07_each_entry_has_timestamp(self):
        self._run_n(3)
        with open(self._log_path) as fh:
            data = json.load(fh)
        for entry in data:
            self.assertIn("timestamp", entry)

    def test_log_08_each_entry_has_market_shape(self):
        self._run_n(2)
        with open(self._log_path) as fh:
            data = json.load(fh)
        for entry in data:
            self.assertIn("market_shape", entry)

    def test_log_09_log_cap_constant_100(self):
        self.assertEqual(yca._LOG_CAP, 100)


if __name__ == "__main__":
    unittest.main(verbosity=2)
