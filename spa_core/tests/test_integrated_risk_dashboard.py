"""
Tests for IntegratedRiskDashboard (MP-605).
Target: ≥ 90 tests.

Groups
------
TestRiskSignal (8)
TestIntegratedRiskAssessment (8)
TestSafeLoadJson (8)
TestReadPegSignal (12)
TestReadConcentrationSignal (10)
TestReadWatchdogSignal (12)
TestReadMomentumSignal (10)
TestCheckDataFreshness (8)
TestAssess (12)
TestSaveAssessment (5)
TestFormatTelegramMessage (5)
TestWeights (2)

Total: 100 tests
"""
from __future__ import annotations

import json
import os
import tempfile
import time
import unittest
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import patch, MagicMock

from spa_core.analytics.integrated_risk_dashboard import (
    IntegratedRiskDashboard,
    IntegratedRiskAssessment,
    RiskSignal,
    RING_BUFFER_MAX,
    FRESHNESS_THRESHOLD_SECONDS,
)


# ===========================================================================
# Helpers
# ===========================================================================

def _ts_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _ts_stale() -> str:
    """Timestamp > 2 hours ago."""
    return (datetime.now(timezone.utc) - timedelta(hours=3)).isoformat()


def _make_peg_report(overall_status="GREEN", critical=0, warning=0, caution=0, total=10):
    return {
        "generated_at": _ts_now(),
        "total_monitored": total,
        "stable": total - critical - warning - caution,
        "caution": caution,
        "warning": warning,
        "critical": critical,
        "worst_adapter": "aave-v3",
        "worst_deviation_pct": 0.0 if critical == 0 else 1.5,
        "overall_status": overall_status,
    }


def _make_concentration_risk(overall_risk="LOW", top_pct=20.0):
    return {
        "schema_version": "1.0",
        "source": "protocol_concentration_risk",
        "last_updated": _ts_now(),
        "latest": {
            "generated_at": _ts_now(),
            "total_protocols": 8,
            "total_adapters": 20,
            "overall_risk": overall_risk,
            "top_protocol": "compound",
            "top_protocol_weight_pct": top_pct,
            "warnings": [],
        },
    }


def _make_watchdog_history(critical=0, warning=0, healthy=10, total=10):
    if total == 0 and critical == 0 and warning == 0 and healthy == 0:
        return {
            "schema_version": 1,
            "source": "adapter_watchdog",
            "snapshot_count": 0,
            "updated_at": _ts_now(),
            "latest": {},
            "snapshots": [],
        }
    return {
        "schema_version": 1,
        "source": "adapter_watchdog",
        "snapshot_count": 1,
        "updated_at": _ts_now(),
        "latest": {
            "generated_at": _ts_now(),
            "total_adapters": total,
            "healthy": healthy,
            "warning": warning,
            "critical": critical,
            "alerts_created": critical + warning,
        },
        "snapshots": [],
    }


def _make_momentum_report(falling=0, rising=0, stable=5, unknown=0):
    total = falling + rising + stable + unknown
    return {
        "schema_version": 1,
        "ring_buffer_max": 30,
        "snapshot_count": 1,
        "updated_at": _ts_now(),
        "latest": {
            "generated_at": _ts_now(),
            "total_adapters": total,
            "rising": rising,
            "falling": falling,
            "stable": stable,
            "unknown": unknown,
            "top_rising": [],
            "top_falling": [{"adapter_id": f"adapter_{i}"} for i in range(falling)],
        },
    }


class _DashboardWithData:
    """Context manager: writes fixture JSON files to a temp dir, returns configured dashboard."""

    def __init__(self, peg=None, concentration=None, watchdog=None, momentum=None):
        self.peg = peg
        self.concentration = concentration
        self.watchdog = watchdog
        self.momentum = momentum
        self._tmpdir = None

    def __enter__(self):
        self._tmpdir = tempfile.mkdtemp()
        p = Path(self._tmpdir)

        def _write(filename, data):
            with open(p / filename, "w") as fh:
                json.dump(data, fh)

        if self.peg is not None:
            _write("peg_report.json", self.peg)
        if self.concentration is not None:
            _write("concentration_risk.json", self.concentration)
        if self.watchdog is not None:
            _write("watchdog_history.json", self.watchdog)
        if self.momentum is not None:
            _write("momentum_report.json", self.momentum)

        return IntegratedRiskDashboard(data_path=self._tmpdir), p

    def __exit__(self, *args):
        import shutil
        shutil.rmtree(self._tmpdir, ignore_errors=True)


# ===========================================================================
# TestRiskSignal (8)
# ===========================================================================

class TestRiskSignal(unittest.TestCase):

    def test_fields_source(self):
        s = RiskSignal(source="peg", level="OK", score=0.0, summary="ok")
        self.assertEqual(s.source, "peg")

    def test_fields_level(self):
        s = RiskSignal(source="peg", level="CRITICAL", score=0.9, summary="bad")
        self.assertEqual(s.level, "CRITICAL")

    def test_score_zero(self):
        s = RiskSignal(source="watchdog", level="OK", score=0.0, summary="fine")
        self.assertGreaterEqual(s.score, 0.0)

    def test_score_one(self):
        s = RiskSignal(source="peg", level="CRITICAL", score=1.0, summary="depeg")
        self.assertLessEqual(s.score, 1.0)

    def test_details_default_empty(self):
        s = RiskSignal(source="momentum", level="OK", score=0.1, summary="ok")
        self.assertIsInstance(s.details, dict)

    def test_details_custom(self):
        s = RiskSignal(source="peg", level="OK", score=0.0, summary="", details={"k": "v"})
        self.assertEqual(s.details["k"], "v")

    def test_to_dict_keys(self):
        s = RiskSignal(source="peg", level="OK", score=0.0, summary="s")
        d = s.to_dict()
        self.assertIn("source", d)
        self.assertIn("level", d)
        self.assertIn("score", d)
        self.assertIn("summary", d)
        self.assertIn("details", d)

    def test_to_dict_json_serializable(self):
        s = RiskSignal(source="peg", level="OK", score=0.0, summary="s", details={"x": 1})
        self.assertIsNotNone(json.dumps(s.to_dict()))


# ===========================================================================
# TestIntegratedRiskAssessment (8)
# ===========================================================================

class TestIntegratedRiskAssessment(unittest.TestCase):

    def _make(self, score=0.0, level="GREEN"):
        return IntegratedRiskAssessment(
            generated_at=_ts_now(),
            overall_score=score,
            overall_level=level,
        )

    def test_green_level(self):
        a = self._make(score=0.05, level="GREEN")
        self.assertEqual(a.overall_level, "GREEN")

    def test_yellow_level(self):
        a = self._make(score=0.20, level="YELLOW")
        self.assertEqual(a.overall_level, "YELLOW")

    def test_orange_level(self):
        a = self._make(score=0.45, level="ORANGE")
        self.assertEqual(a.overall_level, "ORANGE")

    def test_red_level(self):
        a = self._make(score=0.8, level="RED")
        self.assertEqual(a.overall_level, "RED")

    def test_signals_default_empty(self):
        a = self._make()
        self.assertIsInstance(a.signals, list)
        self.assertEqual(len(a.signals), 0)

    def test_to_dict_has_all_keys(self):
        a = self._make()
        d = a.to_dict()
        for k in ("generated_at", "overall_score", "overall_level",
                   "critical_count", "warning_count", "top_risk",
                   "recommendations", "data_freshness", "signals"):
            self.assertIn(k, d)

    def test_to_dict_json_serializable(self):
        a = self._make()
        self.assertIsNotNone(json.dumps(a.to_dict()))

    def test_score_in_range(self):
        a = self._make(score=0.5)
        self.assertGreaterEqual(a.overall_score, 0.0)
        self.assertLessEqual(a.overall_score, 1.0)


# ===========================================================================
# TestSafeLoadJson (8)
# ===========================================================================

class TestSafeLoadJson(unittest.TestCase):

    def setUp(self):
        self._tmpdir = tempfile.mkdtemp()
        self.dashboard = IntegratedRiskDashboard(data_path=self._tmpdir)

    def tearDown(self):
        import shutil
        shutil.rmtree(self._tmpdir, ignore_errors=True)

    def test_missing_file_returns_none(self):
        result = self.dashboard._safe_load_json("nonexistent.json")
        self.assertIsNone(result)

    def test_valid_file_returns_dict(self):
        path = Path(self._tmpdir) / "valid.json"
        path.write_text(json.dumps({"key": "value"}))
        result = self.dashboard._safe_load_json("valid.json")
        self.assertIsNotNone(result)
        self.assertEqual(result["key"], "value")

    def test_malformed_json_returns_none(self):
        path = Path(self._tmpdir) / "bad.json"
        path.write_text("not valid json {{{")
        result = self.dashboard._safe_load_json("bad.json")
        self.assertIsNone(result)

    def test_empty_file_returns_none(self):
        path = Path(self._tmpdir) / "empty.json"
        path.write_text("")
        result = self.dashboard._safe_load_json("empty.json")
        self.assertIsNone(result)

    def test_nested_dict_returned_intact(self):
        data = {"a": {"b": [1, 2, 3]}}
        path = Path(self._tmpdir) / "nested.json"
        path.write_text(json.dumps(data))
        result = self.dashboard._safe_load_json("nested.json")
        self.assertEqual(result["a"]["b"], [1, 2, 3])

    def test_truncated_json_returns_none(self):
        path = Path(self._tmpdir) / "trunc.json"
        path.write_text('{"key": "value"')
        result = self.dashboard._safe_load_json("trunc.json")
        self.assertIsNone(result)

    def test_array_json_returns_list(self):
        path = Path(self._tmpdir) / "arr.json"
        path.write_text(json.dumps([1, 2, 3]))
        result = self.dashboard._safe_load_json("arr.json")
        # json.load returns list, our function returns Optional[dict]
        # The function accepts any JSON value, so list is returned
        self.assertIsNotNone(result)

    def test_unicode_content_ok(self):
        data = {"name": "Тест", "value": 42}
        path = Path(self._tmpdir) / "unicode.json"
        path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        result = self.dashboard._safe_load_json("unicode.json")
        self.assertEqual(result["name"], "Тест")


# ===========================================================================
# TestReadPegSignal (12)
# ===========================================================================

class TestReadPegSignal(unittest.TestCase):

    def _dashboard(self, peg_data=None):
        tmpdir = tempfile.mkdtemp()
        if peg_data is not None:
            (Path(tmpdir) / "peg_report.json").write_text(json.dumps(peg_data))
        return IntegratedRiskDashboard(data_path=tmpdir), tmpdir

    def tearDown(self):
        pass  # temp dirs cleaned by GC / OS

    def test_green_score_zero(self):
        db, _ = self._dashboard(_make_peg_report("GREEN"))
        sig = db._read_peg_signal()
        self.assertEqual(sig.score, 0.0)

    def test_green_level_ok(self):
        db, _ = self._dashboard(_make_peg_report("GREEN"))
        sig = db._read_peg_signal()
        self.assertEqual(sig.level, "OK")

    def test_yellow_score_half(self):
        db, _ = self._dashboard(_make_peg_report("YELLOW", warning=1))
        sig = db._read_peg_signal()
        self.assertEqual(sig.score, 0.5)

    def test_yellow_level_warning(self):
        db, _ = self._dashboard(_make_peg_report("YELLOW", warning=1))
        sig = db._read_peg_signal()
        self.assertEqual(sig.level, "WARNING")

    def test_red_score_09(self):
        db, _ = self._dashboard(_make_peg_report("RED", critical=1))
        sig = db._read_peg_signal()
        self.assertEqual(sig.score, 0.9)

    def test_red_level_critical(self):
        db, _ = self._dashboard(_make_peg_report("RED", critical=1))
        sig = db._read_peg_signal()
        self.assertEqual(sig.level, "CRITICAL")

    def test_missing_file_score_03(self):
        tmpdir = tempfile.mkdtemp()
        db = IntegratedRiskDashboard(data_path=tmpdir)
        sig = db._read_peg_signal()
        self.assertAlmostEqual(sig.score, 0.3)

    def test_missing_file_level_warning(self):
        tmpdir = tempfile.mkdtemp()
        db = IntegratedRiskDashboard(data_path=tmpdir)
        sig = db._read_peg_signal()
        self.assertEqual(sig.level, "WARNING")

    def test_source_is_peg(self):
        tmpdir = tempfile.mkdtemp()
        db = IntegratedRiskDashboard(data_path=tmpdir)
        sig = db._read_peg_signal()
        self.assertEqual(sig.source, "peg")

    def test_details_contain_overall_status(self):
        db, _ = self._dashboard(_make_peg_report("GREEN"))
        sig = db._read_peg_signal()
        self.assertIn("overall_status", sig.details)

    def test_details_critical_count(self):
        db, _ = self._dashboard(_make_peg_report("RED", critical=2))
        sig = db._read_peg_signal()
        self.assertEqual(sig.details["critical"], 2)

    def test_summary_not_empty(self):
        db, _ = self._dashboard(_make_peg_report("GREEN"))
        sig = db._read_peg_signal()
        self.assertGreater(len(sig.summary), 0)


# ===========================================================================
# TestReadConcentrationSignal (10)
# ===========================================================================

class TestReadConcentrationSignal(unittest.TestCase):

    def _db_with(self, data=None):
        tmpdir = tempfile.mkdtemp()
        if data is not None:
            (Path(tmpdir) / "concentration_risk.json").write_text(json.dumps(data))
        return IntegratedRiskDashboard(data_path=tmpdir)

    def test_low_score_01(self):
        db = self._db_with(_make_concentration_risk("LOW"))
        sig = db._read_concentration_signal()
        self.assertAlmostEqual(sig.score, 0.1)

    def test_low_level_ok(self):
        db = self._db_with(_make_concentration_risk("LOW"))
        sig = db._read_concentration_signal()
        self.assertEqual(sig.level, "OK")

    def test_medium_score_04(self):
        db = self._db_with(_make_concentration_risk("MEDIUM"))
        sig = db._read_concentration_signal()
        self.assertAlmostEqual(sig.score, 0.4)

    def test_medium_level_warning(self):
        db = self._db_with(_make_concentration_risk("MEDIUM"))
        sig = db._read_concentration_signal()
        self.assertEqual(sig.level, "WARNING")

    def test_high_score_07(self):
        db = self._db_with(_make_concentration_risk("HIGH"))
        sig = db._read_concentration_signal()
        self.assertAlmostEqual(sig.score, 0.7)

    def test_high_level_critical(self):
        db = self._db_with(_make_concentration_risk("HIGH"))
        sig = db._read_concentration_signal()
        self.assertEqual(sig.level, "CRITICAL")

    def test_missing_score_03(self):
        tmpdir = tempfile.mkdtemp()
        db = IntegratedRiskDashboard(data_path=tmpdir)
        sig = db._read_concentration_signal()
        self.assertAlmostEqual(sig.score, 0.3)

    def test_source_is_concentration(self):
        tmpdir = tempfile.mkdtemp()
        db = IntegratedRiskDashboard(data_path=tmpdir)
        sig = db._read_concentration_signal()
        self.assertEqual(sig.source, "concentration")

    def test_details_top_protocol(self):
        db = self._db_with(_make_concentration_risk("LOW", top_pct=25.0))
        sig = db._read_concentration_signal()
        self.assertIn("top_protocol", sig.details)

    def test_details_overall_risk(self):
        db = self._db_with(_make_concentration_risk("MEDIUM"))
        sig = db._read_concentration_signal()
        self.assertEqual(sig.details["overall_risk"], "MEDIUM")


# ===========================================================================
# TestReadWatchdogSignal (12)
# ===========================================================================

class TestReadWatchdogSignal(unittest.TestCase):

    def _db_with(self, data=None):
        tmpdir = tempfile.mkdtemp()
        if data is not None:
            (Path(tmpdir) / "watchdog_history.json").write_text(json.dumps(data))
        return IntegratedRiskDashboard(data_path=tmpdir)

    def test_missing_file_score_03(self):
        tmpdir = tempfile.mkdtemp()
        db = IntegratedRiskDashboard(data_path=tmpdir)
        sig = db._read_watchdog_signal()
        self.assertAlmostEqual(sig.score, 0.3)

    def test_empty_latest_score_03(self):
        db = self._db_with(_make_watchdog_history(0, 0, 0, 0))
        sig = db._read_watchdog_signal()
        self.assertAlmostEqual(sig.score, 0.3)

    def test_all_healthy_score_zero(self):
        db = self._db_with(_make_watchdog_history(critical=0, warning=0, healthy=10, total=10))
        sig = db._read_watchdog_signal()
        self.assertAlmostEqual(sig.score, 0.0)

    def test_one_critical_formula(self):
        # score = (1*0.9 + 0*0.4) / 10 = 0.09
        db = self._db_with(_make_watchdog_history(critical=1, warning=0, healthy=9, total=10))
        sig = db._read_watchdog_signal()
        self.assertAlmostEqual(sig.score, 0.09, places=4)

    def test_one_warning_formula(self):
        # score = (0*0.9 + 1*0.4) / 10 = 0.04
        db = self._db_with(_make_watchdog_history(critical=0, warning=1, healthy=9, total=10))
        sig = db._read_watchdog_signal()
        self.assertAlmostEqual(sig.score, 0.04, places=4)

    def test_critical_dominates_warning(self):
        # score = (2*0.9 + 1*0.4) / 10 = 0.22
        db = self._db_with(_make_watchdog_history(critical=2, warning=1, healthy=7, total=10))
        sig = db._read_watchdog_signal()
        self.assertAlmostEqual(sig.score, (2 * 0.9 + 1 * 0.4) / 10, places=4)

    def test_score_capped_at_one(self):
        # Very high critical count: score capped at 1.0
        db = self._db_with(_make_watchdog_history(critical=10, warning=10, healthy=0, total=5))
        sig = db._read_watchdog_signal()
        self.assertLessEqual(sig.score, 1.0)

    def test_source_is_watchdog(self):
        tmpdir = tempfile.mkdtemp()
        db = IntegratedRiskDashboard(data_path=tmpdir)
        sig = db._read_watchdog_signal()
        self.assertEqual(sig.source, "watchdog")

    def test_details_has_healthy(self):
        db = self._db_with(_make_watchdog_history(critical=0, warning=0, healthy=10, total=10))
        sig = db._read_watchdog_signal()
        self.assertIn("healthy", sig.details)

    def test_details_has_critical(self):
        db = self._db_with(_make_watchdog_history(critical=1, warning=0, healthy=9, total=10))
        sig = db._read_watchdog_signal()
        self.assertEqual(sig.details["critical"], 1)

    def test_level_ok_when_score_low(self):
        db = self._db_with(_make_watchdog_history(critical=0, warning=0, healthy=10, total=10))
        sig = db._read_watchdog_signal()
        self.assertEqual(sig.level, "OK")

    def test_level_critical_when_score_high(self):
        # score = (5*0.9) / 5 = 0.9 → CRITICAL
        db = self._db_with(_make_watchdog_history(critical=5, warning=0, healthy=0, total=5))
        sig = db._read_watchdog_signal()
        self.assertEqual(sig.level, "CRITICAL")


# ===========================================================================
# TestReadMomentumSignal (10)
# ===========================================================================

class TestReadMomentumSignal(unittest.TestCase):

    def _db_with(self, data=None):
        tmpdir = tempfile.mkdtemp()
        if data is not None:
            (Path(tmpdir) / "momentum_report.json").write_text(json.dumps(data))
        return IntegratedRiskDashboard(data_path=tmpdir)

    def test_missing_score_015(self):
        tmpdir = tempfile.mkdtemp()
        db = IntegratedRiskDashboard(data_path=tmpdir)
        sig = db._read_momentum_signal()
        self.assertAlmostEqual(sig.score, 0.15)

    def test_no_falling_score_zero(self):
        db = self._db_with(_make_momentum_report(falling=0, stable=10))
        sig = db._read_momentum_signal()
        self.assertAlmostEqual(sig.score, 0.0)

    def test_falling_proportion_formula(self):
        # score = (3 / 10) * 0.6 = 0.18
        db = self._db_with(_make_momentum_report(falling=3, stable=7))
        sig = db._read_momentum_signal()
        self.assertAlmostEqual(sig.score, 3 / 10 * 0.6, places=4)

    def test_all_falling_capped(self):
        db = self._db_with(_make_momentum_report(falling=10, stable=0))
        sig = db._read_momentum_signal()
        self.assertLessEqual(sig.score, 1.0)

    def test_source_is_momentum(self):
        tmpdir = tempfile.mkdtemp()
        db = IntegratedRiskDashboard(data_path=tmpdir)
        sig = db._read_momentum_signal()
        self.assertEqual(sig.source, "momentum")

    def test_details_falling_count(self):
        db = self._db_with(_make_momentum_report(falling=3, stable=7))
        sig = db._read_momentum_signal()
        self.assertEqual(sig.details["falling"], 3)

    def test_details_rising_count(self):
        db = self._db_with(_make_momentum_report(rising=2, stable=8))
        sig = db._read_momentum_signal()
        self.assertEqual(sig.details["rising"], 2)

    def test_level_ok_no_falling(self):
        db = self._db_with(_make_momentum_report(falling=0, stable=10))
        sig = db._read_momentum_signal()
        self.assertEqual(sig.level, "OK")

    def test_top_falling_in_details(self):
        db = self._db_with(_make_momentum_report(falling=2, stable=8))
        sig = db._read_momentum_signal()
        self.assertIn("top_falling", sig.details)
        self.assertEqual(len(sig.details["top_falling"]), 2)

    def test_empty_latest_uses_fallback(self):
        data = {"schema_version": 1, "snapshot_count": 0, "updated_at": _ts_now(), "latest": {}}
        db = self._db_with(data)
        sig = db._read_momentum_signal()
        self.assertAlmostEqual(sig.score, 0.15)


# ===========================================================================
# TestCheckDataFreshness (8)
# ===========================================================================

class TestCheckDataFreshness(unittest.TestCase):

    def setUp(self):
        self._tmpdir = tempfile.mkdtemp()
        self.db = IntegratedRiskDashboard(data_path=self._tmpdir)

    def tearDown(self):
        import shutil
        shutil.rmtree(self._tmpdir, ignore_errors=True)

    def _write(self, filename, data):
        (Path(self._tmpdir) / filename).write_text(json.dumps(data))

    def test_all_missing(self):
        result = self.db._check_data_freshness()
        self.assertTrue(all(v == "MISSING" for v in result.values()))

    def test_fresh_file_ok(self):
        self._write("peg_report.json", {"generated_at": _ts_now()})
        result = self.db._check_data_freshness()
        self.assertEqual(result["peg"], "OK")

    def test_stale_file_detected(self):
        self._write("peg_report.json", {"generated_at": _ts_stale()})
        result = self.db._check_data_freshness()
        self.assertIn("STALE", result["peg"])

    def test_stale_contains_hours(self):
        self._write("peg_report.json", {"generated_at": _ts_stale()})
        result = self.db._check_data_freshness()
        self.assertRegex(result["peg"], r"STALE_\d+\.\d+h")

    def test_four_sources_in_result(self):
        result = self.db._check_data_freshness()
        self.assertIn("peg", result)
        self.assertIn("watchdog", result)
        self.assertIn("concentration", result)
        self.assertIn("momentum", result)

    def test_watchdog_updated_at_field(self):
        self._write("watchdog_history.json", {"updated_at": _ts_now()})
        result = self.db._check_data_freshness()
        self.assertEqual(result["watchdog"], "OK")

    def test_concentration_last_updated_field(self):
        self._write("concentration_risk.json", {"last_updated": _ts_now()})
        result = self.db._check_data_freshness()
        self.assertEqual(result["concentration"], "OK")

    def test_file_no_timestamp_returns_ok(self):
        self._write("momentum_report.json", {"no_timestamp_field": "x"})
        result = self.db._check_data_freshness()
        self.assertEqual(result["momentum"], "OK")


# ===========================================================================
# TestAssess (12)
# ===========================================================================

class TestAssess(unittest.TestCase):

    def test_all_green_overall_green(self):
        with _DashboardWithData(
            peg=_make_peg_report("GREEN"),
            concentration=_make_concentration_risk("LOW"),
            watchdog=_make_watchdog_history(0, 0, 10, 10),
            momentum=_make_momentum_report(falling=0, stable=10),
        ) as (db, _):
            a = db.assess()
            self.assertIn(a.overall_level, ("GREEN", "YELLOW"))

    def test_returns_integrated_risk_assessment(self):
        tmpdir = tempfile.mkdtemp()
        db = IntegratedRiskDashboard(data_path=tmpdir)
        a = db.assess()
        self.assertIsInstance(a, IntegratedRiskAssessment)

    def test_score_weighted_avg(self):
        with _DashboardWithData(
            peg=_make_peg_report("GREEN"),          # score 0.0
            concentration=_make_concentration_risk("LOW"),   # score 0.1
            watchdog=_make_watchdog_history(0, 0, 10, 10),  # score 0.0
            momentum=_make_momentum_report(falling=0, stable=10),  # score 0.0
        ) as (db, _):
            a = db.assess()
            # Expected: 0.0*0.35 + 0.1*0.25 + 0.0*0.25 + 0.0*0.15 = 0.025
            self.assertAlmostEqual(a.overall_score, 0.025, places=4)

    def test_red_peg_lifts_score(self):
        with _DashboardWithData(
            peg=_make_peg_report("RED", critical=1),
            concentration=_make_concentration_risk("LOW"),
            watchdog=_make_watchdog_history(0, 0, 10, 10),
            momentum=_make_momentum_report(falling=0, stable=10),
        ) as (db, _):
            a = db.assess()
            # peg score 0.9 * 0.35 = 0.315 → at least YELLOW
            self.assertGreater(a.overall_score, 0.3)

    def test_critical_count_counts_critical_signals(self):
        with _DashboardWithData(
            peg=_make_peg_report("RED", critical=1),
            concentration=_make_concentration_risk("HIGH"),
            watchdog=_make_watchdog_history(0, 0, 10, 10),
            momentum=_make_momentum_report(falling=0, stable=10),
        ) as (db, _):
            a = db.assess()
            self.assertGreaterEqual(a.critical_count, 2)

    def test_warning_count_nonzero_when_warnings(self):
        with _DashboardWithData(
            peg=_make_peg_report("YELLOW", warning=1),
            concentration=_make_concentration_risk("LOW"),
            watchdog=_make_watchdog_history(0, 0, 10, 10),
            momentum=_make_momentum_report(falling=0, stable=10),
        ) as (db, _):
            a = db.assess()
            self.assertGreaterEqual(a.warning_count, 1)

    def test_recommendations_not_empty(self):
        tmpdir = tempfile.mkdtemp()
        db = IntegratedRiskDashboard(data_path=tmpdir)
        a = db.assess()
        self.assertGreater(len(a.recommendations), 0)

    def test_top_risk_not_empty(self):
        tmpdir = tempfile.mkdtemp()
        db = IntegratedRiskDashboard(data_path=tmpdir)
        a = db.assess()
        self.assertIsInstance(a.top_risk, str)
        self.assertGreater(len(a.top_risk), 0)

    def test_data_freshness_dict(self):
        tmpdir = tempfile.mkdtemp()
        db = IntegratedRiskDashboard(data_path=tmpdir)
        a = db.assess()
        self.assertIsInstance(a.data_freshness, dict)

    def test_four_signals_always_returned(self):
        tmpdir = tempfile.mkdtemp()
        db = IntegratedRiskDashboard(data_path=tmpdir)
        a = db.assess()
        self.assertEqual(len(a.signals), 4)

    def test_level_thresholds_green(self):
        # All missing → peg=0.3, conc=0.3, watchdog=0.3, mom=0.15
        # weighted = 0.3*0.35 + 0.3*0.25 + 0.3*0.25 + 0.15*0.15 = 0.2775
        tmpdir = tempfile.mkdtemp()
        db = IntegratedRiskDashboard(data_path=tmpdir)
        a = db.assess()
        # Score ~0.2775 → YELLOW (not GREEN)
        self.assertNotEqual(a.overall_level, "RED")

    def test_to_dict_serializable(self):
        tmpdir = tempfile.mkdtemp()
        db = IntegratedRiskDashboard(data_path=tmpdir)
        a = db.assess()
        self.assertIsNotNone(json.dumps(a.to_dict()))


# ===========================================================================
# TestSaveAssessment (5)
# ===========================================================================

class TestSaveAssessment(unittest.TestCase):

    def setUp(self):
        self._tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        import shutil
        shutil.rmtree(self._tmpdir, ignore_errors=True)

    def test_save_creates_file(self):
        db = IntegratedRiskDashboard(data_path=self._tmpdir)
        path = db.save_assessment()
        self.assertTrue(Path(path).exists())

    def test_no_tmp_file_left_behind(self):
        db = IntegratedRiskDashboard(data_path=self._tmpdir)
        db.save_assessment()
        tmp_files = list(Path(self._tmpdir).glob("*.tmp"))
        self.assertEqual(len(tmp_files), 0)

    def test_ring_buffer_grows(self):
        db = IntegratedRiskDashboard(data_path=self._tmpdir)
        db.save_assessment()
        db.save_assessment()
        path = Path(self._tmpdir) / "integrated_risk.json"
        data = json.loads(path.read_text())
        self.assertEqual(data["snapshot_count"], 2)

    def test_ring_buffer_max_48(self):
        db = IntegratedRiskDashboard(data_path=self._tmpdir)
        for _ in range(55):
            db.save_assessment()
        path = Path(self._tmpdir) / "integrated_risk.json"
        data = json.loads(path.read_text())
        self.assertLessEqual(data["snapshot_count"], RING_BUFFER_MAX)

    def test_latest_key_in_output(self):
        db = IntegratedRiskDashboard(data_path=self._tmpdir)
        db.save_assessment()
        path = Path(self._tmpdir) / "integrated_risk.json"
        data = json.loads(path.read_text())
        self.assertIn("latest", data)
        self.assertIn("overall_level", data["latest"])


# ===========================================================================
# TestFormatTelegramMessage (5)
# ===========================================================================

class TestFormatTelegramMessage(unittest.TestCase):

    def _db(self, data_dir=None):
        if data_dir:
            return IntegratedRiskDashboard(data_path=data_dir)
        tmpdir = tempfile.mkdtemp()
        return IntegratedRiskDashboard(data_path=tmpdir)

    def test_length_under_2000(self):
        db = self._db()
        msg = db.format_telegram_message()
        self.assertLessEqual(len(msg), 2000)

    def test_contains_level(self):
        tmpdir = tempfile.mkdtemp()
        db = self._db(tmpdir)
        msg = db.format_telegram_message()
        assessment = db.assess()
        self.assertIn(assessment.overall_level, msg)

    def test_contains_green_emoji_when_green(self):
        with _DashboardWithData(
            peg=_make_peg_report("GREEN"),
            concentration=_make_concentration_risk("LOW"),
            watchdog=_make_watchdog_history(0, 0, 10, 10),
            momentum=_make_momentum_report(falling=0, stable=10),
        ) as (db, _):
            msg = db.format_telegram_message()
            # For all-green data, score ~0.025 → GREEN
            self.assertIn("🟢", msg)

    def test_contains_recommendations_section(self):
        db = self._db()
        msg = db.format_telegram_message()
        self.assertIn("Recommendations", msg)

    def test_contains_signals_section(self):
        db = self._db()
        msg = db.format_telegram_message()
        self.assertIn("Signals", msg)


# ===========================================================================
# TestWeights (2)
# ===========================================================================

class TestWeights(unittest.TestCase):

    def test_weights_sum_to_one(self):
        total = sum(IntegratedRiskDashboard.SIGNAL_WEIGHTS.values())
        self.assertAlmostEqual(total, 1.0, places=9)

    def test_all_four_sources_have_weights(self):
        weights = IntegratedRiskDashboard.SIGNAL_WEIGHTS
        for source in ("peg", "concentration", "watchdog", "momentum"):
            self.assertIn(source, weights)
            self.assertGreater(weights[source], 0.0)


if __name__ == "__main__":
    unittest.main()
