"""
spa_core/tests/test_strategy_lab_promotion.py — tests for the Strategy-Lab PROMOTION ENGINE
(spa_core/strategy_lab/promotion.py).

NOTE on the filename: the prompt asked for test_promotion_engine.py, but that name is ALREADY
taken by the unrelated spa_core/paper_trading/promotion_engine.py test suite. To keep those
green and avoid a module-name clash, the lab promotion tests live here under the strategy_lab
naming convention (test_strategy_lab_*.py).

Covers:
  - score_sleeve criteria + verdicts: PAPER_CANDIDATE / BACKTEST_PASS / REJECT
  - data-gap kill tolerated vs real kill rejected
  - thresholds sourced from config (not hardcoded)
  - determinism
  - build_report structure + atomic write

stdlib only. Deterministic. LLM-forbidden gate logic.
"""
from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path

from spa_core.strategy_lab import promotion
from spa_core.strategy_lab.promotion import (
    STAGE_BACKTEST_PASS,
    STAGE_PAPER_CANDIDATE,
    STAGE_REJECT,
    build_report,
    promotion_config,
    promotion_verdict,
    score_sleeve,
)


# ── fixtures ─────────────────────────────────────────────────────────────────────────────────
def _result(
    sid="x",
    mandate="stable",
    net_apy=4.0,
    max_dd=0.0,
    beats=True,
    kill=None,
):
    return {
        "id": sid,
        "mandate": mandate,
        "metrics": {
            "net_apy_pct": net_apy,
            "max_drawdown_pct": max_dd,
            "beats_rwa_floor": beats,
        },
        "kill": kill,
    }


def _wf_ok(consistency=80.0, robust=True, max_aum=8_000_000.0):
    return {
        "walk_forward": {"status": "ok", "consistency_pct": consistency, "wf_robust": robust},
        "capacity": {"status": "ok", "max_safe_aum_usd": max_aum},
    }


# walk_forward arg to score_sleeve is the per-sleeve block carrying BOTH walk_forward + capacity.
def _wf_block(consistency=80.0, robust=True, max_aum=8_000_000.0):
    b = _wf_ok(consistency, robust, max_aum)
    # score_sleeve reads .get("status"/"consistency_pct"/"wf_robust") at the TOP level for WF,
    # and .get("capacity") for AUM → flatten the walk_forward sub-dict to the top level.
    return {
        "status": "ok",
        "consistency_pct": consistency,
        "wf_robust": robust,
        "capacity": {"status": "ok", "max_safe_aum_usd": max_aum},
    }


_THR = {
    "max_drawdown_band_pct": 15.0,
    "wf_consistency_min_pct": 70.0,
    "min_capacity_aum_usd": 1_000_000.0,
    "min_net_apy_pct": 0.0,
    "data_gap_kill_substrings": ["missing/invalid", "fail-closed (step raised)", "missing"],
}


# ── score + verdict ────────────────────────────────────────────────────────────────────────────
class TestScoreVerdict(unittest.TestCase):
    def _verdict(self, result, wf=None):
        s = score_sleeve(result, walk_forward=wf, promotion=_THR)
        return s, promotion_verdict(s)

    def test_paper_candidate(self):
        """Beats floor + low DD + WF-robust + capacity-sufficient → PAPER_CANDIDATE."""
        s, v = self._verdict(
            _result(net_apy=5.0, max_dd=2.0, beats=True), wf=_wf_block()
        )
        self.assertEqual(v["stage"], STAGE_PAPER_CANDIDATE)
        self.assertEqual(s["score"], 6)

    def test_backtest_pass_when_no_wf(self):
        """Backtest winner with no WF/capacity evidence → BACKTEST_PASS (PENDING above)."""
        s, v = self._verdict(_result(net_apy=4.0, max_dd=0.0, beats=True), wf=None)
        self.assertEqual(v["stage"], STAGE_BACKTEST_PASS)
        self.assertTrue(s["criteria"]["walk_forward_robust"]["pending"])
        self.assertTrue(s["criteria"]["capacity_sufficient"]["pending"])

    def test_reject_below_floor(self):
        """Does not beat the floor → REJECT regardless of WF."""
        _, v = self._verdict(_result(beats=False, net_apy=0.4), wf=_wf_block())
        self.assertEqual(v["stage"], STAGE_REJECT)

    def test_reject_real_kill(self):
        """A real (drawdown) kill → REJECT even if it nominally beat the floor."""
        kill = {"reason": "drawdown 30.05% > kill 25.00%"}
        _, v = self._verdict(
            _result(beats=True, net_apy=5.0, max_dd=30.0, kill=kill), wf=_wf_block()
        )
        self.assertEqual(v["stage"], STAGE_REJECT)

    def test_data_gap_kill_tolerated(self):
        """A DATA-GAP kill (missing feed value) is tolerated — not_killed_real passes."""
        kill = {"reason": "fail-closed: lrt_ratio('eeth',) missing/invalid on 2024-08-30"}
        s = score_sleeve(_result(beats=True, net_apy=4.0, max_dd=2.0, kill=kill),
                         walk_forward=_wf_block(), promotion=_THR)
        self.assertTrue(s["kill_is_data_gap"])
        self.assertTrue(s["criteria"]["not_killed_real"]["pass"])
        self.assertEqual(promotion_verdict(s)["stage"], STAGE_PAPER_CANDIDATE)

    def test_reject_negative_apy(self):
        """Non-positive net APY fails positive_net_apy → REJECT."""
        _, v = self._verdict(_result(beats=False, net_apy=-2.0, max_dd=24.0))
        self.assertEqual(v["stage"], STAGE_REJECT)

    def test_drawdown_band_from_threshold(self):
        """A DD just over the band fails; just under passes — driven by the config band."""
        over = score_sleeve(_result(beats=True, net_apy=5.0, max_dd=16.0), promotion=_THR)
        self.assertFalse(over["criteria"]["drawdown_within_band"]["pass"])
        under = score_sleeve(_result(beats=True, net_apy=5.0, max_dd=14.0), promotion=_THR)
        self.assertTrue(under["criteria"]["drawdown_within_band"]["pass"])

    def test_wf_below_consistency_threshold_not_paper(self):
        """WF present but below the consistency threshold → stays BACKTEST_PASS."""
        s, v = self._verdict(
            _result(beats=True, net_apy=5.0, max_dd=2.0),
            wf=_wf_block(consistency=50.0, robust=False),
        )
        self.assertEqual(v["stage"], STAGE_BACKTEST_PASS)

    def test_capacity_below_min_not_paper(self):
        """WF-robust but capacity below min AUM → BACKTEST_PASS, not PAPER_CANDIDATE."""
        s, v = self._verdict(
            _result(beats=True, net_apy=5.0, max_dd=2.0),
            wf=_wf_block(max_aum=100_000.0),
        )
        self.assertEqual(v["stage"], STAGE_BACKTEST_PASS)


# ── thresholds come from config ──────────────────────────────────────────────────────────────
class TestConfigThresholds(unittest.TestCase):
    def test_promotion_config_has_keys(self):
        thr = promotion_config()
        for k in ("max_drawdown_band_pct", "wf_consistency_min_pct",
                  "min_capacity_aum_usd", "min_net_apy_pct", "data_gap_kill_substrings"):
            self.assertIn(k, thr)

    def test_band_drives_decision(self):
        """A tighter band injected via config flips a borderline DD from pass to fail."""
        tight = dict(_THR, max_drawdown_band_pct=5.0)
        s = score_sleeve(_result(beats=True, net_apy=5.0, max_dd=8.0), promotion=tight)
        self.assertFalse(s["criteria"]["drawdown_within_band"]["pass"])
        loose = dict(_THR, max_drawdown_band_pct=10.0)
        s2 = score_sleeve(_result(beats=True, net_apy=5.0, max_dd=8.0), promotion=loose)
        self.assertTrue(s2["criteria"]["drawdown_within_band"]["pass"])


# ── determinism ────────────────────────────────────────────────────────────────────────────────
class TestDeterminism(unittest.TestCase):
    def test_score_deterministic(self):
        r = _result(beats=True, net_apy=5.0, max_dd=2.0)
        a = score_sleeve(r, walk_forward=_wf_block(), promotion=_THR)
        b = score_sleeve(r, walk_forward=_wf_block(), promotion=_THR)
        self.assertEqual(a, b)

    def test_report_deterministic_sleeves(self):
        bt = self._mini_backtest()
        r1 = build_report(write=False, backtest=bt, config={"promotion": _THR})
        r2 = build_report(write=False, backtest=bt, config={"promotion": _THR})
        self.assertEqual(r1["sleeves"], r2["sleeves"])
        self.assertEqual(r1["stage_counts"], r2["stage_counts"])

    @staticmethod
    def _mini_backtest():
        return {
            "manifest": {"rwa_floor_apy_pct": 3.4},
            "strategies": {
                "engine_a": {**_result("engine_a", "stable", 3.4, 0.0, True),
                             "is_benchmark": False},
                "rwa_floor": {**_result("rwa_floor", "stable", 3.4, 0.0, True),
                              "is_benchmark": True},
                "variant_d": {**_result("variant_d", "directional", -15.0, 30.0, False,
                                        {"reason": "drawdown 30% > kill 25%"}),
                              "is_benchmark": False},
            },
        }


# ── build_report structure + atomic write ──────────────────────────────────────────────────────
class TestBuildReport(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _bt(self):
        return TestDeterminism._mini_backtest()

    def test_report_structure(self):
        rep = build_report(write=False, backtest=self._bt(), config={"promotion": _THR})
        for k in ("generated_at", "rwa_floor_pct", "thresholds", "n_sleeves",
                  "stage_counts", "sleeves", "pipeline"):
            self.assertIn(k, rep)
        self.assertEqual(rep["rwa_floor_pct"], 3.4)

    def test_benchmark_excluded(self):
        """The rwa_floor benchmark row is NOT a promotable sleeve."""
        rep = build_report(write=False, backtest=self._bt(), config={"promotion": _THR})
        ids = {s["id"] for s in rep["sleeves"]}
        self.assertNotIn("rwa_floor", ids)
        self.assertEqual(rep["n_sleeves"], 2)

    def test_sleeve_fields(self):
        rep = build_report(write=False, backtest=self._bt(), config={"promotion": _THR})
        s = rep["sleeves"][0]
        for k in ("id", "mandate", "stage", "score", "max_score", "criteria", "reason"):
            self.assertIn(k, s)

    def test_engine_a_backtest_pass_variant_d_reject(self):
        # Hermetic: with NO walk-forward evidence (point both WF sources at non-existent files)
        # engine_a clears the backtest but its WF/capacity criteria are PENDING → BACKTEST_PASS.
        # (When the real lab-WF file is present engine_a correctly graduates to PAPER_CANDIDATE —
        # covered by test_strategy_lab_walk_forward.TestPromotionConsumesLabWF.)
        rep = build_report(
            write=False,
            backtest=self._bt(),
            config={"promotion": _THR},
            lab_walk_forward_path=Path(self.tmp) / "no_lab_wf.json",
            walk_forward_path=Path(self.tmp) / "no_tournament_wf.json",
        )
        by_id = {s["id"]: s for s in rep["sleeves"]}
        self.assertEqual(by_id["engine_a"]["stage"], STAGE_BACKTEST_PASS)
        self.assertEqual(by_id["variant_d"]["stage"], STAGE_REJECT)

    def test_atomic_write_creates_file_no_tmp(self):
        out = Path(self.tmp) / "strategy_lab_promotion.json"
        build_report(write=True, backtest=self._bt(), config={"promotion": _THR}, out_path=out)
        self.assertTrue(out.exists())
        with open(out, encoding="utf-8") as f:
            data = json.load(f)
        self.assertIn("sleeves", data)
        leftovers = [x for x in os.listdir(self.tmp) if x.endswith(".tmp")]
        self.assertEqual(leftovers, [])

    def test_missing_backtest_empty_sleeves(self):
        """Fail-closed: a missing backtest → empty sleeves (never promote on no evidence)."""
        rep = build_report(
            write=False,
            backtest_path=Path(self.tmp) / "does_not_exist.json",
            config={"promotion": _THR},
        )
        self.assertEqual(rep["sleeves"], [])
        self.assertEqual(rep["n_sleeves"], 0)

    def test_real_backtest_file_crypto_reject_stable_pass(self):
        """End-to-end over the REAL lab comparison: crypto REJECT, stable engines pass."""
        rep = build_report(write=False)  # reads data/strategy_lab_backtest.json
        if rep["n_sleeves"] == 0:
            self.skipTest("no real backtest file present")
        by_id = {s["id"]: s["stage"] for s in rep["sleeves"]}
        for crypto in ("variant_d", "eth_lst_staking", "btc_lending_sleeve"):
            if crypto in by_id:
                self.assertEqual(by_id[crypto], STAGE_REJECT)
        for stable in ("engine_a", "engine_b", "engine_c", "rwa_sleeve"):
            if stable in by_id:
                self.assertIn(by_id[stable], (STAGE_BACKTEST_PASS, STAGE_PAPER_CANDIDATE))


if __name__ == "__main__":
    unittest.main(verbosity=2)
