"""
spa_core/tests/test_monitor_alerts.py

Tests for Alert dataclass and AlertEngine (spa_core/monitor/alerts.py).

MP-1460 (v10.76) — Sprint 2: monitor/ coverage + BaseAnalytics migration.

Run:
    python3 -m unittest spa_core.tests.test_monitor_alerts -v
"""
from __future__ import annotations

import sys
import unittest
from datetime import datetime, timezone, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from spa_core.monitor.alerts import Alert, AlertEngine


# ─── helpers ──────────────────────────────────────────────────────────────────

def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _old_iso(hours: float) -> str:
    return (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()


def _snap(key="aave-v3-usdc-ethereum", apy=5.0, tvl=50_000_000, ts=None) -> dict:
    return {
        "protocol_key": key,
        "apy_total": apy,
        "tvl_usd": tvl,
        "timestamp": ts or _now_iso(),
        "tier": "T1",
    }


# ─── Alert dataclass Tests ────────────────────────────────────────────────────

class TestAlert(unittest.TestCase):

    def test_construction(self):
        a = Alert(
            severity="WARNING",
            event_type="APY_DROP",
            protocol_key="aave-v3",
            message="APY dropped",
        )
        self.assertEqual(a.severity, "WARNING")
        self.assertEqual(a.event_type, "APY_DROP")
        self.assertEqual(a.protocol_key, "aave-v3")
        self.assertEqual(a.message, "APY dropped")

    def test_str_with_protocol(self):
        a = Alert("WARNING", "APY_DROP", "aave-v3", "APY dropped")
        s = str(a)
        self.assertIn("WARNING", s)
        self.assertIn("aave-v3", s)
        self.assertIn("APY dropped", s)

    def test_str_without_protocol(self):
        a = Alert("CRITICAL", "NO_DATA", None, "No data")
        s = str(a)
        self.assertIn("CRITICAL", s)
        self.assertIn("No data", s)
        self.assertNotIn("None", s)

    def test_details_default_empty(self):
        a = Alert("INFO", "TEST", None, "msg")
        self.assertEqual(a.details, {})

    def test_details_stored(self):
        a = Alert("INFO", "TEST", None, "msg", details={"k": "v"})
        self.assertEqual(a.details["k"], "v")

    def test_timestamp_auto_set(self):
        a = Alert("INFO", "TEST", None, "msg")
        self.assertIsNotNone(a.timestamp)
        # должен быть валидный ISO timestamp
        dt = datetime.fromisoformat(a.timestamp)
        self.assertIsNotNone(dt)

    def test_severity_info(self):
        a = Alert("INFO", "TEST", None, "msg")
        self.assertEqual(a.severity, "INFO")

    def test_severity_critical(self):
        a = Alert("CRITICAL", "KILL_SWITCH", None, "Kill switch")
        self.assertEqual(a.severity, "CRITICAL")


# ─── AlertEngine Tests ────────────────────────────────────────────────────────

class TestAlertEngineCheckSnapshots(unittest.TestCase):

    def setUp(self):
        self.engine = AlertEngine()

    def test_empty_snapshots_no_alerts(self):
        alerts = self.engine.check_snapshots([], [])
        self.assertEqual(alerts, [])

    def test_apy_drop_20pct_triggers_warning(self):
        cur  = [_snap("aave-v3-usdc-ethereum", apy=4.0)]
        prev = [_snap("aave-v3-usdc-ethereum", apy=5.0)]  # 20% drop
        alerts = self.engine.check_snapshots(cur, prev)
        drops = [a for a in alerts if a.event_type == "APY_DROP"]
        self.assertEqual(len(drops), 1)
        self.assertEqual(drops[0].severity, "WARNING")

    def test_apy_drop_60pct_triggers_critical(self):
        cur  = [_snap("aave-v3-usdc-ethereum", apy=2.0)]
        prev = [_snap("aave-v3-usdc-ethereum", apy=5.0)]  # 60% drop
        alerts = self.engine.check_snapshots(cur, prev)
        drops = [a for a in alerts if a.event_type == "APY_DROP"]
        self.assertGreater(len(drops), 0)
        self.assertTrue(any(a.severity == "CRITICAL" for a in drops))

    def test_small_apy_drop_no_alert(self):
        cur  = [_snap("aave-v3-usdc-ethereum", apy=4.9)]
        prev = [_snap("aave-v3-usdc-ethereum", apy=5.0)]  # 2% drop
        alerts = self.engine.check_snapshots(cur, prev)
        drops = [a for a in alerts if a.event_type == "APY_DROP"]
        self.assertEqual(len(drops), 0)

    def test_apy_spike_50pct_triggers_warning(self):
        cur  = [_snap("maple-usdc", apy=8.0)]
        prev = [_snap("maple-usdc", apy=5.0)]   # 60% spike
        alerts = self.engine.check_snapshots(cur, prev)
        spikes = [a for a in alerts if a.event_type == "APY_SPIKE"]
        self.assertGreater(len(spikes), 0)
        self.assertTrue(all(a.severity == "WARNING" for a in spikes))

    def test_small_apy_spike_no_alert(self):
        cur  = [_snap("aave-v3-usdc-ethereum", apy=5.2)]
        prev = [_snap("aave-v3-usdc-ethereum", apy=5.0)]  # 4% spike
        alerts = self.engine.check_snapshots(cur, prev)
        spikes = [a for a in alerts if a.event_type == "APY_SPIKE"]
        self.assertEqual(len(spikes), 0)

    def test_tvl_drop_30pct_triggers_warning(self):
        cur  = [_snap("aave-v3-usdc-ethereum", tvl=35_000_000)]
        prev = [_snap("aave-v3-usdc-ethereum", tvl=50_000_000)]  # 30% drop
        alerts = self.engine.check_snapshots(cur, prev)
        drops = [a for a in alerts if a.event_type == "TVL_DROP"]
        self.assertGreater(len(drops), 0)

    def test_tvl_drop_60pct_triggers_critical(self):
        cur  = [_snap("aave-v3-usdc-ethereum", tvl=20_000_000)]
        prev = [_snap("aave-v3-usdc-ethereum", tvl=50_000_000)]  # 60% drop
        alerts = self.engine.check_snapshots(cur, prev)
        drops = [a for a in alerts if a.event_type == "TVL_DROP"]
        self.assertTrue(any(a.severity == "CRITICAL" for a in drops))

    def test_low_tvl_triggers_warning(self):
        cur = [_snap("aave-v3-usdc-ethereum", tvl=5_000_000)]
        alerts = self.engine.check_snapshots(cur, [])
        low_tvl = [a for a in alerts if a.event_type == "LOW_TVL"]
        self.assertGreater(len(low_tvl), 0)
        self.assertEqual(low_tvl[0].severity, "WARNING")

    def test_normal_tvl_no_low_tvl_alert(self):
        cur = [_snap("aave-v3-usdc-ethereum", tvl=50_000_000)]
        alerts = self.engine.check_snapshots(cur, [])
        low_tvl = [a for a in alerts if a.event_type == "LOW_TVL"]
        self.assertEqual(len(low_tvl), 0)

    def test_stale_data_triggers_warning(self):
        stale_ts = _old_iso(10.0)  # 10 hours ago
        cur = [_snap("aave-v3-usdc-ethereum", ts=stale_ts)]
        alerts = self.engine.check_snapshots(cur, [])
        stale = [a for a in alerts if a.event_type == "STALE_DATA"]
        self.assertGreater(len(stale), 0)

    def test_fresh_data_no_stale_alert(self):
        cur = [_snap("aave-v3-usdc-ethereum", ts=_now_iso())]
        alerts = self.engine.check_snapshots(cur, [])
        stale = [a for a in alerts if a.event_type == "STALE_DATA"]
        self.assertEqual(len(stale), 0)

    def test_no_previous_snapshot_skips_comparison(self):
        cur  = [_snap("new-protocol", apy=5.0)]
        prev = []
        # Should not raise; comparison alerts skipped but staleness/TVL still checked
        alerts = self.engine.check_snapshots(cur, prev)
        self.assertIsInstance(alerts, list)

    def test_multiple_protocols_independent(self):
        cur = [
            _snap("aave-v3-usdc-ethereum",  apy=3.0),  # drop
            _snap("compound-v3-usdc-ethereum", apy=5.0),  # no change
        ]
        prev = [
            _snap("aave-v3-usdc-ethereum",  apy=5.0),
            _snap("compound-v3-usdc-ethereum", apy=5.0),
        ]
        alerts = self.engine.check_snapshots(cur, prev)
        apy_drops = [a for a in alerts if a.event_type == "APY_DROP"]
        self.assertEqual(len(apy_drops), 1)
        self.assertEqual(apy_drops[0].protocol_key, "aave-v3-usdc-ethereum")


class TestAlertEnginePipelineHealth(unittest.TestCase):

    def setUp(self):
        self.engine = AlertEngine()

    def test_empty_snapshots_triggers_critical_no_data(self):
        alerts = self.engine.check_pipeline_health([])
        no_data = [a for a in alerts if a.event_type == "NO_DATA"]
        self.assertGreater(len(no_data), 0)
        self.assertEqual(no_data[0].severity, "CRITICAL")

    def test_all_expected_protocols_no_missing_alert(self):
        expected = [
            "aave-v3-usdc-ethereum", "aave-v3-usdt-ethereum",
            "compound-v3-usdc-ethereum", "morpho-usdc-ethereum",
            "yearn-v3-usdc-ethereum", "maple-usdc-ethereum",
            "euler-v2-usdc-ethereum",
        ]
        snaps = [_snap(key=k) for k in expected]
        alerts = self.engine.check_pipeline_health(snaps)
        missing = [a for a in alerts if a.event_type == "MISSING_PROTOCOL_DATA"]
        self.assertEqual(len(missing), 0)

    def test_partial_protocols_triggers_missing_warning(self):
        snaps = [_snap("aave-v3-usdc-ethereum")]  # only 1 of 7
        alerts = self.engine.check_pipeline_health(snaps)
        missing = [a for a in alerts if a.event_type == "MISSING_PROTOCOL_DATA"]
        self.assertGreater(len(missing), 0)
        self.assertEqual(missing[0].severity, "WARNING")

    def test_alert_returns_list(self):
        alerts = self.engine.check_pipeline_health([_snap()])
        self.assertIsInstance(alerts, list)


class TestAlertEngineConstants(unittest.TestCase):

    def test_apy_drop_threshold_positive(self):
        self.assertGreater(AlertEngine.APY_DROP_THRESHOLD_PCT, 0)

    def test_apy_spike_threshold_positive(self):
        self.assertGreater(AlertEngine.APY_SPIKE_THRESHOLD_PCT, 0)

    def test_tvl_drop_threshold_positive(self):
        self.assertGreater(AlertEngine.TVL_DROP_THRESHOLD_PCT, 0)

    def test_stale_data_hours_positive(self):
        self.assertGreater(AlertEngine.STALE_DATA_HOURS, 0)

    def test_min_tvl_warning_reasonable(self):
        self.assertGreater(AlertEngine.MIN_TVL_WARNING_USD, 1_000_000)


if __name__ == "__main__":
    unittest.main()
