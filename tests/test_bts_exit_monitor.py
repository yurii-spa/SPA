"""
tests/test_bts_exit_monitor.py — BTS Exit Monitor test suite (≥20 tests).

Tests cover:
  - FUNDING_REVERSAL detected when funding < -5%
  - FUNDING_NEGATIVE detected when funding < 0
  - SPREAD_COMPRESSED detected when spread < 10bps
  - clear=true when no exit conditions
  - MANUAL_KILL when kill switch active
  - STALE_DATA when funding stale
  - Multiple simultaneous signals
  - File output structure
"""
import json
import tempfile
import unittest
from datetime import datetime, timezone, timedelta
from pathlib import Path

from spa_core.analytics.bts_exit_monitor import (
    BTSExitMonitor,
    BTSExitSignal,
    EXIT_FILE,
    FUNDING_FILE,
    KILL_SWITCH_FILE,
    STALE_AFTER_S,
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
                "funding_rate_annual": 0.10,
                "open_interest_usd": 500000000.0,
                "mark_price": 3100.0,
                "premium": 0.0001,
                "timestamp": generated_at,
            },
            "BTC": {
                "asset": "BTC",
                "funding_rate_annual": 0.08,
                "open_interest_usd": 800000000.0,
                "mark_price": 65000.0,
                "premium": 0.00005,
                "timestamp": generated_at,
            },
            "SOL": {
                "asset": "SOL",
                "funding_rate_annual": 0.05,
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


class TestBTSExitMonitorConditions(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.data_dir = Path(self.tmpdir)
        self.monitor = BTSExitMonitor(data_dir=self.data_dir)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _write_funding(self, data):
        atomic_save(data, str(self.data_dir / FUNDING_FILE))

    def _write_kill_switch(self, active):
        atomic_save({"active": active}, str(self.data_dir / KILL_SWITCH_FILE))

    # ── Test 1: FUNDING_REVERSAL detected ──
    def test_funding_reversal_detected(self):
        rates = {
            "ETH": {"funding_rate_annual": -0.10},
        }
        data = _make_funding_data(rates=rates)
        signals = self.monitor.evaluate_conditions(data)
        reversal_signals = [s for s in signals if s.reason == "FUNDING_REVERSAL"]
        self.assertGreater(len(reversal_signals), 0)
        self.assertEqual(reversal_signals[0].asset, "ETH")
        self.assertEqual(reversal_signals[0].severity, "CRITICAL")

    # ── Test 2: FUNDING_REVERSAL threshold at -5% ──
    def test_funding_reversal_at_threshold(self):
        rates = {
            "ETH": {"funding_rate_annual": -0.06},
        }
        data = _make_funding_data(rates=rates)
        signals = self.monitor.evaluate_conditions(data)
        reversal = [s for s in signals if s.reason == "FUNDING_REVERSAL" and s.asset == "ETH"]
        self.assertEqual(len(reversal), 1)

    # ── Test 3: No FUNDING_REVERSAL above threshold ──
    def test_no_funding_reversal_above_threshold(self):
        rates = {
            "ETH": {"funding_rate_annual": -0.03},
        }
        data = _make_funding_data(rates=rates)
        signals = self.monitor.evaluate_conditions(data)
        reversal = [s for s in signals if s.reason == "FUNDING_REVERSAL"]
        self.assertEqual(len(reversal), 0)

    # ── Test 4: FUNDING_NEGATIVE detected ──
    def test_funding_negative_detected(self):
        rates = {
            "ETH": {"funding_rate_annual": -0.02},
        }
        data = _make_funding_data(rates=rates)
        signals = self.monitor.evaluate_conditions(data)
        negative = [s for s in signals if s.reason == "FUNDING_NEGATIVE" and s.asset == "ETH"]
        self.assertEqual(len(negative), 1)
        self.assertEqual(negative[0].severity, "HIGH")

    # ── Test 5: SPREAD_COMPRESSED detected ──
    def test_spread_compressed_detected(self):
        rates = {
            "ETH": {"funding_rate_annual": -0.048},
        }
        data = _make_funding_data(rates=rates)
        signals = self.monitor.evaluate_conditions(data)
        compressed = [s for s in signals if s.reason == "SPREAD_COMPRESSED" and s.asset == "ETH"]
        self.assertEqual(len(compressed), 1)

    # ── Test 6: No SPREAD_COMPRESSED above floor ──
    def test_no_spread_compressed_above_floor(self):
        rates = {
            "ETH": {"funding_rate_annual": 0.10},
        }
        data = _make_funding_data(rates=rates)
        signals = self.monitor.evaluate_conditions(data)
        compressed = [s for s in signals if s.reason == "SPREAD_COMPRESSED" and s.asset == "ETH"]
        self.assertEqual(len(compressed), 0)

    # ── Test 7: clear=true when no exit conditions ──
    def test_clear_when_healthy(self):
        data = _make_funding_data()
        signals = self.monitor.evaluate_conditions(data)
        exit_signals = [
            s for s in signals
            if s.reason in ("FUNDING_REVERSAL", "FUNDING_NEGATIVE", "MANUAL_KILL", "STALE_DATA")
        ]
        self.assertEqual(len(exit_signals), 0)

    # ── Test 8: MANUAL_KILL when kill switch active ──
    def test_manual_kill_active(self):
        self._write_kill_switch(True)
        data = _make_funding_data()
        signals = self.monitor.evaluate_conditions(data)
        kill = [s for s in signals if s.reason == "MANUAL_KILL"]
        self.assertEqual(len(kill), 1)
        self.assertEqual(kill[0].severity, "CRITICAL")
        self.assertEqual(kill[0].asset, "ALL")

    # ── Test 9: No kill when switch inactive ──
    def test_no_kill_when_inactive(self):
        self._write_kill_switch(False)
        data = _make_funding_data()
        signals = self.monitor.evaluate_conditions(data)
        kill = [s for s in signals if s.reason == "MANUAL_KILL"]
        self.assertEqual(len(kill), 0)

    # ── Test 10: No kill when switch file missing ──
    def test_no_kill_when_file_missing(self):
        data = _make_funding_data()
        signals = self.monitor.evaluate_conditions(data)
        kill = [s for s in signals if s.reason == "MANUAL_KILL"]
        self.assertEqual(len(kill), 0)

    # ── Test 11: STALE_DATA when funding stale ──
    def test_stale_data_signal(self):
        data = _make_funding_data(stale=True)
        signals = self.monitor.evaluate_conditions(data)
        stale = [s for s in signals if s.reason == "STALE_DATA"]
        self.assertEqual(len(stale), 1)
        self.assertEqual(stale[0].severity, "HIGH")

    # ── Test 12: STALE_DATA when funding None ──
    def test_stale_data_none_funding(self):
        signals = self.monitor.evaluate_conditions(None)
        stale = [s for s in signals if s.reason == "STALE_DATA"]
        self.assertEqual(len(stale), 1)

    # ── Test 13: STALE_DATA when generated_at old ──
    def test_stale_when_old_timestamp(self):
        old_time = (datetime.now(timezone.utc) - timedelta(seconds=STALE_AFTER_S + 100)).isoformat()
        data = _make_funding_data(generated_at=old_time)
        signals = self.monitor.evaluate_conditions(data)
        stale = [s for s in signals if s.reason == "STALE_DATA"]
        self.assertEqual(len(stale), 1)

    # ── Test 14: Multiple assets multiple signals ──
    def test_multiple_assets_signals(self):
        rates = {
            "ETH": {"funding_rate_annual": -0.10},
            "BTC": {"funding_rate_annual": -0.03},
        }
        data = _make_funding_data(rates=rates)
        signals = self.monitor.evaluate_conditions(data)
        eth_signals = [s for s in signals if s.asset == "ETH"]
        btc_signals = [s for s in signals if s.asset == "BTC"]
        self.assertGreater(len(eth_signals), 0)
        self.assertGreater(len(btc_signals), 0)

    # ── Test 15: Signal to_dict structure ──
    def test_signal_to_dict(self):
        signal = BTSExitSignal(
            asset="ETH",
            reason="FUNDING_REVERSAL",
            current_funding_annual=-0.08,
            current_net_spread_bps=-10.0,
            severity="CRITICAL",
        )
        d = signal.to_dict()
        self.assertEqual(d["asset"], "ETH")
        self.assertEqual(d["reason"], "FUNDING_REVERSAL")
        self.assertEqual(d["severity"], "CRITICAL")
        self.assertIn("current_funding_annual", d)
        self.assertIn("current_net_spread_bps", d)


class TestBTSExitMonitorRun(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.data_dir = Path(self.tmpdir)
        self.monitor = BTSExitMonitor(data_dir=self.data_dir)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _write_funding(self, data):
        atomic_save(data, str(self.data_dir / FUNDING_FILE))

    def _write_kill_switch(self, active):
        atomic_save({"active": active}, str(self.data_dir / KILL_SWITCH_FILE))

    # ── Test 16: run writes exit signals file ──
    def test_run_writes_exit_file(self):
        self._write_funding(_make_funding_data())
        self.monitor.run()
        exit_path = self.data_dir / EXIT_FILE
        self.assertTrue(exit_path.exists())

    # ── Test 17: run output has correct structure ──
    def test_run_output_structure(self):
        self._write_funding(_make_funding_data())
        result = self.monitor.run()
        self.assertIn("signal_count", result)
        self.assertIn("clear", result)
        self.assertIn("signals", result)
        self.assertIn("status", result)

    # ── Test 18: run clear when healthy ──
    def test_run_clear_when_healthy(self):
        self._write_funding(_make_funding_data())
        result = self.monitor.run()
        non_compressed = [
            s for s in result["signals"]
            if s["reason"] != "SPREAD_COMPRESSED"
        ]
        self.assertEqual(len(non_compressed), 0)

    # ── Test 19: run signals with kill switch ──
    def test_run_signals_with_kill(self):
        self._write_funding(_make_funding_data())
        self._write_kill_switch(True)
        result = self.monitor.run()
        self.assertGreater(result["signal_count"], 0)
        kill = [s for s in result["signals"] if s["reason"] == "MANUAL_KILL"]
        self.assertEqual(len(kill), 1)

    # ── Test 20: run with no funding file ──
    def test_run_no_funding(self):
        result = self.monitor.run()
        self.assertIn("status", result)
        stale = [s for s in result["signals"] if s["reason"] == "STALE_DATA"]
        self.assertEqual(len(stale), 1)

    # ── Test 21: exit file timestamp field ──
    def test_exit_file_timestamp(self):
        self._write_funding(_make_funding_data())
        self.monitor.run()
        data = json.loads((self.data_dir / EXIT_FILE).read_text())
        self.assertIn("timestamp", data)

    # ── Test 22: exit file active_signals field ──
    def test_exit_file_active_signals(self):
        self._write_funding(_make_funding_data())
        self.monitor.run()
        data = json.loads((self.data_dir / EXIT_FILE).read_text())
        self.assertIn("active_signals", data)
        self.assertIsInstance(data["active_signals"], list)

    # ── Test 23: exit file clear field ──
    def test_exit_file_clear_field(self):
        self._write_funding(_make_funding_data())
        self.monitor.run()
        data = json.loads((self.data_dir / EXIT_FILE).read_text())
        self.assertIn("clear", data)

    # ── Test 24: concurrent funding reversal + spread compressed ──
    def test_reversal_plus_compressed(self):
        rates = {
            "ETH": {"funding_rate_annual": -0.10},
        }
        data = _make_funding_data(rates=rates)
        signals = self.monitor.evaluate_conditions(data)
        eth_reasons = {s.reason for s in signals if s.asset == "ETH"}
        self.assertIn("FUNDING_REVERSAL", eth_reasons)
        self.assertIn("SPREAD_COMPRESSED", eth_reasons)

    # ── Test 25: run status ok ──
    def test_run_status_ok(self):
        self._write_funding(_make_funding_data())
        result = self.monitor.run()
        self.assertEqual(result["status"], "ok")


if __name__ == "__main__":
    unittest.main()
