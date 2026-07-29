"""RTMR (ADR-053) posture re-entry / self-clearing tests."""
from __future__ import annotations

import unittest

from spa_core.monitoring import posture as P


class TestReconcile(unittest.TestCase):
    def _frozen(self, scope="morpho_blue"):
        return P.set_entry(dict(P._EMPTY, entries={}), scope=scope, state=P.FROZEN, now_ts=1, reason="stale")

    def test_clears_after_n_clean_ticks(self) -> None:
        pos = self._frozen()
        for i in range(1, 4):
            pos, cleared = P.reconcile_recovered(pos, {"morpho_blue": "info"}, now_ts=i, reentry_periods=4)
            self.assertEqual(cleared, [])
        pos, cleared = P.reconcile_recovered(pos, {"morpho_blue": "info"}, now_ts=4, reentry_periods=4)
        self.assertEqual(cleared, ["morpho_blue"])
        self.assertEqual(len(pos["entries"]), 0)

    def test_critical_resets_counter(self) -> None:
        pos = P.set_entry(dict(P._EMPTY, entries={}), scope="x", state=P.EXITED, now_ts=1)
        pos, _ = P.reconcile_recovered(pos, {"x": "info"}, now_ts=1, reentry_periods=4)   # rc=1
        pos, _ = P.reconcile_recovered(pos, {"x": "critical"}, now_ts=2, reentry_periods=4)  # reset
        self.assertEqual(pos["entries"]["x"]["recover_count"], 0)

    def test_warn_holds_derisk(self) -> None:
        pos = self._frozen()
        for i in range(1, 10):
            pos, cleared = P.reconcile_recovered(pos, {"morpho_blue": "warn"}, now_ts=i, reentry_periods=4)
        self.assertIn("morpho_blue", pos["entries"])  # never cleared while warn

    def test_absent_scope_treated_as_recovered(self) -> None:
        pos = self._frozen()
        for i in range(1, 5):
            pos, cleared = P.reconcile_recovered(pos, {}, now_ts=i, reentry_periods=4)  # no signal = clean
        self.assertEqual(len(pos["entries"]), 0)

    def test_defensive_lifts_after_clean(self) -> None:
        pos = P.set_portfolio(dict(P._EMPTY, entries={}), state=P.DEFENSIVE, reason="systemic")
        for i in range(1, 5):
            pos, cleared = P.reconcile_recovered(pos, {"a": "info"}, now_ts=i, reentry_periods=4)
        self.assertEqual(pos["portfolio"], P.NORMAL)


class TestReconcilePersistence(unittest.TestCase):
    """Incident 2026-07: rtmr_service saved the posture only `if cleared`, but clearing needs
    recover_count to ACCUMULATE across ticks — and the counter lives in the posture file that is
    re-loaded every tick. Unsaved bumps were discarded, every tick restarted from count=None, and
    self-clear was unreachable: the portfolio stayed DEFENSIVE forever. The service must persist
    the posture on EVERY reconcile change (reconcile_and_persist)."""

    def _run_ticks(self, n: int) -> list:
        import tempfile
        from pathlib import Path
        from unittest import mock
        from spa_core.monitoring import rtmr_service as R
        cleared_all: list = []
        with tempfile.TemporaryDirectory() as td:
            with mock.patch.object(P, "_POSTURE_PATH", Path(td) / "risk_posture.json"):
                seed = P.set_entry(dict(P._EMPTY, entries={}), scope="tvl", state=P.FROZEN,
                                   now_ts=0, until_ts=None, reason="stale/blind tvl sensor")
                P.save_posture(seed, now_ts=0)
                for i in range(1, n + 1):
                    cleared_all += R.reconcile_and_persist({}, now_ts=i,
                                                           cfg={"peg": {"reentry_periods": 4}})
        return cleared_all

    def test_counters_persist_across_ticks_and_clear(self) -> None:
        # 4 clean ticks with NO in-memory state carried between calls → must clear via the FILE
        self.assertIn("tvl", self._run_ticks(4))

    def test_no_clear_before_reentry_periods(self) -> None:
        self.assertEqual(self._run_ticks(3), [])


if __name__ == "__main__":
    unittest.main()
