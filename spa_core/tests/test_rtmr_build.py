"""RTMR (ADR-053) sensor assembly tests — wiring only (no network)."""
from __future__ import annotations

import unittest

from spa_core.monitoring.sensors.build import build_liquidity_sensor, build_peg_sensor
from spa_core.monitoring.sensors.peg import PegSensor
from spa_core.utils.errors import SPAError


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


class TestLiquidityAllCashSkip(unittest.TestCase):
    """All-cash book → the liquidity sensor is SKIPPED, never registered empty.

    Two regressions guarded at once:
      * incident 2026-07 — an empty liquidity sensor trips the sense-loop's
        "sensor produced no signal" stale guard every tick → scope FROZEN →
        the portfolio can never leave DEFENSIVE;
      * MP-1467 SPAError migration — the refusal now travels as ``SourceError``
        (SPAError family) instead of a bare ``RuntimeError``. The register loop
        catches broad ``Exception``, so the skip must stay silent-but-logged and
        must NOT propagate out of ``register_default_sensors``.
    """

    def _empty_depth(self):
        """Patch the provider to report an all-cash book; returns a restore fn."""
        from spa_core.monitoring.sensors import liquidity_providers as LP
        orig = LP.liquidity_inputs
        LP.liquidity_inputs = lambda: ({}, {})
        return lambda: setattr(LP, "liquidity_inputs", orig)

    def test_build_liquidity_sensor_refuses_when_no_positions(self) -> None:
        restore = self._empty_depth()
        try:
            with self.assertRaises(SPAError):   # SourceError <: SPAError <: Exception
                build_liquidity_sensor()
        finally:
            restore()

    def test_register_default_sensors_survives_the_refusal(self) -> None:
        from spa_core.monitoring import sense_loop as SL
        restore = self._empty_depth()
        saved = list(SL._SENSORS)
        SL._SENSORS.clear()
        try:
            from spa_core.monitoring.sensors.build import register_default_sensors
            srcs = register_default_sensors()          # must not raise
            self.assertIn("peg", srcs)                 # other sensors still wired
            self.assertNotIn("liquidity", srcs)        # and the empty one is skipped
        finally:
            SL._SENSORS[:] = saved
            restore()


if __name__ == "__main__":
    unittest.main()
