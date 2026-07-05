"""RTMR (ADR-053) sensor assembly tests — wiring only (no network)."""
from __future__ import annotations

import unittest

from spa_core.monitoring.sensors.build import build_peg_sensor
from spa_core.monitoring.sensors.peg import PegSensor


class TestBuild(unittest.TestCase):
    def test_build_peg_sensor_type_and_scopes(self) -> None:
        s = build_peg_sensor(["USDC", "DAI"])
        self.assertIsInstance(s, PegSensor)
        self.assertEqual(set(s._providers.keys()), {"USDC", "DAI"})
        self.assertEqual(s._peg["USDC"], 1.0)

    def test_unknown_asset_skipped(self) -> None:
        s = build_peg_sensor(["USDC", "NOTACOIN"])
        self.assertNotIn("NOTACOIN", s._providers)  # no providers → not wired

    def test_register_default_sensors(self) -> None:
        from spa_core.monitoring import sense_loop as SL
        saved = list(SL._SENSORS)
        SL._SENSORS.clear()
        try:
            from spa_core.monitoring.sensors.build import register_default_sensors
            srcs = register_default_sensors()
            self.assertIn("peg", srcs)
        finally:
            SL._SENSORS[:] = saved


if __name__ == "__main__":
    unittest.main()
