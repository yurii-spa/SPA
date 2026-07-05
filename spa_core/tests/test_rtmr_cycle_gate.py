"""RTMR (ADR-053) S10.5b — apply_rtmr_posture_gate (additive; cycle_runner does NOT call it yet)."""
from __future__ import annotations

import unittest

from spa_core.monitoring import posture as P
from spa_core.paper_trading.cycle_gates import apply_rtmr_posture_gate

_CAP = 100_000.0


def _pos():
    return dict(P._EMPTY, entries={})


class TestRtmrPostureGate(unittest.TestCase):
    def test_normal_posture_noop(self) -> None:
        t = {"aave_v3": 40000.0, "compound_v3": 20000.0}
        out = apply_rtmr_posture_gate(dict(t), capital_usd=_CAP, now_ts=100, notes=[], posture=_pos())
        self.assertEqual(out, t)

    def test_exited_scope_zeroed(self) -> None:
        pos = P.set_entry(_pos(), scope="aave_v3", state=P.EXITED, now_ts=1, until_ts=None)
        out = apply_rtmr_posture_gate({"aave_v3": 40000.0}, capital_usd=_CAP, now_ts=100, notes=[], posture=pos)
        self.assertEqual(out["aave_v3"], 0.0)

    def test_capped_scope_clamped(self) -> None:
        pos = P.set_entry(_pos(), scope="compound_v3", state=P.CAPPED, now_ts=1, cap=0.05)
        out = apply_rtmr_posture_gate({"compound_v3": 20000.0}, capital_usd=_CAP, now_ts=100, notes=[], posture=pos)
        self.assertEqual(out["compound_v3"], 5000.0)  # 5% × 100k

    def test_cap_above_target_no_increase(self) -> None:
        pos = P.set_entry(_pos(), scope="aave_v3", state=P.CAPPED, now_ts=1, cap=0.9)
        out = apply_rtmr_posture_gate({"aave_v3": 40000.0}, capital_usd=_CAP, now_ts=100, notes=[], posture=pos)
        self.assertEqual(out["aave_v3"], 40000.0)  # min(40k, 90k) — not raised

    def test_defensive_all_cash(self) -> None:
        pos = P.set_portfolio(_pos(), state=P.DEFENSIVE, reason="systemic")
        out = apply_rtmr_posture_gate({"aave_v3": 40000.0, "compound_v3": 20000.0},
                                      capital_usd=_CAP, now_ts=100, notes=[], posture=pos)
        self.assertEqual(set(out.values()), {0.0})

    def test_de_risk_only_property(self) -> None:
        t = {"aave_v3": 40000.0, "compound_v3": 20000.0}
        for st, cap in ((P.EXITED, None), (P.CAPPED, 0.1), (P.CAPPED, 0.99), (P.FROZEN, None)):
            pos = P.set_entry(_pos(), scope="aave_v3", state=st, now_ts=1, cap=cap)
            out = apply_rtmr_posture_gate(dict(t), capital_usd=_CAP, now_ts=100, notes=[], posture=pos)
            for k in t:
                self.assertLessEqual(out[k], t[k] + 1e-6)  # never increases


    def test_asset_depeg_derisks_asset_protocols(self) -> None:
        # a USDC posture must clamp USDC-denominated protocols, leave others intact
        pos = P.set_entry(_pos(), scope="USDC", state=P.EXITED, now_ts=1)
        out = apply_rtmr_posture_gate({"aave_v3": 40000.0, "frax": 10000.0},
                                      capital_usd=_CAP, now_ts=100, notes=[], posture=pos)
        self.assertEqual(out["aave_v3"], 0.0)     # USDC → exited
        self.assertEqual(out["frax"], 10000.0)    # FRAX → untouched

    def test_tighter_of_protocol_and_asset_cap(self) -> None:
        # protocol CAPPED 0.2 + asset CAPPED 0.05 → the tighter (0.05) wins
        pos = P.set_entry(_pos(), scope="aave_v3", state=P.CAPPED, now_ts=1, cap=0.2)
        pos = P.set_entry(pos, scope="USDC", state=P.CAPPED, now_ts=1, cap=0.05)
        out = apply_rtmr_posture_gate({"aave_v3": 40000.0}, capital_usd=_CAP, now_ts=100, notes=[], posture=pos)
        self.assertEqual(out["aave_v3"], 5000.0)  # min(0.2, 0.05) × 100k


if __name__ == "__main__":
    unittest.main()
