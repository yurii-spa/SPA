"""
Tests for AlertThresholdManager — MP-622.

Run:
    python3 -m unittest spa_core.tests.test_alert_threshold_manager -v

Groups:
    TestThresholdDefinition   (8)
    TestAlertEvent            (8)
    TestAlertReport           (8)
    TestLoadMetricValue       (15)
    TestCheckThreshold        (20)
    TestRunAllChecks          (15)
    TestSaveReport            (4)
    TestFormatTelegramMessage (8)
    TestCustomThresholds      (4)
    Total: 90
"""
from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path

from spa_core.analytics.alert_threshold_manager import (
    AlertEvent,
    AlertReport,
    AlertThresholdManager,
    ThresholdDefinition,
    _atomic_write_json,
    RING_BUFFER_MAX,
)


# ===========================================================================
# Helpers
# ===========================================================================

def _make_threshold(
    name="apy_floor",
    metric_path="data/yield_attribution_tracker.json",
    operator="lt",
    threshold_value=3.0,
    severity="CRITICAL",
    message_template="APY {value:.2f}% below {threshold:.2f}%",
) -> ThresholdDefinition:
    return ThresholdDefinition(
        name=name,
        metric_path=metric_path,
        operator=operator,
        threshold_value=threshold_value,
        severity=severity,
        message_template=message_template,
    )


def _make_event(
    name="apy_floor",
    severity="CRITICAL",
    current_value=2.0,
    threshold_value=3.0,
    message="APY 2.00% below 3.00%",
    triggered_at="2026-06-13T08:00:00+00:00",
    is_active=True,
) -> AlertEvent:
    return AlertEvent(
        threshold_name=name,
        severity=severity,
        current_value=current_value,
        threshold_value=threshold_value,
        message=message,
        triggered_at=triggered_at,
        is_active=is_active,
    )


def _make_report(
    generated_at="2026-06-13T08:00:00+00:00",
    thresholds_checked=9,
    alerts_active=0,
    critical_count=0,
    warning_count=0,
    info_count=0,
    events=None,
    all_clear=True,
    summary="",
) -> AlertReport:
    return AlertReport(
        generated_at=generated_at,
        thresholds_checked=thresholds_checked,
        alerts_active=alerts_active,
        critical_count=critical_count,
        warning_count=warning_count,
        info_count=info_count,
        events=events or [],
        all_clear=all_clear,
        summary=summary,
    )


# ===========================================================================
# TestThresholdDefinition (8)
# ===========================================================================

class TestThresholdDefinition(unittest.TestCase):
    """Tests for ThresholdDefinition dataclass."""

    def test_basic_fields_stored(self):
        td = _make_threshold()
        self.assertEqual(td.name, "apy_floor")
        self.assertEqual(td.metric_path, "data/yield_attribution_tracker.json")
        self.assertEqual(td.operator, "lt")
        self.assertAlmostEqual(td.threshold_value, 3.0)
        self.assertEqual(td.severity, "CRITICAL")
        self.assertIn("{value", td.message_template)

    def test_severity_warning_valid(self):
        td = _make_threshold(severity="WARNING")
        self.assertEqual(td.severity, "WARNING")

    def test_severity_info_valid(self):
        td = _make_threshold(severity="INFO")
        self.assertEqual(td.severity, "INFO")

    def test_operator_gt_valid(self):
        td = _make_threshold(operator="gt", threshold_value=50.0)
        self.assertEqual(td.operator, "gt")

    def test_operator_lte_valid(self):
        td = _make_threshold(operator="lte", threshold_value=50.0)
        self.assertEqual(td.operator, "lte")

    def test_operator_gte_valid(self):
        td = _make_threshold(operator="gte", threshold_value=1.0)
        self.assertEqual(td.operator, "gte")

    def test_invalid_operator_raises(self):
        with self.assertRaises(ValueError):
            _make_threshold(operator="neq")

    def test_invalid_severity_raises(self):
        with self.assertRaises(ValueError):
            _make_threshold(severity="URGENT")


# ===========================================================================
# TestAlertEvent (8)
# ===========================================================================

class TestAlertEvent(unittest.TestCase):
    """Tests for AlertEvent dataclass."""

    def test_basic_fields_stored(self):
        ev = _make_event()
        self.assertEqual(ev.threshold_name, "apy_floor")
        self.assertEqual(ev.severity, "CRITICAL")
        self.assertAlmostEqual(ev.current_value, 2.0)
        self.assertAlmostEqual(ev.threshold_value, 3.0)
        self.assertTrue(ev.is_active)

    def test_is_active_false(self):
        ev = _make_event(is_active=False)
        self.assertFalse(ev.is_active)

    def test_to_dict_has_all_keys(self):
        ev = _make_event()
        d = ev.to_dict()
        for key in ("threshold_name", "severity", "current_value",
                    "threshold_value", "message", "triggered_at", "is_active"):
            self.assertIn(key, d)

    def test_to_dict_is_active_true(self):
        ev = _make_event(is_active=True)
        self.assertTrue(ev.to_dict()["is_active"])

    def test_to_dict_is_active_false(self):
        ev = _make_event(is_active=False)
        self.assertFalse(ev.to_dict()["is_active"])

    def test_message_stored(self):
        ev = _make_event(message="T2 exposure 55.0% exceeds cap 50.0%")
        self.assertIn("55.0%", ev.message)

    def test_triggered_at_stored(self):
        ev = _make_event(triggered_at="2026-06-13T10:00:00+00:00")
        self.assertEqual(ev.triggered_at, "2026-06-13T10:00:00+00:00")

    def test_severity_warning(self):
        ev = _make_event(severity="WARNING")
        self.assertEqual(ev.severity, "WARNING")


# ===========================================================================
# TestAlertReport (8)
# ===========================================================================

class TestAlertReport(unittest.TestCase):
    """Tests for AlertReport dataclass."""

    def test_all_clear_true_when_no_alerts(self):
        r = _make_report(alerts_active=0, all_clear=True)
        self.assertTrue(r.all_clear)

    def test_all_clear_false_when_alerts(self):
        r = _make_report(alerts_active=2, critical_count=1, warning_count=1,
                         all_clear=False)
        self.assertFalse(r.all_clear)

    def test_counts_stored(self):
        r = _make_report(critical_count=1, warning_count=2, info_count=1,
                         alerts_active=4, all_clear=False)
        self.assertEqual(r.critical_count, 1)
        self.assertEqual(r.warning_count, 2)
        self.assertEqual(r.info_count, 1)

    def test_summary_auto_generated_all_clear(self):
        r = AlertReport(
            generated_at="2026-06-13T08:00:00+00:00",
            thresholds_checked=9,
            alerts_active=0,
            critical_count=0,
            warning_count=0,
            info_count=0,
        )
        self.assertIn("clear", r.summary.lower())

    def test_summary_auto_generated_with_alerts(self):
        r = AlertReport(
            generated_at="2026-06-13T08:00:00+00:00",
            thresholds_checked=9,
            alerts_active=3,
            critical_count=1,
            warning_count=2,
            info_count=0,
            all_clear=False,
        )
        self.assertIn("3", r.summary)

    def test_summary_format_with_critical_and_warning(self):
        r = AlertReport(
            generated_at="2026-06-13T08:00:00+00:00",
            thresholds_checked=9,
            alerts_active=3,
            critical_count=1,
            warning_count=2,
            info_count=0,
            all_clear=False,
        )
        self.assertIn("CRITICAL", r.summary)
        self.assertIn("WARNING", r.summary)

    def test_to_dict_has_all_keys(self):
        r = _make_report()
        d = r.to_dict()
        for key in ("generated_at", "thresholds_checked", "alerts_active",
                    "critical_count", "warning_count", "info_count",
                    "all_clear", "summary", "events"):
            self.assertIn(key, d)

    def test_to_dict_events_is_list(self):
        ev = _make_event()
        r = _make_report(alerts_active=1, critical_count=1, all_clear=False,
                         events=[ev])
        d = r.to_dict()
        self.assertIsInstance(d["events"], list)
        self.assertEqual(len(d["events"]), 1)


# ===========================================================================
# TestLoadMetricValue (15)
# ===========================================================================

class TestLoadMetricValue(unittest.TestCase):
    """Tests for AlertThresholdManager.load_metric_value."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.data_dir = Path(self.tmpdir) / "data"
        self.data_dir.mkdir()
        self.manager = AlertThresholdManager(data_path=str(self.data_dir))

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _write_json(self, filename: str, payload: dict) -> Path:
        path = self.data_dir / filename
        _atomic_write_json(path, payload)
        return path

    def _write_with_latest(self, filename: str, latest: dict) -> Path:
        payload = {"schema_version": 1, "latest": latest}
        return self._write_json(filename, payload)

    # --- file missing ---
    def test_missing_file_returns_none(self):
        td = _make_threshold(
            name="apy_floor",
            metric_path=str(self.data_dir / "nonexistent.json"),
        )
        result = self.manager.load_metric_value(td)
        self.assertIsNone(result)

    # --- apy_floor / apy_warning ---
    def test_apy_floor_key_extracted(self):
        self._write_with_latest(
            "yield_attribution_tracker.json",
            {"effective_apy_pct": 5.25},
        )
        td = _make_threshold(
            name="apy_floor",
            metric_path=str(self.data_dir / "yield_attribution_tracker.json"),
        )
        result = self.manager.load_metric_value(td)
        self.assertAlmostEqual(result, 5.25)

    def test_apy_warning_key_extracted(self):
        self._write_with_latest(
            "yield_attribution_tracker.json",
            {"effective_apy_pct": 3.8},
        )
        td = _make_threshold(
            name="apy_warning",
            metric_path=str(self.data_dir / "yield_attribution_tracker.json"),
        )
        result = self.manager.load_metric_value(td)
        self.assertAlmostEqual(result, 3.8)

    # --- t2_cap_breach ---
    def test_t2_cap_breach_key_extracted(self):
        self._write_with_latest(
            "tier_exposure.json",
            {"t2_weight_pct": 55.0, "t1_weight_pct": 45.0},
        )
        td = _make_threshold(
            name="t2_cap_breach",
            metric_path=str(self.data_dir / "tier_exposure.json"),
            operator="gt",
            threshold_value=50.0,
        )
        result = self.manager.load_metric_value(td)
        self.assertAlmostEqual(result, 55.0)

    # --- t3_cap_breach ---
    def test_t3_cap_breach_key_extracted(self):
        self._write_with_latest(
            "tier_exposure.json",
            {"t3_weight_pct": 20.0},
        )
        td = _make_threshold(
            name="t3_cap_breach",
            metric_path=str(self.data_dir / "tier_exposure.json"),
            operator="gt",
            threshold_value=15.0,
        )
        result = self.manager.load_metric_value(td)
        self.assertAlmostEqual(result, 20.0)

    # --- chain_concentration ---
    def test_chain_concentration_key_extracted(self):
        self._write_with_latest(
            "chain_exposure.json",
            {"dominant_weight_pct": 80.0},
        )
        td = _make_threshold(
            name="chain_concentration",
            metric_path=str(self.data_dir / "chain_exposure.json"),
            operator="gt",
            threshold_value=70.0,
        )
        result = self.manager.load_metric_value(td)
        self.assertAlmostEqual(result, 80.0)

    # --- deployment_low ---
    def test_deployment_low_key_extracted(self):
        self._write_with_latest(
            "capital_efficiency.json",
            {"deployment_rate_pct": 45.0},
        )
        td = _make_threshold(
            name="deployment_low",
            metric_path=str(self.data_dir / "capital_efficiency.json"),
            operator="lt",
            threshold_value=50.0,
        )
        result = self.manager.load_metric_value(td)
        self.assertAlmostEqual(result, 45.0)

    # --- risk_score_high ---
    def test_risk_score_high_key_extracted(self):
        self._write_with_latest(
            "integrated_risk.json",
            {"overall_score": 0.65},
        )
        td = _make_threshold(
            name="risk_score_high",
            metric_path=str(self.data_dir / "integrated_risk.json"),
            operator="gt",
            threshold_value=0.50,
        )
        result = self.manager.load_metric_value(td)
        self.assertAlmostEqual(result, 0.65)

    # --- risk_score_warning ---
    def test_risk_score_warning_key_extracted(self):
        self._write_with_latest(
            "integrated_risk.json",
            {"overall_score": 0.35},
        )
        td = _make_threshold(
            name="risk_score_warning",
            metric_path=str(self.data_dir / "integrated_risk.json"),
            operator="gt",
            threshold_value=0.25,
        )
        result = self.manager.load_metric_value(td)
        self.assertAlmostEqual(result, 0.35)

    # --- rebalance_needed ---
    def test_rebalance_needed_key_extracted(self):
        self._write_with_latest(
            "rebalance_plan.json",
            {"total_moves": 3},
        )
        td = _make_threshold(
            name="rebalance_needed",
            metric_path=str(self.data_dir / "rebalance_plan.json"),
            operator="gt",
            threshold_value=0,
        )
        result = self.manager.load_metric_value(td)
        self.assertAlmostEqual(result, 3.0)

    # --- key not found ---
    def test_missing_key_returns_none(self):
        self._write_with_latest(
            "yield_attribution_tracker.json",
            {"other_key": 5.0},
        )
        td = _make_threshold(
            name="apy_floor",
            metric_path=str(self.data_dir / "yield_attribution_tracker.json"),
        )
        result = self.manager.load_metric_value(td)
        self.assertIsNone(result)

    # --- array as top-level → last element ---
    def test_array_latest_uses_last_element(self):
        path = self.data_dir / "yield_attribution_tracker.json"
        payload = [
            {"effective_apy_pct": 2.0},
            {"effective_apy_pct": 4.5},
        ]
        _atomic_write_json(path, payload)
        td = _make_threshold(
            name="apy_floor",
            metric_path=str(path),
        )
        result = self.manager.load_metric_value(td)
        self.assertAlmostEqual(result, 4.5)

    # --- unknown threshold name ---
    def test_unknown_threshold_name_returns_none(self):
        self._write_with_latest(
            "some_file.json",
            {"some_key": 1.0},
        )
        td = _make_threshold(
            name="completely_unknown_threshold",
            metric_path=str(self.data_dir / "some_file.json"),
        )
        result = self.manager.load_metric_value(td)
        self.assertIsNone(result)

    # --- bool value → None ---
    def test_bool_value_returns_none(self):
        self._write_with_latest(
            "yield_attribution_tracker.json",
            {"effective_apy_pct": True},
        )
        td = _make_threshold(
            name="apy_floor",
            metric_path=str(self.data_dir / "yield_attribution_tracker.json"),
        )
        result = self.manager.load_metric_value(td)
        self.assertIsNone(result)

    # --- integer value accepted ---
    def test_integer_value_accepted(self):
        self._write_with_latest(
            "rebalance_plan.json",
            {"total_moves": 5},
        )
        td = _make_threshold(
            name="rebalance_needed",
            metric_path=str(self.data_dir / "rebalance_plan.json"),
            operator="gt",
            threshold_value=0,
        )
        result = self.manager.load_metric_value(td)
        self.assertAlmostEqual(result, 5.0)


# ===========================================================================
# TestCheckThreshold (20)
# ===========================================================================

class TestCheckThreshold(unittest.TestCase):
    """Tests for AlertThresholdManager.check_threshold."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.data_dir = Path(self.tmpdir) / "data"
        self.data_dir.mkdir()
        self.manager = AlertThresholdManager(data_path=str(self.data_dir))

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _write_latest(self, filename: str, latest: dict) -> Path:
        path = self.data_dir / filename
        _atomic_write_json(path, {"latest": latest})
        return path

    # --- None value → None event ---
    def test_none_value_returns_none_event(self):
        td = _make_threshold(
            name="apy_floor",
            metric_path=str(self.data_dir / "nonexistent.json"),
        )
        result = self.manager.check_threshold(td)
        self.assertIsNone(result)

    # --- lt operator: triggered ---
    def test_lt_triggered_when_value_less(self):
        self._write_latest("yat.json", {"effective_apy_pct": 2.5})
        td = _make_threshold(
            name="apy_floor",
            metric_path=str(self.data_dir / "yat.json"),
            operator="lt",
            threshold_value=3.0,
        )
        event = self.manager.check_threshold(td)
        self.assertIsNotNone(event)
        self.assertTrue(event.is_active)

    # --- lt operator: not triggered ---
    def test_lt_not_triggered_when_value_greater(self):
        self._write_latest("yat.json", {"effective_apy_pct": 5.0})
        td = _make_threshold(
            name="apy_floor",
            metric_path=str(self.data_dir / "yat.json"),
            operator="lt",
            threshold_value=3.0,
        )
        event = self.manager.check_threshold(td)
        self.assertIsNotNone(event)
        self.assertFalse(event.is_active)

    # --- lt operator: equal → not triggered (strictly less than) ---
    def test_lt_not_triggered_at_exact_boundary(self):
        self._write_latest("yat.json", {"effective_apy_pct": 3.0})
        td = _make_threshold(
            name="apy_floor",
            metric_path=str(self.data_dir / "yat.json"),
            operator="lt",
            threshold_value=3.0,
        )
        event = self.manager.check_threshold(td)
        self.assertFalse(event.is_active)

    # --- gt operator: triggered ---
    def test_gt_triggered_when_value_greater(self):
        self._write_latest("tier.json", {"t2_weight_pct": 60.0})
        td = _make_threshold(
            name="t2_cap_breach",
            metric_path=str(self.data_dir / "tier.json"),
            operator="gt",
            threshold_value=50.0,
        )
        event = self.manager.check_threshold(td)
        self.assertTrue(event.is_active)

    # --- gt operator: not triggered ---
    def test_gt_not_triggered_when_value_less(self):
        self._write_latest("tier.json", {"t2_weight_pct": 40.0})
        td = _make_threshold(
            name="t2_cap_breach",
            metric_path=str(self.data_dir / "tier.json"),
            operator="gt",
            threshold_value=50.0,
        )
        event = self.manager.check_threshold(td)
        self.assertFalse(event.is_active)

    # --- gt operator: exact boundary → not triggered ---
    def test_gt_not_triggered_at_exact_boundary(self):
        self._write_latest("tier.json", {"t2_weight_pct": 50.0})
        td = _make_threshold(
            name="t2_cap_breach",
            metric_path=str(self.data_dir / "tier.json"),
            operator="gt",
            threshold_value=50.0,
        )
        event = self.manager.check_threshold(td)
        self.assertFalse(event.is_active)

    # --- lte operator: triggered at boundary ---
    def test_lte_triggered_at_exact_boundary(self):
        self._write_latest("f.json", {"effective_apy_pct": 3.0})
        td = _make_threshold(
            name="apy_floor",
            metric_path=str(self.data_dir / "f.json"),
            operator="lte",
            threshold_value=3.0,
        )
        event = self.manager.check_threshold(td)
        self.assertTrue(event.is_active)

    # --- lte operator: triggered below ---
    def test_lte_triggered_when_value_less(self):
        self._write_latest("f.json", {"effective_apy_pct": 2.0})
        td = _make_threshold(
            name="apy_floor",
            metric_path=str(self.data_dir / "f.json"),
            operator="lte",
            threshold_value=3.0,
        )
        event = self.manager.check_threshold(td)
        self.assertTrue(event.is_active)

    # --- lte operator: not triggered above ---
    def test_lte_not_triggered_when_value_above(self):
        self._write_latest("f.json", {"effective_apy_pct": 4.0})
        td = _make_threshold(
            name="apy_floor",
            metric_path=str(self.data_dir / "f.json"),
            operator="lte",
            threshold_value=3.0,
        )
        event = self.manager.check_threshold(td)
        self.assertFalse(event.is_active)

    # --- gte operator: triggered at boundary ---
    def test_gte_triggered_at_exact_boundary(self):
        self._write_latest("f.json", {"t2_weight_pct": 50.0})
        td = _make_threshold(
            name="t2_cap_breach",
            metric_path=str(self.data_dir / "f.json"),
            operator="gte",
            threshold_value=50.0,
        )
        event = self.manager.check_threshold(td)
        self.assertTrue(event.is_active)

    # --- gte operator: triggered above ---
    def test_gte_triggered_when_value_greater(self):
        self._write_latest("f.json", {"t2_weight_pct": 55.0})
        td = _make_threshold(
            name="t2_cap_breach",
            metric_path=str(self.data_dir / "f.json"),
            operator="gte",
            threshold_value=50.0,
        )
        event = self.manager.check_threshold(td)
        self.assertTrue(event.is_active)

    # --- gte operator: not triggered below ---
    def test_gte_not_triggered_when_value_below(self):
        self._write_latest("f.json", {"t2_weight_pct": 45.0})
        td = _make_threshold(
            name="t2_cap_breach",
            metric_path=str(self.data_dir / "f.json"),
            operator="gte",
            threshold_value=50.0,
        )
        event = self.manager.check_threshold(td)
        self.assertFalse(event.is_active)

    # --- severity preserved ---
    def test_severity_critical_preserved_in_event(self):
        self._write_latest("f.json", {"effective_apy_pct": 2.0})
        td = _make_threshold(
            name="apy_floor",
            metric_path=str(self.data_dir / "f.json"),
            operator="lt",
            threshold_value=3.0,
            severity="CRITICAL",
        )
        event = self.manager.check_threshold(td)
        self.assertEqual(event.severity, "CRITICAL")

    def test_severity_warning_preserved_in_event(self):
        self._write_latest("f.json", {"effective_apy_pct": 2.0})
        td = _make_threshold(
            name="apy_warning",
            metric_path=str(self.data_dir / "f.json"),
            operator="lt",
            threshold_value=4.0,
            severity="WARNING",
        )
        event = self.manager.check_threshold(td)
        self.assertEqual(event.severity, "WARNING")

    def test_severity_info_preserved_in_event(self):
        self._write_latest("f.json", {"total_moves": 5})
        td = _make_threshold(
            name="rebalance_needed",
            metric_path=str(self.data_dir / "f.json"),
            operator="gt",
            threshold_value=0,
            severity="INFO",
        )
        event = self.manager.check_threshold(td)
        self.assertEqual(event.severity, "INFO")

    # --- message template formatted ---
    def test_message_template_is_formatted(self):
        self._write_latest("f.json", {"effective_apy_pct": 2.5})
        td = _make_threshold(
            name="apy_floor",
            metric_path=str(self.data_dir / "f.json"),
            operator="lt",
            threshold_value=3.0,
            message_template="APY {value:.2f}% below {threshold:.2f}%",
        )
        event = self.manager.check_threshold(td)
        self.assertIn("2.50", event.message)
        self.assertIn("3.00", event.message)

    # --- values stored correctly ---
    def test_current_value_stored_in_event(self):
        self._write_latest("f.json", {"effective_apy_pct": 2.75})
        td = _make_threshold(
            name="apy_floor",
            metric_path=str(self.data_dir / "f.json"),
        )
        event = self.manager.check_threshold(td)
        self.assertAlmostEqual(event.current_value, 2.75)

    def test_threshold_value_stored_in_event(self):
        self._write_latest("f.json", {"effective_apy_pct": 2.75})
        td = _make_threshold(
            name="apy_floor",
            metric_path=str(self.data_dir / "f.json"),
            threshold_value=3.0,
        )
        event = self.manager.check_threshold(td)
        self.assertAlmostEqual(event.threshold_value, 3.0)

    # --- triggered_at is ISO ---
    def test_triggered_at_is_iso_format(self):
        self._write_latest("f.json", {"effective_apy_pct": 2.0})
        td = _make_threshold(
            name="apy_floor",
            metric_path=str(self.data_dir / "f.json"),
        )
        event = self.manager.check_threshold(td)
        self.assertIn("T", event.triggered_at)
        self.assertIn("+", event.triggered_at)

    # --- threshold name stored ---
    def test_threshold_name_stored_in_event(self):
        self._write_latest("f.json", {"effective_apy_pct": 2.0})
        td = _make_threshold(
            name="apy_floor",
            metric_path=str(self.data_dir / "f.json"),
        )
        event = self.manager.check_threshold(td)
        self.assertEqual(event.threshold_name, "apy_floor")


# ===========================================================================
# TestRunAllChecks (15)
# ===========================================================================

class TestRunAllChecks(unittest.TestCase):
    """Tests for AlertThresholdManager.run_all_checks."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.data_dir = Path(self.tmpdir) / "data"
        self.data_dir.mkdir()

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _make_manager_with_thresholds(
        self, thresholds: list
    ) -> AlertThresholdManager:
        return AlertThresholdManager(
            data_path=str(self.data_dir),
            thresholds=thresholds,
        )

    def _write_latest(self, filename: str, latest: dict) -> Path:
        path = self.data_dir / filename
        _atomic_write_json(path, {"latest": latest})
        return path

    # --- all clear when no thresholds breach ---
    def test_all_clear_when_no_breach(self):
        path = str(self.data_dir / "yat.json")
        self._write_latest("yat.json", {"effective_apy_pct": 6.0})
        td = _make_threshold(
            name="apy_floor",
            metric_path=path,
            operator="lt",
            threshold_value=3.0,
        )
        manager = self._make_manager_with_thresholds([td])
        report = manager.run_all_checks()
        self.assertTrue(report.all_clear)
        self.assertEqual(report.alerts_active, 0)

    # --- alert fired when breach ---
    def test_alert_fired_on_breach(self):
        path = str(self.data_dir / "yat.json")
        self._write_latest("yat.json", {"effective_apy_pct": 2.0})
        td = _make_threshold(
            name="apy_floor",
            metric_path=path,
            operator="lt",
            threshold_value=3.0,
        )
        manager = self._make_manager_with_thresholds([td])
        report = manager.run_all_checks()
        self.assertFalse(report.all_clear)
        self.assertEqual(report.alerts_active, 1)

    # --- multiple thresholds, multiple breaches ---
    def test_multiple_breaches_counted(self):
        path1 = str(self.data_dir / "yat.json")
        path2 = str(self.data_dir / "tier.json")
        self._write_latest("yat.json", {"effective_apy_pct": 2.0})
        self._write_latest("tier.json", {"t2_weight_pct": 60.0})
        tds = [
            _make_threshold(
                name="apy_floor",
                metric_path=path1,
                operator="lt",
                threshold_value=3.0,
                severity="CRITICAL",
            ),
            _make_threshold(
                name="t2_cap_breach",
                metric_path=path2,
                operator="gt",
                threshold_value=50.0,
                severity="CRITICAL",
            ),
        ]
        manager = self._make_manager_with_thresholds(tds)
        report = manager.run_all_checks()
        self.assertEqual(report.alerts_active, 2)

    # --- critical count correct ---
    def test_critical_count_correct(self):
        path = str(self.data_dir / "yat.json")
        self._write_latest("yat.json", {"effective_apy_pct": 2.0})
        td = _make_threshold(
            name="apy_floor",
            metric_path=path,
            severity="CRITICAL",
        )
        manager = self._make_manager_with_thresholds([td])
        report = manager.run_all_checks()
        self.assertEqual(report.critical_count, 1)
        self.assertEqual(report.warning_count, 0)
        self.assertEqual(report.info_count, 0)

    # --- warning count correct ---
    def test_warning_count_correct(self):
        path = str(self.data_dir / "yat.json")
        self._write_latest("yat.json", {"effective_apy_pct": 3.5})
        td = _make_threshold(
            name="apy_warning",
            metric_path=path,
            operator="lt",
            threshold_value=4.0,
            severity="WARNING",
        )
        manager = self._make_manager_with_thresholds([td])
        report = manager.run_all_checks()
        self.assertEqual(report.warning_count, 1)
        self.assertEqual(report.critical_count, 0)

    # --- info count correct ---
    def test_info_count_correct(self):
        path = str(self.data_dir / "reb.json")
        self._write_latest("reb.json", {"total_moves": 3})
        td = _make_threshold(
            name="rebalance_needed",
            metric_path=path,
            operator="gt",
            threshold_value=0,
            severity="INFO",
        )
        manager = self._make_manager_with_thresholds([td])
        report = manager.run_all_checks()
        self.assertEqual(report.info_count, 1)

    # --- thresholds_checked count ---
    def test_thresholds_checked_count_is_accurate(self):
        path = str(self.data_dir / "yat.json")
        self._write_latest("yat.json", {"effective_apy_pct": 5.0})
        tds = [
            _make_threshold("apy_floor", metric_path=path),
            _make_threshold("apy_warning", metric_path=path, operator="lt",
                            threshold_value=4.0, severity="WARNING"),
        ]
        manager = self._make_manager_with_thresholds(tds)
        report = manager.run_all_checks()
        self.assertEqual(report.thresholds_checked, 2)

    # --- missing file → threshold skipped ---
    def test_missing_file_threshold_skipped(self):
        td = _make_threshold(
            name="apy_floor",
            metric_path=str(self.data_dir / "ghost.json"),
        )
        manager = self._make_manager_with_thresholds([td])
        report = manager.run_all_checks()
        self.assertTrue(report.all_clear)
        self.assertEqual(report.alerts_active, 0)

    # --- events list only contains active events ---
    def test_events_contains_only_active(self):
        path = str(self.data_dir / "yat.json")
        self._write_latest("yat.json", {"effective_apy_pct": 2.0})
        tds = [
            _make_threshold("apy_floor", metric_path=path,
                            operator="lt", threshold_value=3.0),
            _make_threshold("apy_warning", metric_path=path,
                            operator="lt", threshold_value=1.0,
                            severity="WARNING"),
        ]
        manager = self._make_manager_with_thresholds(tds)
        report = manager.run_all_checks()
        # Only apy_floor should be active (2.0 < 3.0 yes; 2.0 < 1.0 no)
        self.assertEqual(len(report.events), 1)
        self.assertEqual(report.events[0].threshold_name, "apy_floor")

    # --- generated_at is set ---
    def test_generated_at_is_set(self):
        manager = self._make_manager_with_thresholds([])
        report = manager.run_all_checks()
        self.assertIn("T", report.generated_at)

    # --- all_clear consistency ---
    def test_all_clear_consistent_with_alerts_active(self):
        path = str(self.data_dir / "yat.json")
        self._write_latest("yat.json", {"effective_apy_pct": 2.0})
        td = _make_threshold(
            name="apy_floor",
            metric_path=path,
            operator="lt",
            threshold_value=3.0,
        )
        manager = self._make_manager_with_thresholds([td])
        report = manager.run_all_checks()
        # all_clear should match alerts_active == 0
        self.assertEqual(report.all_clear, report.alerts_active == 0)

    # --- mixed severities counted correctly ---
    def test_mixed_severity_counts(self):
        path = str(self.data_dir / "f.json")
        self._write_latest("f.json", {
            "effective_apy_pct": 2.0,
            "t2_weight_pct": 60.0,
            "total_moves": 3,
        })
        tds = [
            _make_threshold("apy_floor", metric_path=path,
                            operator="lt", threshold_value=3.0,
                            severity="CRITICAL"),
            _make_threshold("t2_cap_breach", metric_path=path,
                            operator="gt", threshold_value=50.0,
                            severity="WARNING"),
            _make_threshold("rebalance_needed", metric_path=path,
                            operator="gt", threshold_value=0,
                            severity="INFO"),
        ]
        manager = self._make_manager_with_thresholds(tds)
        report = manager.run_all_checks()
        self.assertEqual(report.critical_count, 1)
        self.assertEqual(report.warning_count, 1)
        self.assertEqual(report.info_count, 1)
        self.assertEqual(report.alerts_active, 3)

    # --- zero thresholds → all_clear ---
    def test_zero_thresholds_all_clear(self):
        manager = self._make_manager_with_thresholds([])
        report = manager.run_all_checks()
        self.assertTrue(report.all_clear)

    # --- alerts active equals sum of active events ---
    def test_alerts_active_equals_events_len(self):
        path = str(self.data_dir / "f.json")
        self._write_latest("f.json", {"effective_apy_pct": 2.0})
        tds = [
            _make_threshold("apy_floor", metric_path=path,
                            operator="lt", threshold_value=3.0),
            _make_threshold("apy_warning", metric_path=path,
                            operator="lt", threshold_value=4.0,
                            severity="WARNING"),
        ]
        manager = self._make_manager_with_thresholds(tds)
        report = manager.run_all_checks()
        self.assertEqual(report.alerts_active, len(report.events))

    # --- summary is non-empty ---
    def test_summary_is_non_empty(self):
        manager = self._make_manager_with_thresholds([])
        report = manager.run_all_checks()
        self.assertTrue(len(report.summary) > 0)


# ===========================================================================
# TestSaveReport (4)
# ===========================================================================

class TestSaveReport(unittest.TestCase):
    """Tests for AlertThresholdManager.save_report."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.data_dir = Path(self.tmpdir) / "data"
        self.data_dir.mkdir()
        self.manager = AlertThresholdManager(
            data_path=str(self.data_dir),
            thresholds=[],  # no thresholds — instant all_clear
        )

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_file_created(self):
        path = self.manager.save_report()
        self.assertTrue(os.path.exists(path))

    def test_no_tmp_files_left(self):
        self.manager.save_report()
        tmp_files = list(self.data_dir.glob("*.tmp"))
        self.assertEqual(len(tmp_files), 0)

    def test_saved_file_is_valid_json(self):
        path = self.manager.save_report()
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        self.assertIn("latest", data)
        self.assertIn("snapshots", data)

    def test_ring_buffer_max_48(self):
        # Save 50 reports — should keep only 48
        for _ in range(50):
            self.manager.save_report()
        out_path = self.data_dir / "alert_report.json"
        with open(out_path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        self.assertLessEqual(len(data["snapshots"]), RING_BUFFER_MAX)
        self.assertEqual(RING_BUFFER_MAX, 48)


# ===========================================================================
# TestFormatTelegramMessage (8)
# ===========================================================================

class TestFormatTelegramMessage(unittest.TestCase):
    """Tests for AlertThresholdManager.format_telegram_message."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.data_dir = Path(self.tmpdir) / "data"
        self.data_dir.mkdir()
        self.manager = AlertThresholdManager(
            data_path=str(self.data_dir),
            thresholds=[],
        )

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _build_active_report(
        self, critical=0, warning=0, info=0, messages=None
    ) -> AlertReport:
        events = []
        for i in range(critical):
            events.append(_make_event(
                name=f"crit_{i}", severity="CRITICAL",
                message=f"Critical alert {i}",
            ))
        for i in range(warning):
            events.append(_make_event(
                name=f"warn_{i}", severity="WARNING",
                message=f"Warning alert {i}",
            ))
        for i in range(info):
            events.append(_make_event(
                name=f"info_{i}", severity="INFO",
                message=f"Info alert {i}",
            ))
        total = critical + warning + info
        return AlertReport(
            generated_at="2026-06-13T08:00:00+00:00",
            thresholds_checked=9,
            alerts_active=total,
            critical_count=critical,
            warning_count=warning,
            info_count=info,
            events=events,
            all_clear=(total == 0),
        )

    def test_length_under_1500_chars(self):
        report = self._build_active_report(critical=2, warning=3, info=1)
        msg = self.manager.format_telegram_message(report)
        self.assertLessEqual(len(msg), 1500)

    def test_critical_emits_red_circle(self):
        report = self._build_active_report(critical=1)
        msg = self.manager.format_telegram_message(report)
        self.assertIn("🔴", msg)

    def test_warning_emits_yellow_circle(self):
        report = self._build_active_report(warning=1)
        msg = self.manager.format_telegram_message(report)
        self.assertIn("🟡", msg)

    def test_info_emits_info_emoji(self):
        report = self._build_active_report(info=1)
        msg = self.manager.format_telegram_message(report)
        self.assertIn("ℹ️", msg)

    def test_all_clear_emits_checkmark(self):
        report = self._build_active_report()  # no alerts
        msg = self.manager.format_telegram_message(report)
        self.assertIn("✅", msg)

    def test_all_clear_no_red_circle(self):
        report = self._build_active_report()
        msg = self.manager.format_telegram_message(report)
        self.assertNotIn("🔴", msg)

    def test_alert_count_in_message(self):
        report = self._build_active_report(critical=2, warning=1)
        msg = self.manager.format_telegram_message(report)
        self.assertIn("3", msg)

    def test_very_long_message_truncated_under_1500(self):
        # Build a report with many events to test truncation
        events = [
            _make_event(
                name=f"evt_{i}",
                severity="WARNING",
                message="A" * 100,
            )
            for i in range(20)
        ]
        report = AlertReport(
            generated_at="2026-06-13T08:00:00+00:00",
            thresholds_checked=20,
            alerts_active=20,
            critical_count=0,
            warning_count=20,
            info_count=0,
            events=events,
            all_clear=False,
        )
        msg = self.manager.format_telegram_message(report)
        self.assertLessEqual(len(msg), 1500)


# ===========================================================================
# TestCustomThresholds (4)
# ===========================================================================

class TestCustomThresholds(unittest.TestCase):
    """Tests for passing custom thresholds to AlertThresholdManager.__init__."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.data_dir = Path(self.tmpdir) / "data"
        self.data_dir.mkdir()

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _write_latest(self, filename: str, latest: dict) -> Path:
        path = self.data_dir / filename
        _atomic_write_json(path, {"latest": latest})
        return path

    def test_custom_thresholds_used_instead_of_defaults(self):
        self._write_latest("custom.json", {"effective_apy_pct": 2.0})
        custom_td = _make_threshold(
            name="apy_floor",
            metric_path=str(self.data_dir / "custom.json"),
            operator="lt",
            threshold_value=3.0,
        )
        manager = AlertThresholdManager(
            data_path=str(self.data_dir),
            thresholds=[custom_td],
        )
        report = manager.run_all_checks()
        # Should fire with our custom threshold
        self.assertEqual(report.thresholds_checked, 1)
        self.assertEqual(report.alerts_active, 1)

    def test_empty_custom_thresholds_all_clear(self):
        manager = AlertThresholdManager(
            data_path=str(self.data_dir),
            thresholds=[],
        )
        report = manager.run_all_checks()
        self.assertTrue(report.all_clear)
        self.assertEqual(report.thresholds_checked, 0)

    def test_multiple_custom_thresholds(self):
        self._write_latest("f.json", {
            "effective_apy_pct": 2.0,
            "t2_weight_pct": 60.0,
        })
        tds = [
            _make_threshold(
                name="apy_floor",
                metric_path=str(self.data_dir / "f.json"),
                operator="lt",
                threshold_value=3.0,
                severity="CRITICAL",
            ),
            _make_threshold(
                name="t2_cap_breach",
                metric_path=str(self.data_dir / "f.json"),
                operator="gt",
                threshold_value=50.0,
                severity="CRITICAL",
            ),
        ]
        manager = AlertThresholdManager(
            data_path=str(self.data_dir),
            thresholds=tds,
        )
        report = manager.run_all_checks()
        self.assertEqual(report.thresholds_checked, 2)
        self.assertEqual(report.alerts_active, 2)

    def test_custom_thresholds_do_not_affect_default(self):
        """DEFAULT_THRESHOLDS class attribute should not be mutated."""
        original_count = len(AlertThresholdManager.DEFAULT_THRESHOLDS)
        td = _make_threshold()
        manager = AlertThresholdManager(
            data_path=str(self.data_dir),
            thresholds=[td],
        )
        # Run checks with custom
        manager.run_all_checks()
        # Default should still have original count
        self.assertEqual(
            len(AlertThresholdManager.DEFAULT_THRESHOLDS),
            original_count,
        )


# ===========================================================================
# Entry point
# ===========================================================================

if __name__ == "__main__":
    unittest.main(verbosity=2)
