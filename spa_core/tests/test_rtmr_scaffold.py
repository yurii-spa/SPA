"""RTMR (ADR-053) S10.1 scaffold tests — RiskSignal fail-closed + posture honor.

Locks the two contracts the whole architecture rests on:
  * fail-closed: stale/missing data ⇒ critical severity (never silence).
  * de-risk-only posture: an active posture entry can only REDUCE exposure (cap ≤ what's
    held; EXITED ⇒ 0), never raise it — and the rebalance-loop's query helpers reflect that.
"""
from __future__ import annotations

import unittest

from spa_core.monitoring import posture as P
from spa_core.monitoring import signal as S


class TestRiskSignalFailClosed(unittest.TestCase):
    def _mk(self, **kw):
        base = dict(
            ts=1000, source="peg", scope="aave_v3:USDC", metric="depeg_pct",
            value=0.001, severity="info", threshold_crossed=False, staleness_ok=True,
        )
        base.update(kw)
        return S.make_signal(**base)

    def test_stale_forces_critical(self) -> None:
        sig = self._mk(severity="info", staleness_ok=False)
        self.assertEqual(sig.severity, S.CRITICAL)  # value/severity irrelevant when stale

    def test_unknown_severity_is_critical(self) -> None:
        self.assertEqual(self._mk(severity="whatever").severity, S.CRITICAL)

    def test_fresh_keeps_severity(self) -> None:
        self.assertEqual(self._mk(severity="warn", staleness_ok=True).severity, S.WARN)

    def test_stale_signal_helper_is_critical(self) -> None:
        sig = S.stale_signal(ts=5, source="tvl", scope="morpho", reason="feed down")
        self.assertTrue(sig.is_critical())
        self.assertFalse(sig.staleness_ok)
        self.assertTrue(sig.is_actionable())

    def test_signal_is_immutable(self) -> None:
        sig = self._mk()
        with self.assertRaises(Exception):
            sig.value = 9.9  # frozen dataclass

    def test_dict_roundtrip_reapplies_failclosed(self) -> None:
        d = S.to_dict(self._mk(severity="info", staleness_ok=False))
        # even if a persisted dict claims 'info', re-hydration keeps it critical
        d["severity"] = "info"
        self.assertEqual(S.from_dict(d).severity, S.CRITICAL)

    def test_max_severity_counts_stale_as_critical(self) -> None:
        sigs = [self._mk(severity="info"), self._mk(severity="info", staleness_ok=False)]
        self.assertEqual(S.max_severity(sigs), S.CRITICAL)

    def test_max_severity_empty_is_info(self) -> None:
        self.assertEqual(S.max_severity([]), S.INFO)


class TestPostureHonor(unittest.TestCase):
    def test_empty_posture_is_normal(self) -> None:
        pos = P.load_posture()
        self.assertEqual(P.entry_state(pos, "anything", now_ts=100), P.NORMAL)

    def test_exited_caps_to_zero(self) -> None:
        pos = P.set_entry(dict(P._EMPTY, entries={}), scope="susde", state=P.EXITED,
                          now_ts=100, until_ts=None, reason="depeg")
        self.assertTrue(P.is_exited(pos, "susde", now_ts=200))
        self.assertEqual(P.cap_for(pos, "susde", now_ts=200), 0.0)

    def test_capped_returns_cap(self) -> None:
        pos = P.set_entry(dict(P._EMPTY, entries={}), scope="pendle", state=P.CAPPED,
                          now_ts=100, cap=0.1, reason="liquidity")
        self.assertEqual(P.cap_for(pos, "pendle", now_ts=150), 0.1)

    def test_frozen_is_frozen_not_exited(self) -> None:
        pos = P.set_entry(dict(P._EMPTY, entries={}), scope="engine_b", state=P.FROZEN, now_ts=100)
        self.assertTrue(P.is_frozen(pos, "engine_b", now_ts=150))
        self.assertFalse(P.is_exited(pos, "engine_b", now_ts=150))

    def test_until_ts_expiry_reverts_to_normal(self) -> None:
        pos = P.set_entry(dict(P._EMPTY, entries={}), scope="frax", state=P.EXITED,
                          now_ts=100, until_ts=200)
        self.assertTrue(P.is_exited(pos, "frax", now_ts=150))       # active
        self.assertEqual(P.entry_state(pos, "frax", now_ts=250), P.NORMAL)  # expired

    def test_de_risk_only_property(self) -> None:
        # cap_for must NEVER return >1 (raising exposure) for any state.
        for st, cap in ((P.EXITED, None), (P.CAPPED, 0.2), (P.FROZEN, None), (P.DEFENSIVE, None)):
            pos = P.set_entry(dict(P._EMPTY, entries={}), scope="x", state=st, now_ts=1, cap=cap)
            c = P.cap_for(pos, "x", now_ts=2)
            self.assertTrue(c is None or 0.0 <= c <= 1.0)

    def test_portfolio_defensive(self) -> None:
        pos = P.set_portfolio(dict(P._EMPTY, entries={}), state=P.DEFENSIVE, reason="systemic")
        self.assertTrue(P.portfolio_defensive(pos))

    def test_save_load_roundtrip(self) -> None:
        import tempfile
        from pathlib import Path
        orig = P._POSTURE_PATH
        try:
            P._POSTURE_PATH = Path(tempfile.mkdtemp()) / "risk_posture.json"
            pos = P.set_entry(dict(P._EMPTY, entries={}), scope="aave_v3", state=P.CAPPED,
                              now_ts=10, cap=0.3)
            P.save_posture(pos, now_ts=10)
            loaded = P.load_posture()
            self.assertEqual(P.cap_for(loaded, "aave_v3", now_ts=11), 0.3)
        finally:
            P._POSTURE_PATH = orig

    def test_unknown_state_rejected(self) -> None:
        with self.assertRaises(ValueError):
            P.set_entry(dict(P._EMPTY, entries={}), scope="x", state="YOLO", now_ts=1)


if __name__ == "__main__":
    unittest.main()
