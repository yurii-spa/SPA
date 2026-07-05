"""RTMR (ADR-053) S10.3b tvl/oracle/liquidity sensor tests — thresholds + fail-closed."""
from __future__ import annotations

import unittest

from spa_core.monitoring import signal as S
from spa_core.monitoring.sensors.tvl import TvlSensor
from spa_core.monitoring.sensors.oracle import OracleSensor
from spa_core.monitoring.sensors.liquidity import LiquiditySensor

_CFG = {"min_quorum": 3, "max_spread": 0.10,
        "tvl": {"drop_24h_exit": 0.20, "drop_1h_exit": 0.10},
        "oracle": {"max_staleness_sec": 90, "max_dev": 0.01},
        "liquidity": {"min_liq_ratio": 2.0}}


def _p(*vals):
    return {f"s{i}": (lambda v=v: v) for i, v in enumerate(vals)}


class TestTvl(unittest.TestCase):
    def test_stable_tvl_info(self) -> None:
        s = TvlSensor({"m": _p(100.0, 100.0, 100.0)}, {"m": (100.0, 100.0)})
        self.assertEqual(s.poll(_CFG, 1)[0].severity, S.INFO)

    def test_big_24h_drop_critical(self) -> None:
        s = TvlSensor({"m": _p(70.0, 70.0, 70.0)}, {"m": (95.0, 100.0)})  # -30% vs 24h
        sig = s.poll(_CFG, 1)[0]
        self.assertTrue(sig.is_critical())

    def test_missing_history_failclosed(self) -> None:
        s = TvlSensor({"m": _p(70.0, 70.0, 70.0)}, {})
        self.assertFalse(s.poll(_CFG, 1)[0].staleness_ok)


class TestOracle(unittest.TestCase):
    def test_healthy_oracle_info(self) -> None:
        s = OracleSensor({"x": {"oracle": lambda: (1.000, 1000), "market": _p(1.0, 1.001, 0.999)}})
        self.assertEqual(s.poll(_CFG, 1010)[0].severity, S.INFO)  # 10s stale, 0 dev

    def test_stale_oracle_critical(self) -> None:
        s = OracleSensor({"x": {"oracle": lambda: (1.0, 1000), "market": _p(1.0, 1.0, 1.0)}})
        self.assertTrue(s.poll(_CFG, 2000)[0].is_critical())  # 1000s stale > 90

    def test_deviation_critical(self) -> None:
        s = OracleSensor({"x": {"oracle": lambda: (1.05, 1000), "market": _p(1.0, 1.0, 1.0)}})
        self.assertTrue(s.poll(_CFG, 1010)[0].is_critical())  # 5% dev > 1%

    def test_oracle_unreadable_failclosed(self) -> None:
        def boom():
            raise RuntimeError("down")
        s = OracleSensor({"x": {"oracle": boom, "market": _p(1.0, 1.0, 1.0)}})
        self.assertFalse(s.poll(_CFG, 1010)[0].staleness_ok)


class TestLiquidity(unittest.TestCase):
    def test_deep_liquidity_info(self) -> None:
        s = LiquiditySensor({"x": _p(500.0, 500.0, 500.0)}, {"x": 100.0})  # ratio 5 > 2
        self.assertEqual(s.poll(_CFG, 1)[0].severity, S.INFO)

    def test_thin_liquidity_warn(self) -> None:
        s = LiquiditySensor({"x": _p(150.0, 150.0, 150.0)}, {"x": 100.0})  # ratio 1.5 < 2
        self.assertEqual(s.poll(_CFG, 1)[0].severity, S.WARN)

    def test_very_thin_critical(self) -> None:
        s = LiquiditySensor({"x": _p(50.0, 50.0, 50.0)}, {"x": 100.0})  # ratio 0.5 < 1.0
        self.assertTrue(s.poll(_CFG, 1)[0].is_critical())

    def test_unknown_position_failclosed(self) -> None:
        s = LiquiditySensor({"x": _p(500.0, 500.0, 500.0)}, {})
        self.assertFalse(s.poll(_CFG, 1)[0].staleness_ok)


if __name__ == "__main__":
    unittest.main()
