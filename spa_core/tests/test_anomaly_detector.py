"""Tests for spa_core.monitoring.anomaly_detector (MP-1579 / Improvement 4).

20 unit tests across:
  - TestApyAnomalies       (6)
  - TestPositionAnomalies  (4)
  - TestEquityDrop         (4)
  - TestDetectorRun        (6)

Run:
  python3 -m unittest spa_core.tests.test_anomaly_detector -v
"""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from spa_core.monitoring.anomaly_detector import (
    KIND_APY_SPIKE,
    KIND_APY_ZERO,
    KIND_EQUITY_DROP,
    KIND_POSITION_ZERO,
    AnomalyDetector,
    detect_apy_anomalies,
    detect_equity_drop,
    detect_position_anomalies,
    main,
)


class TestApyAnomalies(unittest.TestCase):
    def test_spike_over_2x(self):
        a = detect_apy_anomalies({"aave": 4.0}, {"aave": 9.0})
        self.assertEqual(len(a), 1)
        self.assertEqual(a[0].kind, KIND_APY_SPIKE)

    def test_no_spike_under_2x(self):
        a = detect_apy_anomalies({"aave": 4.0}, {"aave": 7.0})
        self.assertEqual(a, [])

    def test_zero_drop(self):
        a = detect_apy_anomalies({"comp": 5.0}, {"comp": 0.0})
        self.assertEqual(len(a), 1)
        self.assertEqual(a[0].kind, KIND_APY_ZERO)

    def test_new_protocol_no_baseline_ignored(self):
        a = detect_apy_anomalies({}, {"new": 100.0})
        self.assertEqual(a, [])

    def test_near_zero_baseline_not_spike(self):
        # baseline below _MIN_APY_FOR_SPIKE → ignore (avoids noise blowups)
        a = detect_apy_anomalies({"x": 0.001}, {"x": 5.0})
        self.assertEqual(a, [])

    def test_multiple_protocols(self):
        a = detect_apy_anomalies(
            {"a": 4.0, "b": 5.0, "c": 3.0},
            {"a": 9.0, "b": 0.0, "c": 3.1})
        kinds = sorted(x.kind for x in a)
        self.assertEqual(kinds, sorted([KIND_APY_ZERO, KIND_APY_SPIKE]))


class TestPositionAnomalies(unittest.TestCase):
    def test_position_to_zero(self):
        a = detect_position_anomalies({"aave": 5000}, {"aave": 0})
        self.assertEqual(len(a), 1)
        self.assertEqual(a[0].kind, KIND_POSITION_ZERO)

    def test_position_missing_treated_as_zero(self):
        a = detect_position_anomalies({"aave": 5000}, {})
        self.assertEqual(len(a), 1)

    def test_position_reduced_not_zero_no_alert(self):
        a = detect_position_anomalies({"aave": 5000}, {"aave": 2000})
        self.assertEqual(a, [])

    def test_prev_zero_ignored(self):
        a = detect_position_anomalies({"aave": 0}, {"aave": 0})
        self.assertEqual(a, [])


class TestEquityDrop(unittest.TestCase):
    def test_drop_over_threshold(self):
        a = detect_equity_drop(100000, 98500)
        self.assertEqual(len(a), 1)
        self.assertEqual(a[0].kind, KIND_EQUITY_DROP)

    def test_drop_under_threshold(self):
        a = detect_equity_drop(100000, 99500)
        self.assertEqual(a, [])

    def test_equity_increase_no_alert(self):
        a = detect_equity_drop(100000, 100500)
        self.assertEqual(a, [])

    def test_zero_prev_safe(self):
        self.assertEqual(detect_equity_drop(0, 0), [])


class TestDetectorRun(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.dir = Path(self.tmp)
        self.sent = []

    def _w(self, name, obj):
        (self.dir / name).write_text(json.dumps(obj), encoding="utf-8")

    def _sender(self, text):
        self.sent.append(text)
        return True

    def test_detect_combines_classes(self):
        det = AnomalyDetector(data_dir=self.dir)
        out = det.detect(
            prev_apys={"a": 4.0}, curr_apys={"a": 9.0},
            prev_positions={"b": 1000}, curr_positions={"b": 0},
            prev_equity=100000, curr_equity=98000)
        self.assertEqual(len(out), 3)

    def test_no_files_no_anomalies(self):
        det = AnomalyDetector(data_dir=self.dir, sender=self._sender)
        out = det.run()
        self.assertEqual(out["count"], 0)
        self.assertEqual(self.sent, [])

    def test_run_alerts_and_logs(self):
        self._w("anomaly_snapshot.json",
                {"apys": {"aave": 4.0}, "positions": {"aave": 5000}, "equity": 100000})
        self._w("adapter_snapshot.json", {"protocols": [{"name": "aave", "apy": 0.0}]})
        self._w("paper_trading_status.json",
                {"current_positions": {"aave": 0}, "current_equity": 98000})
        det = AnomalyDetector(data_dir=self.dir, sender=self._sender)
        out = det.run(alert=True, write=True)
        self.assertGreaterEqual(out["count"], 1)
        self.assertGreaterEqual(len(self.sent), 1)
        self.assertTrue((self.dir / "anomaly_log.json").exists())

    def test_log_ring_buffer_and_count(self):
        det = AnomalyDetector(data_dir=self.dir, sender=self._sender)
        from spa_core.monitoring.anomaly_detector import Anomaly
        anomalies = [Anomaly(kind=KIND_EQUITY_DROP, severity="critical",
                             subject="portfolio", message=f"m{i}")
                     for i in range(3)]
        det.log_anomalies(anomalies)
        doc = json.loads((self.dir / "anomaly_log.json").read_text())
        self.assertEqual(doc["count"], 3)
        self.assertEqual(len(doc["anomalies"]), 3)

    def test_sender_failure_does_not_crash(self):
        det = AnomalyDetector(data_dir=self.dir, sender=lambda t: (_ for _ in ()).throw(RuntimeError()))
        from spa_core.monitoring.anomaly_detector import Anomaly
        sent = det.alert([Anomaly(kind=KIND_EQUITY_DROP, severity="critical",
                                  subject="portfolio", message="x")])
        self.assertEqual(sent, 0)

    def test_main_check_exit_zero(self):
        self.assertEqual(main(["--check", "--data-dir", str(self.dir)]), 0)


if __name__ == "__main__":
    unittest.main()
