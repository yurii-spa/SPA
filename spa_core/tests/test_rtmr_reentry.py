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


if __name__ == "__main__":
    unittest.main()
