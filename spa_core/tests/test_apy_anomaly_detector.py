#!/usr/bin/env python3
"""Unit tests for MP-771 APYAnomalyDetector (SPA-V622).

Run:
    python3 -m unittest spa_core/tests/test_apy_anomaly_detector.py -v

All tests use stdlib unittest only — no pytest, no numpy.
"""
import json
import math
import os
import sys
import tempfile
import unittest
from pathlib import Path

# Ensure project root on path
_REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO_ROOT))

from spa_core.analytics.apy_anomaly_detector import (
    APYAnomalyDetector,
    _mean,
    _population_std,
    _compute_z_score,
    _label,
    _severity,
    _detect_single,
    _load_json_list,
    _atomic_write,
    detect_anomalies,
    write_status,
    DEFAULT_THRESHOLD,
    RING_BUFFER_CAP,
    LOG_FILENAME,
    SEV_LOW_LO,
    SEV_MEDIUM_LO,
    SEV_HIGH_LO,
)


# ===========================================================================
# 1. Statistical helpers — _mean
# ===========================================================================

class TestMean(unittest.TestCase):

    def test_mean_empty_returns_none(self):
        self.assertIsNone(_mean([]))

    def test_mean_single(self):
        self.assertAlmostEqual(_mean([5.0]), 5.0, places=10)

    def test_mean_two_values(self):
        self.assertAlmostEqual(_mean([2.0, 4.0]), 3.0, places=10)

    def test_mean_all_same(self):
        self.assertAlmostEqual(_mean([3.0, 3.0, 3.0]), 3.0, places=10)

    def test_mean_mixed(self):
        self.assertAlmostEqual(_mean([0.03, 0.05, 0.04]), 0.04, places=10)

    def test_mean_with_zero(self):
        self.assertAlmostEqual(_mean([0.0, 0.0, 0.0]), 0.0, places=10)

    def test_mean_large_list(self):
        series = list(range(1, 101))
        self.assertAlmostEqual(_mean(series), 50.5, places=10)


# ===========================================================================
# 2. Statistical helpers — _population_std
# ===========================================================================

class TestPopulationStd(unittest.TestCase):

    def test_std_empty_returns_none(self):
        self.assertIsNone(_population_std([]))

    def test_std_single_value_is_zero(self):
        self.assertAlmostEqual(_population_std([5.0]), 0.0, places=10)

    def test_std_all_same_is_zero(self):
        self.assertAlmostEqual(_population_std([3.0, 3.0, 3.0]), 0.0, places=10)

    def test_std_known_values(self):
        # [2, 4, 4, 4, 5, 5, 7, 9] → pop std = 2.0
        result = _population_std([2, 4, 4, 4, 5, 5, 7, 9])
        self.assertAlmostEqual(result, 2.0, places=8)

    def test_std_two_values(self):
        # [0, 2] → mean=1, var=1, std=1
        self.assertAlmostEqual(_population_std([0.0, 2.0]), 1.0, places=10)

    def test_std_symmetry(self):
        self.assertAlmostEqual(
            _population_std([1.0, 2.0, 3.0]),
            _population_std([3.0, 2.0, 1.0]),
            places=10,
        )

    def test_std_non_negative(self):
        for series in [[0.03, 0.05], [0.1], [0.0, 0.0, 0.5]]:
            result = _population_std(series)
            if result is not None:
                self.assertGreaterEqual(result, 0.0)


# ===========================================================================
# 3. _compute_z_score
# ===========================================================================

class TestComputeZScore(unittest.TestCase):

    def test_empty_history_returns_none_z(self):
        z, mu, sigma, notes = _compute_z_score(0.05, [])
        self.assertIsNone(z)
        self.assertIsNone(mu)
        self.assertIsNone(sigma)
        self.assertTrue(any("Empty" in n for n in notes))

    def test_single_data_point_std_zero_current_equals_mean(self):
        z, mu, sigma, notes = _compute_z_score(0.05, [0.05])
        self.assertAlmostEqual(z, 0.0, places=10)
        self.assertAlmostEqual(mu, 0.05, places=10)
        self.assertAlmostEqual(sigma, 0.0, places=10)
        self.assertTrue(any("std_dev=0" in n for n in notes))

    def test_single_data_point_std_zero_current_differs(self):
        z, mu, sigma, notes = _compute_z_score(0.10, [0.05])
        self.assertIsNone(z)
        self.assertAlmostEqual(mu, 0.05, places=10)
        self.assertAlmostEqual(sigma, 0.0, places=10)
        self.assertTrue(any("indeterminate" in n for n in notes))

    def test_all_same_current_equals_mean(self):
        z, mu, sigma, notes = _compute_z_score(0.05, [0.05, 0.05, 0.05])
        self.assertAlmostEqual(z, 0.0, places=10)

    def test_all_same_current_differs(self):
        z, mu, sigma, notes = _compute_z_score(0.08, [0.05, 0.05, 0.05])
        self.assertIsNone(z)

    def test_z_score_positive_spike(self):
        history = [0.03, 0.04, 0.03, 0.04, 0.03]
        current = 0.20  # far above mean
        z, mu, sigma, _ = _compute_z_score(current, history)
        self.assertIsNotNone(z)
        self.assertGreater(z, 2.0)

    def test_z_score_negative_drop(self):
        history = [0.10, 0.11, 0.10, 0.11, 0.10]
        current = 0.01  # far below mean
        z, mu, sigma, _ = _compute_z_score(current, history)
        self.assertIsNotNone(z)
        self.assertLess(z, -2.0)

    def test_z_score_normal_range(self):
        history = [0.04, 0.05, 0.06, 0.04, 0.05]
        current = 0.045
        z, mu, sigma, _ = _compute_z_score(current, history)
        self.assertIsNotNone(z)
        self.assertGreater(abs(z), 0.0)
        self.assertLess(abs(z), 2.0)

    def test_z_score_mean_returned(self):
        history = [0.04, 0.06]
        z, mu, sigma, _ = _compute_z_score(0.05, history)
        self.assertAlmostEqual(mu, 0.05, places=10)

    def test_z_score_std_returned(self):
        history = [0.04, 0.06]
        z, mu, sigma, _ = _compute_z_score(0.05, history)
        expected_sigma = _population_std(history)
        self.assertAlmostEqual(sigma, expected_sigma, places=10)


# ===========================================================================
# 4. _label helper
# ===========================================================================

class TestLabel(unittest.TestCase):

    def test_none_z_is_normal(self):
        self.assertEqual(_label(None, 2.0), "NORMAL")

    def test_z_above_threshold_is_spike(self):
        self.assertEqual(_label(2.1, 2.0), "SPIKE")

    def test_z_below_neg_threshold_is_drop(self):
        self.assertEqual(_label(-2.1, 2.0), "DROP")

    def test_z_at_threshold_is_normal(self):
        self.assertEqual(_label(2.0, 2.0), "NORMAL")

    def test_z_at_neg_threshold_is_normal(self):
        self.assertEqual(_label(-2.0, 2.0), "NORMAL")

    def test_z_zero_is_normal(self):
        self.assertEqual(_label(0.0, 2.0), "NORMAL")

    def test_custom_threshold_low(self):
        self.assertEqual(_label(1.5, 1.0), "SPIKE")

    def test_custom_threshold_high(self):
        self.assertEqual(_label(2.0, 3.0), "NORMAL")

    def test_very_large_positive_z_is_spike(self):
        self.assertEqual(_label(100.0, 2.0), "SPIKE")

    def test_very_large_negative_z_is_drop(self):
        self.assertEqual(_label(-100.0, 2.0), "DROP")


# ===========================================================================
# 5. _severity helper
# ===========================================================================

class TestSeverity(unittest.TestCase):

    def test_none_z_returns_none(self):
        self.assertIsNone(_severity(None))

    def test_z_below_low_threshold_returns_none(self):
        self.assertIsNone(_severity(1.5))
        self.assertIsNone(_severity(-1.5))

    def test_z_at_low_boundary_is_low(self):
        self.assertEqual(_severity(SEV_LOW_LO), "LOW")
        self.assertEqual(_severity(-SEV_LOW_LO), "LOW")

    def test_z_in_low_range(self):
        self.assertEqual(_severity(2.5), "LOW")
        self.assertEqual(_severity(-2.5), "LOW")

    def test_z_just_below_medium_is_low(self):
        self.assertEqual(_severity(2.99), "LOW")

    def test_z_at_medium_boundary_is_medium(self):
        self.assertEqual(_severity(SEV_MEDIUM_LO), "MEDIUM")
        self.assertEqual(_severity(-SEV_MEDIUM_LO), "MEDIUM")

    def test_z_in_medium_range(self):
        self.assertEqual(_severity(3.5), "MEDIUM")
        self.assertEqual(_severity(-3.5), "MEDIUM")

    def test_z_just_below_high_is_medium(self):
        self.assertEqual(_severity(3.99), "MEDIUM")

    def test_z_at_high_boundary_is_high(self):
        self.assertEqual(_severity(SEV_HIGH_LO), "HIGH")
        self.assertEqual(_severity(-SEV_HIGH_LO), "HIGH")

    def test_z_above_high_is_high(self):
        self.assertEqual(_severity(10.0), "HIGH")
        self.assertEqual(_severity(-10.0), "HIGH")


# ===========================================================================
# 6. _detect_single
# ===========================================================================

class TestDetectSingle(unittest.TestCase):

    def _spike_history(self):
        return [0.03, 0.033, 0.031, 0.032, 0.034, 0.031, 0.033, 0.032]

    def test_returns_dict(self):
        r = _detect_single("p", [0.05, 0.06], 0.055)
        self.assertIsInstance(r, dict)

    def test_protocol_name_preserved(self):
        r = _detect_single("aave_v3", [0.05], 0.05)
        self.assertEqual(r["protocol"], "aave_v3")

    def test_normal_label_for_in_range_current(self):
        history = [0.05, 0.05, 0.05, 0.05, 0.05, 0.05, 0.05]
        r = _detect_single("p", history, 0.05)
        self.assertEqual(r["label"], "NORMAL")
        self.assertFalse(r["is_anomaly"])

    def test_spike_label_detected(self):
        history = self._spike_history()
        r = _detect_single("p", history, 0.30, threshold=2.0)
        self.assertEqual(r["label"], "SPIKE")
        self.assertTrue(r["is_anomaly"])

    def test_drop_label_detected(self):
        history = [0.10, 0.11, 0.10, 0.11, 0.10, 0.11, 0.10, 0.11]
        r = _detect_single("p", history, 0.001, threshold=2.0)
        self.assertEqual(r["label"], "DROP")
        self.assertTrue(r["is_anomaly"])

    def test_empty_history_is_normal(self):
        r = _detect_single("p", [], 0.05)
        self.assertEqual(r["label"], "NORMAL")
        self.assertFalse(r["is_anomaly"])
        self.assertIsNone(r["z_score"])

    def test_single_data_point_current_equals_history_is_normal(self):
        r = _detect_single("p", [0.05], 0.05)
        self.assertEqual(r["label"], "NORMAL")

    def test_single_data_point_current_differs_is_normal(self):
        # Indeterminate → NORMAL
        r = _detect_single("p", [0.05], 0.99)
        self.assertEqual(r["label"], "NORMAL")
        self.assertIsNone(r["z_score"])

    def test_severity_none_for_normal(self):
        history = [0.05, 0.05, 0.05, 0.05]
        r = _detect_single("p", history, 0.05)
        self.assertIsNone(r["severity"])

    def test_severity_low_for_moderate_spike(self):
        history = [0.03, 0.04, 0.05, 0.06, 0.07]
        mu = sum(history) / len(history)
        sigma = math.sqrt(sum((x - mu) ** 2 for x in history) / len(history))
        current = mu + 2.5 * sigma
        r = _detect_single("p", history, current, threshold=2.0)
        self.assertEqual(r["label"], "SPIKE")
        self.assertEqual(r["severity"], "LOW")

    def test_severity_medium_for_high_spike(self):
        history = [0.03, 0.04, 0.05, 0.06, 0.07]
        mu = sum(history) / len(history)
        sigma = math.sqrt(sum((x - mu) ** 2 for x in history) / len(history))
        current = mu + 3.5 * sigma
        r = _detect_single("p", history, current, threshold=2.0)
        self.assertEqual(r["severity"], "MEDIUM")

    def test_severity_high_for_extreme_spike(self):
        history = [0.03, 0.04, 0.05, 0.06, 0.07]
        mu = sum(history) / len(history)
        sigma = math.sqrt(sum((x - mu) ** 2 for x in history) / len(history))
        current = mu + 4.5 * sigma
        r = _detect_single("p", history, current, threshold=2.0)
        self.assertEqual(r["severity"], "HIGH")

    def test_required_keys_present(self):
        r = _detect_single("p", [0.05], 0.05)
        for key in [
            "protocol", "current_apy", "history_len", "mean_apy",
            "std_dev_apy", "z_score", "threshold", "label",
            "is_anomaly", "severity", "warnings",
        ]:
            self.assertIn(key, r, f"Missing key: {key}")

    def test_history_len_reported(self):
        r = _detect_single("p", [0.03, 0.04, 0.05], 0.05)
        self.assertEqual(r["history_len"], 3)

    def test_custom_threshold_tighter(self):
        history = [0.03, 0.04, 0.05, 0.06, 0.07]
        mu = sum(history) / len(history)
        sigma = math.sqrt(sum((x - mu) ** 2 for x in history) / len(history))
        current = mu + 1.2 * sigma
        r_default = _detect_single("p", history, current, threshold=2.0)
        r_tight = _detect_single("p", history, current, threshold=1.0)
        self.assertEqual(r_default["label"], "NORMAL")
        self.assertEqual(r_tight["label"], "SPIKE")


# ===========================================================================
# 7. APYAnomalyDetector.detect()
# ===========================================================================

class TestDetectorDetect(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.detector = APYAnomalyDetector(data_dir=self.tmp)

    def _history(self):
        return {
            "aave_v3": [0.03, 0.031, 0.032, 0.03, 0.031],
            "compound": [0.05, 0.051, 0.049, 0.05, 0.051],
        }

    def test_detect_returns_dict(self):
        r = self.detector.detect({}, {})
        self.assertIsInstance(r, dict)

    def test_detect_empty_current_apys(self):
        r = self.detector.detect({}, {})
        self.assertEqual(r["protocol_count"], 0)
        self.assertEqual(r["anomaly_count"], 0)

    def test_detect_schema_version(self):
        r = self.detector.detect({}, {})
        self.assertEqual(r["schema_version"], 1)

    def test_detect_mp_tag(self):
        r = self.detector.detect({}, {})
        self.assertEqual(r["mp_tag"], "MP-771")

    def test_detect_protocol_count(self):
        r = self.detector.detect(self._history(), {"aave_v3": 0.031, "compound": 0.050})
        self.assertEqual(r["protocol_count"], 2)

    def test_detect_no_anomalies_when_all_normal(self):
        hist = self._history()
        current = {"aave_v3": 0.031, "compound": 0.050}
        r = self.detector.detect(hist, current)
        self.assertEqual(r["anomaly_count"], 0)
        self.assertEqual(len(r["anomalies"]), 0)

    def test_detect_all_anomalies_when_all_spike(self):
        hist = self._history()
        current = {"aave_v3": 1.0, "compound": 1.0}  # extreme spikes
        r = self.detector.detect(hist, current, threshold=2.0)
        self.assertEqual(r["anomaly_count"], 2)

    def test_detect_one_spike_one_normal(self):
        hist = self._history()
        current = {"aave_v3": 1.0, "compound": 0.050}
        r = self.detector.detect(hist, current, threshold=2.0)
        self.assertEqual(r["anomaly_count"], 1)

    def test_detect_anomalies_list_contains_only_anomalies(self):
        hist = self._history()
        current = {"aave_v3": 1.0, "compound": 0.050}
        r = self.detector.detect(hist, current, threshold=2.0)
        for a in r["anomalies"]:
            self.assertTrue(a["is_anomaly"])

    def test_detect_per_protocol_all_included(self):
        hist = self._history()
        current = {"aave_v3": 0.031, "compound": 0.050}
        r = self.detector.detect(hist, current)
        protos = {p["protocol"] for p in r["per_protocol"]}
        self.assertIn("aave_v3", protos)
        self.assertIn("compound", protos)

    def test_detect_threshold_default_is_2(self):
        r = self.detector.detect({}, {})
        self.assertAlmostEqual(r["threshold"], DEFAULT_THRESHOLD, places=4)

    def test_detect_custom_threshold_stored(self):
        r = self.detector.detect({}, {}, threshold=1.5)
        self.assertAlmostEqual(r["threshold"], 1.5, places=4)

    def test_detect_summary_total_matches_protocol_count(self):
        hist = self._history()
        current = {"aave_v3": 0.031, "compound": 0.050}
        r = self.detector.detect(hist, current)
        self.assertEqual(r["summary"]["total"], r["protocol_count"])

    def test_detect_summary_spike_plus_drop_plus_normal_equals_total(self):
        hist = self._history()
        current = {"aave_v3": 0.031, "compound": 0.050}
        r = self.detector.detect(hist, current)
        s = r["summary"]
        self.assertEqual(s["SPIKE"] + s["DROP"] + s["NORMAL"], s["total"])

    def test_detect_stores_last_result(self):
        self.assertIsNone(self.detector._last_result)
        self.detector.detect({}, {})
        self.assertIsNotNone(self.detector._last_result)

    def test_detect_missing_history_uses_empty(self):
        r = self.detector.detect({}, {"new_proto": 0.05})
        pp = r["per_protocol"][0]
        self.assertEqual(pp["history_len"], 0)
        self.assertEqual(pp["label"], "NORMAL")

    def test_detect_drop_labelled_correctly(self):
        hist = {"p": [0.10, 0.11, 0.10, 0.11, 0.10, 0.11]}
        r = self.detector.detect(hist, {"p": 0.001}, threshold=2.0)
        self.assertEqual(r["per_protocol"][0]["label"], "DROP")

    def test_detect_result_json_serialisable(self):
        r = self.detector.detect(self._history(), {"aave_v3": 0.031})
        try:
            json.dumps(r)
        except (TypeError, ValueError) as e:
            self.fail(f"detect() result not JSON-serialisable: {e}")


# ===========================================================================
# 8. APYAnomalyDetector.get_anomalies()
# ===========================================================================

class TestGetAnomalies(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.detector = APYAnomalyDetector(data_dir=self.tmp)

    def test_empty_before_detect(self):
        self.assertEqual(self.detector.get_anomalies(), [])

    def test_empty_when_no_anomalies(self):
        hist = {"p": [0.05, 0.05, 0.05, 0.05, 0.05]}
        self.detector.detect(hist, {"p": 0.05})
        self.assertEqual(self.detector.get_anomalies(), [])

    def test_returns_anomalies(self):
        hist = {"p": [0.03, 0.031, 0.032, 0.03, 0.031]}
        self.detector.detect(hist, {"p": 1.0}, threshold=2.0)
        anomalies = self.detector.get_anomalies()
        self.assertEqual(len(anomalies), 1)
        self.assertEqual(anomalies[0]["protocol"], "p")

    def test_returns_list(self):
        self.detector.detect({}, {})
        self.assertIsInstance(self.detector.get_anomalies(), list)

    def test_anomalies_are_is_anomaly_true(self):
        hist = {"p": [0.03, 0.031, 0.032, 0.03, 0.031]}
        self.detector.detect(hist, {"p": 1.0}, threshold=2.0)
        for a in self.detector.get_anomalies():
            self.assertTrue(a["is_anomaly"])


# ===========================================================================
# 9. APYAnomalyDetector.get_severity_summary()
# ===========================================================================

class TestGetSeveritySummary(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.detector = APYAnomalyDetector(data_dir=self.tmp)

    def test_empty_before_detect(self):
        s = self.detector.get_severity_summary()
        self.assertEqual(s["total"], 0)
        self.assertEqual(s["SPIKE"], 0)
        self.assertEqual(s["DROP"], 0)
        self.assertEqual(s["NORMAL"], 0)

    def test_summary_has_required_keys(self):
        self.detector.detect({}, {})
        s = self.detector.get_severity_summary()
        for k in ["total", "SPIKE", "DROP", "NORMAL", "LOW", "MEDIUM", "HIGH", "by_protocol"]:
            self.assertIn(k, s, f"Missing summary key: {k}")

    def test_summary_by_protocol_populated(self):
        hist = {"p": [0.05] * 5}
        self.detector.detect(hist, {"p": 0.05})
        s = self.detector.get_severity_summary()
        self.assertIn("p", s["by_protocol"])

    def test_summary_spike_count(self):
        hist = {
            "p1": [0.03, 0.031, 0.032, 0.030, 0.031],
            "p2": [0.05, 0.051, 0.049, 0.050, 0.051],
        }
        self.detector.detect(hist, {"p1": 1.0, "p2": 0.050}, threshold=2.0)
        s = self.detector.get_severity_summary()
        self.assertEqual(s["SPIKE"], 1)
        self.assertEqual(s["NORMAL"], 1)

    def test_summary_returns_copy(self):
        self.detector.detect({}, {})
        s1 = self.detector.get_severity_summary()
        s1["SPIKE"] = 9999
        s2 = self.detector.get_severity_summary()
        self.assertNotEqual(s2.get("SPIKE"), 9999)


# ===========================================================================
# 10. APYAnomalyDetector.save() — ring buffer & atomic write
# ===========================================================================

class TestDetectorSave(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.detector = APYAnomalyDetector(data_dir=self.tmp)

    def _log_path(self):
        return Path(self.tmp) / LOG_FILENAME

    def test_save_returns_false_before_detect(self):
        self.assertFalse(self.detector.save())

    def test_save_returns_true_after_detect(self):
        self.detector.detect({}, {})
        self.assertTrue(self.detector.save())

    def test_save_creates_file(self):
        self.detector.detect({}, {})
        self.detector.save()
        self.assertTrue(self._log_path().exists())

    def test_save_file_valid_json_list(self):
        self.detector.detect({}, {})
        self.detector.save()
        with open(self._log_path()) as f:
            data = json.load(f)
        self.assertIsInstance(data, list)

    def test_save_appends_entries(self):
        for _ in range(3):
            self.detector.detect({}, {})
            self.detector.save()
        with open(self._log_path()) as f:
            data = json.load(f)
        self.assertEqual(len(data), 3)

    def test_ring_buffer_caps(self):
        det = APYAnomalyDetector(data_dir=self.tmp, ring_cap=5)
        for i in range(8):
            det.detect({}, {f"proto_{i}": 0.05})
            det.save()
        with open(self._log_path()) as f:
            data = json.load(f)
        self.assertEqual(len(data), 5)

    def test_ring_buffer_keeps_newest_entries(self):
        det = APYAnomalyDetector(data_dir=self.tmp, ring_cap=3)
        for i in range(6):
            det.detect({}, {f"proto_{i}": 0.05})
            det.save()
        with open(self._log_path()) as f:
            data = json.load(f)
        protos_in_last = []
        for entry in data:
            for pp in entry.get("per_protocol", []):
                protos_in_last.append(pp.get("protocol"))
        self.assertIn("proto_5", protos_in_last)
        self.assertNotIn("proto_0", protos_in_last)

    def test_ring_buffer_default_cap(self):
        self.assertEqual(RING_BUFFER_CAP, 100)


# ===========================================================================
# 11. detect_anomalies functional API
# ===========================================================================

class TestDetectAnomaliesFunctional(unittest.TestCase):

    def test_returns_dict(self):
        r = detect_anomalies({}, {})
        self.assertIsInstance(r, dict)

    def test_empty_input(self):
        r = detect_anomalies({}, {})
        self.assertEqual(r["anomaly_count"], 0)

    def test_spike_detected(self):
        hist = {"p": [0.03, 0.031, 0.032, 0.030, 0.031]}
        r = detect_anomalies(hist, {"p": 1.0}, threshold=2.0)
        self.assertGreater(r["anomaly_count"], 0)

    def test_normal_not_anomaly(self):
        hist = {"p": [0.05] * 10}
        r = detect_anomalies(hist, {"p": 0.05})
        self.assertEqual(r["anomaly_count"], 0)

    def test_custom_threshold(self):
        history = [0.04, 0.05, 0.06, 0.04, 0.05]
        mu = sum(history) / len(history)
        sigma = math.sqrt(sum((x - mu) ** 2 for x in history) / len(history))
        current = mu + 1.2 * sigma
        r_default = detect_anomalies({"p": history}, {"p": current}, threshold=2.0)
        r_tight = detect_anomalies({"p": history}, {"p": current}, threshold=1.0)
        self.assertEqual(r_default["anomaly_count"], 0)
        self.assertEqual(r_tight["anomaly_count"], 1)


# ===========================================================================
# 12. write_status functional API
# ===========================================================================

class TestWriteStatusFunctional(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def test_creates_log_file(self):
        write_status({}, {}, data_dir=self.tmp)
        self.assertTrue((Path(self.tmp) / LOG_FILENAME).exists())

    def test_returns_dict(self):
        r = write_status({}, {}, data_dir=self.tmp)
        self.assertIsInstance(r, dict)

    def test_empty_input(self):
        r = write_status({}, {}, data_dir=self.tmp)
        self.assertEqual(r["anomaly_count"], 0)


# ===========================================================================
# 13. _atomic_write and _load_json_list
# ===========================================================================

class TestAtomicWriteLoad(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def test_atomic_write_creates_file(self):
        p = Path(self.tmp) / "test.json"
        _atomic_write(p, [{"key": "val"}])
        self.assertTrue(p.exists())

    def test_atomic_write_valid_json(self):
        p = Path(self.tmp) / "test.json"
        _atomic_write(p, {"a": 1})
        with open(p) as f:
            self.assertEqual(json.load(f), {"a": 1})

    def test_atomic_write_no_tmp_leftover(self):
        p = Path(self.tmp) / "test.json"
        _atomic_write(p, [])
        tmp_files = list(Path(self.tmp).rglob("*.tmp"))
        self.assertEqual(len(tmp_files), 0)

    def test_load_json_list_missing_file(self):
        p = Path(self.tmp) / "nonexistent.json"
        self.assertEqual(_load_json_list(p), [])

    def test_load_json_list_empty_list(self):
        p = Path(self.tmp) / "empty.json"
        p.write_text("[]")
        self.assertEqual(_load_json_list(p), [])

    def test_load_json_list_valid_data(self):
        p = Path(self.tmp) / "data.json"
        _atomic_write(p, [{"x": 1}, {"x": 2}])
        self.assertEqual(len(_load_json_list(p)), 2)

    def test_load_json_list_non_list_returns_empty(self):
        p = Path(self.tmp) / "obj.json"
        _atomic_write(p, {"key": "val"})
        self.assertEqual(_load_json_list(p), [])

    def test_load_json_list_invalid_json_returns_empty(self):
        p = Path(self.tmp) / "bad.json"
        p.write_text("not json {{")
        self.assertEqual(_load_json_list(p), [])


# ===========================================================================
# 14. Constants sanity
# ===========================================================================

class TestConstants(unittest.TestCase):

    def test_default_threshold(self):
        self.assertAlmostEqual(DEFAULT_THRESHOLD, 2.0, places=6)

    def test_ring_buffer_cap(self):
        self.assertEqual(RING_BUFFER_CAP, 100)

    def test_severity_boundaries_ordered(self):
        self.assertLess(SEV_LOW_LO, SEV_MEDIUM_LO)
        self.assertLess(SEV_MEDIUM_LO, SEV_HIGH_LO)

    def test_log_filename(self):
        self.assertEqual(LOG_FILENAME, "apy_anomaly_log.json")

    def test_sev_low_boundary(self):
        self.assertAlmostEqual(SEV_LOW_LO, 2.0, places=6)

    def test_sev_medium_boundary(self):
        self.assertAlmostEqual(SEV_MEDIUM_LO, 3.0, places=6)

    def test_sev_high_boundary(self):
        self.assertAlmostEqual(SEV_HIGH_LO, 4.0, places=6)


if __name__ == "__main__":
    unittest.main(verbosity=2)
