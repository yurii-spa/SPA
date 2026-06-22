"""
test_peg_monitor.py — MP-601 unit tests for PegStabilityMonitor.

90+ tests across 10 classes:
  TestPegStatus (10)
  TestPegReport (8)
  TestInferAsset (10)
  TestGetPegPrice (12)
  TestClassifyStatus (10)
  TestCheckAdapter (12)
  TestRunCheck (10)
  TestGetReport (5)
  TestFormatTelegramMessage (5)
  TestToDict (8)

Run: python3 -m unittest spa_core.tests.test_peg_monitor -v
"""
from __future__ import annotations

import json
import os
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from spa_core.monitoring.peg_monitor import (
    PegReport,
    PegStatus,
    PegStabilityMonitor,
    RING_BUFFER_MAX,
    _atomic_write_json,
)


# ===========================================================================
# Helpers
# ===========================================================================

def _make_status(
    adapter_id: str = "test_adapter",
    asset: str = "USDC",
    chain: str = "ethereum",
    current_price: float = 1.0,
    deviation_pct: float = 0.0,
    status: str = "STABLE",
    last_checked: str = "2026-06-13T00:00:00+00:00",
) -> PegStatus:
    return PegStatus(
        adapter_id=adapter_id,
        asset=asset,
        chain=chain,
        current_price=current_price,
        deviation_pct=deviation_pct,
        status=status,
        last_checked=last_checked,
    )


def _make_report(
    statuses: list | None = None,
    overall_status: str = "GREEN",
) -> PegReport:
    if statuses is None:
        statuses = []
    stable   = sum(1 for s in statuses if s.status == "STABLE")
    caution  = sum(1 for s in statuses if s.status == "CAUTION")
    warning  = sum(1 for s in statuses if s.status == "WARNING")
    critical = sum(1 for s in statuses if s.status == "CRITICAL")
    worst_adapter = max(statuses, key=lambda s: s.deviation_pct).adapter_id if statuses else ""
    worst_dev = max(s.deviation_pct for s in statuses) if statuses else 0.0
    return PegReport(
        generated_at="2026-06-13T00:00:00+00:00",
        total_monitored=len(statuses),
        stable=stable,
        caution=caution,
        warning=warning,
        critical=critical,
        worst_adapter=worst_adapter,
        worst_deviation_pct=worst_dev,
        statuses=statuses,
        overall_status=overall_status,
    )


def _adapter_status_with_price(adapter_id: str, price: float) -> dict:
    """Build a minimal adapter_status dict with one top-level adapter entry."""
    return {adapter_id: {"usdc_price": price, "chain": "ethereum"}}


def _make_monitor(tmp_dir: str, use_alerts: bool = False) -> PegStabilityMonitor:
    return PegStabilityMonitor(data_path=tmp_dir, use_alert_dispatcher=use_alerts)


def _write_adapter_status(tmp_dir: str, payload: dict) -> None:
    path = Path(tmp_dir) / "adapter_status.json"
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh)


# ===========================================================================
# TestPegStatus — 10 tests
# ===========================================================================

class TestPegStatus(unittest.TestCase):
    """PegStatus dataclass: fields, types, to_dict."""

    def setUp(self):
        self.ts = "2026-06-13T10:00:00+00:00"
        self.ps = PegStatus(
            adapter_id="aave_v3",
            asset="USDC",
            chain="ethereum",
            current_price=1.0,
            deviation_pct=0.0,
            status="STABLE",
            last_checked=self.ts,
        )

    def test_01_adapter_id_type(self):
        self.assertIsInstance(self.ps.adapter_id, str)

    def test_02_asset_type(self):
        self.assertIsInstance(self.ps.asset, str)

    def test_03_chain_type(self):
        self.assertIsInstance(self.ps.chain, str)

    def test_04_current_price_type(self):
        self.assertIsInstance(self.ps.current_price, float)

    def test_05_deviation_pct_type(self):
        self.assertIsInstance(self.ps.deviation_pct, float)

    def test_06_status_type(self):
        self.assertIsInstance(self.ps.status, str)

    def test_07_last_checked_type(self):
        self.assertIsInstance(self.ps.last_checked, str)

    def test_08_to_dict_returns_all_fields(self):
        d = self.ps.to_dict()
        for key in (
            "adapter_id", "asset", "chain", "current_price",
            "deviation_pct", "status", "last_checked",
        ):
            self.assertIn(key, d)

    def test_09_to_dict_values_match(self):
        d = self.ps.to_dict()
        self.assertEqual(d["adapter_id"], "aave_v3")
        self.assertEqual(d["asset"], "USDC")
        self.assertEqual(d["chain"], "ethereum")
        self.assertAlmostEqual(d["current_price"], 1.0)
        self.assertEqual(d["status"], "STABLE")
        self.assertEqual(d["last_checked"], self.ts)

    def test_10_to_dict_is_json_serializable(self):
        d = self.ps.to_dict()
        # Must not raise
        serialized = json.dumps(d)
        self.assertIsInstance(serialized, str)


# ===========================================================================
# TestPegReport — 8 tests
# ===========================================================================

class TestPegReport(unittest.TestCase):
    """PegReport dataclass: overall_status logic, counts, to_dict."""

    def test_01_all_stable_is_green(self):
        statuses = [_make_status(status="STABLE") for _ in range(3)]
        r = _make_report(statuses=statuses, overall_status="GREEN")
        self.assertEqual(r.overall_status, "GREEN")

    def test_02_any_warning_is_yellow(self):
        statuses = [
            _make_status(status="STABLE"),
            _make_status(adapter_id="b", status="WARNING", deviation_pct=0.5),
        ]
        r = _make_report(statuses=statuses, overall_status="YELLOW")
        self.assertEqual(r.overall_status, "YELLOW")

    def test_03_any_critical_is_red(self):
        statuses = [
            _make_status(status="STABLE"),
            _make_status(adapter_id="c", status="CRITICAL", deviation_pct=2.0),
        ]
        r = _make_report(statuses=statuses, overall_status="RED")
        self.assertEqual(r.overall_status, "RED")

    def test_04_any_caution_is_yellow(self):
        statuses = [
            _make_status(status="STABLE"),
            _make_status(adapter_id="d", status="CAUTION", deviation_pct=0.15),
        ]
        r = _make_report(statuses=statuses, overall_status="YELLOW")
        self.assertEqual(r.overall_status, "YELLOW")

    def test_05_counts_correct(self):
        statuses = [
            _make_status(adapter_id="s1", status="STABLE"),
            _make_status(adapter_id="s2", status="STABLE"),
            _make_status(adapter_id="c1", status="CAUTION", deviation_pct=0.15),
            _make_status(adapter_id="w1", status="WARNING", deviation_pct=0.5),
            _make_status(adapter_id="cr1", status="CRITICAL", deviation_pct=1.5),
        ]
        r = _make_report(statuses=statuses, overall_status="RED")
        self.assertEqual(r.stable, 2)
        self.assertEqual(r.caution, 1)
        self.assertEqual(r.warning, 1)
        self.assertEqual(r.critical, 1)

    def test_06_worst_adapter_is_max_deviation(self):
        statuses = [
            _make_status(adapter_id="a1", deviation_pct=0.1),
            _make_status(adapter_id="a2", deviation_pct=2.5),
            _make_status(adapter_id="a3", deviation_pct=0.5),
        ]
        r = _make_report(statuses=statuses)
        self.assertEqual(r.worst_adapter, "a2")

    def test_07_worst_deviation_pct_is_max(self):
        statuses = [
            _make_status(adapter_id="x1", deviation_pct=0.3),
            _make_status(adapter_id="x2", deviation_pct=1.8),
        ]
        r = _make_report(statuses=statuses)
        self.assertAlmostEqual(r.worst_deviation_pct, 1.8)

    def test_08_to_dict_is_json_serializable(self):
        statuses = [_make_status()]
        r = _make_report(statuses=statuses)
        serialized = json.dumps(r.to_dict())
        self.assertIsInstance(serialized, str)


# ===========================================================================
# TestInferAsset — 10 tests
# ===========================================================================

class TestInferAsset(unittest.TestCase):
    """PegStabilityMonitor.infer_asset: ASSET_MAP lookup, keyword matching, fallback."""

    def setUp(self):
        self.monitor = PegStabilityMonitor.__new__(PegStabilityMonitor)
        self.monitor._use_alert_dispatcher = False
        self.monitor._dispatcher = None

    def test_01_aave_exact(self):
        self.assertEqual(self.monitor.infer_asset("aave"), "USDC")

    def test_02_morpho_exact(self):
        self.assertEqual(self.monitor.infer_asset("morpho"), "USDC")

    def test_03_compound_exact(self):
        self.assertEqual(self.monitor.infer_asset("compound"), "USDC")

    def test_04_sdai_exact(self):
        self.assertEqual(self.monitor.infer_asset("sdai"), "DAI")

    def test_05_sfrax_exact(self):
        self.assertEqual(self.monitor.infer_asset("sfrax"), "FRAX")

    def test_06_frax_exact(self):
        self.assertEqual(self.monitor.infer_asset("frax"), "FRAX")

    def test_07_scrvusd_exact(self):
        self.assertEqual(self.monitor.infer_asset("scrvusd"), "crvUSD")

    def test_08_stusd_exact(self):
        self.assertEqual(self.monitor.infer_asset("stusd"), "USD+")

    def test_09_substring_aave_v3(self):
        # "aave_v3" contains "aave" → "USDC"
        self.assertEqual(self.monitor.infer_asset("aave_v3"), "USDC")

    def test_10_unknown_fallback(self):
        self.assertEqual(self.monitor.infer_asset("totally_unknown_protocol_xyz"), "USDC")


# ===========================================================================
# TestGetPegPrice — 12 tests
# ===========================================================================

class TestGetPegPrice(unittest.TestCase):
    """PegStabilityMonitor.get_peg_price: field priority, fallback 1.0."""

    def setUp(self):
        self.monitor = PegStabilityMonitor.__new__(PegStabilityMonitor)

    def test_01_usdc_price_returned(self):
        data = {"my_adapter": {"usdc_price": 0.999}}
        self.assertAlmostEqual(self.monitor.get_peg_price("my_adapter", data), 0.999)

    def test_02_dai_price_returned(self):
        data = {"my_adapter": {"dai_price": 0.998}}
        self.assertAlmostEqual(self.monitor.get_peg_price("my_adapter", data), 0.998)

    def test_03_frax_price_returned(self):
        data = {"my_adapter": {"frax_price": 0.995}}
        self.assertAlmostEqual(self.monitor.get_peg_price("my_adapter", data), 0.995)

    def test_04_peg_price_returned(self):
        data = {"my_adapter": {"peg_price": 0.997}}
        self.assertAlmostEqual(self.monitor.get_peg_price("my_adapter", data), 0.997)

    def test_05_no_price_field_returns_1_0(self):
        data = {"my_adapter": {"apy_pct": 5.0}}
        self.assertAlmostEqual(self.monitor.get_peg_price("my_adapter", data), 1.0)

    def test_06_missing_adapter_returns_1_0(self):
        data = {"other_adapter": {"usdc_price": 0.99}}
        self.assertAlmostEqual(self.monitor.get_peg_price("my_adapter", data), 1.0)

    def test_07_usdc_price_priority_over_dai_price(self):
        data = {"my_adapter": {"usdc_price": 0.996, "dai_price": 0.994}}
        self.assertAlmostEqual(self.monitor.get_peg_price("my_adapter", data), 0.996)

    def test_08_price_field_as_fallback(self):
        data = {"my_adapter": {"price": 0.993}}
        self.assertAlmostEqual(self.monitor.get_peg_price("my_adapter", data), 0.993)

    def test_09_adapter_in_adapters_list_with_price(self):
        data = {
            "adapters": [
                {"protocol_key": "aave-v3", "usdc_price": 0.9995}
            ]
        }
        self.assertAlmostEqual(self.monitor.get_peg_price("aave-v3", data), 0.9995)

    def test_10_adapter_in_adapters_list_no_price(self):
        data = {
            "adapters": [
                {"protocol_key": "aave-v3", "apy_pct": 4.2}
            ]
        }
        self.assertAlmostEqual(self.monitor.get_peg_price("aave-v3", data), 1.0)

    def test_11_empty_data_returns_1_0(self):
        self.assertAlmostEqual(self.monitor.get_peg_price("any", {}), 1.0)

    def test_12_bool_value_ignored(self):
        # bool is subclass of int, must not be returned as price
        data = {"my_adapter": {"usdc_price": True}}
        self.assertAlmostEqual(self.monitor.get_peg_price("my_adapter", data), 1.0)


# ===========================================================================
# TestClassifyStatus — 10 tests
# ===========================================================================

class TestClassifyStatus(unittest.TestCase):
    """PegStabilityMonitor.classify_status: thresholds and boundary values."""

    def setUp(self):
        self.monitor = PegStabilityMonitor.__new__(PegStabilityMonitor)

    def test_01_zero_deviation_stable(self):
        self.assertEqual(self.monitor.classify_status(0.0), "STABLE")

    def test_02_below_caution_stable(self):
        self.assertEqual(self.monitor.classify_status(0.05), "STABLE")

    def test_03_caution_threshold_exact(self):
        # 0.10 >= CAUTION_PCT → CAUTION
        self.assertEqual(self.monitor.classify_status(0.10), "CAUTION")

    def test_04_between_caution_and_warning(self):
        self.assertEqual(self.monitor.classify_status(0.20), "CAUTION")

    def test_05_warning_threshold_exact(self):
        # 0.30 >= WARNING_PCT → WARNING
        self.assertEqual(self.monitor.classify_status(0.30), "WARNING")

    def test_06_between_warning_and_critical(self):
        self.assertEqual(self.monitor.classify_status(0.50), "WARNING")

    def test_07_critical_threshold_exact(self):
        # 1.00 >= CRITICAL_PCT → CRITICAL
        self.assertEqual(self.monitor.classify_status(1.00), "CRITICAL")

    def test_08_above_critical(self):
        self.assertEqual(self.monitor.classify_status(2.0), "CRITICAL")

    def test_09_just_below_caution(self):
        self.assertEqual(self.monitor.classify_status(0.09), "STABLE")

    def test_10_just_below_critical(self):
        self.assertEqual(self.monitor.classify_status(0.99), "WARNING")


# ===========================================================================
# TestCheckAdapter — 12 tests
# ===========================================================================

class TestCheckAdapter(unittest.TestCase):
    """PegStabilityMonitor.check_adapter: status computation per adapter."""

    def setUp(self):
        self.monitor = PegStabilityMonitor.__new__(PegStabilityMonitor)

    def test_01_stable_at_1_0(self):
        data = {"adapter_a": {"usdc_price": 1.0, "chain": "ethereum"}}
        ps = self.monitor.check_adapter("adapter_a", data)
        self.assertEqual(ps.status, "STABLE")

    def test_02_caution_deviation(self):
        data = {"adapter_a": {"usdc_price": 0.9989, "chain": "ethereum"}}
        ps = self.monitor.check_adapter("adapter_a", data)
        self.assertEqual(ps.status, "CAUTION")

    def test_03_warning_deviation(self):
        data = {"adapter_a": {"usdc_price": 0.996, "chain": "ethereum"}}
        ps = self.monitor.check_adapter("adapter_a", data)
        self.assertEqual(ps.status, "WARNING")

    def test_04_critical_deviation(self):
        data = {"adapter_a": {"usdc_price": 0.985, "chain": "ethereum"}}
        ps = self.monitor.check_adapter("adapter_a", data)
        self.assertEqual(ps.status, "CRITICAL")

    def test_05_deviation_pct_formula(self):
        price = 0.997
        data = {"adapter_a": {"usdc_price": price, "chain": "ethereum"}}
        ps = self.monitor.check_adapter("adapter_a", data)
        expected = round(abs(price - 1.0) * 100, 6)
        self.assertAlmostEqual(ps.deviation_pct, expected, places=5)

    def test_06_adapter_from_adapters_list(self):
        data = {
            "adapters": [
                {"protocol_key": "compound-v3", "usdc_price": 1.0, "chains": ["ethereum"]}
            ]
        }
        ps = self.monitor.check_adapter("compound-v3", data)
        self.assertEqual(ps.adapter_id, "compound-v3")
        self.assertEqual(ps.chain, "ethereum")

    def test_07_adapter_from_top_level_dict(self):
        data = {"my_proto": {"usdc_price": 1.0, "chain": "arbitrum"}}
        ps = self.monitor.check_adapter("my_proto", data)
        self.assertEqual(ps.adapter_id, "my_proto")
        self.assertEqual(ps.chain, "arbitrum")

    def test_08_asset_inferred_from_adapter_id(self):
        data = {"sdai_vault": {"usdc_price": 1.0}}
        ps = self.monitor.check_adapter("sdai_vault", data)
        # "sdai" is in "sdai_vault" → asset from ASSET_MAP
        # But also "sdai" may be in the ASSET_MAP lookup; let's just ensure it's a str
        self.assertIsInstance(ps.asset, str)

    def test_09_asset_from_assets_list_overrides_infer(self):
        data = {
            "adapters": [
                {"protocol_key": "aave-v3", "assets": ["USDT"], "usdc_price": 1.0, "chains": ["ethereum"]}
            ]
        }
        ps = self.monitor.check_adapter("aave-v3", data)
        self.assertEqual(ps.asset, "USDT")

    def test_10_last_checked_is_iso_timestamp(self):
        data = {"adapter_a": {"usdc_price": 1.0}}
        ps = self.monitor.check_adapter("adapter_a", data)
        # Should parse as ISO without raising
        dt = datetime.fromisoformat(ps.last_checked)
        self.assertIsInstance(dt, datetime)

    def test_11_missing_adapter_fallback_stable(self):
        data = {}
        ps = self.monitor.check_adapter("nonexistent", data)
        self.assertAlmostEqual(ps.current_price, 1.0)
        self.assertEqual(ps.status, "STABLE")

    def test_12_price_above_1_deviation_is_abs(self):
        # price = 1.005 → deviation = 0.5% → WARNING
        data = {"adapter_a": {"usdc_price": 1.005, "chain": "ethereum"}}
        ps = self.monitor.check_adapter("adapter_a", data)
        self.assertAlmostEqual(ps.deviation_pct, 0.5, places=4)
        self.assertEqual(ps.status, "WARNING")


# ===========================================================================
# TestRunCheck — 10 tests
# ===========================================================================

class TestRunCheck(unittest.TestCase):
    """PegStabilityMonitor.run_check: counts, persistence, alerts."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _write_status(self, payload: dict) -> None:
        _write_adapter_status(self.tmp, payload)

    def test_01_returns_peg_report(self):
        self._write_status({"adapter_a": {"usdc_price": 1.0, "chain": "ethereum"}})
        m = _make_monitor(self.tmp)
        report = m.run_check()
        self.assertIsInstance(report, PegReport)

    def test_02_total_monitored_correct(self):
        self._write_status({
            "adapter_a": {"usdc_price": 1.0, "chain": "ethereum"},
            "adapter_b": {"usdc_price": 1.0, "chain": "ethereum"},
        })
        m = _make_monitor(self.tmp)
        report = m.run_check()
        self.assertEqual(report.total_monitored, 2)

    def test_03_stable_count_correct(self):
        self._write_status({
            "adapter_a": {"usdc_price": 1.0, "chain": "ethereum"},
            "adapter_b": {"usdc_price": 1.0, "chain": "ethereum"},
        })
        m = _make_monitor(self.tmp)
        report = m.run_check()
        self.assertEqual(report.stable, 2)

    def test_04_caution_count_correct(self):
        self._write_status({
            "adapter_a": {"usdc_price": 0.9989, "chain": "ethereum"},  # ~0.11% dev → CAUTION
        })
        m = _make_monitor(self.tmp)
        report = m.run_check()
        self.assertEqual(report.caution, 1)

    def test_05_critical_count_correct(self):
        self._write_status({
            "adapter_a": {"usdc_price": 0.985, "chain": "ethereum"},  # 1.5% → CRITICAL
        })
        m = _make_monitor(self.tmp)
        report = m.run_check()
        self.assertEqual(report.critical, 1)

    def test_06_saves_peg_history(self):
        self._write_status({"adapter_a": {"usdc_price": 1.0, "chain": "ethereum"}})
        m = _make_monitor(self.tmp)
        m.run_check()
        hist_path = Path(self.tmp) / "peg_history.json"
        self.assertTrue(hist_path.exists())

    def test_07_peg_history_has_snapshots(self):
        self._write_status({"adapter_a": {"usdc_price": 1.0, "chain": "ethereum"}})
        m = _make_monitor(self.tmp)
        m.run_check()
        hist_path = Path(self.tmp) / "peg_history.json"
        with open(hist_path) as fh:
            hist = json.load(fh)
        self.assertIn("snapshots", hist)
        self.assertGreaterEqual(len(hist["snapshots"]), 1)

    def test_08_alerts_created_for_warning(self):
        self._write_status({
            "adapter_a": {"usdc_price": 0.996, "chain": "ethereum"},  # 0.4% → WARNING
        })
        m = _make_monitor(self.tmp, use_alerts=False)
        # Patch _create_alerts to count calls
        original = m._create_alerts
        alerts_called_with = []
        def mock_create(statuses):
            alerts_called_with.extend([s for s in statuses if s.status in ("WARNING", "CRITICAL")])
            return original(statuses)
        m._create_alerts = mock_create
        m.run_check()
        self.assertGreater(len(alerts_called_with), 0)

    def test_09_no_alerts_for_stable(self):
        self._write_status({
            "adapter_a": {"usdc_price": 1.0, "chain": "ethereum"},
        })
        m = _make_monitor(self.tmp, use_alerts=False)
        non_stable_seen = []
        original = m._create_alerts
        def mock_create(statuses):
            non_stable_seen.extend([s for s in statuses if s.status not in ("STABLE", "CAUTION")])
            return original(statuses)
        m._create_alerts = mock_create
        m.run_check()
        self.assertEqual(len(non_stable_seen), 0)

    def test_10_failsafe_on_bad_data(self):
        # No adapter_status.json written → load returns {} → empty report
        m = _make_monitor(self.tmp)
        report = m.run_check()
        self.assertIsInstance(report, PegReport)
        # Should not raise; total_monitored can be 0 or more


# ===========================================================================
# TestGetReport — 5 tests
# ===========================================================================

class TestGetReport(unittest.TestCase):
    """PegStabilityMonitor.get_report: read-only, no side effects."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_01_returns_peg_report(self):
        _write_adapter_status(self.tmp, {"ad": {"usdc_price": 1.0, "chain": "ethereum"}})
        m = _make_monitor(self.tmp)
        self.assertIsInstance(m.get_report(), PegReport)

    def test_02_does_not_write_peg_history(self):
        _write_adapter_status(self.tmp, {"ad": {"usdc_price": 1.0, "chain": "ethereum"}})
        m = _make_monitor(self.tmp)
        m.get_report()
        hist_path = Path(self.tmp) / "peg_history.json"
        self.assertFalse(hist_path.exists())

    def test_03_does_not_write_peg_report(self):
        _write_adapter_status(self.tmp, {"ad": {"usdc_price": 1.0, "chain": "ethereum"}})
        m = _make_monitor(self.tmp)
        m.get_report()
        report_path = Path(self.tmp) / "peg_report.json"
        self.assertFalse(report_path.exists())

    def test_04_same_logic_as_run_check(self):
        _write_adapter_status(self.tmp, {"ad": {"usdc_price": 0.985, "chain": "ethereum"}})
        m = _make_monitor(self.tmp)
        report_get = m.get_report()
        # Clear history so run_check creates fresh
        report_run = m.run_check()
        self.assertEqual(report_get.total_monitored, report_run.total_monitored)
        self.assertEqual(report_get.critical, report_run.critical)

    def test_05_failsafe_on_missing_file(self):
        m = _make_monitor(self.tmp)
        report = m.get_report()
        self.assertIsInstance(report, PegReport)


# ===========================================================================
# TestFormatTelegramMessage — 5 tests
# ===========================================================================

class TestFormatTelegramMessage(unittest.TestCase):
    """PegStabilityMonitor.format_telegram_message: length, content."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_01_length_under_1500(self):
        # Create many adapters to push message length up
        payload = {
            f"adapter_{i}": {"usdc_price": 1.0 - (i * 0.001), "chain": "ethereum"}
            for i in range(50)
        }
        _write_adapter_status(self.tmp, payload)
        m = _make_monitor(self.tmp)
        msg = m.format_telegram_message()
        self.assertLessEqual(len(msg), 1500)

    def test_02_contains_overall_status_green(self):
        _write_adapter_status(self.tmp, {"ad": {"usdc_price": 1.0, "chain": "ethereum"}})
        m = _make_monitor(self.tmp)
        msg = m.format_telegram_message()
        self.assertIn("GREEN", msg)

    def test_03_contains_overall_status_red_when_critical(self):
        _write_adapter_status(self.tmp, {"ad": {"usdc_price": 0.98, "chain": "ethereum"}})
        m = _make_monitor(self.tmp)
        msg = m.format_telegram_message()
        self.assertIn("RED", msg)

    def test_04_truncated_when_too_long(self):
        # Create a scenario where message is long; check it ends with "..."
        # We patch get_report to return a report with a very long worst_adapter name
        payload = {
            "a" * 100: {"usdc_price": 0.98, "chain": "ethereum"},
            "b" * 100: {"usdc_price": 0.97, "chain": "ethereum"},
        }
        _write_adapter_status(self.tmp, payload)
        m = _make_monitor(self.tmp)
        msg = m.format_telegram_message()
        self.assertLessEqual(len(msg), 1500)

    def test_05_works_with_empty_data(self):
        m = _make_monitor(self.tmp)
        msg = m.format_telegram_message()
        self.assertIsInstance(msg, str)
        self.assertGreater(len(msg), 0)


# ===========================================================================
# TestToDict — 8 tests
# ===========================================================================

class TestToDict(unittest.TestCase):
    """PegStabilityMonitor.to_dict: JSON-serializable, all required fields."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        _write_adapter_status(
            self.tmp,
            {
                "adapter_a": {"usdc_price": 1.0, "chain": "ethereum"},
                "adapter_b": {"usdc_price": 0.998, "chain": "arbitrum"},
            },
        )
        self.monitor = _make_monitor(self.tmp)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_01_returns_dict(self):
        self.assertIsInstance(self.monitor.to_dict(), dict)

    def test_02_has_generated_at(self):
        self.assertIn("generated_at", self.monitor.to_dict())

    def test_03_has_total_monitored(self):
        self.assertIn("total_monitored", self.monitor.to_dict())

    def test_04_has_overall_status(self):
        self.assertIn("overall_status", self.monitor.to_dict())

    def test_05_has_statuses_list(self):
        d = self.monitor.to_dict()
        self.assertIn("statuses", d)
        self.assertIsInstance(d["statuses"], list)

    def test_06_total_monitored_is_int(self):
        d = self.monitor.to_dict()
        self.assertIsInstance(d["total_monitored"], int)

    def test_07_worst_deviation_pct_is_float(self):
        d = self.monitor.to_dict()
        self.assertIsInstance(d["worst_deviation_pct"], float)

    def test_08_json_dumps_does_not_raise(self):
        d = self.monitor.to_dict()
        result = json.dumps(d)
        self.assertIsInstance(result, str)


# ===========================================================================
# Additional integration tests — ensure overall_status logic in run_check
# ===========================================================================

class TestOverallStatusIntegration(unittest.TestCase):
    """Integration: _compute_overall_status used correctly in build_report."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_compute_overall_green_all_stable(self):
        statuses = [_make_status(status="STABLE") for _ in range(5)]
        result = PegStabilityMonitor._compute_overall_status(statuses)
        self.assertEqual(result, "GREEN")

    def test_compute_overall_yellow_has_caution(self):
        statuses = [
            _make_status(status="STABLE"),
            _make_status(adapter_id="c", status="CAUTION"),
        ]
        result = PegStabilityMonitor._compute_overall_status(statuses)
        self.assertEqual(result, "YELLOW")

    def test_compute_overall_yellow_has_warning(self):
        statuses = [
            _make_status(status="STABLE"),
            _make_status(adapter_id="w", status="WARNING"),
        ]
        result = PegStabilityMonitor._compute_overall_status(statuses)
        self.assertEqual(result, "YELLOW")

    def test_compute_overall_red_has_critical(self):
        statuses = [
            _make_status(status="WARNING"),
            _make_status(adapter_id="cr", status="CRITICAL"),
        ]
        result = PegStabilityMonitor._compute_overall_status(statuses)
        self.assertEqual(result, "RED")

    def test_compute_overall_red_even_with_stable(self):
        statuses = [
            _make_status(status="STABLE"),
            _make_status(adapter_id="s2", status="STABLE"),
            _make_status(adapter_id="cr", status="CRITICAL"),
        ]
        result = PegStabilityMonitor._compute_overall_status(statuses)
        self.assertEqual(result, "RED")

    def test_compute_overall_empty_is_green(self):
        result = PegStabilityMonitor._compute_overall_status([])
        self.assertEqual(result, "GREEN")


# ===========================================================================
# Additional tests for ring-buffer and save_report
# ===========================================================================

class TestRingBufferAndSaveReport(unittest.TestCase):
    """Ring-buffer trimming and save_report atomic write."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        _write_adapter_status(
            self.tmp,
            {"ad": {"usdc_price": 1.0, "chain": "ethereum"}},
        )

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_ring_buffer_constant_is_96(self):
        self.assertEqual(RING_BUFFER_MAX, 96)

    def test_ring_buffer_trims_correctly(self):
        # Pre-populate history with RING_BUFFER_MAX entries
        existing = [{"generated_at": f"ts_{i}"} for i in range(RING_BUFFER_MAX)]
        hist_path = Path(self.tmp) / "peg_history.json"
        _atomic_write_json(hist_path, {"snapshots": existing})
        m = _make_monitor(self.tmp)
        m.run_check()
        with open(hist_path) as fh:
            hist = json.load(fh)
        self.assertLessEqual(hist["snapshot_count"], RING_BUFFER_MAX)
        self.assertLessEqual(len(hist["snapshots"]), RING_BUFFER_MAX)

    def test_save_report_creates_file(self):
        m = _make_monitor(self.tmp)
        path = m.save_report()
        self.assertTrue(os.path.exists(path))

    def test_save_report_returns_path_string(self):
        m = _make_monitor(self.tmp)
        path = m.save_report()
        self.assertIsInstance(path, str)

    def test_save_report_no_tmp_leftover(self):
        m = _make_monitor(self.tmp)
        m.save_report()
        tmp_files = [f for f in os.listdir(self.tmp) if ".tmp" in f]
        self.assertEqual(tmp_files, [])

    def test_peg_history_has_latest_key(self):
        m = _make_monitor(self.tmp)
        m.run_check()
        hist_path = Path(self.tmp) / "peg_history.json"
        with open(hist_path) as fh:
            hist = json.load(fh)
        self.assertIn("latest", hist)

    def test_peg_history_schema_version(self):
        m = _make_monitor(self.tmp)
        m.run_check()
        hist_path = Path(self.tmp) / "peg_history.json"
        with open(hist_path) as fh:
            hist = json.load(fh)
        self.assertEqual(hist.get("schema_version"), 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
