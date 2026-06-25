"""
spa_core/tests/test_strategy_lab_walk_forward.py — tests for the LAB-SLEEVE walk-forward +
capacity module (spa_core/strategy_lab/walk_forward.py) and its consumption by the promotion
engine.

Covers:
  - WF consistency computed per sleeve from a synthetic equity series (robust + non-robust)
  - capacity (max_safe_aum_usd) from synthetic market-TVL config (present + absent → PENDING)
  - determinism (two runs over the same inputs are identical)
  - build_report structure, keyed by sleeve id, benchmark excluded, fail-closed on missing bt
  - atomic write (no leftover .tmp)
  - promotion now CONSUMES the lab-WF file: a sleeve with good WF + beats-floor → PAPER_CANDIDATE,
    and a sleeve whose WF is poor stays out of PAPER_CANDIDATE.

stdlib only. Deterministic. LLM-forbidden gate logic.
"""
from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path

from spa_core.strategy_lab import walk_forward as wf
from spa_core.strategy_lab import promotion
from spa_core.strategy_lab.promotion import (
    STAGE_BACKTEST_PASS,
    STAGE_PAPER_CANDIDATE,
    STAGE_REJECT,
)


# ── synthetic equity helpers ───────────────────────────────────────────────────────────────────
def _steady_growth(n=300, daily=0.0003, start=100_000.0):
    """A monotonically compounding equity series — every test window should hold (robust)."""
    eq = [start]
    for _ in range(n - 1):
        eq.append(eq[-1] * (1.0 + daily))
    return eq


def _flat(n=300, start=100_000.0):
    """A perfectly flat equity series — test return ~0, never strictly positive → not robust."""
    return [start] * n


def _crash_then_flat(n=300, start=100_000.0):
    """Grows in early windows, then collapses and stays down — inconsistent → not robust."""
    half = n // 2
    eq = [start]
    for _ in range(half - 1):
        eq.append(eq[-1] * 1.0006)
    crash = eq[-1] * 0.5
    eq += [crash] * (n - half)
    return eq


# ── PART A: walk-forward consistency ───────────────────────────────────────────────────────────
class TestWalkForwardEquity(unittest.TestCase):
    def test_robust_steady_growth(self):
        r = wf.walk_forward_equity(_steady_growth(), train=180, test=60, step=60)
        self.assertEqual(r["status"], "ok")
        self.assertGreater(r["n_windows"], 0)
        self.assertEqual(r["consistency_pct"], 100.0)
        self.assertTrue(r["wf_robust"])

    def test_not_robust_flat(self):
        r = wf.walk_forward_equity(_flat(), train=180, test=60, step=60)
        self.assertEqual(r["status"], "ok")
        # flat → test return not strictly positive → no window holds → not robust.
        self.assertEqual(r["consistency_pct"], 0.0)
        self.assertFalse(r["wf_robust"])

    def test_not_robust_crash(self):
        r = wf.walk_forward_equity(_crash_then_flat(), train=120, test=40, step=40)
        self.assertEqual(r["status"], "ok")
        self.assertLess(r["consistency_pct"], 70.0)
        self.assertFalse(r["wf_robust"])

    def test_insufficient_history_failclosed(self):
        r = wf.walk_forward_equity(_steady_growth(n=50), train=180, test=60, step=60)
        self.assertEqual(r["status"], "insufficient_history")
        self.assertIsNone(r["wf_robust"])
        self.assertEqual(r["n_windows"], 0)

    def test_insufficient_data_failclosed(self):
        r = wf.walk_forward_equity([100_000.0])
        self.assertEqual(r["status"], "insufficient_data")
        self.assertIsNone(r["wf_robust"])

    def test_deterministic(self):
        a = wf.walk_forward_equity(_steady_growth(), train=180, test=60, step=60)
        b = wf.walk_forward_equity(_steady_growth(), train=180, test=60, step=60)
        self.assertEqual(a, b)


# ── PART B: capacity ────────────────────────────────────────────────────────────────────────────
class TestCapacity(unittest.TestCase):
    def test_capacity_from_tvl(self):
        c = wf.capacity_for_sleeve({"market_tvl_usd": 15_000_000_000.0, "max_pool_pct": 0.02})
        self.assertEqual(c["status"], "ok")
        self.assertEqual(c["max_safe_aum_usd"], 300_000_000.0)

    def test_capacity_default_pct(self):
        c = wf.capacity_for_sleeve({"market_tvl_usd": 1_000_000_000.0})  # default 2%
        self.assertEqual(c["max_safe_aum_usd"], 20_000_000.0)

    def test_capacity_absent_failclosed(self):
        for bad in (None, {}, {"market_tvl_usd": 0}, {"market_tvl_usd": None}):
            c = wf.capacity_for_sleeve(bad)
            self.assertEqual(c["status"], "insufficient_data")
            self.assertIsNone(c["max_safe_aum_usd"])

    def test_capacity_deterministic(self):
        cfg = {"market_tvl_usd": 5_000_000_000.0, "max_pool_pct": 0.02}
        self.assertEqual(wf.capacity_for_sleeve(cfg), wf.capacity_for_sleeve(cfg))


# ── build_report structure + atomic ─────────────────────────────────────────────────────────────
def _mini_backtest():
    return {
        "manifest": {"rwa_floor_apy_pct": 3.4},
        "strategies": {
            "engine_a": {"id": "engine_a", "is_benchmark": False,
                         "equity_series": _steady_growth()},
            "rwa_floor": {"id": "rwa_floor", "is_benchmark": True,
                          "equity_series": _steady_growth()},
            "variant_d": {"id": "variant_d", "is_benchmark": False,
                          "equity_series": _flat()},
        },
    }


def _mini_config():
    return {
        "capacity": {
            "engine_a": {"market_tvl_usd": 15_000_000_000.0, "max_pool_pct": 0.02},
            "variant_d": {"market_tvl_usd": 5_000_000_000.0, "max_pool_pct": 0.02},
        }
    }


class TestBuildReport(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_structure_keyed_by_sleeve(self):
        rep = wf.build_report(write=False, backtest=_mini_backtest(), config=_mini_config())
        for k in ("generated_at", "model", "llm_forbidden", "method", "n_sleeves", "sleeves"):
            self.assertIn(k, rep)
        self.assertTrue(rep["llm_forbidden"])
        self.assertIn("engine_a", rep["sleeves"])
        # benchmark excluded
        self.assertNotIn("rwa_floor", rep["sleeves"])
        self.assertEqual(rep["n_sleeves"], 2)

    def test_flattened_shape_promotion_reads(self):
        rep = wf.build_report(write=False, backtest=_mini_backtest(), config=_mini_config())
        ea = rep["sleeves"]["engine_a"]
        for k in ("status", "consistency_pct", "wf_robust", "n_windows",
                  "max_safe_aum_usd", "capacity", "walk_forward"):
            self.assertIn(k, ea)
        self.assertTrue(ea["wf_robust"])
        self.assertEqual(ea["max_safe_aum_usd"], 300_000_000.0)

    def test_capacity_absent_sleeve_pending(self):
        bt = _mini_backtest()
        bt["strategies"]["engine_a"]["equity_series"] = _steady_growth()
        rep = wf.build_report(write=False, backtest=bt, config={"capacity": {}})
        # no capacity config → max_safe_aum_usd None (fail-closed PENDING downstream)
        self.assertIsNone(rep["sleeves"]["engine_a"]["max_safe_aum_usd"])

    def test_missing_backtest_failclosed(self):
        rep = wf.build_report(
            write=False,
            backtest_path=Path(self.tmp) / "nope.json",
            config=_mini_config(),
        )
        self.assertEqual(rep["sleeves"], {})
        self.assertEqual(rep["n_sleeves"], 0)

    def test_atomic_write_no_tmp(self):
        out = Path(self.tmp) / "strategy_lab_walk_forward.json"
        wf.build_report(write=True, backtest=_mini_backtest(), config=_mini_config(),
                        out_path=out)
        self.assertTrue(out.exists())
        with open(out, encoding="utf-8") as f:
            data = json.load(f)
        self.assertIn("sleeves", data)
        leftovers = [x for x in os.listdir(self.tmp) if x.endswith(".tmp")]
        self.assertEqual(leftovers, [])

    def test_deterministic_report_sleeves(self):
        bt, cfg = _mini_backtest(), _mini_config()
        r1 = wf.build_report(write=False, backtest=bt, config=cfg)
        r2 = wf.build_report(write=False, backtest=bt, config=cfg)
        self.assertEqual(r1["sleeves"], r2["sleeves"])


# ── promotion CONSUMES the lab-WF file ──────────────────────────────────────────────────────────
class TestPromotionConsumesLabWF(unittest.TestCase):
    """The whole point: a sleeve with good WF + capacity + beats-floor reaches PAPER_CANDIDATE
    via the lab-WF file (not PENDING), while poor WF keeps it out."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.thr = {
            "max_drawdown_band_pct": 15.0,
            "wf_consistency_min_pct": 70.0,
            "min_capacity_aum_usd": 1_000_000.0,
            "min_net_apy_pct": 0.0,
            "data_gap_kill_substrings": ["missing/invalid", "fail-closed (step raised)"],
        }

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _promotion_backtest(self):
        # a backtest as the PROMOTION engine reads it (metrics, not equity series)
        def row(sid, napy, dd, beats, bench=False):
            return {"id": sid, "mandate": "stable", "is_benchmark": bench,
                    "metrics": {"net_apy_pct": napy, "max_drawdown_pct": dd,
                                "beats_rwa_floor": beats}, "kill": None}
        return {
            "manifest": {"rwa_floor_apy_pct": 3.4},
            "strategies": {
                "good_sleeve": row("good_sleeve", 5.0, 0.0, True),
                "weak_wf_sleeve": row("weak_wf_sleeve", 5.0, 0.0, True),
            },
        }

    def _write_lab_wf(self):
        doc = {
            "sleeves": {
                "good_sleeve": {
                    "status": "ok", "consistency_pct": 100.0, "wf_robust": True,
                    "n_windows": 3, "max_safe_aum_usd": 50_000_000.0,
                    "capacity": {"status": "ok", "max_safe_aum_usd": 50_000_000.0},
                },
                "weak_wf_sleeve": {
                    "status": "ok", "consistency_pct": 20.0, "wf_robust": False,
                    "n_windows": 3, "max_safe_aum_usd": 50_000_000.0,
                    "capacity": {"status": "ok", "max_safe_aum_usd": 50_000_000.0},
                },
            }
        }
        p = Path(self.tmp) / "strategy_lab_walk_forward.json"
        p.write_text(json.dumps(doc), encoding="utf-8")
        return p

    def test_good_wf_promotes_weak_wf_holds(self):
        lab_wf_path = self._write_lab_wf()
        rep = promotion.build_report(
            write=False,
            backtest=self._promotion_backtest(),
            config={"promotion": self.thr},
            lab_walk_forward_path=lab_wf_path,
            # ensure no accidental fallthrough to the real tournament file
            walk_forward_path=Path(self.tmp) / "no_tournament.json",
        )
        by_id = {s["id"]: s for s in rep["sleeves"]}
        # good WF + capacity + beats floor → PAPER_CANDIDATE, NOT pending
        good = by_id["good_sleeve"]
        self.assertEqual(good["stage"], STAGE_PAPER_CANDIDATE)
        self.assertFalse(good["criteria"]["walk_forward_robust"]["pending"])
        self.assertFalse(good["criteria"]["capacity_sufficient"]["pending"])
        # poor WF (consistency below threshold / not robust) → stays BACKTEST_PASS
        weak = by_id["weak_wf_sleeve"]
        self.assertEqual(weak["stage"], STAGE_BACKTEST_PASS)
        self.assertFalse(weak["criteria"]["walk_forward_robust"]["pass"])

    def test_absent_lab_wf_falls_back_pending(self):
        """No lab-WF file AND no tournament match → criteria PENDING → BACKTEST_PASS (old path)."""
        rep = promotion.build_report(
            write=False,
            backtest=self._promotion_backtest(),
            config={"promotion": self.thr},
            lab_walk_forward_path=Path(self.tmp) / "missing.json",
            walk_forward_path=Path(self.tmp) / "missing_tournament.json",
        )
        by_id = {s["id"]: s for s in rep["sleeves"]}
        self.assertEqual(by_id["good_sleeve"]["stage"], STAGE_BACKTEST_PASS)
        self.assertTrue(by_id["good_sleeve"]["criteria"]["walk_forward_robust"]["pending"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
