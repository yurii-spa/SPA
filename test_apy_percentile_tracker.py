"""
Tests for APYPercentileTracker (MP-644).

spa_core/tests/test_apy_percentile_tracker.py

Runs under both ``python3 -m unittest`` and pytest. All I/O is confined to a
tempfile.TemporaryDirectory — the production data/ dir is never touched.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

# Ensure spa_core package is importable
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from spa_core.analytics.apy_percentile_tracker import (
    APYPercentileTracker,
    AdapterPercentile,
    _classify_zone,
    _compute_percentile,
    _safe_float,
    _atomic_write,
    _now_iso,
    _RING_BUFFER_MAX,
    _TELEGRAM_MAX_CHARS,
    _OUTPUT_FILENAME,
    _ZONE_AT_HIGH_LABEL,
    _ZONE_ELEVATED_LABEL,
    _ZONE_NORMAL_LABEL,
    _ZONE_LOW_LABEL,
    _ZONE_AT_LOW_LABEL,
    _ZONE_UNKNOWN_LABEL,
)

_MODULE = "spa_core.analytics.apy_percentile_tracker"


# ---------------------------------------------------------------------------
# _safe_float
# ---------------------------------------------------------------------------

class TestSafeFloat(unittest.TestCase):

    def test_int(self):
        self.assertEqual(_safe_float(5), 5.0)

    def test_float(self):
        self.assertEqual(_safe_float(3.14), 3.14)

    def test_str(self):
        self.assertEqual(_safe_float("2.5"), 2.5)

    def test_bool_true(self):
        self.assertIsNone(_safe_float(True))

    def test_bool_false(self):
        self.assertIsNone(_safe_float(False))

    def test_none(self):
        self.assertIsNone(_safe_float(None))

    def test_garbage(self):
        self.assertIsNone(_safe_float("xyz"))

    def test_list(self):
        self.assertIsNone(_safe_float([1]))


# ---------------------------------------------------------------------------
# _compute_percentile
# ---------------------------------------------------------------------------

class TestComputePercentile(unittest.TestCase):

    def test_empty_history(self):
        self.assertEqual(_compute_percentile(5.0, []), 0.0)

    def test_all_below(self):
        # current above all → 100
        self.assertEqual(_compute_percentile(10.0, [1.0, 2.0, 3.0]), 100.0)

    def test_all_above(self):
        # current below all → 0
        self.assertEqual(_compute_percentile(0.5, [1.0, 2.0, 3.0]), 0.0)

    def test_median(self):
        # [1,2,3,4]; current=2 → values<=2 are {1,2} → 2/4 = 50
        self.assertEqual(_compute_percentile(2.0, [1.0, 2.0, 3.0, 4.0]), 50.0)

    def test_current_equals_one(self):
        # current matches one value → counted (<=)
        self.assertEqual(_compute_percentile(3.0, [1.0, 3.0, 5.0, 7.0, 9.0]), 40.0)

    def test_all_equal(self):
        # current == all → all <= → 100
        self.assertEqual(_compute_percentile(5.0, [5.0, 5.0, 5.0]), 100.0)

    def test_single_history(self):
        self.assertEqual(_compute_percentile(5.0, [5.0]), 100.0)

    def test_single_history_below(self):
        self.assertEqual(_compute_percentile(1.0, [5.0]), 0.0)

    def test_known_array_quarter(self):
        hist = [10.0, 20.0, 30.0, 40.0]
        # current=10 → {10} <= → 1/4 = 25
        self.assertEqual(_compute_percentile(10.0, hist), 25.0)

    def test_known_array_three_quarter(self):
        hist = [10.0, 20.0, 30.0, 40.0]
        # current=30 → {10,20,30} → 3/4 = 75
        self.assertEqual(_compute_percentile(30.0, hist), 75.0)

    def test_clamped_high(self):
        self.assertLessEqual(_compute_percentile(99.0, [1.0, 2.0]), 100.0)

    def test_clamped_low(self):
        self.assertGreaterEqual(_compute_percentile(-99.0, [1.0, 2.0]), 0.0)


# ---------------------------------------------------------------------------
# _classify_zone boundaries
# ---------------------------------------------------------------------------

class TestClassifyZone(unittest.TestCase):

    def test_none_unknown(self):
        self.assertEqual(_classify_zone(None), _ZONE_UNKNOWN_LABEL)

    def test_at_high_exact_80(self):
        self.assertEqual(_classify_zone(80.0), _ZONE_AT_HIGH_LABEL)

    def test_at_high_100(self):
        self.assertEqual(_classify_zone(100.0), _ZONE_AT_HIGH_LABEL)

    def test_at_high_above(self):
        self.assertEqual(_classify_zone(95.0), _ZONE_AT_HIGH_LABEL)

    def test_elevated_just_below_80(self):
        self.assertEqual(_classify_zone(79.99), _ZONE_ELEVATED_LABEL)

    def test_elevated_exact_60(self):
        self.assertEqual(_classify_zone(60.0), _ZONE_ELEVATED_LABEL)

    def test_normal_just_below_60(self):
        self.assertEqual(_classify_zone(59.99), _ZONE_NORMAL_LABEL)

    def test_normal_exact_40(self):
        self.assertEqual(_classify_zone(40.0), _ZONE_NORMAL_LABEL)

    def test_low_just_below_40(self):
        self.assertEqual(_classify_zone(39.99), _ZONE_LOW_LABEL)

    def test_low_exact_20(self):
        self.assertEqual(_classify_zone(20.0), _ZONE_LOW_LABEL)

    def test_at_low_just_below_20(self):
        self.assertEqual(_classify_zone(19.99), _ZONE_AT_LOW_LABEL)

    def test_at_low_zero(self):
        self.assertEqual(_classify_zone(0.0), _ZONE_AT_LOW_LABEL)


# ---------------------------------------------------------------------------
# compute_adapter
# ---------------------------------------------------------------------------

class TestComputeAdapter(unittest.TestCase):

    def setUp(self):
        self.t = APYPercentileTracker(data_dir=tempfile.mkdtemp())

    def test_too_short_history_unknown(self):
        ap = self.t.compute_adapter("x", 5.0, [5.0])
        self.assertEqual(ap.zone, _ZONE_UNKNOWN_LABEL)
        self.assertIsNone(ap.percentile)

    def test_empty_history_unknown(self):
        ap = self.t.compute_adapter("x", 5.0, [])
        self.assertEqual(ap.zone, _ZONE_UNKNOWN_LABEL)
        self.assertIsNone(ap.percentile)
        self.assertIsNone(ap.history_min)

    def test_two_points_computes(self):
        ap = self.t.compute_adapter("x", 5.0, [4.0, 6.0])
        self.assertIsNotNone(ap.percentile)
        self.assertEqual(ap.history_len, 2)

    def test_at_high(self):
        ap = self.t.compute_adapter("x", 100.0, [1.0, 2.0, 3.0, 4.0, 5.0])
        self.assertEqual(ap.zone, _ZONE_AT_HIGH_LABEL)
        self.assertEqual(ap.percentile, 100.0)

    def test_at_low(self):
        ap = self.t.compute_adapter("x", 0.0, [1.0, 2.0, 3.0, 4.0, 5.0])
        self.assertEqual(ap.zone, _ZONE_AT_LOW_LABEL)
        self.assertEqual(ap.percentile, 0.0)

    def test_history_min_max(self):
        ap = self.t.compute_adapter("x", 3.0, [1.0, 9.0])
        self.assertEqual(ap.history_min, 1.0)
        self.assertEqual(ap.history_max, 9.0)

    def test_current_apy_preserved(self):
        ap = self.t.compute_adapter("x", 7.7, [1.0, 2.0])
        self.assertEqual(ap.current_apy, 7.7)

    def test_garbage_in_history_filtered(self):
        ap = self.t.compute_adapter("x", 3.0, [1.0, "bad", None, 5.0])
        self.assertEqual(ap.history_len, 2)

    def test_all_garbage_history_unknown(self):
        ap = self.t.compute_adapter("x", 3.0, ["a", None, True])
        self.assertEqual(ap.zone, _ZONE_UNKNOWN_LABEL)

    def test_adapter_id_preserved(self):
        ap = self.t.compute_adapter("aave_v3", 3.0, [1.0, 2.0])
        self.assertEqual(ap.adapter_id, "aave_v3")


# ---------------------------------------------------------------------------
# generate_report
# ---------------------------------------------------------------------------

class TestGenerateReport(unittest.TestCase):

    def setUp(self):
        self.t = APYPercentileTracker(data_dir=tempfile.mkdtemp())

    def test_empty_maps(self):
        rep = self.t.generate_report({}, {})
        self.assertEqual(rep["adapter_count"], 0)
        self.assertEqual(rep["adapters"], [])

    def test_has_generated_at(self):
        rep = self.t.generate_report({}, {})
        self.assertIn("generated_at", rep)

    def test_has_advisory(self):
        rep = self.t.generate_report({}, {})
        self.assertIn("advisory", rep)
        self.assertIn("mean-reversion", rep["advisory"])

    def test_single_adapter(self):
        rep = self.t.generate_report(
            {"a": 5.0}, {"a": [1.0, 2.0, 3.0, 4.0, 5.0]}
        )
        self.assertEqual(rep["adapter_count"], 1)
        self.assertEqual(rep["adapters"][0]["zone"], _ZONE_AT_HIGH_LABEL)

    def test_multiple_adapters_sorted(self):
        rep = self.t.generate_report(
            {"zeta": 1.0, "alpha": 1.0},
            {"zeta": [1.0, 2.0], "alpha": [1.0, 2.0]},
        )
        ids = [a["adapter_id"] for a in rep["adapters"]]
        self.assertEqual(ids, sorted(ids))

    def test_zone_counts(self):
        rep = self.t.generate_report(
            {"high": 100.0, "low": 0.0, "new": 5.0},
            {
                "high": [1.0, 2.0, 3.0],
                "low": [10.0, 20.0, 30.0],
                "new": [5.0],  # < 2 points → UNKNOWN
            },
        )
        zc = rep["zone_counts"]
        self.assertEqual(zc[_ZONE_AT_HIGH_LABEL], 1)
        self.assertEqual(zc[_ZONE_AT_LOW_LABEL], 1)
        self.assertEqual(zc[_ZONE_UNKNOWN_LABEL], 1)

    def test_missing_history_unknown(self):
        rep = self.t.generate_report({"a": 5.0}, {})
        self.assertEqual(rep["adapters"][0]["zone"], _ZONE_UNKNOWN_LABEL)

    def test_history_not_list(self):
        rep = self.t.generate_report({"a": 5.0}, {"a": "broken"})
        self.assertEqual(rep["adapters"][0]["zone"], _ZONE_UNKNOWN_LABEL)

    def test_garbage_current_apy(self):
        rep = self.t.generate_report({"a": "bad"}, {"a": [1.0, 2.0]})
        self.assertEqual(rep["adapters"][0]["current_apy"], 0.0)

    def test_apy_map_not_dict(self):
        rep = self.t.generate_report(None, {})  # type: ignore
        self.assertEqual(rep["adapter_count"], 0)

    def test_all_zones_present_in_counts(self):
        rep = self.t.generate_report({}, {})
        for z in [
            _ZONE_AT_HIGH_LABEL, _ZONE_ELEVATED_LABEL, _ZONE_NORMAL_LABEL,
            _ZONE_LOW_LABEL, _ZONE_AT_LOW_LABEL, _ZONE_UNKNOWN_LABEL,
        ]:
            self.assertIn(z, rep["zone_counts"])


# ---------------------------------------------------------------------------
# Stub creation
# ---------------------------------------------------------------------------

class TestStub(unittest.TestCase):

    def test_stub_created_on_init(self):
        with tempfile.TemporaryDirectory() as d:
            APYPercentileTracker(data_dir=d)
            self.assertTrue((Path(d) / _OUTPUT_FILENAME).exists())

    def test_stub_is_empty_list(self):
        with tempfile.TemporaryDirectory() as d:
            APYPercentileTracker(data_dir=d)
            with open(Path(d) / _OUTPUT_FILENAME) as fh:
                data = json.load(fh)
            self.assertEqual(data, [])

    def test_stub_does_not_overwrite(self):
        with tempfile.TemporaryDirectory() as d:
            out = Path(d) / _OUTPUT_FILENAME
            with open(out, "w") as fh:
                json.dump([{"x": 1}], fh)
            APYPercentileTracker(data_dir=d)
            with open(out) as fh:
                data = json.load(fh)
            self.assertEqual(data, [{"x": 1}])


# ---------------------------------------------------------------------------
# save_report — atomic, ring-buffer
# ---------------------------------------------------------------------------

class TestSaveReport(unittest.TestCase):

    def test_creates_file(self):
        with tempfile.TemporaryDirectory() as d:
            t = APYPercentileTracker(data_dir=d)
            rep = t.generate_report({"a": 5.0}, {"a": [1.0, 2.0]})
            path = t.save_report(rep)
            self.assertTrue(os.path.exists(path))

    def test_valid_json(self):
        with tempfile.TemporaryDirectory() as d:
            t = APYPercentileTracker(data_dir=d)
            rep = t.generate_report({"a": 5.0}, {"a": [1.0, 2.0]})
            t.save_report(rep)
            with open(Path(d) / _OUTPUT_FILENAME) as fh:
                data = json.load(fh)
            self.assertIsInstance(data, list)

    def test_appends(self):
        with tempfile.TemporaryDirectory() as d:
            t = APYPercentileTracker(data_dir=d)
            t.save_report(t.generate_report({"a": 5.0}, {"a": [1.0, 2.0]}))
            t.save_report(t.generate_report({"a": 5.0}, {"a": [1.0, 2.0]}))
            with open(Path(d) / _OUTPUT_FILENAME) as fh:
                data = json.load(fh)
            self.assertEqual(len(data), 2)

    def test_ring_buffer_cap(self):
        with tempfile.TemporaryDirectory() as d:
            t = APYPercentileTracker(data_dir=d)
            for _ in range(_RING_BUFFER_MAX + 7):
                t.save_report(t.generate_report({"a": 5.0}, {"a": [1.0, 2.0]}))
            with open(Path(d) / _OUTPUT_FILENAME) as fh:
                data = json.load(fh)
            self.assertEqual(len(data), _RING_BUFFER_MAX)

    def test_no_tmp_left(self):
        with tempfile.TemporaryDirectory() as d:
            t = APYPercentileTracker(data_dir=d)
            t.save_report(t.generate_report({"a": 5.0}, {"a": [1.0, 2.0]}))
            leftovers = [
                p for p in Path(d).glob(".tmp_apy_percentile_*")
            ]
            self.assertEqual(leftovers, [])

    def test_corrupt_existing_recovered(self):
        with tempfile.TemporaryDirectory() as d:
            out = Path(d) / _OUTPUT_FILENAME
            t = APYPercentileTracker(data_dir=d)
            with open(out, "w") as fh:
                fh.write("{not a list")
            t.save_report(t.generate_report({"a": 5.0}, {"a": [1.0, 2.0]}))
            with open(out) as fh:
                data = json.load(fh)
            self.assertEqual(len(data), 1)

    def test_existing_not_list_recovered(self):
        with tempfile.TemporaryDirectory() as d:
            out = Path(d) / _OUTPUT_FILENAME
            t = APYPercentileTracker(data_dir=d)
            with open(out, "w") as fh:
                json.dump({"not": "a list"}, fh)
            t.save_report(t.generate_report({"a": 5.0}, {"a": [1.0, 2.0]}))
            with open(out) as fh:
                data = json.load(fh)
            self.assertEqual(len(data), 1)

    def test_returns_path(self):
        with tempfile.TemporaryDirectory() as d:
            t = APYPercentileTracker(data_dir=d)
            path = t.save_report(t.generate_report({}, {}))
            self.assertTrue(path.endswith(_OUTPUT_FILENAME))


# ---------------------------------------------------------------------------
# format_telegram_message
# ---------------------------------------------------------------------------

class TestTelegram(unittest.TestCase):

    def setUp(self):
        self.t = APYPercentileTracker(data_dir=tempfile.mkdtemp())

    def test_empty_report(self):
        msg = self.t.format_telegram_message({})
        self.assertIn("No adapter data", msg)

    def test_no_adapters(self):
        rep = self.t.generate_report({}, {})
        msg = self.t.format_telegram_message(rep)
        self.assertIn("No adapter data", msg)

    def test_header(self):
        rep = self.t.generate_report({"a": 5.0}, {"a": [1.0, 2.0]})
        msg = self.t.format_telegram_message(rep)
        self.assertIn("APY Percentile Tracker", msg)

    def test_contains_adapter(self):
        rep = self.t.generate_report({"aave": 5.0}, {"aave": [1.0, 2.0, 3.0]})
        msg = self.t.format_telegram_message(rep)
        self.assertIn("aave", msg)

    def test_length_cap(self):
        apy_map = {f"adapter_{i}": float(i) for i in range(500)}
        history_map = {f"adapter_{i}": [1.0, 2.0, 3.0] for i in range(500)}
        rep = self.t.generate_report(apy_map, history_map)
        msg = self.t.format_telegram_message(rep)
        self.assertLessEqual(len(msg), _TELEGRAM_MAX_CHARS)

    def test_unknown_zone_shown(self):
        rep = self.t.generate_report({"new": 5.0}, {"new": [5.0]})
        msg = self.t.format_telegram_message(rep)
        self.assertIn("UNKNOWN", msg)

    def test_non_dict_report(self):
        msg = self.t.format_telegram_message("garbage")  # type: ignore
        self.assertIn("No adapter data", msg)


# ---------------------------------------------------------------------------
# AdapterPercentile to_dict / from_dict
# ---------------------------------------------------------------------------

class TestAdapterPercentileSerialization(unittest.TestCase):

    def test_to_dict_keys(self):
        ap = AdapterPercentile("a", 5.0, 50.0, _ZONE_NORMAL_LABEL, 4, 1.0, 9.0)
        dd = ap.to_dict()
        for k in [
            "adapter_id", "current_apy", "percentile", "zone",
            "history_len", "history_min", "history_max",
        ]:
            self.assertIn(k, dd)

    def test_to_dict_none_percentile(self):
        ap = AdapterPercentile("a", 5.0, None, _ZONE_UNKNOWN_LABEL, 1, None, None)
        dd = ap.to_dict()
        self.assertIsNone(dd["percentile"])
        self.assertIsNone(dd["history_min"])

    def test_round_trip(self):
        ap = AdapterPercentile("a", 5.0, 50.0, _ZONE_NORMAL_LABEL, 4, 1.0, 9.0)
        ap2 = AdapterPercentile.from_dict(ap.to_dict())
        self.assertEqual(ap2.adapter_id, "a")
        self.assertEqual(ap2.zone, _ZONE_NORMAL_LABEL)
        self.assertEqual(ap2.history_len, 4)
        self.assertAlmostEqual(ap2.percentile, 50.0)

    def test_round_trip_none(self):
        ap = AdapterPercentile("a", 5.0, None, _ZONE_UNKNOWN_LABEL, 1, None, None)
        ap2 = AdapterPercentile.from_dict(ap.to_dict())
        self.assertIsNone(ap2.percentile)
        self.assertIsNone(ap2.history_min)

    def test_json_serializable(self):
        ap = AdapterPercentile("a", 5.0, 50.0, _ZONE_NORMAL_LABEL, 4, 1.0, 9.0)
        json.dumps(ap.to_dict())  # must not raise

    def test_from_dict_defaults(self):
        ap = AdapterPercentile.from_dict({})
        self.assertEqual(ap.adapter_id, "")
        self.assertEqual(ap.zone, _ZONE_UNKNOWN_LABEL)


# ---------------------------------------------------------------------------
# _atomic_write / _now_iso
# ---------------------------------------------------------------------------

class TestHelpers(unittest.TestCase):

    def test_atomic_write_creates(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "x.json"
            _atomic_write(p, [1, 2, 3])
            with open(p) as fh:
                self.assertEqual(json.load(fh), [1, 2, 3])

    def test_atomic_write_no_tmp_left(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "x.json"
            _atomic_write(p, {"a": 1})
            tmps = list(Path(d).glob(".tmp*"))
            self.assertEqual(tmps, [])

    def test_now_iso_format(self):
        ts = _now_iso()
        self.assertIn("T", ts)
        self.assertTrue(ts.endswith("+00:00") or ts.endswith("Z"))


# ---------------------------------------------------------------------------
# CLI via subprocess
# ---------------------------------------------------------------------------

class TestCLI(unittest.TestCase):

    def _run(self, extra_args):
        repo_root = str(Path(__file__).resolve().parents[2])
        cmd = [sys.executable, "-m", _MODULE] + extra_args
        return subprocess.run(
            cmd, cwd=repo_root, capture_output=True, text=True, timeout=60
        )

    def test_check_exit_zero(self):
        with tempfile.TemporaryDirectory() as d:
            res = self._run(["--check", "--data-dir", d])
            self.assertEqual(res.returncode, 0)

    def test_check_does_not_append(self):
        with tempfile.TemporaryDirectory() as d:
            self._run(["--check", "--data-dir", d])
            # stub created ([]) but check should not append a report
            with open(Path(d) / _OUTPUT_FILENAME) as fh:
                data = json.load(fh)
            self.assertEqual(data, [])

    def test_run_exit_zero(self):
        with tempfile.TemporaryDirectory() as d:
            res = self._run(["--run", "--data-dir", d])
            self.assertEqual(res.returncode, 0)

    def test_run_writes_report(self):
        with tempfile.TemporaryDirectory() as d:
            self._run(["--run", "--data-dir", d])
            with open(Path(d) / _OUTPUT_FILENAME) as fh:
                data = json.load(fh)
            self.assertGreaterEqual(len(data), 1)

    def test_default_exit_zero(self):
        with tempfile.TemporaryDirectory() as d:
            res = self._run(["--data-dir", d])
            self.assertEqual(res.returncode, 0)

    def test_stub_created_by_cli(self):
        with tempfile.TemporaryDirectory() as d:
            self._run(["--check", "--data-dir", d])
            self.assertTrue((Path(d) / _OUTPUT_FILENAME).exists())


if __name__ == "__main__":
    unittest.main()
