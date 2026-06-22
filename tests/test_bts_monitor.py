"""
tests/test_bts_monitor.py — BTS Monitor test suite (≥30 tests).

Tests cover:
  - Empty opportunities when feed stale or missing
  - Correct ranking by net_spread_bps
  - New EXCELLENT detection (transition logic)
  - No alert when EXCELLENT was already EXCELLENT
  - Heartbeat written after run
  - Summary counts correct
  - Edge cases: malformed data, empty rates, partial data
"""
import json
import tempfile
import unittest
from datetime import datetime, timezone, timedelta
from pathlib import Path

from spa_core.monitoring.bts_monitor import (
    BTSMonitor,
    BTSOpportunity,
    OPP_FILENAME,
    STATUS_FILENAME,
    FUNDING_FILENAME,
    ADAPTER_STATUS_FILENAME,
    STALE_AFTER_S,
    DEFAULT_SPOT_YIELD,
)
from spa_core.utils.atomic import atomic_save


def _make_funding_data(
    rates=None,
    stale=False,
    generated_at=None,
):
    if generated_at is None:
        generated_at = datetime.now(timezone.utc).isoformat()
    if rates is None:
        rates = {
            "ETH": {
                "asset": "ETH",
                "funding_rate_1h": 0.0001,
                "funding_rate_8h": 0.0008,
                "funding_rate_annual": 0.876,
                "open_interest_usd": 500000000.0,
                "mark_price": 3100.0,
                "premium": 0.0001,
                "timestamp": generated_at,
            },
            "BTC": {
                "asset": "BTC",
                "funding_rate_1h": 0.00005,
                "funding_rate_8h": 0.0004,
                "funding_rate_annual": 0.438,
                "open_interest_usd": 800000000.0,
                "mark_price": 65000.0,
                "premium": 0.00005,
                "timestamp": generated_at,
            },
            "SOL": {
                "asset": "SOL",
                "funding_rate_1h": 0.00002,
                "funding_rate_8h": 0.00016,
                "funding_rate_annual": 0.1752,
                "open_interest_usd": 100000000.0,
                "mark_price": 170.0,
                "premium": 0.00002,
                "timestamp": generated_at,
            },
        }
    return {
        "schema_version": 1,
        "source": "perp_funding_feed",
        "venue": "hyperliquid",
        "generated_at": generated_at,
        "stale": stale,
        "rates": rates,
    }


def _make_adapter_status():
    return {
        "aave_v3": {"apy": 0.031, "tvl": 5000000},
        "compound_v3": {"apy": 0.033, "tvl": 8000000},
    }


class TestBTSMonitorScan(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.data_dir = Path(self.tmpdir)
        self.monitor = BTSMonitor(
            data_dir=self.data_dir,
            use_alert_dispatcher=False,
        )

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _write_funding(self, data):
        atomic_save(data, str(self.data_dir / FUNDING_FILENAME))

    def _write_adapter_status(self, data):
        atomic_save(data, str(self.data_dir / ADAPTER_STATUS_FILENAME))

    def _write_opportunities(self, data):
        atomic_save(data, str(self.data_dir / OPP_FILENAME))

    # ── Test 1: Empty opportunities when feed missing ──
    def test_empty_when_no_funding_file(self):
        opps = self.monitor.scan()
        self.assertEqual(opps, [])

    # ── Test 2: Empty opportunities when feed stale ──
    def test_empty_when_feed_stale(self):
        data = _make_funding_data(stale=True)
        self._write_funding(data)
        opps = self.monitor.scan()
        self.assertEqual(opps, [])

    # ── Test 3: Empty when generated_at is old ──
    def test_empty_when_generated_at_old(self):
        old_time = (datetime.now(timezone.utc) - timedelta(seconds=STALE_AFTER_S + 100)).isoformat()
        data = _make_funding_data(generated_at=old_time)
        self._write_funding(data)
        opps = self.monitor.scan()
        self.assertEqual(opps, [])

    # ── Test 4: Valid scan returns opportunities ──
    def test_valid_scan_returns_opportunities(self):
        self._write_funding(_make_funding_data())
        self._write_adapter_status(_make_adapter_status())
        opps = self.monitor.scan()
        self.assertGreater(len(opps), 0)
        self.assertLessEqual(len(opps), 5)

    # ── Test 5: Correct ranking by net_spread_bps ──
    def test_ranked_by_net_spread_descending(self):
        self._write_funding(_make_funding_data())
        self._write_adapter_status(_make_adapter_status())
        opps = self.monitor.scan()
        if len(opps) >= 2:
            for i in range(len(opps) - 1):
                self.assertGreaterEqual(opps[i].net_spread_bps, opps[i + 1].net_spread_bps)

    # ── Test 6: ETH has highest spread with given data ──
    def test_eth_top_ranked(self):
        self._write_funding(_make_funding_data())
        self._write_adapter_status(_make_adapter_status())
        opps = self.monitor.scan()
        self.assertEqual(opps[0].asset, "ETH")

    # ── Test 7: All 3 assets present ──
    def test_three_assets_scanned(self):
        self._write_funding(_make_funding_data())
        self._write_adapter_status(_make_adapter_status())
        opps = self.monitor.scan()
        assets = {o.asset for o in opps}
        self.assertEqual(assets, {"ETH", "BTC", "SOL"})

    # ── Test 8: Empty rates dict ──
    def test_empty_rates(self):
        data = _make_funding_data(rates={})
        self._write_funding(data)
        opps = self.monitor.scan()
        self.assertEqual(opps, [])

    # ── Test 9: Malformed funding rate ──
    def test_malformed_funding_rate_skipped(self):
        data = _make_funding_data(rates={
            "ETH": {"funding_rate_annual": "invalid"},
        })
        self._write_funding(data)
        opps = self.monitor.scan()
        self.assertEqual(opps, [])

    # ── Test 10: Missing funding_rate_annual key ──
    def test_missing_funding_rate_key(self):
        data = _make_funding_data(rates={
            "ETH": {"asset": "ETH", "mark_price": 3000},
        })
        self._write_funding(data)
        opps = self.monitor.scan()
        self.assertEqual(opps, [])

    # ── Test 11: Opportunity to_dict structure ──
    def test_opportunity_to_dict(self):
        opp = BTSOpportunity(
            asset="ETH",
            spot_yield_pct=5.0,
            perp_funding_pct=10.0,
            net_spread_bps=130.0,
            edge_quality="EXCELLENT",
            recommended_action="ENTER",
            annual_pnl_usd=2600.0,
            gross_spread_bps=150.0,
        )
        d = opp.to_dict()
        self.assertEqual(d["asset"], "ETH")
        self.assertEqual(d["edge_quality"], "EXCELLENT")
        self.assertIn("net_spread_bps", d)
        self.assertIn("annual_pnl_usd", d)

    # ── Test 12: spot yield from adapter_status ──
    def test_spot_yield_from_adapter_status(self):
        yield_val = self.monitor._get_spot_yield({"aave_v3": {"apy": 0.06}})
        self.assertAlmostEqual(yield_val, 0.06, places=3)

    # ── Test 13: spot yield defaults when no adapter ──
    def test_spot_yield_default(self):
        yield_val = self.monitor._get_spot_yield({})
        self.assertEqual(yield_val, DEFAULT_SPOT_YIELD)

    # ── Test 14: spot yield handles percent format ──
    def test_spot_yield_percent_format(self):
        yield_val = self.monitor._get_spot_yield({"aave_v3": {"apy": 8.5}})
        self.assertAlmostEqual(yield_val, 0.085, places=3)

    # ── Test 15: only single asset in rates ──
    def test_single_asset_scan(self):
        rates = {
            "BTC": {
                "asset": "BTC",
                "funding_rate_annual": 0.5,
                "open_interest_usd": 800000000,
                "mark_price": 65000,
                "premium": 0.0001,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            },
        }
        self._write_funding(_make_funding_data(rates=rates))
        opps = self.monitor.scan()
        self.assertEqual(len(opps), 1)
        self.assertEqual(opps[0].asset, "BTC")


class TestBTSMonitorExcellentDetection(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.data_dir = Path(self.tmpdir)
        self.monitor = BTSMonitor(
            data_dir=self.data_dir,
            use_alert_dispatcher=False,
        )

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _write_previous_opportunities(self, opps_data):
        atomic_save(opps_data, str(self.data_dir / OPP_FILENAME))

    # ── Test 16: new EXCELLENT detected when none before ──
    def test_new_excellent_from_empty(self):
        current = [
            BTSOpportunity("ETH", 5.0, 15.0, 180.0, "EXCELLENT", "ENTER", 3600.0),
        ]
        new_exc = self.monitor._detect_new_excellent(current)
        self.assertEqual(len(new_exc), 1)
        self.assertEqual(new_exc[0].asset, "ETH")

    # ── Test 17: no alert when already EXCELLENT ──
    def test_no_alert_when_already_excellent(self):
        self._write_previous_opportunities({
            "opportunities": [
                {"asset": "ETH", "edge_quality": "EXCELLENT"},
            ],
        })
        current = [
            BTSOpportunity("ETH", 5.0, 15.0, 180.0, "EXCELLENT", "ENTER", 3600.0),
        ]
        new_exc = self.monitor._detect_new_excellent(current)
        self.assertEqual(len(new_exc), 0)

    # ── Test 18: new EXCELLENT when previous was GOOD ──
    def test_transition_from_good_to_excellent(self):
        self._write_previous_opportunities({
            "opportunities": [
                {"asset": "ETH", "edge_quality": "GOOD"},
            ],
        })
        current = [
            BTSOpportunity("ETH", 5.0, 15.0, 180.0, "EXCELLENT", "ENTER", 3600.0),
        ]
        new_exc = self.monitor._detect_new_excellent(current)
        self.assertEqual(len(new_exc), 1)

    # ── Test 19: multiple assets, only new one alerts ──
    def test_multi_asset_new_excellent(self):
        self._write_previous_opportunities({
            "opportunities": [
                {"asset": "ETH", "edge_quality": "EXCELLENT"},
                {"asset": "BTC", "edge_quality": "GOOD"},
            ],
        })
        current = [
            BTSOpportunity("ETH", 5.0, 15.0, 180.0, "EXCELLENT", "ENTER", 3600.0),
            BTSOpportunity("BTC", 3.0, 12.0, 130.0, "EXCELLENT", "ENTER", 2600.0),
        ]
        new_exc = self.monitor._detect_new_excellent(current)
        self.assertEqual(len(new_exc), 1)
        self.assertEqual(new_exc[0].asset, "BTC")

    # ── Test 20: GOOD does not trigger ──
    def test_good_not_new_excellent(self):
        current = [
            BTSOpportunity("ETH", 5.0, 8.0, 60.0, "GOOD", "ENTER", 1200.0),
        ]
        new_exc = self.monitor._detect_new_excellent(current)
        self.assertEqual(len(new_exc), 0)

    # ── Test 21: previous file corrupt → treat as empty ──
    def test_corrupt_previous_file(self):
        (self.data_dir / OPP_FILENAME).write_text("not json")
        current = [
            BTSOpportunity("ETH", 5.0, 15.0, 180.0, "EXCELLENT", "ENTER", 3600.0),
        ]
        new_exc = self.monitor._detect_new_excellent(current)
        self.assertEqual(len(new_exc), 1)

    # ── Test 22: no current EXCELLENT → no new ──
    def test_no_current_excellent(self):
        current = [
            BTSOpportunity("ETH", 5.0, 3.0, 30.0, "MARGINAL", "MONITOR", 600.0),
        ]
        new_exc = self.monitor._detect_new_excellent(current)
        self.assertEqual(len(new_exc), 0)


class TestBTSMonitorRun(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.data_dir = Path(self.tmpdir)
        self.monitor = BTSMonitor(
            data_dir=self.data_dir,
            use_alert_dispatcher=False,
        )

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _write_funding(self, data):
        atomic_save(data, str(self.data_dir / FUNDING_FILENAME))

    def _write_adapter_status(self, data):
        atomic_save(data, str(self.data_dir / ADAPTER_STATUS_FILENAME))

    # ── Test 23: run writes heartbeat ──
    def test_run_writes_heartbeat(self):
        self._write_funding(_make_funding_data())
        self._write_adapter_status(_make_adapter_status())
        self.monitor.run()
        status_path = self.data_dir / STATUS_FILENAME
        self.assertTrue(status_path.exists())
        status = json.loads(status_path.read_text())
        self.assertIn("last_run", status)
        self.assertEqual(status["status"], "ok")

    # ── Test 24: run writes opportunities file ──
    def test_run_writes_opportunities(self):
        self._write_funding(_make_funding_data())
        self._write_adapter_status(_make_adapter_status())
        self.monitor.run()
        opp_path = self.data_dir / OPP_FILENAME
        self.assertTrue(opp_path.exists())
        data = json.loads(opp_path.read_text())
        self.assertIn("opportunities", data)
        self.assertIn("summary", data)

    # ── Test 25: summary counts correct ──
    def test_summary_counts(self):
        self._write_funding(_make_funding_data())
        self._write_adapter_status(_make_adapter_status())
        self.monitor.run()
        opp_path = self.data_dir / OPP_FILENAME
        data = json.loads(opp_path.read_text())
        summary = data["summary"]
        opps = data["opportunities"]
        self.assertEqual(summary["total_analyzed"], len(opps))
        actual_excellent = sum(1 for o in opps if o["edge_quality"] == "EXCELLENT")
        self.assertEqual(summary["excellent_count"], actual_excellent)
        actual_enter = sum(1 for o in opps if o["recommended_action"] == "ENTER")
        self.assertEqual(summary["enter_count"], actual_enter)

    # ── Test 26: run with no data writes empty stale ──
    def test_run_empty_writes_stale(self):
        self.monitor.run()
        opp_path = self.data_dir / OPP_FILENAME
        self.assertTrue(opp_path.exists())
        data = json.loads(opp_path.read_text())
        self.assertTrue(data["stale_feed"])
        self.assertEqual(data["opportunities"], [])

    # ── Test 27: run returns report dict ──
    def test_run_returns_report(self):
        self._write_funding(_make_funding_data())
        self._write_adapter_status(_make_adapter_status())
        report = self.monitor.run()
        self.assertIn("opportunities", report)
        self.assertIn("status", report)
        self.assertEqual(report["status"], "ok")

    # ── Test 28: heartbeat has opportunity count ──
    def test_heartbeat_opportunity_count(self):
        self._write_funding(_make_funding_data())
        self._write_adapter_status(_make_adapter_status())
        self.monitor.run()
        status = json.loads((self.data_dir / STATUS_FILENAME).read_text())
        self.assertGreater(status["opportunities_found"], 0)

    # ── Test 29: generated_at timestamp in opportunities ──
    def test_generated_at_in_opportunities(self):
        self._write_funding(_make_funding_data())
        self._write_adapter_status(_make_adapter_status())
        self.monitor.run()
        data = json.loads((self.data_dir / OPP_FILENAME).read_text())
        self.assertIn("generated_at", data)
        self.assertIsInstance(data["generated_at"], float)

    # ── Test 30: stale_feed false when valid data ──
    def test_stale_feed_false_when_valid(self):
        self._write_funding(_make_funding_data())
        self._write_adapter_status(_make_adapter_status())
        self.monitor.run()
        data = json.loads((self.data_dir / OPP_FILENAME).read_text())
        self.assertFalse(data["stale_feed"])

    # ── Test 31: new_excellent count in heartbeat ──
    def test_new_excellent_in_heartbeat(self):
        self._write_funding(_make_funding_data())
        self._write_adapter_status(_make_adapter_status())
        self.monitor.run()
        status = json.loads((self.data_dir / STATUS_FILENAME).read_text())
        self.assertIn("new_excellent", status)
        self.assertIsInstance(status["new_excellent"], int)

    # ── Test 32: second run preserves transition logic ──
    def test_second_run_no_spurious_new_excellent(self):
        self._write_funding(_make_funding_data())
        self._write_adapter_status(_make_adapter_status())
        self.monitor.run()
        first_status = json.loads((self.data_dir / STATUS_FILENAME).read_text())

        self.monitor.run()
        second_status = json.loads((self.data_dir / STATUS_FILENAME).read_text())
        self.assertEqual(second_status["new_excellent"], 0)

    # ── Test 33: adapter status with invalid apy ──
    def test_adapter_status_invalid_apy(self):
        self._write_funding(_make_funding_data())
        self._write_adapter_status({"aave_v3": {"apy": "invalid"}})
        opps = self.monitor.scan()
        self.assertGreater(len(opps), 0)

    # ── Test 34: funding data with None value ──
    def test_funding_none_value(self):
        data = _make_funding_data(rates={
            "ETH": {"funding_rate_annual": None},
        })
        self._write_funding(data)
        opps = self.monitor.scan()
        self.assertEqual(opps, [])

    # ── Test 35: top 5 limit ──
    def test_top_5_limit(self):
        rates = {}
        for i, asset in enumerate(["ETH", "BTC", "SOL", "DOGE", "AVAX", "MATIC"]):
            rates[asset] = {
                "asset": asset,
                "funding_rate_annual": 0.5 + i * 0.1,
                "open_interest_usd": 100000000,
                "mark_price": 1000,
                "premium": 0.0001,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
        data = _make_funding_data(rates=rates)
        self._write_funding(data)
        opps = self.monitor.scan()
        self.assertLessEqual(len(opps), 5)


class TestBTSMonitorAlerts(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.data_dir = Path(self.tmpdir)
        self.monitor = BTSMonitor(
            data_dir=self.data_dir,
            use_alert_dispatcher=False,
        )

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    # ── Test 36: _create_alerts logs when no dispatcher ──
    def test_create_alerts_log_only(self):
        opps = [
            BTSOpportunity("ETH", 5.0, 15.0, 180.0, "EXCELLENT", "ENTER", 3600.0),
        ]
        sent = self.monitor._create_alerts(opps)
        self.assertEqual(sent, 1)

    # ── Test 37: _create_alerts returns 0 for empty list ──
    def test_create_alerts_empty(self):
        sent = self.monitor._create_alerts([])
        self.assertEqual(sent, 0)


if __name__ == "__main__":
    unittest.main()
