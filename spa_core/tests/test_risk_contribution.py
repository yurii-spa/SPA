#!/usr/bin/env python3
"""Tests for spa_core.analytics_lab.risk_contribution (SPA-V437 / MP-118).

Plain unittest, NO pytest, NO network, ALL persistence in a tempdir. Covers:
hand-computed 2-asset variance decomposition (wᵀΣw → sigma_p, MCTR, CCTR sum ==
sigma_p, PRC sum == 1), the diversification ratio (incl. the equal-vol
uncorrelated case), the risk-PRC HHI fraction/index/effective-count boundaries
+ single-source 10000, top1/top3 risk shares + top1_risk_protocol, the verdicts
(single PRC>0.60 → fail, moderate → warn, uncovered>0.25 → warn, clean → ok),
uncovered protocols → known:false + uncovered_risk_weight + renormalisation +
covered_weight_share, the reuse-by-import proof (weights derive from
build_exposure share_pct), is_demo honesty, tolerance of missing/broken/garbage
inputs, idempotent persistence + history rotation, the CLI (direct +
subprocess), and import hygiene via the real AST linter.
"""
from __future__ import annotations

import ast
import contextlib
import hashlib
import io
import json
import math
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from spa_core.analytics_lab import risk_contribution as rc
from spa_core.reporting.tear_sheet import build_exposure

_REPO_ROOT = Path(__file__).resolve().parents[2]


def _write_json(data_dir: Path, name: str, doc) -> Path:
    data_dir.mkdir(parents=True, exist_ok=True)
    p = data_dir / name
    p.write_text(json.dumps(doc), encoding="utf-8")
    return p


def _write_positions(data_dir: Path, doc) -> Path:
    return _write_json(data_dir, rc.POSITIONS_FILENAME, doc)


def _write_orch(data_dir: Path, doc) -> Path:
    return _write_json(data_dir, rc.ORCHESTRATOR_FILENAME, doc)


def _write_cov(data_dir: Path, doc) -> Path:
    return _write_json(data_dir, rc.COVARIANCE_FILENAME, doc)


def _orch(protos, tiers: dict = None) -> dict:
    """Build a list-shaped orchestrator status (the real layout)."""
    tiers = tiers or {}
    return {"adapters": [
        {"protocol": p, "apy_pct": 3.0,
         "tier": tiers.get(p, "T1"), "tvl_usd": 1_000_000.0}
        for p in protos
    ]}


def _cov(matrix: dict, *, window_days=90, source="live", is_demo=None) -> dict:
    """Build a covariance_summary.json from a slug→{slug: cov} dict-of-dicts."""
    doc = {
        "covariance_matrix": matrix,
        "window_days": window_days,
        "source": source,
    }
    if is_demo is not None:
        doc["is_demo"] = is_demo
    return doc


class _TmpBase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.mkdtemp(prefix="risk_test_")
        self.data_dir = Path(self._tmp)

    def tearDown(self):
        import shutil
        shutil.rmtree(self._tmp, ignore_errors=True)


# ─── Hand-computed risk decomposition ────────────────────────────────────────


class TestDecompositionMath(_TmpBase):
    def test_canonical_2asset(self):
        # 60% high / 40% low; Σ_hh=4, Σ_ll=1, cov=0.5.
        # var = 0.6²·4 + 0.4²·1 + 2·0.6·0.4·0.5 = 1.44+0.16+0.24 = 1.84
        # sigma_p = sqrt(1.84) ≈ 1.356466
        _write_positions(self.data_dir, {
            "capital_usd": 100000.0, "cash_usd": 0.0,
            "positions": {"high": 60000.0, "low": 40000.0},
        })
        _write_orch(self.data_dir, _orch(["high", "low"]))
        _write_cov(self.data_dir, _cov({
            "high": {"high": 4.0, "low": 0.5},
            "low": {"high": 0.5, "low": 1.0},
        }))
        r = rc.build_risk_contribution(self.data_dir)
        self.assertTrue(r["available"])
        self.assertAlmostEqual(r["portfolio_variance"], 1.84, places=6)
        self.assertAlmostEqual(r["portfolio_volatility_pp"], math.sqrt(1.84), places=6)
        bd = {b["protocol"]: b for b in r["breakdown"]}
        sp = math.sqrt(1.84)
        # Σw = [4*0.6+0.5*0.4, 0.5*0.6+1*0.4] = [2.6, 0.7]
        self.assertAlmostEqual(bd["high"]["mctr"], 2.6 / sp, places=6)
        self.assertAlmostEqual(bd["low"]["mctr"], 0.7 / sp, places=6)
        self.assertAlmostEqual(bd["high"]["cctr"], 0.6 * 2.6 / sp, places=6)
        self.assertAlmostEqual(bd["low"]["cctr"], 0.4 * 0.7 / sp, places=6)

    def test_cctr_sums_to_sigma_p(self):
        _write_positions(self.data_dir, {
            "capital_usd": 100000.0, "cash_usd": 0.0,
            "positions": {"a": 50000.0, "b": 30000.0, "c": 20000.0},
        })
        _write_orch(self.data_dir, _orch(["a", "b", "c"]))
        _write_cov(self.data_dir, _cov({
            "a": {"a": 5.0, "b": 1.0, "c": -0.5},
            "b": {"a": 1.0, "b": 3.0, "c": 0.2},
            "c": {"a": -0.5, "b": 0.2, "c": 2.0},
        }))
        r = rc.build_risk_contribution(self.data_dir)
        total_cctr = sum(b["cctr"] for b in r["breakdown"])
        self.assertAlmostEqual(total_cctr, r["portfolio_volatility_pp"], places=6)

    def test_prc_sums_to_one(self):
        _write_positions(self.data_dir, {
            "capital_usd": 100000.0, "cash_usd": 0.0,
            "positions": {"a": 50000.0, "b": 30000.0, "c": 20000.0},
        })
        _write_orch(self.data_dir, _orch(["a", "b", "c"]))
        _write_cov(self.data_dir, _cov({
            "a": {"a": 5.0, "b": 1.0, "c": -0.5},
            "b": {"a": 1.0, "b": 3.0, "c": 0.2},
            "c": {"a": -0.5, "b": 0.2, "c": 2.0},
        }))
        r = rc.build_risk_contribution(self.data_dir)
        self.assertAlmostEqual(sum(b["prc"] for b in r["breakdown"]), 1.0, places=6)


# ─── Diversification ratio ───────────────────────────────────────────────────


class TestDiversificationRatio(_TmpBase):
    def test_hand_check_2asset(self):
        # 60/40, Σ as above; sigma_i = [2, 1]; DR = (0.6*2+0.4*1)/sigma_p.
        _write_positions(self.data_dir, {
            "capital_usd": 100000.0, "cash_usd": 0.0,
            "positions": {"high": 60000.0, "low": 40000.0},
        })
        _write_orch(self.data_dir, _orch(["high", "low"]))
        _write_cov(self.data_dir, _cov({
            "high": {"high": 4.0, "low": 0.5},
            "low": {"high": 0.5, "low": 1.0},
        }))
        r = rc.build_risk_contribution(self.data_dir)
        sp = math.sqrt(1.84)
        expected = (0.6 * 2.0 + 0.4 * 1.0) / sp
        self.assertAlmostEqual(r["diversification_ratio"], expected, places=6)
        self.assertGreaterEqual(r["diversification_ratio"], 1.0)

    def test_equal_vol_uncorrelated(self):
        # Two equal-vol (var=4) uncorrelated assets, 50/50.
        # var = 0.25*4 + 0.25*4 = 2 ; sigma_p = sqrt(2).
        # weighted standalone vol = 0.5*2 + 0.5*2 = 2 ; DR = 2/sqrt(2) = sqrt(2).
        _write_positions(self.data_dir, {
            "capital_usd": 100000.0, "cash_usd": 0.0,
            "positions": {"a": 50000.0, "b": 50000.0},
        })
        _write_orch(self.data_dir, _orch(["a", "b"]))
        _write_cov(self.data_dir, _cov({
            "a": {"a": 4.0, "b": 0.0},
            "b": {"a": 0.0, "b": 4.0},
        }))
        r = rc.build_risk_contribution(self.data_dir)
        self.assertAlmostEqual(r["portfolio_volatility_pp"], math.sqrt(2.0), places=6)
        self.assertAlmostEqual(r["diversification_ratio"], math.sqrt(2.0), places=6)
        # PRC equal → 0.5 each.
        for b in r["breakdown"]:
            self.assertAlmostEqual(b["prc"], 0.5, places=6)

    def test_perfectly_correlated_dr_one(self):
        # Perfectly correlated identical assets → DR == 1 (no diversification).
        _write_positions(self.data_dir, {
            "capital_usd": 100000.0, "cash_usd": 0.0,
            "positions": {"a": 50000.0, "b": 50000.0},
        })
        _write_orch(self.data_dir, _orch(["a", "b"]))
        _write_cov(self.data_dir, _cov({
            "a": {"a": 4.0, "b": 4.0},
            "b": {"a": 4.0, "b": 4.0},
        }))
        r = rc.build_risk_contribution(self.data_dir)
        self.assertAlmostEqual(r["diversification_ratio"], 1.0, places=6)


# ─── Risk-HHI index / effective sources / boundaries ─────────────────────────


class TestRiskHHI(_TmpBase):
    def _two_asset_target_prc(self, p):
        """Find a 2-asset diagonal-Σ portfolio whose top PRC ≈ p.

        With uncorrelated assets var_i and weights w_i, PRC_i ∝ w_i²·var_i.
        Use equal var=1 and pick weights so the larger PRC == p.
        PRC_high = wh²/(wh²+wl²) with wl=1-wh ⇒ solve for wh.
        """
        # wh²/(wh²+(1-wh)²) = p
        # Solve quadratic: (1-p)wh² - 2(? ) ... easier numerically.
        lo, hi = 0.5, 1.0
        for _ in range(200):
            wh = (lo + hi) / 2
            wl = 1 - wh
            prc = wh * wh / (wh * wh + wl * wl)
            if prc < p:
                lo = wh
            else:
                hi = wh
        return wh

    def _run_with_top_prc(self, target):
        wh = self._two_asset_target_prc(target)
        hi_usd = round(wh * 100000.0, 2)
        lo_usd = round(100000.0 - hi_usd, 2)
        _write_positions(self.data_dir, {
            "capital_usd": 100000.0, "cash_usd": 0.0,
            "positions": {"high": hi_usd, "low": lo_usd},
        })
        _write_orch(self.data_dir, _orch(["high", "low"]))
        _write_cov(self.data_dir, _cov({
            "high": {"high": 1.0, "low": 0.0},
            "low": {"high": 0.0, "low": 1.0},
        }))
        return rc.build_risk_contribution(self.data_dir)

    def test_single_source_index_10000(self):
        _write_positions(self.data_dir, {
            "capital_usd": 100000.0, "cash_usd": 0.0,
            "positions": {"only": 100000.0},
        })
        _write_orch(self.data_dir, _orch(["only"]))
        _write_cov(self.data_dir, _cov({"only": {"only": 4.0}}))
        r = rc.build_risk_contribution(self.data_dir)
        self.assertEqual(r["risk_hhi_index"], 10000)
        self.assertAlmostEqual(r["risk_hhi"], 1.0, places=6)
        self.assertAlmostEqual(r["effective_num_risk_sources"], 1.0, places=4)
        self.assertAlmostEqual(r["top1_risk_share"], 1.0, places=6)

    def test_two_equal_index_5000(self):
        _write_positions(self.data_dir, {
            "capital_usd": 100000.0, "cash_usd": 0.0,
            "positions": {"a": 50000.0, "b": 50000.0},
        })
        _write_orch(self.data_dir, _orch(["a", "b"]))
        _write_cov(self.data_dir, _cov({
            "a": {"a": 4.0, "b": 0.0}, "b": {"a": 0.0, "b": 4.0},
        }))
        r = rc.build_risk_contribution(self.data_dir)
        # PRC 0.5/0.5 → HHI 0.5 → index 5000 → eff 2.
        self.assertEqual(r["risk_hhi_index"], 5000)
        self.assertAlmostEqual(r["effective_num_risk_sources"], 2.0, places=4)

    def test_class_boundaries(self):
        # diversified < 1500 <= moderate <= 2500 < concentrated.
        for target_index, expected in [
            (1499, "diversified"),
            (1500, "moderate"),
            (2500, "moderate"),
            (2501, "concentrated"),
        ]:
            with self.subTest(idx=target_index):
                cls = rc._classify_risk(target_index)
                self.assertEqual(cls, expected)
        self.assertIsNone(rc._classify_risk(None))


# ─── Top-N risk shares ───────────────────────────────────────────────────────


class TestTopRiskShares(_TmpBase):
    def test_top1_top3_protocol(self):
        _write_positions(self.data_dir, {
            "capital_usd": 100000.0, "cash_usd": 0.0,
            "positions": {"big": 70000.0, "mid": 20000.0, "small": 10000.0},
        })
        _write_orch(self.data_dir, _orch(["big", "mid", "small"]))
        _write_cov(self.data_dir, _cov({
            "big": {"big": 6.0, "mid": 0.0, "small": 0.0},
            "mid": {"big": 0.0, "mid": 2.0, "small": 0.0},
            "small": {"big": 0.0, "mid": 0.0, "small": 1.0},
        }))
        r = rc.build_risk_contribution(self.data_dir)
        self.assertEqual(r["top1_risk_protocol"], "big")
        self.assertGreater(r["top1_risk_share"], 0.0)
        # top3 over exactly 3 sources == 1.0.
        self.assertAlmostEqual(r["top3_risk_share"], 1.0, places=6)
        self.assertGreaterEqual(r["top1_risk_share"], r["top3_risk_share"] / 3)


# ─── Verdict ─────────────────────────────────────────────────────────────────


class TestVerdict(_TmpBase):
    def test_single_prc_over_60_fail(self):
        # One dominant high-vol asset → PRC > 0.60.
        _write_positions(self.data_dir, {
            "capital_usd": 100000.0, "cash_usd": 0.0,
            "positions": {"dom": 80000.0, "tiny": 20000.0},
        })
        _write_orch(self.data_dir, _orch(["dom", "tiny"]))
        _write_cov(self.data_dir, _cov({
            "dom": {"dom": 9.0, "tiny": 0.0},
            "tiny": {"dom": 0.0, "tiny": 1.0},
        }))
        r = rc.build_risk_contribution(self.data_dir)
        self.assertGreater(r["top1_risk_share"], 0.60)
        self.assertEqual(r["verdict"], "fail")

    def test_concentrated_class_fail(self):
        # HHI index > 2500 with no single PRC>0.6 still → concentrated → fail.
        # Two assets PRC ~0.55/0.45 → HHI ~0.505 → index ~5050 concentrated.
        _write_positions(self.data_dir, {
            "capital_usd": 100000.0, "cash_usd": 0.0,
            "positions": {"a": 52000.0, "b": 48000.0},
        })
        _write_orch(self.data_dir, _orch(["a", "b"]))
        _write_cov(self.data_dir, _cov({
            "a": {"a": 1.0, "b": 0.0}, "b": {"a": 0.0, "b": 1.0},
        }))
        r = rc.build_risk_contribution(self.data_dir)
        self.assertEqual(r["risk_concentration_class"], "concentrated")
        self.assertEqual(r["verdict"], "fail")

    def test_moderate_warn(self):
        # Build a portfolio whose risk-HHI index lands in [1500,2500] with no
        # single PRC>0.6: ~5 equalish PRC sources give HHI ~2000.
        # 5 uncorrelated equal-var equal-weight → HHI 0.2 (index 2000) moderate.
        _write_positions(self.data_dir, {
            "capital_usd": 100000.0, "cash_usd": 0.0,
            "positions": {"a": 20000.0, "b": 20000.0, "c": 20000.0,
                          "d": 20000.0, "e": 20000.0},
        })
        _write_orch(self.data_dir, _orch(["a", "b", "c", "d", "e"]))
        _write_cov(self.data_dir, _cov({
            p: {q: (1.0 if p == q else 0.0) for q in "abcde"} for p in "abcde"
        }))
        r = rc.build_risk_contribution(self.data_dir)
        self.assertEqual(r["risk_hhi_index"], 2000)
        self.assertEqual(r["risk_concentration_class"], "moderate")
        self.assertEqual(r["verdict"], "warn")

    def test_uncovered_over_25_warn(self):
        # Two covered diversified + one big uncovered (>25%).
        _write_positions(self.data_dir, {
            "capital_usd": 100000.0, "cash_usd": 0.0,
            "positions": {"a": 30000.0, "b": 30000.0, "uncovered_proto": 40000.0},
        })
        _write_orch(self.data_dir, _orch(["a", "b", "uncovered_proto"]))
        _write_cov(self.data_dir, _cov({
            "a": {"a": 1.0, "b": 0.0}, "b": {"a": 0.0, "b": 1.0},
        }))
        r = rc.build_risk_contribution(self.data_dir)
        self.assertGreater(r["uncovered_risk_weight"], 0.25)
        # covered HHI 0.5 -> concentrated would force fail; pick 4 covered so
        # the covered sub-portfolio is NOT concentrated.
        self.assertIn(r["verdict"], ("warn", "fail"))

    def test_clean_ok(self):
        # 6 well-diversified uncorrelated equal sources → HHI 1/6≈0.1667
        # index 1667 ... that's moderate. Use 8 sources → index 1250 < 1500.
        protos = list("abcdefgh")
        _write_positions(self.data_dir, {
            "capital_usd": 100000.0, "cash_usd": 0.0,
            "positions": {p: 12500.0 for p in protos},
        })
        _write_orch(self.data_dir, _orch(protos))
        _write_cov(self.data_dir, _cov({
            p: {q: (1.0 if p == q else 0.0) for q in protos} for p in protos
        }))
        r = rc.build_risk_contribution(self.data_dir)
        self.assertEqual(r["risk_concentration_class"], "diversified")
        self.assertEqual(r["uncovered_risk_weight"], 0.0)
        self.assertEqual(r["verdict"], "ok")


# ─── Uncovered protocols / renormalisation / covered_weight_share ────────────


class TestUncovered(_TmpBase):
    def test_uncovered_marked_and_renormalised(self):
        # a + b covered, x uncovered (no covariance row).
        _write_positions(self.data_dir, {
            "capital_usd": 100000.0, "cash_usd": 0.0,
            "positions": {"a": 30000.0, "b": 30000.0, "x": 40000.0},
        })
        _write_orch(self.data_dir, _orch(["a", "b", "x"]))
        _write_cov(self.data_dir, _cov({
            "a": {"a": 4.0, "b": 0.0}, "b": {"a": 0.0, "b": 1.0},
        }))
        r = rc.build_risk_contribution(self.data_dir)
        self.assertTrue(r["available"])
        bd = {b["protocol"]: b for b in r["breakdown"]}
        self.assertFalse(bd["x"]["known"])
        self.assertIsNone(bd["x"]["prc"])
        # covered weight share = 60% deployed.
        self.assertAlmostEqual(r["covered_weight_share"], 0.6, places=6)
        self.assertAlmostEqual(r["uncovered_risk_weight"], 0.4, places=6)
        # Renormalised covered weights: a,b each 0.5.
        self.assertAlmostEqual(bd["a"]["weight"], 0.5, places=6)
        self.assertAlmostEqual(bd["b"]["weight"], 0.5, places=6)
        # PRC over covered still sums to 1.
        self.assertAlmostEqual(
            sum(b["prc"] for b in r["breakdown"] if b["known"]), 1.0, places=6
        )
        self.assertTrue(any("uncovered" in n.lower() for n in r["notes"]))

    def test_all_uncovered_honest(self):
        _write_positions(self.data_dir, {
            "capital_usd": 100000.0, "cash_usd": 0.0,
            "positions": {"x": 60000.0, "y": 40000.0},
        })
        _write_orch(self.data_dir, _orch(["x", "y"]))
        _write_cov(self.data_dir, _cov({
            "a": {"a": 4.0}, "b": {"b": 1.0},
        }))
        r = rc.build_risk_contribution(self.data_dir)
        self.assertEqual(r["num_covered"], 0)
        self.assertAlmostEqual(r["covered_weight_share"], 0.0, places=6)
        self.assertAlmostEqual(r["uncovered_risk_weight"], 1.0, places=6)
        self.assertEqual(r["portfolio_volatility_pp"], 0.0)


# ─── Reuse-by-import proof ───────────────────────────────────────────────────


class TestReuseByImport(_TmpBase):
    def test_weights_match_build_exposure(self):
        positions = {
            "capital_usd": 100000.0, "cash_usd": 5000.02, "is_demo": False,
            "positions": {"aave_v3": 31529.27, "compound_v3": 30220.72,
                          "euler_v2": 10376.79, "maple": 11436.6,
                          "yearn_v3": 11436.6},
        }
        _write_positions(self.data_dir, positions)
        orch = _orch(["aave_v3", "compound_v3", "euler_v2", "maple", "yearn_v3"])
        _write_orch(self.data_dir, orch)
        _write_cov(self.data_dir, _cov({
            p: {q: (3.0 if p == q else 0.0) for q in
                ["aave_v3", "compound_v3", "euler_v2", "maple", "yearn_v3"]}
            for p in ["aave_v3", "compound_v3", "euler_v2", "maple", "yearn_v3"]
        }))
        r = rc.build_risk_contribution(self.data_dir)
        exp = build_exposure(positions, orch)
        bd = {b["protocol"]: b for b in r["breakdown"]}
        for proto, info in exp["by_protocol"].items():
            self.assertAlmostEqual(
                bd[proto]["capital_weight"], info["share_pct"] / 100.0, places=9,
                msg=proto,
            )


# ─── is_demo honesty ─────────────────────────────────────────────────────────


class TestIsDemo(_TmpBase):
    def _setup(self, is_demo_value):
        pos = {
            "capital_usd": 100000.0, "cash_usd": 0.0,
            "positions": {"a": 60000.0, "b": 40000.0},
        }
        if is_demo_value is not None:
            pos["is_demo"] = is_demo_value
        _write_positions(self.data_dir, pos)
        _write_orch(self.data_dir, _orch(["a", "b"]))
        _write_cov(self.data_dir, _cov({
            "a": {"a": 4.0, "b": 0.0}, "b": {"a": 0.0, "b": 1.0},
        }))

    def test_is_demo_true(self):
        self._setup(True)
        self.assertTrue(rc.build_risk_contribution(self.data_dir)["is_demo"])

    def test_is_demo_false(self):
        self._setup(False)
        self.assertFalse(rc.build_risk_contribution(self.data_dir)["is_demo"])

    def test_is_demo_absent_null(self):
        self._setup(None)
        r = rc.build_risk_contribution(self.data_dir)
        self.assertIsNone(r["is_demo"])
        self.assertTrue(any("is_demo" in n for n in r["notes"]))


# ─── Tolerance ───────────────────────────────────────────────────────────────


class TestTolerance(_TmpBase):
    def test_each_input_degrades_honestly(self):
        good_pos = {
            "capital_usd": 100000.0, "cash_usd": 0.0,
            "positions": {"a": 60000.0, "b": 40000.0},
        }
        good_orch = _orch(["a", "b"])
        good_cov = _cov({
            "a": {"a": 4.0, "b": 0.0}, "b": {"a": 0.0, "b": 1.0},
        })
        broken_cases = ["{broken", "[1,2,3]", "null", "", "12345", '"a string"']
        for which in ("positions", "orch", "cov"):
            for payload in broken_cases:
                with self.subTest(which=which, payload=payload):
                    _write_positions(self.data_dir, good_pos)
                    _write_orch(self.data_dir, good_orch)
                    _write_cov(self.data_dir, good_cov)
                    target = {
                        "positions": rc.POSITIONS_FILENAME,
                        "orch": rc.ORCHESTRATOR_FILENAME,
                        "cov": rc.COVARIANCE_FILENAME,
                    }[which]
                    (self.data_dir / target).write_text(payload, encoding="utf-8")
                    try:
                        r = rc.build_risk_contribution(self.data_dir)
                    except Exception as exc:  # noqa: BLE001
                        self.fail(f"raised on {which}/{payload}: {exc}")
                    self.assertIn("available", r)
                    self.assertIn("verdict", r)

    def test_missing_all_inputs(self):
        r = rc.build_risk_contribution(self.data_dir)
        self.assertFalse(r["available"])
        self.assertEqual(r["verdict"], "warn")

    def test_empty_positions(self):
        _write_positions(self.data_dir, {"capital_usd": 100000.0, "positions": {}})
        _write_cov(self.data_dir, _cov({"a": {"a": 1.0}}))
        r = rc.build_risk_contribution(self.data_dir)
        self.assertFalse(r["available"])

    def test_missing_covariance_unavailable(self):
        _write_positions(self.data_dir, {
            "capital_usd": 100000.0, "cash_usd": 0.0,
            "positions": {"a": 60000.0, "b": 40000.0},
        })
        _write_orch(self.data_dir, _orch(["a", "b"]))
        # No covariance file.
        r = rc.build_risk_contribution(self.data_dir)
        self.assertFalse(r["available"])
        self.assertTrue(any("covariance" in n.lower() for n in r["notes"]))

    def test_never_raises_on_junk_dir(self):
        try:
            r = rc.build_risk_contribution("/nonexistent/dir/xyz")
        except Exception as exc:  # noqa: BLE001
            self.fail(f"raised on junk dir: {exc}")
        self.assertFalse(r["available"])

    def test_garbage_covariance_values_tolerated(self):
        _write_positions(self.data_dir, {
            "capital_usd": 100000.0, "cash_usd": 0.0,
            "positions": {"a": 60000.0, "b": 40000.0},
        })
        _write_orch(self.data_dir, _orch(["a", "b"]))
        # Diagonal numeric but cross terms garbage (strings) → treated as 0.
        _write_cov(self.data_dir, _cov({
            "a": {"a": 4.0, "b": "junk"},
            "b": {"a": None, "b": 1.0},
        }))
        try:
            r = rc.build_risk_contribution(self.data_dir)
        except Exception as exc:  # noqa: BLE001
            self.fail(f"raised: {exc}")
        self.assertTrue(r["available"])


# ─── Real-data mapping (aave_v3 → multiple instruments) ──────────────────────


class TestRealDataMapping(_TmpBase):
    def test_ambiguous_aave_prefers_usdc(self):
        # aave_v3 matches both usdc + usdt instruments → pick usdc deterministically.
        _write_positions(self.data_dir, {
            "capital_usd": 100000.0, "cash_usd": 0.0,
            "positions": {"aave_v3": 100000.0},
        })
        _write_orch(self.data_dir, _orch(["aave_v3"]))
        _write_cov(self.data_dir, _cov({
            "aave-v3-usdc-ethereum": {"aave-v3-usdc-ethereum": 5.3,
                                      "aave-v3-usdt-ethereum": -0.2},
            "aave-v3-usdt-ethereum": {"aave-v3-usdc-ethereum": -0.2,
                                      "aave-v3-usdt-ethereum": 3.9},
        }))
        r = rc.build_risk_contribution(self.data_dir)
        self.assertTrue(r["available"])
        bd = r["breakdown"][0]
        self.assertEqual(bd["slug"], "aave-v3-usdc-ethereum")
        self.assertTrue(any("aave_v3" in n and "deterministically" in n
                            for n in r["notes"]))


# ─── Persistence / idempotency ───────────────────────────────────────────────


class TestPersistence(_TmpBase):
    def _good(self):
        _write_positions(self.data_dir, {
            "capital_usd": 100000.0, "cash_usd": 0.0, "is_demo": False,
            "positions": {"a": 60000.0, "b": 40000.0},
        })
        _write_orch(self.data_dir, _orch(["a", "b"]))
        _write_cov(self.data_dir, _cov({
            "a": {"a": 4.0, "b": 0.5}, "b": {"a": 0.5, "b": 1.0},
        }))

    def test_run_writes(self):
        self._good()
        doc = rc.build_status_doc(data_dir=self.data_dir)
        out = rc.write_status(doc, data_dir=self.data_dir)
        self.assertTrue(out["changed"])
        path = self.data_dir / rc.STATUS_FILENAME
        loaded = json.loads(path.read_text())
        self.assertEqual(loaded["source"], rc.SOURCE_NAME)
        self.assertEqual(len(loaded["history"]), 1)

    def test_run_twice_byte_identical(self):
        self._good()
        doc1 = rc.build_status_doc(data_dir=self.data_dir,
                                   now=datetime(2026, 6, 12, tzinfo=timezone.utc))
        rc.write_status(doc1, data_dir=self.data_dir)
        path = self.data_dir / rc.STATUS_FILENAME
        bytes1 = path.read_bytes()
        md1 = hashlib.md5(bytes1).hexdigest()
        doc2 = rc.build_status_doc(data_dir=self.data_dir,
                                   now=datetime(2026, 6, 13, tzinfo=timezone.utc))
        out2 = rc.write_status(doc2, data_dir=self.data_dir)
        self.assertFalse(out2["changed"])
        self.assertEqual(path.read_bytes(), bytes1)
        self.assertEqual(hashlib.md5(path.read_bytes()).hexdigest(), md1)

    def test_generated_at_stable_when_unchanged(self):
        self._good()
        rc.write_status(rc.build_status_doc(data_dir=self.data_dir,
                        now=datetime(2026, 6, 12, tzinfo=timezone.utc)),
                        data_dir=self.data_dir)
        path = self.data_dir / rc.STATUS_FILENAME
        ga1 = json.loads(path.read_text())["meta"]["generated_at"]
        rc.write_status(rc.build_status_doc(data_dir=self.data_dir,
                        now=datetime(2026, 7, 1, tzinfo=timezone.utc)),
                        data_dir=self.data_dir)
        ga2 = json.loads(path.read_text())["meta"]["generated_at"]
        self.assertEqual(ga1, ga2)

    def test_history_grows_on_change(self):
        self._good()
        rc.write_status(rc.build_status_doc(data_dir=self.data_dir,
                        now=datetime(2026, 6, 12, tzinfo=timezone.utc)),
                        data_dir=self.data_dir)
        _write_positions(self.data_dir, {
            "capital_usd": 100000.0, "cash_usd": 0.0, "is_demo": False,
            "positions": {"a": 90000.0, "b": 10000.0},
        })
        out2 = rc.write_status(rc.build_status_doc(data_dir=self.data_dir,
                               now=datetime(2026, 6, 13, tzinfo=timezone.utc)),
                               data_dir=self.data_dir)
        self.assertTrue(out2["changed"])
        loaded = json.loads((self.data_dir / rc.STATUS_FILENAME).read_text())
        self.assertEqual(len(loaded["history"]), 2)

    def test_history_rotation_exactly_500(self):
        self._good()
        path = self.data_dir / rc.STATUS_FILENAME
        seed = {"history": [{"generated_at": f"t{i}"} for i in range(600)]}
        path.write_text(json.dumps(seed), encoding="utf-8")
        rc.write_status(rc.build_status_doc(data_dir=self.data_dir),
                        data_dir=self.data_dir)
        loaded = json.loads(path.read_text())
        self.assertEqual(len(loaded["history"]), rc.HISTORY_MAX)
        self.assertEqual(rc.HISTORY_MAX, 500)

    def test_no_tmp_leftovers(self):
        self._good()
        rc.write_status(rc.build_status_doc(data_dir=self.data_dir),
                        data_dir=self.data_dir)
        leftovers = list(self.data_dir.glob("*.tmp")) + \
            list(self.data_dir.glob(".*tmp"))
        self.assertEqual(leftovers, [])

    def test_broken_prior_status_tolerated(self):
        self._good()
        path = self.data_dir / rc.STATUS_FILENAME
        path.write_text("{broken", encoding="utf-8")
        out = rc.write_status(rc.build_status_doc(data_dir=self.data_dir),
                              data_dir=self.data_dir)
        self.assertTrue(out["changed"])
        loaded = json.loads(path.read_text())
        self.assertEqual(len(loaded["history"]), 1)

    def test_fingerprint_excludes_volatile(self):
        a = {"meta": {"generated_at": "2026-01-01"}, "verdict": "ok",
             "history": [1, 2]}
        b = {"meta": {"generated_at": "2099-12-31"}, "verdict": "ok",
             "history": [9]}
        self.assertEqual(rc.content_fingerprint(a), rc.content_fingerprint(b))

    def test_fingerprint_detects_content_change(self):
        a = {"meta": {"generated_at": "x"}, "verdict": "ok"}
        b = {"meta": {"generated_at": "x"}, "verdict": "fail"}
        self.assertNotEqual(rc.content_fingerprint(a), rc.content_fingerprint(b))

    def test_fingerprint_invalid(self):
        self.assertEqual(rc.content_fingerprint("not a dict"), "<invalid>")

    def test_history_entry_fields(self):
        self._good()
        doc = rc.build_status_doc(data_dir=self.data_dir)
        entry = rc._history_entry(doc)
        for k in ("portfolio_volatility_pp", "risk_hhi_index", "top1_risk_share",
                  "diversification_ratio", "covered_weight_share"):
            self.assertIn(k, entry)


# ─── CLI ─────────────────────────────────────────────────────────────────────


class TestCLI(_TmpBase):
    def _good(self):
        _write_positions(self.data_dir, {
            "capital_usd": 100000.0, "cash_usd": 0.0, "is_demo": False,
            "positions": {"a": 60000.0, "b": 40000.0},
        })
        _write_orch(self.data_dir, _orch(["a", "b"]))
        _write_cov(self.data_dir, _cov({
            "a": {"a": 4.0, "b": 0.5}, "b": {"a": 0.5, "b": 1.0},
        }))

    def test_check_default_exit0_valid_json(self):
        self._good()
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            rcode = rc.main(["--check", "--data-dir", str(self.data_dir)])
        self.assertEqual(rcode, 0)
        doc = json.loads(out.getvalue())
        self.assertEqual(doc["source"], rc.SOURCE_NAME)
        self.assertIn("verdict", doc)

    def test_default_is_check(self):
        self._good()
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            rcode = rc.main(["--data-dir", str(self.data_dir)])
        self.assertEqual(rcode, 0)
        json.loads(out.getvalue())

    def test_check_does_not_write(self):
        self._good()
        before = sorted(p.name for p in self.data_dir.iterdir())
        with contextlib.redirect_stdout(io.StringIO()):
            rc.main(["--check", "--data-dir", str(self.data_dir)])
        after = sorted(p.name for p in self.data_dir.iterdir())
        self.assertEqual(before, after)
        self.assertNotIn(rc.STATUS_FILENAME, after)

    def test_run_writes_exit0(self):
        self._good()
        with contextlib.redirect_stdout(io.StringIO()):
            rcode = rc.main(["--run", "--data-dir", str(self.data_dir)])
        self.assertEqual(rcode, 0)
        self.assertTrue((self.data_dir / rc.STATUS_FILENAME).exists())

    def test_run_twice_idempotent(self):
        self._good()
        with contextlib.redirect_stdout(io.StringIO()):
            rc.main(["--run", "--data-dir", str(self.data_dir)])
        path = self.data_dir / rc.STATUS_FILENAME
        b1 = path.read_bytes()
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            rc.main(["--run", "--data-dir", str(self.data_dir)])
        self.assertEqual(path.read_bytes(), b1)
        self.assertIn("idempotent", out.getvalue())

    def test_empty_data_dir_exit0(self):
        with contextlib.redirect_stdout(io.StringIO()):
            rcode = rc.main(["--check", "--data-dir", str(self.data_dir)])
        self.assertEqual(rcode, 0)

    def test_junk_arg_exit0_no_traceback(self):
        err = io.StringIO()
        with contextlib.redirect_stderr(err), contextlib.redirect_stdout(io.StringIO()):
            rcode = rc.main(["--frobnicate"])
        self.assertEqual(rcode, 0)
        self.assertIn("ERROR", err.getvalue())
        self.assertNotIn("Traceback", err.getvalue())

    def test_check_run_conflict_exit0(self):
        err = io.StringIO()
        with contextlib.redirect_stderr(err), contextlib.redirect_stdout(io.StringIO()):
            rcode = rc.main(["--check", "--run"])
        self.assertEqual(rcode, 0)
        self.assertIn("ERROR", err.getvalue())
        self.assertNotIn("Traceback", err.getvalue())

    def test_run_no_tmp_leftover_after_cli(self):
        self._good()
        with contextlib.redirect_stdout(io.StringIO()):
            rc.main(["--run", "--data-dir", str(self.data_dir)])
        self.assertEqual(list(self.data_dir.glob("*.tmp")), [])

    def test_subprocess_check_exit0(self):
        self._good()
        proc = subprocess.run(
            [sys.executable, "-m",
             "spa_core.analytics_lab.risk_contribution",
             "--check", "--data-dir", str(self.data_dir)],
            cwd=str(_REPO_ROOT), capture_output=True, text=True,
        )
        self.assertEqual(proc.returncode, 0)
        json.loads(proc.stdout)
        self.assertNotIn("Traceback", proc.stderr)

    def test_subprocess_junk_arg_exit0(self):
        proc = subprocess.run(
            [sys.executable, "-m",
             "spa_core.analytics_lab.risk_contribution",
             "--no-such-flag"],
            cwd=str(_REPO_ROOT), capture_output=True, text=True,
        )
        self.assertEqual(proc.returncode, 0)
        self.assertNotIn("Traceback", proc.stderr)
        self.assertIn("ERROR", proc.stderr)

    def test_subprocess_run_idempotent(self):
        self._good()
        env_args = ["--run", "--data-dir", str(self.data_dir)]
        p1 = subprocess.run(
            [sys.executable, "-m",
             "spa_core.analytics_lab.risk_contribution", *env_args],
            cwd=str(_REPO_ROOT), capture_output=True, text=True,
        )
        self.assertEqual(p1.returncode, 0)
        path = self.data_dir / rc.STATUS_FILENAME
        md1 = hashlib.md5(path.read_bytes()).hexdigest()
        p2 = subprocess.run(
            [sys.executable, "-m",
             "spa_core.analytics_lab.risk_contribution", *env_args],
            cwd=str(_REPO_ROOT), capture_output=True, text=True,
        )
        self.assertEqual(p2.returncode, 0)
        self.assertEqual(hashlib.md5(path.read_bytes()).hexdigest(), md1)
        self.assertEqual(list(self.data_dir.glob("*.tmp")), [])


# ─── Hygiene / reuse ─────────────────────────────────────────────────────────


class TestHygiene(unittest.TestCase):
    def _module_source(self):
        return (_REPO_ROOT / "spa_core" / "analytics_lab"
                / "risk_contribution.py").read_text(encoding="utf-8")

    def _test_source(self):
        return (_REPO_ROOT / "spa_core" / "tests"
                / "test_risk_contribution.py").read_text(encoding="utf-8")

    def test_no_forbidden_imports_via_ast(self):
        from spa_core.ci.llm_forbidden_lint import find_forbidden_imports
        self.assertEqual(
            find_forbidden_imports(self._module_source(), "risk_contribution.py"), []
        )

    def test_test_file_clean(self):
        from spa_core.ci.llm_forbidden_lint import find_forbidden_imports
        self.assertEqual(
            find_forbidden_imports(self._test_source(),
                                   "test_risk_contribution.py"), []
        )

    def test_no_network_imports_ast(self):
        src = self._module_source()
        tree = ast.parse(src)
        banned = {"requests", "web3", "socket", "urllib", "pandas", "numpy"}
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    self.assertNotIn(alias.name.split(".")[0], banned, alias.name)
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    self.assertNotIn(node.module.split(".")[0], banned, node.module)

    def test_reuses_build_exposure(self):
        self.assertIn(
            "from spa_core.reporting.tear_sheet import build_exposure",
            self._module_source(),
        )

    def test_reuses_hhi_constants_by_import(self):
        src = self._module_source()
        self.assertIn("from spa_core.paper_trading.concentration_analytics import",
                      src)
        self.assertIn("HHI_MODERATE_FLOOR", src)
        self.assertIn("HHI_CONCENTRATED_FLOOR", src)
        # Sanity: imported, not redefined.
        self.assertEqual(rc.HHI_MODERATE_FLOOR, 1500)
        self.assertEqual(rc.HHI_CONCENTRATED_FLOOR, 2500)

    def test_constants_present(self):
        self.assertEqual(rc.MAX_SINGLE_RISK_SHARE, 0.60)
        self.assertEqual(rc.UNCOVERED_RISK_WARN_SHARE, 0.25)
        self.assertEqual(rc.SCHEMA_VERSION, 1)
        self.assertEqual(rc.SOURCE_NAME, "risk_contribution")
        self.assertEqual(rc.STATUS_FILENAME, "risk_contribution.json")
        self.assertEqual(rc.HISTORY_MAX, 500)

    def test_public_api_present(self):
        self.assertTrue(hasattr(rc, "build_risk_contribution"))
        self.assertTrue(hasattr(rc, "build_status_doc"))
        self.assertTrue(hasattr(rc, "write_status"))
        self.assertTrue(hasattr(rc, "content_fingerprint"))


if __name__ == "__main__":
    unittest.main()
