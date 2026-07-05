"""RTMR (ADR-053) staleness hysteresis — transient stale ignored, persistent stale de-risks."""
from __future__ import annotations

import unittest

from spa_core.monitoring import rtmr_service as SVC
from spa_core.monitoring import signal as S

_CFG = {"stale_ticks_before_derisk": 3}


class TestHysteresis(unittest.TestCase):
    def setUp(self) -> None:
        SVC._STALE_STREAK.clear()

    def _stale(self):
        return S.stale_signal(ts=1, source="tvl", scope="aave_v3", reason="rate-limit")

    def test_transient_stale_not_actionable(self) -> None:
        for _ in range(2):
            out = SVC._debounce_stale([self._stale()], _CFG)
            self.assertFalse(out[0].is_actionable())      # ticks 1-2: pending, no de-risk
            self.assertEqual(out[0].severity, S.INFO)

    def test_persistent_stale_becomes_critical(self) -> None:
        for _ in range(2):
            SVC._debounce_stale([self._stale()], _CFG)
        out = SVC._debounce_stale([self._stale()], _CFG)  # 3rd → persistent
        self.assertTrue(out[0].is_critical())
        self.assertTrue(out[0].is_actionable())

    def test_recovery_resets_streak(self) -> None:
        for _ in range(2):
            SVC._debounce_stale([self._stale()], _CFG)
        fresh = S.make_signal(ts=5, source="tvl", scope="aave_v3", metric="m", value=0.0,
                              severity="info", threshold_crossed=False, staleness_ok=True)
        SVC._debounce_stale([fresh], _CFG)
        self.assertNotIn(("tvl", "aave_v3"), SVC._STALE_STREAK)
        # a new stale after recovery starts the streak over (not immediately critical)
        out = SVC._debounce_stale([self._stale()], _CFG)
        self.assertFalse(out[0].is_actionable())

    def test_fresh_signal_passes_through(self) -> None:
        warn = S.make_signal(ts=1, source="peg", scope="USDC", metric="depeg_pct", value=0.006,
                             severity="warn", threshold_crossed=True, staleness_ok=True)
        out = SVC._debounce_stale([warn], _CFG)
        self.assertEqual(out[0].severity, S.WARN)  # real fresh signals are untouched


if __name__ == "__main__":
    unittest.main()
