"""RTMR (ADR-053) S10.4 reaction + actions tests — ladder, de-risk-only property, paper apply."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from spa_core.monitoring import signal as S
from spa_core.monitoring import reaction as R
from spa_core.monitoring import actions as A
from spa_core.monitoring import posture as P

_CFG = {"systemic": {"warn_protocols_n": 3}, "cooldown_days": 3}


def _sig(source, scope, severity, staleness_ok=True):
    return S.make_signal(ts=1, source=source, scope=scope, metric="m", value=0.0,
                         severity=severity, threshold_crossed=(severity != S.INFO), staleness_ok=staleness_ok)


class TestLadder(unittest.TestCase):
    def test_peg_critical_full_exit(self) -> None:
        a = R.match_rule(_sig("peg", "x", S.CRITICAL), _CFG)
        self.assertEqual(a.kind, R.FULL_EXIT)

    def test_peg_warn_reduce(self) -> None:
        self.assertEqual(R.match_rule(_sig("peg", "x", S.WARN), _CFG).kind, R.REDUCE)

    def test_oracle_critical_freeze(self) -> None:
        self.assertEqual(R.match_rule(_sig("oracle", "x", S.CRITICAL), _CFG).kind, R.FREEZE)

    def test_stale_is_freeze_failclosed(self) -> None:
        self.assertEqual(R.match_rule(_sig("peg", "x", S.INFO, staleness_ok=False), _CFG).kind, R.FREEZE)

    def test_info_no_action(self) -> None:
        self.assertIsNone(R.match_rule(_sig("peg", "x", S.INFO), _CFG))

    def test_systemic_market_exit(self) -> None:
        sigs = [_sig("peg", "a", S.WARN), _sig("tvl", "b", S.WARN), _sig("oracle", "c", S.CRITICAL)]
        kinds = {a.kind for a in R.evaluate(sigs, _CFG)}
        self.assertIn(R.MARKET_EXIT, kinds)

    def test_dedupe_keeps_most_severe(self) -> None:
        sigs = [_sig("peg", "x", S.WARN), _sig("tvl", "x", S.CRITICAL)]  # same scope
        acts = [a for a in R.evaluate(sigs, _CFG) if a.scope == "x"]
        self.assertEqual(len(acts), 1)
        self.assertEqual(acts[0].kind, R.FULL_EXIT)

    def test_de_risk_only_property(self) -> None:
        # PROPERTY (§12): every action on any signal combination is de-risk-only.
        for src in ("peg", "tvl", "oracle", "liquidity", "weird"):
            for sev in (S.WARN, S.CRITICAL):
                for stale in (True, False):
                    for a in R.evaluate([_sig(src, "x", sev, stale)], _CFG):
                        self.assertTrue(a.is_de_risk_only())


class TestApply(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = Path(tempfile.mkdtemp())
        self._op, self._ol = P._POSTURE_PATH, A._LOG
        P._POSTURE_PATH = self._tmp / "posture.json"
        A._LOG = self._tmp / "reaction_log.json"

    def tearDown(self) -> None:
        P._POSTURE_PATH, A._LOG = self._op, self._ol

    def test_full_exit_caps_scope_to_zero(self) -> None:
        pos = A.apply_actions([R.Action(R.FULL_EXIT, "susde", reason="depeg")], now_ts=1000, cfg=_CFG, notify=False)
        self.assertEqual(P.cap_for(pos, "susde", now_ts=1001), 0.0)

    def test_reduce_caps_scope(self) -> None:
        pos = A.apply_actions([R.Action(R.REDUCE, "pendle", pct=0.3)], now_ts=1000, cfg=_CFG, notify=False)
        self.assertEqual(P.cap_for(pos, "pendle", now_ts=1001), 0.3)

    def test_market_exit_defensive(self) -> None:
        pos = A.apply_actions([R.Action(R.MARKET_EXIT, R.PORTFOLIO, reason="systemic")], now_ts=1000, cfg=_CFG, notify=False)
        self.assertTrue(P.portfolio_defensive(pos))

    def test_log_written(self) -> None:
        A.apply_actions([R.Action(R.FREEZE, "x")], now_ts=1000, cfg=_CFG, notify=False)
        import json
        log = json.loads(A._LOG.read_text())
        self.assertEqual(log[0]["mode"], "paper")


    def test_notify_only_on_posture_change(self) -> None:
        # applying the SAME exit twice must not re-notify (posture unchanged) — no Telegram spam
        calls = []
        import spa_core.monitoring.actions as AA
        orig = AA._notify
        AA._notify = lambda ts, applied: calls.append(applied)
        try:
            AA.apply_actions([R.Action(R.FULL_EXIT, "susde")], now_ts=1000, cfg=_CFG, notify=True)
            AA.apply_actions([R.Action(R.FULL_EXIT, "susde")], now_ts=1050, cfg=_CFG, notify=True)
        finally:
            AA._notify = orig
        self.assertEqual(len(calls), 1)  # notified once (first change), not on the re-apply

    def test_react_and_apply_paper(self) -> None:
        sigs = [_sig("peg", "usdc", S.CRITICAL)]
        pos = A.react_and_apply(sigs, now_ts=1000, cfg=_CFG, notify=False)
        self.assertEqual(P.cap_for(pos, "usdc", now_ts=1001), 0.0)  # exited, no capital moved (paper)


if __name__ == "__main__":
    unittest.main()
