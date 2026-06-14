"""
test_adapter_watchdog.py — MP-596 tests for AdapterWatchdog.

90+ unit tests. All tests use in-memory / tempdir mock data.
Run: python3 -m unittest spa_core.tests.test_adapter_watchdog -v
"""
from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from spa_core.monitoring.adapter_watchdog import (
    RING_BUFFER_MAX,
    AdapterHealth,
    AdapterWatchdog,
    WatchdogReport,
    _atomic_write_json,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_adapter_entry(
    protocol_key: str = "aave_v3",
    tier: str = "T1",
    chains: list = None,
    mock_apy_eth_usdc: float = 4.2,
    risk_score: float = None,
    usdc_price: float = None,
) -> dict:
    entry = {
        "protocol_key": protocol_key,
        "tier": tier,
        "chains": chains or ["ethereum"],
        "mock_apy": {
            "ethereum": {"USDC": mock_apy_eth_usdc}
        },
    }
    if risk_score is not None:
        entry["risk_score"] = risk_score
    if usdc_price is not None:
        entry["usdc_price"] = usdc_price
    return entry


def _make_adapter_status(*entries: dict) -> dict:
    return {
        "generated_at": "2026-06-13T10:00:00+00:00",
        "schema_version": 1,
        "adapters": list(entries),
    }


def _make_prev_snapshot(adapter_statuses: list) -> dict:
    return {
        "generated_at": "2026-06-12T10:00:00+00:00",
        "total_adapters": len(adapter_statuses),
        "healthy": len(adapter_statuses),
        "warning": 0,
        "critical": 0,
        "alerts_created": 0,
        "summary": "prev",
        "adapter_statuses": adapter_statuses,
    }


def _make_history(snapshots: list) -> dict:
    latest = snapshots[-1] if snapshots else {}
    return {
        "schema_version": 1,
        "source": "adapter_watchdog",
        "ring_buffer_max": RING_BUFFER_MAX,
        "snapshot_count": len(snapshots),
        "updated_at": latest.get("generated_at", ""),
        "latest": latest,
        "snapshots": snapshots,
    }


def _make_watchdog(tmpdir: str) -> AdapterWatchdog:
    return AdapterWatchdog(data_path=tmpdir, use_alert_dispatcher=False)


# ===========================================================================
# TestAdapterHealth
# ===========================================================================

class TestAdapterHealth(unittest.TestCase):
    """10 tests — AdapterHealth dataclass."""

    def _make(self, **kw) -> AdapterHealth:
        defaults = dict(
            adapter_id="aave_v3",
            chain="ethereum",
            tier="T1",
            apy_pct=4.2,
            risk_score=0.20,
            peg_price=1.0,
            is_healthy=True,
            apy_change_pct=0.0,
            alert_level="OK",
        )
        defaults.update(kw)
        return AdapterHealth(**defaults)

    def test_01_adapter_id_type(self):
        h = self._make(adapter_id="aave_v3")
        self.assertIsInstance(h.adapter_id, str)

    def test_02_chain_type(self):
        h = self._make(chain="ethereum")
        self.assertIsInstance(h.chain, str)

    def test_03_tier_type(self):
        h = self._make(tier="T1")
        self.assertIsInstance(h.tier, str)

    def test_04_apy_pct_float(self):
        h = self._make(apy_pct=5.5)
        self.assertAlmostEqual(h.apy_pct, 5.5)

    def test_05_risk_score_float(self):
        h = self._make(risk_score=0.35)
        self.assertAlmostEqual(h.risk_score, 0.35)

    def test_06_peg_price_float(self):
        h = self._make(peg_price=0.998)
        self.assertAlmostEqual(h.peg_price, 0.998)

    def test_07_is_healthy_true(self):
        h = self._make(is_healthy=True)
        self.assertTrue(h.is_healthy)

    def test_08_is_healthy_false_apy_zero(self):
        h = self._make(apy_pct=0.0, is_healthy=False)
        self.assertFalse(h.is_healthy)

    def test_09_apy_change_pct_type(self):
        h = self._make(apy_change_pct=-1.5)
        self.assertIsInstance(h.apy_change_pct, float)

    def test_10_alert_level_string(self):
        for lvl in ("OK", "WARNING", "CRITICAL"):
            h = self._make(alert_level=lvl)
            self.assertEqual(h.alert_level, lvl)


# ===========================================================================
# TestWatchdogReport
# ===========================================================================

class TestWatchdogReport(unittest.TestCase):
    """8 tests — WatchdogReport dataclass."""

    def _make_report(self, **kw) -> WatchdogReport:
        defaults = dict(
            generated_at="2026-06-13T10:00:00+00:00",
            total_adapters=5,
            healthy=3,
            warning=1,
            critical=1,
            alerts_created=2,
            adapter_statuses=[],
            summary="OK 3 WARN 1 CRIT 1",
        )
        defaults.update(kw)
        return WatchdogReport(**defaults)

    def test_01_generated_at_type(self):
        r = self._make_report()
        self.assertIsInstance(r.generated_at, str)

    def test_02_total_adapters_int(self):
        r = self._make_report(total_adapters=10)
        self.assertEqual(r.total_adapters, 10)

    def test_03_healthy_count(self):
        r = self._make_report(healthy=3)
        self.assertEqual(r.healthy, 3)

    def test_04_warning_count(self):
        r = self._make_report(warning=2)
        self.assertEqual(r.warning, 2)

    def test_05_critical_count(self):
        r = self._make_report(critical=1)
        self.assertEqual(r.critical, 1)

    def test_06_alerts_created_int(self):
        r = self._make_report(alerts_created=4)
        self.assertEqual(r.alerts_created, 4)

    def test_07_summary_is_string(self):
        r = self._make_report(summary="hello summary")
        self.assertIsInstance(r.summary, str)
        self.assertEqual(r.summary, "hello summary")

    def test_08_adapter_statuses_list(self):
        h = AdapterHealth("a", "eth", "T1", 4.0, 0.2, 1.0, True, 0.0, "OK")
        r = self._make_report(adapter_statuses=[h])
        self.assertEqual(len(r.adapter_statuses), 1)
        self.assertIsInstance(r.adapter_statuses[0], AdapterHealth)


# ===========================================================================
# TestLoadCurrentStatus
# ===========================================================================

class TestLoadCurrentStatus(unittest.TestCase):
    """10 tests — load_current_status."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.wd = _make_watchdog(self.tmp)

    def _write(self, data, filename="adapter_status.json"):
        path = os.path.join(self.tmp, filename)
        with open(path, "w") as f:
            json.dump(data, f)

    def test_01_missing_file_returns_empty(self):
        result = self.wd.load_current_status()
        self.assertIsInstance(result, dict)
        self.assertEqual(result, {})

    def test_02_valid_dict_returned(self):
        self._write({"key": "val"})
        result = self.wd.load_current_status()
        self.assertEqual(result, {"key": "val"})

    def test_03_returns_dict_not_list(self):
        self._write({"adapters": [{"a": 1}]})
        result = self.wd.load_current_status()
        self.assertIsInstance(result, dict)

    def test_04_empty_json_object_returned(self):
        self._write({})
        result = self.wd.load_current_status()
        self.assertEqual(result, {})

    def test_05_list_json_returns_empty(self):
        path = os.path.join(self.tmp, "adapter_status.json")
        with open(path, "w") as f:
            f.write("[1, 2, 3]")
        result = self.wd.load_current_status()
        self.assertEqual(result, {})

    def test_06_corrupt_json_returns_empty(self):
        path = os.path.join(self.tmp, "adapter_status.json")
        with open(path, "w") as f:
            f.write("{invalid json")
        result = self.wd.load_current_status()
        self.assertEqual(result, {})

    def test_07_adapters_list_preserved(self):
        data = {"adapters": [{"protocol_key": "aave_v3"}]}
        self._write(data)
        result = self.wd.load_current_status()
        self.assertEqual(len(result["adapters"]), 1)

    def test_08_nested_data_preserved(self):
        data = {
            "adapters": [{"protocol_key": "aave_v3", "tier": "T1"}],
            "generated_at": "2026-06-13"
        }
        self._write(data)
        result = self.wd.load_current_status()
        self.assertEqual(result["adapters"][0]["tier"], "T1")

    def test_09_no_exception_on_read_error(self):
        # Remove read permission to force error — fallback to empty
        path = os.path.join(self.tmp, "adapter_status.json")
        with open(path, "w") as f:
            f.write("{}")
        os.chmod(path, 0o000)
        try:
            result = self.wd.load_current_status()
            self.assertIsInstance(result, dict)
        finally:
            os.chmod(path, 0o644)

    def test_10_returns_dict_type_always(self):
        result = self.wd.load_current_status()
        self.assertIsInstance(result, dict)


# ===========================================================================
# TestLoadPreviousSnapshot
# ===========================================================================

class TestLoadPreviousSnapshot(unittest.TestCase):
    """8 tests — load_previous_snapshot."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.wd = _make_watchdog(self.tmp)

    def _write_history(self, data):
        path = os.path.join(self.tmp, "watchdog_history.json")
        with open(path, "w") as f:
            json.dump(data, f)

    def test_01_no_history_file_returns_empty(self):
        result = self.wd.load_previous_snapshot()
        self.assertEqual(result, {})

    def test_02_returns_latest_from_history(self):
        hist = _make_history([{"generated_at": "2026-06-12", "x": 1}])
        self._write_history(hist)
        result = self.wd.load_previous_snapshot()
        self.assertEqual(result.get("x"), 1)

    def test_03_returns_dict(self):
        result = self.wd.load_previous_snapshot()
        self.assertIsInstance(result, dict)

    def test_04_corrupt_file_returns_empty(self):
        path = os.path.join(self.tmp, "watchdog_history.json")
        with open(path, "w") as f:
            f.write("{bad json")
        result = self.wd.load_previous_snapshot()
        self.assertEqual(result, {})

    def test_05_list_json_returns_empty(self):
        path = os.path.join(self.tmp, "watchdog_history.json")
        with open(path, "w") as f:
            f.write("[1, 2]")
        result = self.wd.load_previous_snapshot()
        self.assertEqual(result, {})

    def test_06_multiple_snapshots_returns_latest(self):
        snap1 = {"generated_at": "2026-06-11", "x": 10}
        snap2 = {"generated_at": "2026-06-12", "x": 20}
        hist = _make_history([snap1, snap2])
        self._write_history(hist)
        result = self.wd.load_previous_snapshot()
        self.assertEqual(result.get("x"), 20)

    def test_07_empty_snapshots_list_returns_empty(self):
        hist = {"schema_version": 1, "snapshots": [], "latest": {}}
        self._write_history(hist)
        result = self.wd.load_previous_snapshot()
        self.assertEqual(result, {})

    def test_08_no_exception_raised(self):
        """load_previous_snapshot никогда не бросает исключений."""
        try:
            result = self.wd.load_previous_snapshot()
            self.assertIsInstance(result, dict)
        except Exception as e:
            self.fail(f"load_previous_snapshot raised: {e}")


# ===========================================================================
# TestClassifyAdapter
# ===========================================================================

class TestClassifyAdapter(unittest.TestCase):
    """20 tests — classify_adapter."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.wd = _make_watchdog(self.tmp)

    def _classify(self, apy=4.2, tier="T1", peg=1.0, risk=None, prev_apy=None,
                  adapter_id="aave_v3", chains=None):
        entry = _make_adapter_entry(
            protocol_key=adapter_id,
            tier=tier,
            chains=chains or ["ethereum"],
            mock_apy_eth_usdc=apy,
            risk_score=risk,
            usdc_price=peg if peg != 1.0 else None,
        )
        current = _make_adapter_status(entry)
        if prev_apy is not None:
            prev_entry = {"adapter_id": adapter_id, "apy_pct": prev_apy}
            previous = _make_prev_snapshot([prev_entry])
        else:
            previous = {}
        return self.wd.classify_adapter(adapter_id, current, previous)

    def test_01_ok_healthy_adapter(self):
        h = self._classify(apy=4.2)
        self.assertEqual(h.alert_level, "OK")

    def test_02_apy_below_floor_is_critical(self):
        h = self._classify(apy=0.3)
        self.assertEqual(h.alert_level, "CRITICAL")

    def test_03_apy_exactly_at_floor_not_critical(self):
        # apy < 0.5 → CRITICAL; 0.5 is NOT < 0.5 → not critical from floor alone
        h = self._classify(apy=0.5)
        # May be OK or WARNING but not CRITICAL from floor rule
        self.assertNotEqual(h.alert_level, "CRITICAL")

    def test_04_apy_drop_warning(self):
        h = self._classify(apy=3.0, prev_apy=4.1)  # diff = -1.1 → WARNING
        self.assertEqual(h.alert_level, "WARNING")

    def test_05_apy_drop_critical(self):
        h = self._classify(apy=2.0, prev_apy=4.5)  # diff = -2.5 → CRITICAL
        self.assertEqual(h.alert_level, "CRITICAL")

    def test_06_apy_drop_exactly_2_is_critical(self):
        h = self._classify(apy=2.0, prev_apy=4.0)  # diff = -2.0 ≤ -2.0 → CRITICAL
        self.assertEqual(h.alert_level, "CRITICAL")

    def test_07_apy_drop_exactly_1_is_warning(self):
        h = self._classify(apy=3.2, prev_apy=4.2)  # diff = -1.0 ≤ -1.0 → WARNING
        self.assertEqual(h.alert_level, "WARNING")

    def test_08_apy_drop_less_than_1_is_ok(self):
        h = self._classify(apy=3.5, prev_apy=4.2)  # diff = -0.7 > -1 → OK
        self.assertEqual(h.alert_level, "OK")

    def test_09_peg_tolerance_warning(self):
        h = self._classify(apy=4.2, peg=0.994)  # dev=0.006 > 0.005 → WARNING
        self.assertEqual(h.alert_level, "WARNING")

    def test_10_peg_critical(self):
        h = self._classify(apy=4.2, peg=0.97)  # dev=0.03 > 0.02 → CRITICAL
        self.assertEqual(h.alert_level, "CRITICAL")

    def test_11_peg_within_tolerance_ok(self):
        h = self._classify(apy=4.2, peg=1.003)  # dev=0.003 ≤ 0.005 → OK
        self.assertEqual(h.alert_level, "OK")

    def test_12_risk_score_high_warning(self):
        h = self._classify(apy=4.2, risk=0.95)  # risk > 0.9 → WARNING
        self.assertEqual(h.alert_level, "WARNING")

    def test_13_risk_score_below_ceiling_ok(self):
        h = self._classify(apy=4.2, risk=0.85)  # risk ≤ 0.9 → OK
        self.assertEqual(h.alert_level, "OK")

    def test_14_no_history_apy_change_is_zero(self):
        h = self._classify(apy=4.2, prev_apy=None)
        self.assertAlmostEqual(h.apy_change_pct, 0.0)

    def test_15_apy_change_positive_is_ok(self):
        h = self._classify(apy=5.0, prev_apy=4.0)  # +1.0 → OK
        self.assertEqual(h.alert_level, "OK")

    def test_16_adapter_id_correct(self):
        h = self._classify(adapter_id="compound_v3")
        self.assertEqual(h.adapter_id, "compound_v3")

    def test_17_tier_extracted(self):
        h = self._classify(tier="T2")
        self.assertEqual(h.tier, "T2")

    def test_18_chain_extracted_from_chains_list(self):
        h = self._classify(chains=["arbitrum"])
        self.assertEqual(h.chain, "arbitrum")

    def test_19_is_healthy_false_when_apy_zero(self):
        h = self._classify(apy=0.0)
        self.assertFalse(h.is_healthy)

    def test_20_is_healthy_false_when_peg_bad(self):
        h = self._classify(apy=4.2, peg=0.97)
        self.assertFalse(h.is_healthy)


# ===========================================================================
# TestCreateAlerts
# ===========================================================================

class TestCreateAlerts(unittest.TestCase):
    """10 tests — create_alerts."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.wd = _make_watchdog(self.tmp)

    def _make_health(self, adapter_id="aave_v3", alert_level="OK", apy=4.2) -> AdapterHealth:
        return AdapterHealth(
            adapter_id=adapter_id,
            chain="ethereum",
            tier="T1",
            apy_pct=apy,
            risk_score=0.2,
            peg_price=1.0,
            is_healthy=True,
            apy_change_pct=0.0,
            alert_level=alert_level,
        )

    def test_01_no_alerts_for_ok(self):
        statuses = [self._make_health("aave_v3", "OK")]
        count = self.wd.create_alerts(statuses)
        self.assertEqual(count, 0)

    def test_02_warning_creates_alert(self):
        statuses = [self._make_health("aave_v3", "WARNING")]
        count = self.wd.create_alerts(statuses)
        self.assertEqual(count, 1)

    def test_03_critical_creates_alert(self):
        statuses = [self._make_health("aave_v3", "CRITICAL")]
        count = self.wd.create_alerts(statuses)
        self.assertEqual(count, 1)

    def test_04_multiple_non_ok_creates_multiple_alerts(self):
        statuses = [
            self._make_health("aave_v3", "WARNING"),
            self._make_health("compound_v3", "CRITICAL"),
        ]
        count = self.wd.create_alerts(statuses)
        self.assertEqual(count, 2)

    def test_05_mixed_statuses_count_correct(self):
        statuses = [
            self._make_health("a1", "OK"),
            self._make_health("a2", "WARNING"),
            self._make_health("a3", "OK"),
            self._make_health("a4", "CRITICAL"),
        ]
        count = self.wd.create_alerts(statuses)
        self.assertEqual(count, 2)

    def test_06_empty_list_returns_zero(self):
        count = self.wd.create_alerts([])
        self.assertEqual(count, 0)

    def test_07_all_ok_returns_zero(self):
        statuses = [self._make_health(f"a{i}", "OK") for i in range(5)]
        count = self.wd.create_alerts(statuses)
        self.assertEqual(count, 0)

    def test_08_returns_int(self):
        count = self.wd.create_alerts([])
        self.assertIsInstance(count, int)

    def test_09_all_critical_returns_correct_count(self):
        statuses = [self._make_health(f"a{i}", "CRITICAL") for i in range(3)]
        count = self.wd.create_alerts(statuses)
        self.assertEqual(count, 3)

    def test_10_dispatcher_disabled_still_counts(self):
        """use_alert_dispatcher=False 不影响 count."""
        wd = AdapterWatchdog(data_path=self.tmp, use_alert_dispatcher=False)
        statuses = [
            self._make_health("a1", "WARNING"),
            self._make_health("a2", "CRITICAL"),
        ]
        count = wd.create_alerts(statuses)
        self.assertEqual(count, 2)


# ===========================================================================
# TestRunCheck
# ===========================================================================

class TestRunCheck(unittest.TestCase):
    """10 tests — run_check."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.wd = _make_watchdog(self.tmp)

    def _write_adapter_status(self, data: dict):
        path = os.path.join(self.tmp, "adapter_status.json")
        with open(path, "w") as f:
            json.dump(data, f)

    def _write_history(self, data: dict):
        path = os.path.join(self.tmp, "watchdog_history.json")
        with open(path, "w") as f:
            json.dump(data, f)

    def test_01_returns_watchdog_report(self):
        entry = _make_adapter_entry("aave_v3")
        self._write_adapter_status(_make_adapter_status(entry))
        report = self.wd.run_check()
        self.assertIsInstance(report, WatchdogReport)

    def test_02_total_adapters_correct(self):
        entries = [_make_adapter_entry(f"adapter_{i}") for i in range(3)]
        self._write_adapter_status(_make_adapter_status(*entries))
        report = self.wd.run_check()
        self.assertEqual(report.total_adapters, 3)

    def test_03_healthy_count_correct_all_ok(self):
        entry = _make_adapter_entry("aave_v3", mock_apy_eth_usdc=4.2)
        self._write_adapter_status(_make_adapter_status(entry))
        report = self.wd.run_check()
        self.assertEqual(report.critical, 0)

    def test_04_critical_detected(self):
        entry = _make_adapter_entry("aave_v3", mock_apy_eth_usdc=0.1)  # < 0.5%
        self._write_adapter_status(_make_adapter_status(entry))
        report = self.wd.run_check()
        self.assertGreater(report.critical, 0)

    def test_05_saves_history_file(self):
        entry = _make_adapter_entry("aave_v3")
        self._write_adapter_status(_make_adapter_status(entry))
        self.wd.run_check()
        hist_path = os.path.join(self.tmp, "watchdog_history.json")
        self.assertTrue(os.path.exists(hist_path))

    def test_06_ring_buffer_max_48(self):
        entry = _make_adapter_entry("aave_v3")
        self._write_adapter_status(_make_adapter_status(entry))
        # Создадим историю с 50 снимками — должно быть обрезано до 48
        old_snaps = [
            {"generated_at": f"2026-06-01T0{i%10}:00:00+00:00", "adapter_statuses": []}
            for i in range(50)
        ]
        hist = _make_history(old_snaps)
        self._write_history(hist)
        self.wd.run_check()
        hist_path = os.path.join(self.tmp, "watchdog_history.json")
        with open(hist_path) as f:
            saved = json.load(f)
        self.assertLessEqual(len(saved["snapshots"]), RING_BUFFER_MAX)

    def test_07_generated_at_is_iso_string(self):
        self._write_adapter_status(_make_adapter_status())
        report = self.wd.run_check()
        self.assertIn("T", report.generated_at)

    def test_08_no_exception_on_missing_status(self):
        try:
            report = self.wd.run_check()
            self.assertIsInstance(report, WatchdogReport)
        except Exception as e:
            self.fail(f"run_check raised: {e}")

    def test_09_summary_not_empty(self):
        entry = _make_adapter_entry("aave_v3")
        self._write_adapter_status(_make_adapter_status(entry))
        report = self.wd.run_check()
        self.assertIsInstance(report.summary, str)
        self.assertGreater(len(report.summary), 0)

    def test_10_history_has_latest_key(self):
        entry = _make_adapter_entry("aave_v3")
        self._write_adapter_status(_make_adapter_status(entry))
        self.wd.run_check()
        hist_path = os.path.join(self.tmp, "watchdog_history.json")
        with open(hist_path) as f:
            saved = json.load(f)
        self.assertIn("latest", saved)


# ===========================================================================
# TestGetReport
# ===========================================================================

class TestGetReport(unittest.TestCase):
    """6 tests — get_report (no side effects)."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.wd = _make_watchdog(self.tmp)

    def _write_adapter_status(self, data: dict):
        path = os.path.join(self.tmp, "adapter_status.json")
        with open(path, "w") as f:
            json.dump(data, f)

    def test_01_returns_watchdog_report(self):
        self._write_adapter_status(_make_adapter_status())
        report = self.wd.get_report()
        self.assertIsInstance(report, WatchdogReport)

    def test_02_no_history_file_written(self):
        self._write_adapter_status(_make_adapter_status())
        self.wd.get_report()
        hist_path = os.path.join(self.tmp, "watchdog_history.json")
        self.assertFalse(os.path.exists(hist_path))

    def test_03_alerts_created_is_zero(self):
        entry = _make_adapter_entry("aave_v3", mock_apy_eth_usdc=0.1)  # CRITICAL
        self._write_adapter_status(_make_adapter_status(entry))
        report = self.wd.get_report()
        self.assertEqual(report.alerts_created, 0)

    def test_04_total_adapters_correct(self):
        entries = [_make_adapter_entry(f"a{i}") for i in range(4)]
        self._write_adapter_status(_make_adapter_status(*entries))
        report = self.wd.get_report()
        self.assertEqual(report.total_adapters, 4)

    def test_05_returns_on_missing_file(self):
        report = self.wd.get_report()
        self.assertIsInstance(report, WatchdogReport)
        self.assertEqual(report.total_adapters, 0)

    def test_06_summary_string_populated(self):
        entry = _make_adapter_entry("aave_v3")
        self._write_adapter_status(_make_adapter_status(entry))
        report = self.wd.get_report()
        self.assertIsInstance(report.summary, str)


# ===========================================================================
# TestToDict
# ===========================================================================

class TestToDict(unittest.TestCase):
    """4 tests — to_dict / JSON-serialisable."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.wd = _make_watchdog(self.tmp)

    def _write_adapter_status(self, data: dict):
        path = os.path.join(self.tmp, "adapter_status.json")
        with open(path, "w") as f:
            json.dump(data, f)

    def test_01_returns_dict(self):
        self._write_adapter_status(_make_adapter_status())
        result = self.wd.to_dict()
        self.assertIsInstance(result, dict)

    def test_02_json_serializable(self):
        entry = _make_adapter_entry("aave_v3")
        self._write_adapter_status(_make_adapter_status(entry))
        result = self.wd.to_dict()
        try:
            json.dumps(result)
        except (TypeError, ValueError) as e:
            self.fail(f"to_dict not JSON-serializable: {e}")

    def test_03_has_required_keys(self):
        self._write_adapter_status(_make_adapter_status())
        result = self.wd.to_dict()
        for key in ("generated_at", "total_adapters", "healthy", "warning",
                    "critical", "alerts_created", "summary", "adapter_statuses"):
            self.assertIn(key, result, f"missing key: {key}")

    def test_04_adapter_statuses_serializable(self):
        entry = _make_adapter_entry("compound_v3", tier="T1")
        self._write_adapter_status(_make_adapter_status(entry))
        result = self.wd.to_dict()
        statuses = result.get("adapter_statuses", [])
        self.assertIsInstance(statuses, list)
        if statuses:
            json.dumps(statuses[0])  # must not raise


# ===========================================================================
# TestFormatSummary
# ===========================================================================

class TestFormatSummary(unittest.TestCase):
    """4 tests — format_summary."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.wd = _make_watchdog(self.tmp)

    def _write_adapter_status(self, data: dict):
        path = os.path.join(self.tmp, "adapter_status.json")
        with open(path, "w") as f:
            json.dump(data, f)

    def test_01_returns_string(self):
        self._write_adapter_status(_make_adapter_status())
        result = self.wd.format_summary()
        self.assertIsInstance(result, str)

    def test_02_len_le_500(self):
        entries = [_make_adapter_entry(f"adapter_{i}", mock_apy_eth_usdc=0.1) for i in range(10)]
        self._write_adapter_status(_make_adapter_status(*entries))
        result = self.wd.format_summary()
        self.assertLessEqual(len(result), 500)

    def test_03_contains_adapter_counts(self):
        entry = _make_adapter_entry("aave_v3", mock_apy_eth_usdc=4.2)
        self._write_adapter_status(_make_adapter_status(entry))
        result = self.wd.format_summary()
        self.assertIn("1", result)   # total_adapters = 1

    def test_04_contains_watchdog_label(self):
        self._write_adapter_status(_make_adapter_status())
        result = self.wd.format_summary()
        self.assertIn("Watchdog", result)


# ===========================================================================
# Additional edge-case tests (total ≥ 90)
# ===========================================================================

class TestAdapterHealthToDict(unittest.TestCase):
    """5 tests — AdapterHealth.to_dict."""

    def _make(self, **kw) -> AdapterHealth:
        defaults = dict(
            adapter_id="aave_v3", chain="ethereum", tier="T1",
            apy_pct=4.2, risk_score=0.2, peg_price=1.0,
            is_healthy=True, apy_change_pct=0.0, alert_level="OK",
        )
        defaults.update(kw)
        return AdapterHealth(**defaults)

    def test_01_to_dict_returns_dict(self):
        h = self._make()
        self.assertIsInstance(h.to_dict(), dict)

    def test_02_all_fields_present(self):
        h = self._make()
        d = h.to_dict()
        for f in ("adapter_id", "chain", "tier", "apy_pct", "risk_score",
                  "peg_price", "is_healthy", "apy_change_pct", "alert_level"):
            self.assertIn(f, d)

    def test_03_alert_level_preserved(self):
        h = self._make(alert_level="CRITICAL")
        self.assertEqual(h.to_dict()["alert_level"], "CRITICAL")

    def test_04_json_serializable(self):
        h = self._make()
        json.dumps(h.to_dict())

    def test_05_is_healthy_boolean(self):
        h = self._make(is_healthy=False)
        self.assertIs(h.to_dict()["is_healthy"], False)


class TestWatchdogReportToDict(unittest.TestCase):
    """5 tests — WatchdogReport.to_dict."""

    def _make(self) -> WatchdogReport:
        h = AdapterHealth("a", "eth", "T1", 4.0, 0.2, 1.0, True, 0.0, "OK")
        return WatchdogReport(
            generated_at="2026-06-13T00:00:00+00:00",
            total_adapters=1, healthy=1, warning=0, critical=0,
            alerts_created=0, adapter_statuses=[h], summary="test",
        )

    def test_01_to_dict_keys(self):
        d = self._make().to_dict()
        self.assertIn("adapter_statuses", d)

    def test_02_adapter_statuses_is_list(self):
        d = self._make().to_dict()
        self.assertIsInstance(d["adapter_statuses"], list)

    def test_03_json_serializable(self):
        json.dumps(self._make().to_dict())

    def test_04_adapter_status_entry_is_dict(self):
        d = self._make().to_dict()
        self.assertIsInstance(d["adapter_statuses"][0], dict)

    def test_05_counts_match(self):
        d = self._make().to_dict()
        self.assertEqual(d["total_adapters"], 1)
        self.assertEqual(d["healthy"], 1)


class TestExtractAdapterIds(unittest.TestCase):
    """5 tests — _extract_adapter_ids."""

    def test_01_returns_list(self):
        result = AdapterWatchdog._extract_adapter_ids({})
        self.assertIsInstance(result, list)

    def test_02_empty_adapters_returns_empty(self):
        result = AdapterWatchdog._extract_adapter_ids({"adapters": []})
        self.assertEqual(result, [])

    def test_03_extracts_protocol_keys(self):
        data = {"adapters": [
            {"protocol_key": "aave_v3"},
            {"protocol_key": "compound_v3"},
        ]}
        result = AdapterWatchdog._extract_adapter_ids(data)
        self.assertEqual(result, ["aave_v3", "compound_v3"])

    def test_04_ignores_entries_without_protocol_key(self):
        data = {"adapters": [{"name": "no_key"}, {"protocol_key": "aave_v3"}]}
        result = AdapterWatchdog._extract_adapter_ids(data)
        self.assertEqual(result, ["aave_v3"])

    def test_05_no_adapters_key_returns_empty(self):
        result = AdapterWatchdog._extract_adapter_ids({"other": "data"})
        self.assertEqual(result, [])


class TestExtractApy(unittest.TestCase):
    """5 tests — _extract_apy static method."""

    def test_01_apy_pct_field(self):
        self.assertAlmostEqual(AdapterWatchdog._extract_apy({"apy_pct": 5.5}), 5.5)

    def test_02_apy_field_fallback(self):
        self.assertAlmostEqual(AdapterWatchdog._extract_apy({"apy": 3.2}), 3.2)

    def test_03_mock_apy_usdc_fallback(self):
        entry = {"mock_apy": {"ethereum": {"USDC": 4.8}}}
        self.assertAlmostEqual(AdapterWatchdog._extract_apy(entry), 4.8)

    def test_04_empty_returns_zero(self):
        self.assertAlmostEqual(AdapterWatchdog._extract_apy({}), 0.0)

    def test_05_zero_apy_returns_zero(self):
        self.assertAlmostEqual(AdapterWatchdog._extract_apy({"apy_pct": 0}), 0.0)


class TestBuildPrevApyIndex(unittest.TestCase):
    """5 tests — _build_prev_apy_index."""

    def test_01_returns_dict(self):
        result = AdapterWatchdog._build_prev_apy_index({})
        self.assertIsInstance(result, dict)

    def test_02_empty_previous_returns_empty(self):
        result = AdapterWatchdog._build_prev_apy_index({})
        self.assertEqual(result, {})

    def test_03_builds_index_correctly(self):
        prev = {"adapter_statuses": [{"adapter_id": "aave_v3", "apy_pct": 4.5}]}
        result = AdapterWatchdog._build_prev_apy_index(prev)
        self.assertAlmostEqual(result["aave_v3"], 4.5)

    def test_04_skips_invalid_entries(self):
        prev = {"adapter_statuses": [{"no_id": "x", "apy_pct": 4.5}]}
        result = AdapterWatchdog._build_prev_apy_index(prev)
        self.assertEqual(result, {})

    def test_05_multiple_adapters(self):
        prev = {"adapter_statuses": [
            {"adapter_id": "a1", "apy_pct": 3.0},
            {"adapter_id": "a2", "apy_pct": 6.0},
        ]}
        result = AdapterWatchdog._build_prev_apy_index(prev)
        self.assertEqual(len(result), 2)
        self.assertAlmostEqual(result["a2"], 6.0)


class TestClassifyLevel(unittest.TestCase):
    """6 extra edge-case tests for _classify_level."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.wd = _make_watchdog(self.tmp)

    def test_01_zero_apy_critical(self):
        lvl = self.wd._classify_level(0.0, 0.0, 0.0, 0.2)
        self.assertEqual(lvl, "CRITICAL")

    def test_02_normal_apy_ok(self):
        lvl = self.wd._classify_level(5.0, 0.0, 0.0, 0.2)
        self.assertEqual(lvl, "OK")

    def test_03_large_peg_dev_critical(self):
        lvl = self.wd._classify_level(5.0, 0.0, 0.03, 0.2)
        self.assertEqual(lvl, "CRITICAL")

    def test_04_moderate_peg_dev_warning(self):
        lvl = self.wd._classify_level(5.0, 0.0, 0.008, 0.2)
        self.assertEqual(lvl, "WARNING")

    def test_05_high_risk_score_warning(self):
        lvl = self.wd._classify_level(5.0, 0.0, 0.0, 0.95)
        self.assertEqual(lvl, "WARNING")

    def test_06_peg_worse_than_apy_drop_critical_wins(self):
        lvl = self.wd._classify_level(5.0, -1.5, 0.03, 0.2)
        self.assertEqual(lvl, "CRITICAL")


class TestAtomicWriteJson(unittest.TestCase):
    """4 tests — _atomic_write_json helper."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def test_01_creates_file(self):
        path = Path(self.tmp) / "test.json"
        _atomic_write_json(path, {"key": "value"})
        self.assertTrue(path.exists())

    def test_02_content_correct(self):
        path = Path(self.tmp) / "test.json"
        _atomic_write_json(path, {"x": 42})
        with open(path) as f:
            data = json.load(f)
        self.assertEqual(data["x"], 42)

    def test_03_no_tmp_file_left(self):
        path = Path(self.tmp) / "out.json"
        _atomic_write_json(path, {})
        tmp_files = list(Path(self.tmp).glob("*.tmp"))
        self.assertEqual(tmp_files, [])

    def test_04_creates_parent_dir(self):
        path = Path(self.tmp) / "subdir" / "out.json"
        _atomic_write_json(path, {"ok": True})
        self.assertTrue(path.exists())


class TestWatchdogDefaultPath(unittest.TestCase):
    """3 tests — default data_path behaviour."""

    def test_01_default_path_is_data_dir(self):
        wd = AdapterWatchdog()
        self.assertTrue(str(wd._data_dir).endswith("data"))

    def test_02_custom_path_used(self):
        wd = AdapterWatchdog(data_path="/tmp/custom")
        self.assertEqual(str(wd._data_dir), "/tmp/custom")

    def test_03_dispatcher_disabled_flag(self):
        wd = AdapterWatchdog(use_alert_dispatcher=False)
        self.assertFalse(wd._use_alert_dispatcher)


class TestExtractChain(unittest.TestCase):
    """4 tests — _extract_chain static method."""

    def test_01_chains_list_first(self):
        entry = {"chains": ["arbitrum", "ethereum"]}
        self.assertEqual(AdapterWatchdog._extract_chain(entry), "arbitrum")

    def test_02_single_chain(self):
        entry = {"chains": ["base"]}
        self.assertEqual(AdapterWatchdog._extract_chain(entry), "base")

    def test_03_chain_field_fallback(self):
        entry = {"chain": "optimism"}
        self.assertEqual(AdapterWatchdog._extract_chain(entry), "optimism")

    def test_04_no_chain_defaults_ethereum(self):
        self.assertEqual(AdapterWatchdog._extract_chain({}), "ethereum")


class TestExtractRiskScore(unittest.TestCase):
    """4 tests — _extract_risk_score static method."""

    def test_01_explicit_risk_score(self):
        entry = {"risk_score": 0.45}
        self.assertAlmostEqual(AdapterWatchdog._extract_risk_score(entry), 0.45)

    def test_02_t1_default(self):
        entry = {"tier": "T1"}
        self.assertAlmostEqual(AdapterWatchdog._extract_risk_score(entry), 0.20)

    def test_03_t2_default(self):
        entry = {"tier": "T2"}
        self.assertAlmostEqual(AdapterWatchdog._extract_risk_score(entry), 0.35)

    def test_04_unknown_tier_fallback(self):
        entry = {"tier": "TX"}
        self.assertAlmostEqual(AdapterWatchdog._extract_risk_score(entry), 0.30)


if __name__ == "__main__":
    unittest.main()
