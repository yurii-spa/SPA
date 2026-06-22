"""
Tests for spa_core.analytics.performance_regression_detector (MP-635).

Coverage: 48 unit tests across:
  - TestRegressionAlertDataclass        (6)
  - TestSafeFloat                       (5)
  - TestDetectApyRegressionNone         (5)
  - TestDetectApyRegressionWarning      (4)
  - TestDetectApyRegressionCritical     (4)
  - TestDetectSharpeRegression          (6)
  - TestDetectDrawdownRegression        (6)
  - TestDetectAllocationDrift           (6)
  - TestScanAll                         (5)
  - TestLogAlertsRingBuffer             (5)
  - TestGenerateReport                  (8)
  - TestNowIso                          (1)   (total = 61)

Run:
  python3 -m pytest spa_core/tests/test_performance_regression_detector.py -v
  python3 -m unittest spa_core.tests.test_performance_regression_detector -v
"""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from typing import Optional

# ---------------------------------------------------------------------------
# Path setup
# ---------------------------------------------------------------------------
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from spa_core.analytics.performance_regression_detector import (
    RT_APY_DROP,
    RT_SHARPE_DROP,
    RT_DRAWDOWN_INCREASE,
    RT_ALLOCATION_DRIFT,
    SEV_CRITICAL,
    SEV_WARNING,
    _ALERTS_FILE,
    _RING_BUFFER_MAX,
    RegressionAlert,
    PerformanceRegressionDetector,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_detector(tmp_dir: Optional[str] = None) -> PerformanceRegressionDetector:
    if tmp_dir is None:
        tmp_dir = tempfile.mkdtemp()
    return PerformanceRegressionDetector(data_dir=tmp_dir)


def _alert(
    regression_type: str = RT_APY_DROP,
    adapter: str = "test_adapter",
    prev: float = 5.0,
    curr: float = 3.0,
    change_pct: float = -40.0,
    severity: str = SEV_WARNING,
    details: str = "test",
) -> RegressionAlert:
    return RegressionAlert(
        timestamp="2026-01-01T00:00:00+00:00",
        regression_type=regression_type,
        adapter_or_strategy=adapter,
        previous_value=prev,
        current_value=curr,
        change_pct=change_pct,
        severity=severity,
        details=details,
    )


# ===========================================================================
# TestRegressionAlertDataclass
# ===========================================================================

class TestRegressionAlertDataclass(unittest.TestCase):
    """Tests for RegressionAlert dataclass construction and serialisation."""

    def test_create_basic(self):
        a = _alert()
        self.assertEqual(a.regression_type, RT_APY_DROP)
        self.assertEqual(a.adapter_or_strategy, "test_adapter")

    def test_to_dict_has_all_keys(self):
        a = _alert()
        d = a.to_dict()
        expected = {
            "timestamp", "regression_type", "adapter_or_strategy",
            "previous_value", "current_value", "change_pct", "severity", "details",
        }
        self.assertEqual(set(d.keys()), expected)

    def test_from_dict_roundtrip(self):
        a = _alert(prev=10.5, curr=7.2, change_pct=-31.4)
        restored = RegressionAlert.from_dict(a.to_dict())
        self.assertAlmostEqual(restored.previous_value, 10.5)
        self.assertAlmostEqual(restored.current_value, 7.2)
        self.assertAlmostEqual(restored.change_pct, -31.4)

    def test_from_dict_coerces_floats(self):
        d = {
            "timestamp": "2026-01-01T00:00:00+00:00",
            "regression_type": RT_APY_DROP,
            "adapter_or_strategy": "foo",
            "previous_value": "5.0",
            "current_value": "3.5",
            "change_pct": "-30.0",
            "severity": SEV_WARNING,
            "details": "test",
        }
        a = RegressionAlert.from_dict(d)
        self.assertIsInstance(a.previous_value, float)
        self.assertIsInstance(a.current_value, float)

    def test_severity_field(self):
        a = _alert(severity=SEV_CRITICAL)
        self.assertEqual(a.severity, SEV_CRITICAL)

    def test_to_dict_is_json_serialisable(self):
        a = _alert()
        serialised = json.dumps(a.to_dict())
        self.assertIn("APY_DROP", serialised)


# ===========================================================================
# TestSafeFloat
# ===========================================================================

class TestSafeFloat(unittest.TestCase):
    """Tests for the internal _safe_float helper."""

    def setUp(self):
        self.det = _make_detector()

    def test_valid_float(self):
        self.assertAlmostEqual(self.det._safe_float(3.14), 3.14)

    def test_int_converts(self):
        self.assertAlmostEqual(self.det._safe_float(5), 5.0)

    def test_string_converts(self):
        self.assertAlmostEqual(self.det._safe_float("2.5"), 2.5)

    def test_none_returns_default(self):
        self.assertAlmostEqual(self.det._safe_float(None), 0.0)

    def test_bad_string_returns_default(self):
        self.assertAlmostEqual(self.det._safe_float("not_a_number", -1.0), -1.0)


# ===========================================================================
# TestDetectApyRegressionNone
# ===========================================================================

class TestDetectApyRegressionNone(unittest.TestCase):
    """Cases where APY regression should return None."""

    def setUp(self):
        self.det = _make_detector()

    def test_no_change(self):
        self.assertIsNone(self.det.detect_apy_regression("a", 5.0, 5.0))

    def test_improvement(self):
        self.assertIsNone(self.det.detect_apy_regression("a", 5.0, 6.0))

    def test_small_drop_below_warning(self):
        # 14% drop — below 15% WARNING threshold
        self.assertIsNone(self.det.detect_apy_regression("a", 10.0, 8.60))

    def test_zero_previous_returns_none(self):
        self.assertIsNone(self.det.detect_apy_regression("a", 0.0, 3.0))

    def test_near_zero_previous_returns_none(self):
        self.assertIsNone(self.det.detect_apy_regression("a", 1e-10, 5.0))


# ===========================================================================
# TestDetectApyRegressionWarning
# ===========================================================================

class TestDetectApyRegressionWarning(unittest.TestCase):
    """APY drops that should trigger WARNING."""

    def setUp(self):
        self.det = _make_detector()

    def test_exactly_warning_threshold(self):
        # 15% relative drop
        result = self.det.detect_apy_regression("a", 10.0, 8.5)
        self.assertIsNotNone(result)
        self.assertEqual(result.severity, SEV_WARNING)

    def test_between_warning_and_critical(self):
        # 20% drop: warning but not critical
        result = self.det.detect_apy_regression("a", 10.0, 8.0)
        self.assertIsNotNone(result)
        self.assertEqual(result.severity, SEV_WARNING)

    def test_regression_type_is_apy_drop(self):
        result = self.det.detect_apy_regression("aave", 5.0, 4.0)
        self.assertEqual(result.regression_type, RT_APY_DROP)

    def test_change_pct_is_negative(self):
        result = self.det.detect_apy_regression("a", 10.0, 8.0)
        self.assertLess(result.change_pct, 0)


# ===========================================================================
# TestDetectApyRegressionCritical
# ===========================================================================

class TestDetectApyRegressionCritical(unittest.TestCase):
    """APY drops that should trigger CRITICAL."""

    def setUp(self):
        self.det = _make_detector()

    def test_exactly_critical_threshold(self):
        # 30% relative drop
        result = self.det.detect_apy_regression("a", 10.0, 7.0)
        self.assertIsNotNone(result)
        self.assertEqual(result.severity, SEV_CRITICAL)

    def test_above_critical_threshold(self):
        result = self.det.detect_apy_regression("a", 10.0, 5.0)
        self.assertEqual(result.severity, SEV_CRITICAL)

    def test_adapter_id_preserved(self):
        result = self.det.detect_apy_regression("compound_v3", 10.0, 5.0)
        self.assertEqual(result.adapter_or_strategy, "compound_v3")

    def test_values_preserved(self):
        result = self.det.detect_apy_regression("a", 10.0, 6.0)
        self.assertAlmostEqual(result.previous_value, 10.0)
        self.assertAlmostEqual(result.current_value, 6.0)


# ===========================================================================
# TestDetectSharpeRegression
# ===========================================================================

class TestDetectSharpeRegression(unittest.TestCase):
    """Tests for detect_sharpe_regression."""

    def setUp(self):
        self.det = _make_detector()

    def test_no_drop_returns_none(self):
        self.assertIsNone(self.det.detect_sharpe_regression("s0", 1.5, 1.5))

    def test_improvement_returns_none(self):
        self.assertIsNone(self.det.detect_sharpe_regression("s0", 1.0, 1.5))

    def test_small_drop_below_warning(self):
        # 0.1 drop, below 0.2 warning threshold
        self.assertIsNone(self.det.detect_sharpe_regression("s0", 1.5, 1.4))

    def test_warning_threshold(self):
        # 0.25 absolute drop (clearly above 0.2 threshold)
        result = self.det.detect_sharpe_regression("s0", 1.5, 1.25)
        self.assertIsNotNone(result)
        self.assertEqual(result.severity, SEV_WARNING)

    def test_critical_threshold(self):
        # 0.5 absolute drop
        result = self.det.detect_sharpe_regression("s0", 1.5, 1.0)
        self.assertIsNotNone(result)
        self.assertEqual(result.severity, SEV_CRITICAL)

    def test_regression_type(self):
        result = self.det.detect_sharpe_regression("s1", 2.0, 1.3)
        self.assertEqual(result.regression_type, RT_SHARPE_DROP)


# ===========================================================================
# TestDetectDrawdownRegression
# ===========================================================================

class TestDetectDrawdownRegression(unittest.TestCase):
    """Tests for detect_drawdown_regression."""

    def setUp(self):
        self.det = _make_detector()

    def test_no_change_returns_none(self):
        self.assertIsNone(self.det.detect_drawdown_regression("s0", 5.0, 5.0))

    def test_improvement_returns_none(self):
        # drawdown decreased (less bad)
        self.assertIsNone(self.det.detect_drawdown_regression("s0", 5.0, 3.0))

    def test_small_increase_below_warning(self):
        # 40% relative increase, below 50% threshold
        self.assertIsNone(self.det.detect_drawdown_regression("s0", 5.0, 7.0))

    def test_warning_threshold(self):
        # 50% relative increase: 5.0 → 7.5
        result = self.det.detect_drawdown_regression("s0", 5.0, 7.5)
        self.assertIsNotNone(result)
        self.assertEqual(result.severity, SEV_WARNING)

    def test_critical_threshold(self):
        # 100% relative increase: 5.0 → 10.0
        result = self.det.detect_drawdown_regression("s0", 5.0, 10.0)
        self.assertIsNotNone(result)
        self.assertEqual(result.severity, SEV_CRITICAL)

    def test_regression_type(self):
        result = self.det.detect_drawdown_regression("s0", 2.0, 5.0)
        self.assertEqual(result.regression_type, RT_DRAWDOWN_INCREASE)


# ===========================================================================
# TestDetectAllocationDrift
# ===========================================================================

class TestDetectAllocationDrift(unittest.TestCase):
    """Tests for detect_allocation_drift."""

    def setUp(self):
        self.det = _make_detector()

    def test_no_drift_returns_empty(self):
        result = self.det.detect_allocation_drift({"a": 0.3}, {"a": 0.3})
        self.assertEqual(result, [])

    def test_small_drift_below_threshold(self):
        # 10% relative drift — below 20% threshold
        result = self.det.detect_allocation_drift({"a": 0.5}, {"a": 0.45})
        self.assertEqual(result, [])

    def test_drift_at_threshold_triggers_warning(self):
        # 25% relative drift: target 0.4, actual 0.3 → drift = 0.1/0.4*100 = 25% > 20%
        result = self.det.detect_allocation_drift({"a": 0.4}, {"a": 0.3})
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].severity, SEV_WARNING)

    def test_multiple_adapters_partial_drift(self):
        targets = {"a": 0.5, "b": 0.5}
        actuals = {"a": 0.35, "b": 0.5}  # only "a" drifts (30% relative)
        result = self.det.detect_allocation_drift(targets, actuals)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].adapter_or_strategy, "a")

    def test_regression_type(self):
        result = self.det.detect_allocation_drift({"a": 0.5}, {"a": 0.0})
        self.assertEqual(result[0].regression_type, RT_ALLOCATION_DRIFT)

    def test_missing_actual_treated_as_zero(self):
        # adapter present in target but absent in actual
        result = self.det.detect_allocation_drift({"a": 0.5}, {})
        self.assertEqual(len(result), 1)


# ===========================================================================
# TestScanAll
# ===========================================================================

class TestScanAll(unittest.TestCase):
    """Tests for scan_all orchestrator."""

    def setUp(self):
        self.det = _make_detector()

    def test_empty_snapshots(self):
        result = self.det.scan_all({}, {})
        self.assertEqual(result, [])

    def test_detects_apy_drop(self):
        prev = {"aave": {"apy": 10.0, "drawdown": 1.0, "weight": 0.5}}
        curr = {"aave": {"apy": 6.0, "drawdown": 1.0, "weight": 0.5}}
        result = self.det.scan_all(prev, curr)
        types = [a.regression_type for a in result]
        self.assertIn(RT_APY_DROP, types)

    def test_detects_drawdown_regression(self):
        prev = {"aave": {"apy": 5.0, "drawdown": 2.0, "weight": 0.5}}
        curr = {"aave": {"apy": 5.0, "drawdown": 5.0, "weight": 0.5}}
        result = self.det.scan_all(prev, curr)
        types = [a.regression_type for a in result]
        self.assertIn(RT_DRAWDOWN_INCREASE, types)

    def test_detects_allocation_drift(self):
        prev = {"aave": {"apy": 5.0, "drawdown": 1.0, "weight": 0.5}}
        curr = {"aave": {"apy": 5.0, "drawdown": 1.0, "weight": 0.2}}
        result = self.det.scan_all(prev, curr)
        types = [a.regression_type for a in result]
        self.assertIn(RT_ALLOCATION_DRIFT, types)

    def test_clean_snapshot_returns_no_alerts(self):
        prev = {"aave": {"apy": 5.0, "drawdown": 1.0, "weight": 0.5}}
        curr = {"aave": {"apy": 5.2, "drawdown": 0.9, "weight": 0.5}}
        result = self.det.scan_all(prev, curr)
        self.assertEqual(result, [])


# ===========================================================================
# TestLogAlertsRingBuffer
# ===========================================================================

class TestLogAlertsRingBuffer(unittest.TestCase):
    """Tests for log_alerts persistence and ring-buffer behaviour."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.det = _make_detector(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_creates_file_on_first_log(self):
        self.det.log_alerts([_alert()])
        self.assertTrue((Path(self.tmp.name) / _ALERTS_FILE).exists())

    def test_file_contains_valid_json(self):
        self.det.log_alerts([_alert()])
        with open(Path(self.tmp.name) / _ALERTS_FILE) as fh:
            data = json.load(fh)
        self.assertIsInstance(data, list)

    def test_alerts_accumulate(self):
        self.det.log_alerts([_alert(adapter="a1")])
        self.det.log_alerts([_alert(adapter="a2")])
        with open(Path(self.tmp.name) / _ALERTS_FILE) as fh:
            data = json.load(fh)
        self.assertEqual(len(data), 2)

    def test_ring_buffer_truncates_to_50(self):
        # Log 60 alerts — should keep only 50
        for i in range(60):
            self.det.log_alerts([_alert(adapter=f"a{i}")])
        with open(Path(self.tmp.name) / _ALERTS_FILE) as fh:
            data = json.load(fh)
        self.assertLessEqual(len(data), _RING_BUFFER_MAX)

    def test_empty_list_no_op(self):
        self.det.log_alerts([])
        self.assertFalse((Path(self.tmp.name) / _ALERTS_FILE).exists())


# ===========================================================================
# TestGenerateReport
# ===========================================================================

class TestGenerateReport(unittest.TestCase):
    """Tests for generate_report output structure and content."""

    def setUp(self):
        self.det = _make_detector()

    def _prev(self, **kwargs) -> dict:
        base = {"apy": 5.0, "drawdown": 1.0, "weight": 0.5}
        base.update(kwargs)
        return {"aave": base}

    def _curr(self, **kwargs) -> dict:
        base = {"apy": 5.0, "drawdown": 1.0, "weight": 0.5}
        base.update(kwargs)
        return {"aave": base}

    def test_report_has_required_keys(self):
        report = self.det.generate_report({}, {})
        for key in ("alerts", "critical_count", "warning_count",
                    "info_count", "clean_count", "advisory", "generated_at"):
            self.assertIn(key, report)

    def test_clean_report_zero_alerts(self):
        report = self.det.generate_report(self._prev(), self._curr())
        self.assertEqual(report["critical_count"], 0)
        self.assertEqual(report["warning_count"], 0)

    def test_clean_report_advisory_ok(self):
        report = self.det.generate_report(self._prev(), self._curr())
        self.assertIn("OK", report["advisory"])

    def test_warning_advisory_contains_word(self):
        prev = self._prev(apy=10.0)
        curr = self._curr(apy=8.0)
        report = self.det.generate_report(prev, curr)
        self.assertIn("WARNING", report["advisory"])

    def test_critical_advisory_contains_word(self):
        prev = self._prev(apy=10.0)
        curr = self._curr(apy=5.0)
        report = self.det.generate_report(prev, curr)
        self.assertIn("CRITICAL", report["advisory"])

    def test_alerts_list_is_serialisable(self):
        prev = self._prev(apy=10.0)
        curr = self._curr(apy=5.0)
        report = self.det.generate_report(prev, curr)
        json.dumps(report)  # should not raise

    def test_generated_at_is_iso(self):
        report = self.det.generate_report({}, {})
        ts = report["generated_at"]
        # Should parse without error
        datetime.fromisoformat(ts.replace("Z", "+00:00"))

    def test_clean_count_reflects_unaffected(self):
        prev = {
            "aave": {"apy": 10.0, "drawdown": 1.0, "weight": 0.3},
            "comp": {"apy": 5.0, "drawdown": 0.5, "weight": 0.3},
        }
        curr = {
            "aave": {"apy": 5.0, "drawdown": 1.0, "weight": 0.3},  # APY drop
            "comp": {"apy": 5.0, "drawdown": 0.5, "weight": 0.3},  # clean
        }
        report = self.det.generate_report(prev, curr)
        # comp is clean (no regression triggered for it)
        self.assertGreaterEqual(report["clean_count"], 1)


# ===========================================================================
# TestNowIso
# ===========================================================================

class TestNowIso(unittest.TestCase):
    def test_now_iso_returns_string(self):
        det = _make_detector()
        ts = det._now_iso()
        self.assertIsInstance(ts, str)
        self.assertIn("T", ts)


# ===========================================================================
# Edge-case and integration tests
# ===========================================================================

class TestEdgeCases(unittest.TestCase):

    def setUp(self):
        self.det = _make_detector()

    def test_negative_apy_previous_triggers_detection(self):
        # previous APY is negative — change from -2 to -4 should not be
        # seen as an improvement: change_pct = (-4 - (-2)) / 2 * 100 = -100%
        result = self.det.detect_apy_regression("a", -2.0, -4.0)
        self.assertIsNotNone(result)

    def test_detect_multiple_drift_adapters(self):
        targets = {"a": 0.4, "b": 0.4, "c": 0.2}
        actuals = {"a": 0.1, "b": 0.1, "c": 0.2}
        results = self.det.detect_allocation_drift(targets, actuals)
        self.assertEqual(len(results), 2)

    def test_drawdown_both_zero_no_alert(self):
        # Both zero → denominator clamps to 0.001 → relative_increase = 0
        result = self.det.detect_drawdown_regression("s", 0.0, 0.0)
        self.assertIsNone(result)

    def test_scan_all_missing_fields_graceful(self):
        # snapshot entries missing some keys — should not raise
        prev = {"a": {"apy": 5.0}}
        curr = {"a": {"apy": 3.0}}
        result = self.det.scan_all(prev, curr)
        # Should only have APY alert (no drawdown/weight data)
        self.assertTrue(all(a.regression_type == RT_APY_DROP for a in result))

    def test_scan_all_non_dict_entry_graceful(self):
        prev = {"a": None}
        curr = {"a": None}
        # should not raise
        result = self.det.scan_all(prev, curr)
        self.assertEqual(result, [])

    def test_full_pipeline(self):
        """End-to-end: scan, generate_report, log_alerts all work together."""
        with tempfile.TemporaryDirectory() as tmp:
            det = PerformanceRegressionDetector(data_dir=tmp)
            prev = {"aave": {"apy": 10.0, "drawdown": 1.0, "weight": 0.5, "sharpe": 1.5}}
            curr = {"aave": {"apy": 5.0, "drawdown": 3.0, "weight": 0.2, "sharpe": 0.8}}
            report = det.generate_report(prev, curr)
            alerts = [RegressionAlert.from_dict(a) for a in report["alerts"]]
            det.log_alerts(alerts)
            path = Path(tmp) / _ALERTS_FILE
            self.assertTrue(path.exists())
            with open(path) as fh:
                saved = json.load(fh)
            self.assertGreater(len(saved), 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
