"""RTMR (ADR-053) S10.5a posture-gate tests — rebalance honors posture, de-risk-only clamp."""
from __future__ import annotations

import unittest

from spa_core.monitoring import posture as P
from spa_core.monitoring import posture_gate as G

_TARGET = {"aave_v3": 0.40, "susde": 0.20, "pendle": 0.20, "frax": 0.20}


def _pos():
    return dict(P._EMPTY, entries={})


class TestPostureGate(unittest.TestCase):
    def test_no_posture_unchanged(self) -> None:
        out, notes = G.apply_posture(_TARGET, _pos(), now_ts=100)
        self.assertEqual(out, _TARGET)
        self.assertEqual(notes, [])

    def test_exited_scope_zeroed(self) -> None:
        pos = P.set_entry(_pos(), scope="susde", state=P.EXITED, now_ts=1, until_ts=None)
        out, _ = G.apply_posture(_TARGET, pos, now_ts=100)
        self.assertEqual(out["susde"], 0.0)
        self.assertEqual(out["aave_v3"], 0.40)  # others untouched

    def test_capped_scope_clamped(self) -> None:
        pos = P.set_entry(_pos(), scope="pendle", state=P.CAPPED, now_ts=1, cap=0.05)
        out, _ = G.apply_posture(_TARGET, pos, now_ts=100)
        self.assertEqual(out["pendle"], 0.05)

    def test_cap_never_raises(self) -> None:
        # a cap ABOVE the target must NOT raise the weight (de-risk-only)
        pos = P.set_entry(_pos(), scope="frax", state=P.CAPPED, now_ts=1, cap=0.9)
        out, _ = G.apply_posture(_TARGET, pos, now_ts=100)
        self.assertEqual(out["frax"], 0.20)  # min(0.20, 0.9) = 0.20, unchanged

    def test_defensive_all_cash(self) -> None:
        pos = P.set_portfolio(_pos(), state=P.DEFENSIVE, reason="systemic")
        out, notes = G.apply_posture(_TARGET, pos, now_ts=100)
        self.assertEqual(set(out.values()), {0.0})
        self.assertTrue(any("all-cash" in n for n in notes))

    def test_de_risk_only_never_increases(self) -> None:
        # property: for any single posture entry, no output weight exceeds its input
        for st, cap in ((P.EXITED, None), (P.CAPPED, 0.1), (P.CAPPED, 0.9), (P.FROZEN, None)):
            pos = P.set_entry(_pos(), scope="pendle", state=st, now_ts=1, cap=cap)
            out, _ = G.apply_posture(_TARGET, pos, now_ts=100)
            for k in _TARGET:
                self.assertLessEqual(out[k], _TARGET[k] + 1e-9)

    def test_would_change(self) -> None:
        self.assertFalse(G.would_change(_TARGET, _pos(), now_ts=100))
        pos = P.set_entry(_pos(), scope="susde", state=P.EXITED, now_ts=1)
        self.assertTrue(G.would_change(_TARGET, pos, now_ts=100))


if __name__ == "__main__":
    unittest.main()
