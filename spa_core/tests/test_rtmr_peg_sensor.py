"""RTMR (ADR-053) S10.3b peg sensor tests — multisource depeg → config severity, fail-closed."""
from __future__ import annotations

import unittest

from spa_core.monitoring import signal as S
from spa_core.monitoring.sensors.peg import PegSensor, peg_severity, peg_config

_CFG = {"peg": {"reduce_at": 0.005, "exit_at": 0.010}, "min_quorum": 3, "max_spread": 0.02,
        "overrides": {"aave_v3:USDC": {"peg": {"exit_at": 0.008}}}}


def _providers(*prices):
    return {f"src{i}": (lambda v=v: v) for i, v in enumerate(prices)}


class TestPegSeverity(unittest.TestCase):
    def test_ladder(self) -> None:
        self.assertEqual(peg_severity(0.0006, _CFG["peg"])[0], S.INFO)
        self.assertEqual(peg_severity(0.006, _CFG["peg"])[0], S.WARN)
        self.assertEqual(peg_severity(0.02, _CFG["peg"])[0], S.CRITICAL)

    def test_override_tightens_exit(self) -> None:
        pcfg = peg_config(_CFG, "aave_v3:USDC")
        self.assertEqual(pcfg["exit_at"], 0.008)  # per-asset override applied


class TestPegSensor(unittest.TestCase):
    def test_on_peg_is_info(self) -> None:
        s = PegSensor({"x:USDC": _providers(1.000, 1.001, 0.999)})
        sig = s.poll(_CFG, 1000)[0]
        self.assertEqual(sig.severity, S.INFO)
        self.assertFalse(sig.threshold_crossed)

    def test_small_depeg_is_warn(self) -> None:
        s = PegSensor({"x:USDC": _providers(0.994, 0.993, 0.994)})  # ~0.6% depeg
        sig = s.poll(_CFG, 1000)[0]
        self.assertEqual(sig.severity, S.WARN)

    def test_big_depeg_is_critical(self) -> None:
        s = PegSensor({"x:USDC": _providers(0.97, 0.971, 0.969)})  # ~3% depeg
        sig = s.poll(_CFG, 1000)[0]
        self.assertTrue(sig.is_critical())
        self.assertTrue(sig.threshold_crossed)

    def test_quorum_fail_is_stale_critical(self) -> None:
        # only 2 fresh sources < min_quorum 3 → fail-closed critical
        s = PegSensor({"x:USDC": _providers(1.0, 1.0)})
        sig = s.poll(_CFG, 1000)[0]
        self.assertTrue(sig.is_critical())
        self.assertFalse(sig.staleness_ok)
        self.assertIn("quorum", sig.detail.get("reason", ""))

    def test_disagreement_is_stale_critical(self) -> None:
        s = PegSensor({"x:USDC": _providers(1.00, 1.00, 1.10)})  # split feed
        sig = s.poll(_CFG, 1000)[0]
        self.assertTrue(sig.is_critical())
        self.assertFalse(sig.staleness_ok)

    def test_source_attr_for_registry(self) -> None:
        self.assertEqual(PegSensor({}).source, "peg")

    def test_plugs_into_sense_loop(self) -> None:
        from spa_core.monitoring import sense_loop as SL
        import tempfile
        from pathlib import Path
        orig = (SL._LATEST, SL._LOG, SL._HEARTBEAT)
        try:
            tmp = Path(tempfile.mkdtemp())
            SL._LATEST, SL._LOG, SL._HEARTBEAT = tmp/"l.json", tmp/"log.json", tmp/"hb.json"
            s = PegSensor({"x:USDC": _providers(0.97, 0.971, 0.969)})
            sigs = SL.run_tick([s], _CFG, now_ts=1000)
            self.assertTrue(any(x.is_critical() for x in sigs))
        finally:
            SL._LATEST, SL._LOG, SL._HEARTBEAT = orig


if __name__ == "__main__":
    unittest.main()
