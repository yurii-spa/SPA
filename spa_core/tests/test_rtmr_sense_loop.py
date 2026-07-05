"""RTMR (ADR-053) S10.2 sense-loop tests — fail-closed on sensor death + persist + heartbeat."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from spa_core.monitoring import sense_loop as SL
from spa_core.monitoring import signal as S


def _good_sensor(cfg, now_ts):
    return [S.make_signal(ts=now_ts, source="peg", scope="aave_v3:USDC", metric="depeg_pct",
                          value=0.001, severity="info", threshold_crossed=False, staleness_ok=True)]
_good_sensor.source = "peg"


def _raising_sensor(cfg, now_ts):
    raise RuntimeError("boom")
_raising_sensor.source = "tvl"


def _empty_sensor(cfg, now_ts):
    return []
_empty_sensor.source = "oracle"


class TestSenseLoop(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = Path(tempfile.mkdtemp())
        self._orig = (SL._LATEST, SL._LOG, SL._HEARTBEAT)
        SL._LATEST = self._tmp / "latest.json"
        SL._LOG = self._tmp / "signal_log.json"
        SL._HEARTBEAT = self._tmp / "heartbeat.json"

    def tearDown(self) -> None:
        SL._LATEST, SL._LOG, SL._HEARTBEAT = self._orig

    def test_good_sensor_signal_collected(self) -> None:
        sigs = SL.run_tick([_good_sensor], {}, now_ts=1000)
        self.assertEqual(len(sigs), 1)
        self.assertEqual(sigs[0].source, "peg")

    def test_raising_sensor_becomes_critical(self) -> None:
        # fail-closed: a sensor that raises must produce a critical signal, not crash the loop
        sigs = SL.run_tick([_raising_sensor], {}, now_ts=1000)
        self.assertEqual(len(sigs), 1)
        self.assertTrue(sigs[0].is_critical())
        self.assertFalse(sigs[0].staleness_ok)
        self.assertEqual(sigs[0].source, "tvl")

    def test_empty_sensor_becomes_critical(self) -> None:
        # a blind sensor (no signal) is also critical — silence never reads as OK
        sigs = SL.run_tick([_empty_sensor], {}, now_ts=1000)
        self.assertTrue(sigs[0].is_critical())

    def test_mixed_batch_max_severity_critical(self) -> None:
        SL.run_tick([_good_sensor, _raising_sensor], {}, now_ts=1000)
        snap = json.loads(SL._LATEST.read_text())
        self.assertEqual(snap["max_severity"], S.CRITICAL)  # one dead sensor drags the batch to critical
        self.assertEqual(snap["count"], 2)

    def test_persists_latest_and_log(self) -> None:
        SL.run_tick([_good_sensor], {}, now_ts=1000)
        SL.run_tick([_good_sensor], {}, now_ts=1045)
        self.assertTrue(SL._LATEST.exists())
        log = json.loads(SL._LOG.read_text())
        self.assertEqual(len(log), 2)  # append-only

    def test_heartbeat_written(self) -> None:
        SL.run_tick([_good_sensor], {}, now_ts=1000)
        self.assertEqual(SL.heartbeat_age_sec(now_ts=1010), 10.0)

    def test_heartbeat_missing_is_none(self) -> None:
        self.assertIsNone(SL.heartbeat_age_sec(now_ts=1))  # no heartbeat yet → None (caller treats as stale)


class TestSensorRegistry(unittest.TestCase):
    def setUp(self) -> None:
        self._saved = list(SL._SENSORS)
        SL._SENSORS.clear()

    def tearDown(self) -> None:
        SL._SENSORS[:] = self._saved

    def test_register_idempotent_by_source(self) -> None:
        SL.register_sensor(_good_sensor)
        SL.register_sensor(_good_sensor)  # same .source → replace, not duplicate
        self.assertEqual(SL.registered_sources().count("peg"), 1)

    def test_register_distinct_sources(self) -> None:
        SL.register_sensor(_good_sensor)
        SL.register_sensor(_raising_sensor)
        self.assertEqual(set(SL.registered_sources()), {"peg", "tvl"})


if __name__ == "__main__":
    unittest.main()
