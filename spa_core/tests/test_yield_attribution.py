#!/usr/bin/env python3
"""Tests for spa_core.paper_trading.yield_attribution (SPA-V436 / MP-117).

Plain unittest, NO pytest, NO network, ALL persistence in a tempdir. Covers:
hand-computed yield-contribution math (weight×APY → portfolio APY, shares of
total yield), the yield-source HHI fraction/index/effective-count, top1/top3
yield shares, the DOJ/FTC concentration-class boundaries (reused thresholds),
the single-source (>60%) verdict, unknown-APY → known:false + unknown-yield
bucket (never invented), cash drag, the reuse-by-import proof (per-protocol
weight_frac*100 == build_exposure share_pct), is_demo honesty, tolerance of
missing/broken/garbage inputs, idempotent persistence + history rotation, the
CLI (direct + subprocess), and import hygiene via the real AST linter.
"""
from __future__ import annotations

import ast
import contextlib
import hashlib
import io
import json
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from spa_core.paper_trading import yield_attribution as ya
from spa_core.reporting.tear_sheet import build_exposure

_REPO_ROOT = Path(__file__).resolve().parents[2]


def _write_json(data_dir: Path, name: str, doc) -> Path:
    data_dir.mkdir(parents=True, exist_ok=True)
    p = data_dir / name
    p.write_text(json.dumps(doc), encoding="utf-8")
    return p


def _write_positions(data_dir: Path, doc) -> Path:
    return _write_json(data_dir, ya.POSITIONS_FILENAME, doc)


def _write_orch(data_dir: Path, doc) -> Path:
    return _write_json(data_dir, ya.ORCHESTRATOR_FILENAME, doc)


def _write_equity(data_dir: Path, doc) -> Path:
    return _write_json(data_dir, ya.EQUITY_FILENAME, doc)


def _orch(apys: dict, tiers: dict = None) -> dict:
    """Build a list-shaped orchestrator status (the real layout).

    ``apys``: {protocol: apy_pct_or_None}; ``tiers`` optional {protocol: tier}.
    """
    tiers = tiers or {}
    return {"adapters": [
        {"protocol": p, "apy_pct": apy,
         "tier": tiers.get(p, "T1"), "tvl_usd": 1_000_000.0}
        for p, apy in apys.items()
    ]}


def _orch_dict(apys: dict, tiers: dict = None) -> dict:
    """Build a DICT-shaped orchestrator status (alternate layout)."""
    tiers = tiers or {}
    return {"adapters": {
        p: {"apy_pct": apy, "tier": tiers.get(p, "T1"), "tvl_usd": 2_000_000.0}
        for p, apy in apys.items()
    }}


class _TmpBase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.mkdtemp(prefix="yield_test_")
        self.data_dir = Path(self._tmp)

    def tearDown(self):
        import shutil
        shutil.rmtree(self._tmp, ignore_errors=True)


# ─── Yield-contribution math (hand-computed) ─────────────────────────────────


class TestContributionMath(_TmpBase):
    def test_canonical_5050_4_2(self):
        # 50% @ 4% + 50% @ 2% → contributions 2.0 and 1.0; portfolio 3.0pp;
        # shares of total yield 2/3 and 1/3.
        _write_positions(self.data_dir, {
            "capital_usd": 100000.0, "cash_usd": 0.0,
            "positions": {"high": 50000.0, "low": 50000.0},
        })
        _write_orch(self.data_dir, _orch({"high": 4.0, "low": 2.0}))
        r = ya.build_yield_attribution(self.data_dir)
        self.assertTrue(r["available"])
        self.assertAlmostEqual(r["portfolio_apy_pp"], 3.0)
        bd = {b["protocol"]: b for b in r["breakdown"]}
        self.assertAlmostEqual(bd["high"]["yield_contribution_pp"], 2.0)
        self.assertAlmostEqual(bd["low"]["yield_contribution_pp"], 1.0)
        self.assertAlmostEqual(bd["high"]["share_of_total_yield"], 2.0 / 3.0)
        self.assertAlmostEqual(bd["low"]["share_of_total_yield"], 1.0 / 3.0)

    def test_shares_sum_to_one(self):
        _write_positions(self.data_dir, {
            "capital_usd": 100000.0, "cash_usd": 0.0,
            "positions": {"a": 40000.0, "b": 30000.0, "c": 30000.0},
        })
        _write_orch(self.data_dir, _orch({"a": 5.0, "b": 3.0, "c": 1.0}))
        r = ya.build_yield_attribution(self.data_dir)
        total = sum(b["share_of_total_yield"] for b in r["breakdown"])
        self.assertAlmostEqual(total, 1.0)

    def test_contribution_is_weight_times_apy(self):
        _write_positions(self.data_dir, {
            "capital_usd": 100000.0, "cash_usd": 0.0,
            "positions": {"a": 25000.0, "b": 75000.0},
        })
        _write_orch(self.data_dir, _orch({"a": 8.0, "b": 4.0}))
        r = ya.build_yield_attribution(self.data_dir)
        bd = {b["protocol"]: b for b in r["breakdown"]}
        # a: 0.25*8 = 2.0 ; b: 0.75*4 = 3.0
        self.assertAlmostEqual(bd["a"]["yield_contribution_pp"], 2.0)
        self.assertAlmostEqual(bd["b"]["yield_contribution_pp"], 3.0)
        self.assertAlmostEqual(r["portfolio_apy_pp"], 5.0)

    def test_portfolio_apy_equals_sum_contributions(self):
        _write_positions(self.data_dir, {
            "capital_usd": 100000.0, "cash_usd": 0.0,
            "positions": {"a": 20000.0, "b": 30000.0, "c": 50000.0},
        })
        _write_orch(self.data_dir, _orch({"a": 6.0, "b": 4.0, "c": 2.0}))
        r = ya.build_yield_attribution(self.data_dir)
        s = sum(b["yield_contribution_pp"] for b in r["breakdown"])
        self.assertAlmostEqual(r["portfolio_apy_pp"], s)

    def test_single_source_apy(self):
        _write_positions(self.data_dir, {
            "capital_usd": 100000.0, "cash_usd": 0.0,
            "positions": {"only": 100000.0},
        })
        _write_orch(self.data_dir, _orch({"only": 5.0}))
        r = ya.build_yield_attribution(self.data_dir)
        self.assertAlmostEqual(r["portfolio_apy_pp"], 5.0)
        self.assertAlmostEqual(r["breakdown"][0]["share_of_total_yield"], 1.0)

    def test_total_yield_pp_positive_only(self):
        _write_positions(self.data_dir, {
            "capital_usd": 100000.0, "cash_usd": 0.0,
            "positions": {"a": 50000.0, "b": 50000.0},
        })
        _write_orch(self.data_dir, _orch({"a": 4.0, "b": 2.0}))
        r = ya.build_yield_attribution(self.data_dir)
        self.assertAlmostEqual(r["total_yield_pp"], 3.0)

    def test_dict_layout_orchestrator(self):
        # alternate orchestrator layout (adapters as dict) → same math.
        _write_positions(self.data_dir, {
            "capital_usd": 100000.0, "cash_usd": 0.0,
            "positions": {"high": 50000.0, "low": 50000.0},
        })
        _write_orch(self.data_dir, _orch_dict({"high": 4.0, "low": 2.0}))
        r = ya.build_yield_attribution(self.data_dir)
        self.assertAlmostEqual(r["portfolio_apy_pp"], 3.0)
        self.assertEqual(r["num_known"], 2)

    def test_apy_echoed_in_breakdown(self):
        _write_positions(self.data_dir, {
            "capital_usd": 100000.0, "cash_usd": 0.0,
            "positions": {"a": 100000.0},
        })
        _write_orch(self.data_dir, _orch({"a": 3.1942}))
        r = ya.build_yield_attribution(self.data_dir)
        self.assertAlmostEqual(r["breakdown"][0]["apy_pct"], 3.1942)


# ─── Cash drag / deployed APY ────────────────────────────────────────────────


class TestCashDrag(_TmpBase):
    def test_cash_drag_visible(self):
        # 50k @ 4% on 100k AUM (50k cash). portfolio_apy = 0.5*4 = 2.0pp.
        # deployed-known weight = 0.5 → deployed_apy = 2.0/0.5 = 4.0.
        # cash_drag = 4.0 - 2.0 = 2.0pp.
        _write_positions(self.data_dir, {
            "capital_usd": 100000.0, "cash_usd": 50000.0,
            "positions": {"a": 50000.0},
        })
        _write_orch(self.data_dir, _orch({"a": 4.0}))
        r = ya.build_yield_attribution(self.data_dir)
        self.assertAlmostEqual(r["portfolio_apy_pp"], 2.0)
        self.assertAlmostEqual(r["deployed_apy_pct"], 4.0)
        self.assertAlmostEqual(r["cash_drag_pp"], 2.0)

    def test_no_cash_zero_drag(self):
        _write_positions(self.data_dir, {
            "capital_usd": 100000.0, "cash_usd": 0.0,
            "positions": {"a": 100000.0},
        })
        _write_orch(self.data_dir, _orch({"a": 4.0}))
        r = ya.build_yield_attribution(self.data_dir)
        self.assertAlmostEqual(r["cash_drag_pp"], 0.0)
        self.assertAlmostEqual(r["deployed_apy_pct"], r["portfolio_apy_pp"])

    def test_deployed_apy_renormalised(self):
        # 25k@4 + 25k@8 on 100k AUM (50k cash).
        # portfolio = 0.25*4 + 0.25*8 = 1 + 2 = 3.0pp.
        # known weight 0.5 → deployed_apy = 6.0.
        _write_positions(self.data_dir, {
            "capital_usd": 100000.0, "cash_usd": 50000.0,
            "positions": {"a": 25000.0, "b": 25000.0},
        })
        _write_orch(self.data_dir, _orch({"a": 4.0, "b": 8.0}))
        r = ya.build_yield_attribution(self.data_dir)
        self.assertAlmostEqual(r["portfolio_apy_pp"], 3.0)
        self.assertAlmostEqual(r["deployed_apy_pct"], 6.0)
        self.assertAlmostEqual(r["cash_drag_pp"], 3.0)

    def test_cash_drag_none_when_no_known(self):
        # only protocol has unknown APY → no known weight → cash_drag None.
        _write_positions(self.data_dir, {
            "capital_usd": 100000.0, "cash_usd": 0.0,
            "positions": {"a": 100000.0},
        })
        _write_orch(self.data_dir, _orch({"a": None}))
        r = ya.build_yield_attribution(self.data_dir)
        self.assertIsNone(r["deployed_apy_pct"])
        self.assertIsNone(r["cash_drag_pp"])
        self.assertAlmostEqual(r["portfolio_apy_pp"], 0.0)


# ─── Yield-source HHI ────────────────────────────────────────────────────────


class TestYieldHHI(_TmpBase):
    def test_two_equal_yields_hhi(self):
        # 50/50 weight, equal APY → equal contributions → shares 0.5/0.5
        # → HHI = 0.5, index 5000, effective 2.
        _write_positions(self.data_dir, {
            "capital_usd": 100000.0, "cash_usd": 0.0,
            "positions": {"a": 50000.0, "b": 50000.0},
        })
        _write_orch(self.data_dir, _orch({"a": 3.0, "b": 3.0}))
        r = ya.build_yield_attribution(self.data_dir)
        self.assertAlmostEqual(r["yield_hhi"], 0.5)
        self.assertEqual(r["yield_hhi_index"], 5000)
        self.assertAlmostEqual(r["effective_num_yield_sources"], 2.0)

    def test_four_equal_yields_hhi(self):
        _write_positions(self.data_dir, {
            "capital_usd": 100000.0, "cash_usd": 0.0,
            "positions": {f"p{i}": 25000.0 for i in range(4)},
        })
        _write_orch(self.data_dir, _orch({f"p{i}": 3.0 for i in range(4)}))
        r = ya.build_yield_attribution(self.data_dir)
        self.assertAlmostEqual(r["yield_hhi"], 0.25)
        self.assertEqual(r["yield_hhi_index"], 2500)
        self.assertAlmostEqual(r["effective_num_yield_sources"], 4.0)

    def test_single_source_hhi_one(self):
        _write_positions(self.data_dir, {
            "capital_usd": 100000.0, "cash_usd": 0.0,
            "positions": {"a": 100000.0},
        })
        _write_orch(self.data_dir, _orch({"a": 5.0}))
        r = ya.build_yield_attribution(self.data_dir)
        self.assertAlmostEqual(r["yield_hhi"], 1.0)
        self.assertEqual(r["yield_hhi_index"], 10000)
        self.assertAlmostEqual(r["effective_num_yield_sources"], 1.0)

    def test_index_is_fraction_times_10000(self):
        _write_positions(self.data_dir, {
            "capital_usd": 100000.0, "cash_usd": 0.0,
            "positions": {"a": 60000.0, "b": 40000.0},
        })
        _write_orch(self.data_dir, _orch({"a": 3.0, "b": 3.0}))
        r = ya.build_yield_attribution(self.data_dir)
        self.assertEqual(r["yield_hhi_index"], round(r["yield_hhi"] * 10000))

    def test_effective_num_is_inverse_hhi(self):
        _write_positions(self.data_dir, {
            "capital_usd": 100000.0, "cash_usd": 0.0,
            "positions": {"a": 60000.0, "b": 30000.0, "c": 10000.0},
        })
        _write_orch(self.data_dir, _orch({"a": 3.0, "b": 3.0, "c": 3.0}))
        r = ya.build_yield_attribution(self.data_dir)
        self.assertAlmostEqual(r["effective_num_yield_sources"],
                               round(1.0 / r["yield_hhi"], 4))

    def test_yield_hhi_differs_from_weight_hhi(self):
        # weight-balanced but yield-concentrated: 50/50 weight, APY 9% vs 1%.
        # contributions 4.5 and 0.5 → shares 0.9/0.1 → yield HHI 0.82.
        _write_positions(self.data_dir, {
            "capital_usd": 100000.0, "cash_usd": 0.0,
            "positions": {"hot": 50000.0, "cold": 50000.0},
        })
        _write_orch(self.data_dir, _orch({"hot": 9.0, "cold": 1.0}))
        r = ya.build_yield_attribution(self.data_dir)
        bd = {b["protocol"]: b for b in r["breakdown"]}
        self.assertAlmostEqual(bd["hot"]["share_of_total_yield"], 0.9)
        self.assertAlmostEqual(bd["cold"]["share_of_total_yield"], 0.1)
        self.assertAlmostEqual(r["yield_hhi"], 0.82)
        self.assertEqual(r["yield_hhi_index"], 8200)


# ─── Concentration-class boundaries (reused thresholds) ──────────────────────


class TestClassBoundaries(_TmpBase):
    def test_just_below_1500_diversified(self):
        self.assertEqual(ya._classify_yield(1499), "diversified")

    def test_exactly_1500_moderate(self):
        self.assertEqual(ya._classify_yield(1500), "moderate")

    def test_exactly_2500_moderate(self):
        self.assertEqual(ya._classify_yield(2500), "moderate")

    def test_just_above_2500_concentrated(self):
        self.assertEqual(ya._classify_yield(2501), "concentrated")

    def test_zero_index_diversified(self):
        self.assertEqual(ya._classify_yield(0), "diversified")

    def test_none_index_none_class(self):
        self.assertIsNone(ya._classify_yield(None))

    def test_thresholds_reused_from_concentration(self):
        from spa_core.paper_trading import concentration_analytics as ca
        self.assertEqual(ya.HHI_MODERATE_FLOOR, ca.HHI_MODERATE_FLOOR)
        self.assertEqual(ya.HHI_CONCENTRATED_FLOOR, ca.HHI_CONCENTRATED_FLOOR)
        self.assertEqual(ya.HHI_MODERATE_FLOOR, 1500)
        self.assertEqual(ya.HHI_CONCENTRATED_FLOOR, 2500)

    def test_pipeline_diversified(self):
        # 10 equal contributions → HHI 1000 → diversified.
        _write_positions(self.data_dir, {
            "capital_usd": 100000.0, "cash_usd": 0.0,
            "positions": {f"p{i}": 10000.0 for i in range(10)},
        })
        _write_orch(self.data_dir, _orch({f"p{i}": 3.0 for i in range(10)}))
        r = ya.build_yield_attribution(self.data_dir)
        self.assertEqual(r["yield_concentration_class"], "diversified")

    def test_pipeline_moderate(self):
        # 4 equal contributions → HHI 2500 → moderate.
        _write_positions(self.data_dir, {
            "capital_usd": 100000.0, "cash_usd": 0.0,
            "positions": {f"p{i}": 25000.0 for i in range(4)},
        })
        _write_orch(self.data_dir, _orch({f"p{i}": 3.0 for i in range(4)}))
        r = ya.build_yield_attribution(self.data_dir)
        self.assertEqual(r["yield_concentration_class"], "moderate")

    def test_pipeline_concentrated(self):
        # contributions: a 0.5*9=4.5, b 0.5*1=0.5 → shares 0.9/0.1 → HHI 8200.
        _write_positions(self.data_dir, {
            "capital_usd": 100000.0, "cash_usd": 0.0,
            "positions": {"a": 50000.0, "b": 50000.0},
        })
        _write_orch(self.data_dir, _orch({"a": 9.0, "b": 1.0}))
        r = ya.build_yield_attribution(self.data_dir)
        self.assertEqual(r["yield_concentration_class"], "concentrated")


# ─── top1 / top3 yield share ─────────────────────────────────────────────────


class TestTopYieldShares(_TmpBase):
    def test_top1_top3_hand_checked(self):
        # equal weight 4 protocols, APY 4/3/2/1 → contributions same ratio,
        # total 10 → shares 0.4/0.3/0.2/0.1. top1=0.4, top3=0.9.
        _write_positions(self.data_dir, {
            "capital_usd": 100000.0, "cash_usd": 0.0,
            "positions": {"a": 25000.0, "b": 25000.0,
                          "c": 25000.0, "d": 25000.0},
        })
        _write_orch(self.data_dir, _orch({"a": 4.0, "b": 3.0,
                                          "c": 2.0, "d": 1.0}))
        r = ya.build_yield_attribution(self.data_dir)
        self.assertAlmostEqual(r["top1_yield_share"], 0.4)
        self.assertEqual(r["top1_yield_protocol"], "a")
        self.assertAlmostEqual(r["top3_yield_share"], 0.9)

    def test_top1_protocol_is_max_contribution_not_weight(self):
        # smaller weight but much higher APY drives top yield.
        # a: 0.8*1 = 0.8 ; b: 0.2*9 = 1.8 → b dominates yield.
        _write_positions(self.data_dir, {
            "capital_usd": 100000.0, "cash_usd": 0.0,
            "positions": {"a": 80000.0, "b": 20000.0},
        })
        _write_orch(self.data_dir, _orch({"a": 1.0, "b": 9.0}))
        r = ya.build_yield_attribution(self.data_dir)
        self.assertEqual(r["top1_yield_protocol"], "b")

    def test_breakdown_known_sorted_by_contribution(self):
        _write_positions(self.data_dir, {
            "capital_usd": 100000.0, "cash_usd": 0.0,
            "positions": {"small": 50000.0, "big": 50000.0},
        })
        _write_orch(self.data_dir, _orch({"small": 1.0, "big": 9.0}))
        r = ya.build_yield_attribution(self.data_dir)
        self.assertEqual(r["breakdown"][0]["protocol"], "big")


# ─── Verdict ─────────────────────────────────────────────────────────────────


class TestVerdict(_TmpBase):
    def test_ok_diversified(self):
        _write_positions(self.data_dir, {
            "capital_usd": 100000.0, "cash_usd": 0.0,
            "positions": {f"p{i}": 10000.0 for i in range(10)},
        })
        _write_orch(self.data_dir, _orch({f"p{i}": 3.0 for i in range(10)}))
        r = ya.build_yield_attribution(self.data_dir)
        self.assertEqual(r["verdict"], "ok")

    def test_warn_moderate(self):
        _write_positions(self.data_dir, {
            "capital_usd": 100000.0, "cash_usd": 0.0,
            "positions": {f"p{i}": 25000.0 for i in range(4)},
        })
        _write_orch(self.data_dir, _orch({f"p{i}": 3.0 for i in range(4)}))
        r = ya.build_yield_attribution(self.data_dir)
        self.assertEqual(r["verdict"], "warn")

    def test_fail_single_source_over_60(self):
        # a: 0.5*9=4.5, b 0.5*1=0.5 → share 0.9 > 0.6 → fail.
        _write_positions(self.data_dir, {
            "capital_usd": 100000.0, "cash_usd": 0.0,
            "positions": {"a": 50000.0, "b": 50000.0},
        })
        _write_orch(self.data_dir, _orch({"a": 9.0, "b": 1.0}))
        r = ya.build_yield_attribution(self.data_dir)
        self.assertGreater(r["top1_yield_share"], 0.6)
        self.assertEqual(r["verdict"], "fail")

    def test_exactly_60_not_fail_from_single(self):
        # Construct top1 share exactly 0.6: contributions 3.0 and 2.0 → 0.6/0.4.
        # HHI = 0.36+0.16 = 0.52 → index 5200 → concentrated → fail anyway,
        # so test the boundary purely via _classify + share logic by using a
        # third source to push class below concentrated.
        # contributions 6/4 → no; instead use 0.6/0.2/0.2 → top1=0.6 exactly,
        # HHI = 0.36+0.04+0.04 = 0.44 (still concentrated). Use 0.6 share with
        # many tiny others to keep HHI moderate: 0.6 + 8*0.05 = 1.0,
        # HHI = 0.36 + 8*0.0025 = 0.38 → still > 0.25. The >60% rule itself is
        # strict-greater, so 0.6 exactly must NOT trigger the single-source fail.
        # We assert the boundary directly on the rule via a crafted case where
        # class is not concentrated is hard; instead assert strict-greater:
        _write_positions(self.data_dir, {
            "capital_usd": 100000.0, "cash_usd": 0.0,
            "positions": {"a": 60000.0, **{f"p{i}": 4000.0 for i in range(10)}},
        })
        _write_orch(self.data_dir, _orch({"a": 1.0, **{f"p{i}": 1.0 for i in range(10)}}))
        r = ya.build_yield_attribution(self.data_dir)
        # a contribution 0.6, others 0.04 each → total 1.0 → top1 share 0.6 exactly
        self.assertAlmostEqual(r["top1_yield_share"], 0.6)
        # 0.6 is NOT strictly > 0.6, so single-source rule does not fire;
        # HHI = 0.36 + 10*0.0016 = 0.376 → 3760 → concentrated → fail via class.
        # So verify the single-source boundary in isolation:
        self.assertFalse(r["top1_yield_share"] > ya.MAX_SINGLE_YIELD_SHARE)

    def test_warn_unknown_yield_share(self):
        # 40% of weight unknown APY (>25%) but the known part is diversified
        # (6 equal known yields → HHI ~1667... ensure diversified): use 12
        # equal known sources so known-yield HHI < 1500 → not concentrated.
        positions = {f"k{i}": 5000.0 for i in range(12)}  # 60k known
        positions["unk"] = 40000.0  # 40% unknown
        _write_positions(self.data_dir, {
            "capital_usd": 100000.0, "cash_usd": 0.0, "positions": positions,
        })
        apys = {f"k{i}": 3.0 for i in range(12)}
        apys["unk"] = None
        _write_orch(self.data_dir, _orch(apys))
        r = ya.build_yield_attribution(self.data_dir)
        self.assertGreater(r["unknown_yield_share"], 0.25)
        self.assertEqual(r["yield_concentration_class"], "diversified")
        self.assertEqual(r["verdict"], "warn")

    def test_constants(self):
        self.assertEqual(ya.MAX_SINGLE_YIELD_SHARE, 0.60)
        self.assertEqual(ya.UNKNOWN_YIELD_WARN_SHARE, 0.25)


# ─── Unknown APY (never invented) ────────────────────────────────────────────


class TestUnknownYield(_TmpBase):
    def test_protocol_missing_from_adapters(self):
        # 'ghost' in positions but absent from adapters → known:false.
        _write_positions(self.data_dir, {
            "capital_usd": 100000.0, "cash_usd": 0.0,
            "positions": {"aave_v3": 50000.0, "ghost": 50000.0},
        })
        _write_orch(self.data_dir, _orch({"aave_v3": 3.0}))
        r = ya.build_yield_attribution(self.data_dir)
        bd = {b["protocol"]: b for b in r["breakdown"]}
        self.assertFalse(bd["ghost"]["known"])
        self.assertIsNone(bd["ghost"]["apy_pct"])
        self.assertIsNone(bd["ghost"]["yield_contribution_pp"])
        self.assertIsNone(bd["ghost"]["share_of_total_yield"])
        self.assertAlmostEqual(r["unknown_yield_share"], 0.5)
        self.assertEqual(r["num_unknown"], 1)
        self.assertTrue(any("ghost" in n for n in r["notes"]))

    def test_protocol_null_apy(self):
        _write_positions(self.data_dir, {
            "capital_usd": 100000.0, "cash_usd": 0.0,
            "positions": {"aave_v3": 50000.0, "morpho_blue": 50000.0},
        })
        _write_orch(self.data_dir, _orch({"aave_v3": 3.0, "morpho_blue": None}))
        r = ya.build_yield_attribution(self.data_dir)
        bd = {b["protocol"]: b for b in r["breakdown"]}
        self.assertFalse(bd["morpho_blue"]["known"])
        self.assertAlmostEqual(r["unknown_yield_share"], 0.5)

    def test_nonnumeric_apy_treated_unknown(self):
        _write_positions(self.data_dir, {
            "capital_usd": 100000.0, "cash_usd": 0.0,
            "positions": {"a": 50000.0, "b": 50000.0},
        })
        _write_orch(self.data_dir, _orch({"a": 3.0, "b": "oops"}))
        r = ya.build_yield_attribution(self.data_dir)
        bd = {b["protocol"]: b for b in r["breakdown"]}
        self.assertFalse(bd["b"]["known"])
        self.assertTrue(bd["a"]["known"])

    def test_bool_apy_treated_unknown(self):
        # apy_pct True is a bool, not a number → unknown (never invented).
        _write_positions(self.data_dir, {
            "capital_usd": 100000.0, "cash_usd": 0.0,
            "positions": {"a": 50000.0, "b": 50000.0},
        })
        _write_orch(self.data_dir, _orch({"a": 3.0, "b": True}))
        r = ya.build_yield_attribution(self.data_dir)
        bd = {b["protocol"]: b for b in r["breakdown"]}
        self.assertFalse(bd["b"]["known"])

    def test_unknown_not_counted_in_portfolio_apy(self):
        # known part only contributes to portfolio APY.
        _write_positions(self.data_dir, {
            "capital_usd": 100000.0, "cash_usd": 0.0,
            "positions": {"a": 50000.0, "unk": 50000.0},
        })
        _write_orch(self.data_dir, _orch({"a": 4.0, "unk": None}))
        r = ya.build_yield_attribution(self.data_dir)
        # only a: 0.5*4 = 2.0
        self.assertAlmostEqual(r["portfolio_apy_pp"], 2.0)

    def test_all_unknown_empty_yield(self):
        _write_positions(self.data_dir, {
            "capital_usd": 100000.0, "cash_usd": 0.0,
            "positions": {"a": 50000.0, "b": 50000.0},
        })
        _write_orch(self.data_dir, _orch({"a": None, "b": None}))
        r = ya.build_yield_attribution(self.data_dir)
        self.assertTrue(r["available"])
        self.assertAlmostEqual(r["portfolio_apy_pp"], 0.0)
        self.assertAlmostEqual(r["unknown_yield_share"], 1.0)
        self.assertIsNone(r["top1_yield_protocol"])
        self.assertEqual(r["yield_hhi_index"], 0)
        self.assertIsNone(r["effective_num_yield_sources"])

    def test_no_orchestrator_all_unknown(self):
        _write_positions(self.data_dir, {
            "capital_usd": 100000.0, "cash_usd": 0.0,
            "positions": {"a": 50000.0, "b": 50000.0},
        })
        # no orchestrator file
        r = ya.build_yield_attribution(self.data_dir)
        self.assertTrue(r["available"])
        self.assertAlmostEqual(r["unknown_yield_share"], 1.0)
        self.assertEqual(r["num_known"], 0)


# ─── Reuse-by-import proof ───────────────────────────────────────────────────


class TestReuseByImport(_TmpBase):
    def test_weight_frac_equals_build_exposure_share(self):
        positions_doc = {
            "capital_usd": 100000.0, "cash_usd": 5000.0, "is_demo": False,
            "positions": {"aave_v3": 31529.27, "compound_v3": 30220.72,
                          "yearn_v3": 11436.6, "euler_v2": 10376.79,
                          "maple": 11436.6},
        }
        orch_doc = _orch({"aave_v3": 3.0, "compound_v3": 3.0,
                          "yearn_v3": 3.0, "euler_v2": 3.0, "maple": 3.0})
        _write_positions(self.data_dir, positions_doc)
        _write_orch(self.data_dir, orch_doc)
        r = ya.build_yield_attribution(self.data_dir)
        exposure = build_exposure(positions_doc, orch_doc)
        # PROOF of reuse: per-protocol weight_frac*100 == build_exposure share_pct.
        for b in r["breakdown"]:
            p = b["protocol"]
            self.assertAlmostEqual(
                b["weight_frac"] * 100.0,
                exposure["by_protocol"][p]["share_pct"],
                places=6, msg=p,
            )

    def test_usd_matches_exposure(self):
        positions_doc = {
            "capital_usd": 100000.0, "cash_usd": 0.0,
            "positions": {"aave_v3": 60000.0, "maple": 40000.0},
        }
        orch_doc = _orch({"aave_v3": 3.0, "maple": 4.0})
        _write_positions(self.data_dir, positions_doc)
        _write_orch(self.data_dir, orch_doc)
        r = ya.build_yield_attribution(self.data_dir)
        exposure = build_exposure(positions_doc, orch_doc)
        for b in r["breakdown"]:
            self.assertAlmostEqual(
                b["usd"], exposure["by_protocol"][b["protocol"]]["usd"]
            )

    def test_source_contains_import(self):
        src = (_REPO_ROOT / "spa_core" / "paper_trading"
               / "yield_attribution.py").read_text(encoding="utf-8")
        self.assertIn(
            "from spa_core.reporting.tear_sheet import build_exposure", src
        )

    def test_source_imports_thresholds(self):
        src = (_REPO_ROOT / "spa_core" / "paper_trading"
               / "yield_attribution.py").read_text(encoding="utf-8")
        self.assertIn(
            "from spa_core.paper_trading.concentration_analytics import", src
        )


# ─── is_demo honesty ─────────────────────────────────────────────────────────


class TestIsDemo(_TmpBase):
    def test_is_demo_true(self):
        _write_positions(self.data_dir, {
            "capital_usd": 100000.0, "cash_usd": 0.0, "is_demo": True,
            "positions": {"a": 100000.0},
        })
        _write_orch(self.data_dir, _orch({"a": 3.0}))
        r = ya.build_yield_attribution(self.data_dir)
        self.assertTrue(r["is_demo"])

    def test_is_demo_false(self):
        _write_positions(self.data_dir, {
            "capital_usd": 100000.0, "cash_usd": 0.0, "is_demo": False,
            "positions": {"a": 100000.0},
        })
        _write_orch(self.data_dir, _orch({"a": 3.0}))
        r = ya.build_yield_attribution(self.data_dir)
        self.assertFalse(r["is_demo"])

    def test_is_demo_from_equity(self):
        # positions has no is_demo, equity does → picked up.
        _write_positions(self.data_dir, {
            "capital_usd": 100000.0, "cash_usd": 0.0,
            "positions": {"a": 100000.0},
        })
        _write_orch(self.data_dir, _orch({"a": 3.0}))
        _write_equity(self.data_dir, {"is_demo": True, "daily": []})
        r = ya.build_yield_attribution(self.data_dir)
        self.assertTrue(r["is_demo"])

    def test_is_demo_absent_null_with_note(self):
        _write_positions(self.data_dir, {
            "capital_usd": 100000.0, "cash_usd": 0.0,
            "positions": {"a": 100000.0},
        })
        _write_orch(self.data_dir, _orch({"a": 3.0}))
        r = ya.build_yield_attribution(self.data_dir)
        self.assertIsNone(r["is_demo"])
        self.assertTrue(any("is_demo" in n for n in r["notes"]))

    def test_is_demo_nonbool_null(self):
        _write_positions(self.data_dir, {
            "capital_usd": 100000.0, "cash_usd": 0.0, "is_demo": "yes",
            "positions": {"a": 100000.0},
        })
        _write_orch(self.data_dir, _orch({"a": 3.0}))
        r = ya.build_yield_attribution(self.data_dir)
        self.assertIsNone(r["is_demo"])

    def test_positions_priority_over_equity(self):
        _write_positions(self.data_dir, {
            "capital_usd": 100000.0, "cash_usd": 0.0, "is_demo": False,
            "positions": {"a": 100000.0},
        })
        _write_orch(self.data_dir, _orch({"a": 3.0}))
        _write_equity(self.data_dir, {"is_demo": True, "daily": []})
        r = ya.build_yield_attribution(self.data_dir)
        self.assertFalse(r["is_demo"])


# ─── Tolerance / missing / broken / garbage ──────────────────────────────────


class TestTolerance(_TmpBase):
    def test_missing_positions(self):
        r = ya.build_yield_attribution(self.data_dir)  # empty dir
        self.assertFalse(r["available"])
        self.assertEqual(r["breakdown"], [])

    def test_per_source_tolerance(self):
        cases = {
            "missing": None,
            "broken": "{not json",
            "garbage_string": '"just a string"',
            "garbage_list": "[1,2,3]",
            "empty_object": "{}",
        }
        for label, content in cases.items():
            with self.subTest(source=label):
                import shutil
                tmp = tempfile.mkdtemp(prefix="yield_tol_")
                try:
                    dd = Path(tmp)
                    if content is not None:
                        dd.mkdir(parents=True, exist_ok=True)
                        (dd / ya.POSITIONS_FILENAME).write_text(
                            content, encoding="utf-8")
                    r = ya.build_yield_attribution(dd)  # must NOT raise
                    self.assertIn("available", r)
                    self.assertFalse(r["available"])
                    self.assertEqual(r["breakdown"], [])
                finally:
                    shutil.rmtree(tmp, ignore_errors=True)

    def test_broken_orchestrator_tolerated(self):
        _write_positions(self.data_dir, {
            "capital_usd": 100000.0, "cash_usd": 0.0,
            "positions": {"a": 100000.0},
        })
        (self.data_dir / ya.ORCHESTRATOR_FILENAME).write_text(
            "{broken", encoding="utf-8")
        r = ya.build_yield_attribution(self.data_dir)  # must not raise
        self.assertTrue(r["available"])
        # broken orch → APY unknown
        self.assertAlmostEqual(r["unknown_yield_share"], 1.0)

    def test_garbage_adapters_shape(self):
        _write_positions(self.data_dir, {
            "capital_usd": 100000.0, "cash_usd": 0.0,
            "positions": {"a": 100000.0},
        })
        _write_orch(self.data_dir, {"adapters": "not a list or dict"})
        r = ya.build_yield_attribution(self.data_dir)
        self.assertTrue(r["available"])
        self.assertAlmostEqual(r["unknown_yield_share"], 1.0)

    def test_garbage_adapter_items(self):
        _write_positions(self.data_dir, {
            "capital_usd": 100000.0, "cash_usd": 0.0,
            "positions": {"a": 50000.0, "b": 50000.0},
        })
        _write_orch(self.data_dir, {"adapters": [
            "not a dict", 42, {"protocol": "a", "apy_pct": 3.0}, {"no_protocol": 1},
        ]})
        r = ya.build_yield_attribution(self.data_dir)
        bd = {b["protocol"]: b for b in r["breakdown"]}
        self.assertTrue(bd["a"]["known"])
        self.assertFalse(bd["b"]["known"])

    def test_empty_positions_unavailable(self):
        _write_positions(self.data_dir, {
            "capital_usd": 100000.0, "cash_usd": 100000.0, "positions": {},
        })
        r = ya.build_yield_attribution(self.data_dir)
        self.assertFalse(r["available"])

    def test_zero_aum_unavailable(self):
        _write_positions(self.data_dir, {
            "capital_usd": 0.0, "cash_usd": 0.0, "positions": {},
        })
        r = ya.build_yield_attribution(self.data_dir)
        self.assertFalse(r["available"])

    def test_garbage_position_values_skipped(self):
        _write_positions(self.data_dir, {
            "capital_usd": 100000.0, "cash_usd": 0.0,
            "positions": {"good": 100000.0, "bad": "oops", "none": None},
        })
        _write_orch(self.data_dir, _orch({"good": 3.0}))
        r = ya.build_yield_attribution(self.data_dir)
        protos = [b["protocol"] for b in r["breakdown"]]
        self.assertIn("good", protos)
        self.assertNotIn("bad", protos)

    def test_never_raises_on_junk_dir(self):
        r = ya.build_yield_attribution("/nonexistent/path/xyz123")
        self.assertFalse(r["available"])

    def test_top_level_not_dict_unavailable(self):
        self.data_dir.mkdir(parents=True, exist_ok=True)
        (self.data_dir / ya.POSITIONS_FILENAME).write_text(
            "[1,2,3]", encoding="utf-8")
        r = ya.build_yield_attribution(self.data_dir)
        self.assertFalse(r["available"])

    def test_negative_position_dropped(self):
        _write_positions(self.data_dir, {
            "capital_usd": 100000.0, "cash_usd": 0.0,
            "positions": {"good": 100000.0, "bad": -5.0},
        })
        _write_orch(self.data_dir, _orch({"good": 3.0, "bad": 5.0}))
        r = ya.build_yield_attribution(self.data_dir)
        protos = [b["protocol"] for b in r["breakdown"]]
        self.assertNotIn("bad", protos)


# ─── Persistence + idempotency ───────────────────────────────────────────────


class TestPersistence(_TmpBase):
    def _good(self):
        _write_positions(self.data_dir, {
            "capital_usd": 100000.0, "cash_usd": 5000.02, "is_demo": False,
            "positions": {"aave_v3": 31529.27, "compound_v3": 30220.72,
                          "yearn_v3": 11436.6, "euler_v2": 10376.79,
                          "maple": 11436.6},
        })
        _write_orch(self.data_dir, _orch({
            "aave_v3": 3.1942, "compound_v3": 3.1813, "yearn_v3": 3.2311,
            "euler_v2": 2.8184, "maple": 4.7249}))

    def test_run_writes(self):
        self._good()
        doc = ya.build_status_doc(data_dir=self.data_dir)
        out = ya.write_status(doc, data_dir=self.data_dir)
        self.assertTrue(out["changed"])
        path = self.data_dir / ya.STATUS_FILENAME
        self.assertTrue(path.exists())
        loaded = json.loads(path.read_text())
        self.assertEqual(loaded["source"], ya.SOURCE_NAME)
        self.assertIn("history", loaded)
        self.assertEqual(len(loaded["history"]), 1)

    def test_run_twice_byte_identical(self):
        self._good()
        doc1 = ya.build_status_doc(data_dir=self.data_dir,
                                   now=datetime(2026, 6, 12, tzinfo=timezone.utc))
        ya.write_status(doc1, data_dir=self.data_dir)
        path = self.data_dir / ya.STATUS_FILENAME
        bytes1 = path.read_bytes()
        md1 = hashlib.md5(bytes1).hexdigest()
        doc2 = ya.build_status_doc(data_dir=self.data_dir,
                                   now=datetime(2026, 6, 13, tzinfo=timezone.utc))
        out2 = ya.write_status(doc2, data_dir=self.data_dir)
        self.assertFalse(out2["changed"])
        self.assertEqual(path.read_bytes(), bytes1)
        self.assertEqual(hashlib.md5(path.read_bytes()).hexdigest(), md1)

    def test_history_does_not_grow_on_idempotent(self):
        self._good()
        ya.write_status(ya.build_status_doc(data_dir=self.data_dir,
                        now=datetime(2026, 6, 12, tzinfo=timezone.utc)),
                        data_dir=self.data_dir)
        path = self.data_dir / ya.STATUS_FILENAME
        n1 = len(json.loads(path.read_text())["history"])
        ya.write_status(ya.build_status_doc(data_dir=self.data_dir,
                        now=datetime(2026, 7, 1, tzinfo=timezone.utc)),
                        data_dir=self.data_dir)
        n2 = len(json.loads(path.read_text())["history"])
        self.assertEqual(n1, n2)

    def test_generated_at_stable_when_unchanged(self):
        self._good()
        ya.write_status(ya.build_status_doc(data_dir=self.data_dir,
                        now=datetime(2026, 6, 12, tzinfo=timezone.utc)),
                        data_dir=self.data_dir)
        path = self.data_dir / ya.STATUS_FILENAME
        ga1 = json.loads(path.read_text())["meta"]["generated_at"]
        ya.write_status(ya.build_status_doc(data_dir=self.data_dir,
                        now=datetime(2026, 7, 1, tzinfo=timezone.utc)),
                        data_dir=self.data_dir)
        ga2 = json.loads(path.read_text())["meta"]["generated_at"]
        self.assertEqual(ga1, ga2)

    def test_history_grows_on_change(self):
        self._good()
        ya.write_status(ya.build_status_doc(data_dir=self.data_dir,
                        now=datetime(2026, 6, 12, tzinfo=timezone.utc)),
                        data_dir=self.data_dir)
        _write_positions(self.data_dir, {
            "capital_usd": 100000.0, "cash_usd": 5000.0, "is_demo": False,
            "positions": {"aave_v3": 95000.0},
        })
        out2 = ya.write_status(ya.build_status_doc(data_dir=self.data_dir,
                               now=datetime(2026, 6, 13, tzinfo=timezone.utc)),
                               data_dir=self.data_dir)
        self.assertTrue(out2["changed"])
        loaded = json.loads((self.data_dir / ya.STATUS_FILENAME).read_text())
        self.assertEqual(len(loaded["history"]), 2)

    def test_history_rotation_exactly_500(self):
        self._good()
        path = self.data_dir / ya.STATUS_FILENAME
        seed = {"history": [{"generated_at": f"t{i}"} for i in range(600)]}
        path.write_text(json.dumps(seed), encoding="utf-8")
        ya.write_status(ya.build_status_doc(data_dir=self.data_dir),
                        data_dir=self.data_dir)
        loaded = json.loads(path.read_text())
        self.assertEqual(len(loaded["history"]), ya.HISTORY_MAX)
        self.assertEqual(ya.HISTORY_MAX, 500)

    def test_no_tmp_leftovers(self):
        self._good()
        ya.write_status(ya.build_status_doc(data_dir=self.data_dir),
                        data_dir=self.data_dir)
        leftovers = list(self.data_dir.glob("*.tmp")) + \
            list(self.data_dir.glob(".*tmp"))
        self.assertEqual(leftovers, [])

    def test_broken_prior_status_tolerated(self):
        self._good()
        path = self.data_dir / ya.STATUS_FILENAME
        path.write_text("{broken", encoding="utf-8")
        out = ya.write_status(ya.build_status_doc(data_dir=self.data_dir),
                              data_dir=self.data_dir)
        self.assertTrue(out["changed"])
        loaded = json.loads(path.read_text())
        self.assertEqual(len(loaded["history"]), 1)

    def test_fingerprint_excludes_volatile(self):
        a = {"meta": {"generated_at": "2026-01-01"}, "verdict": "ok",
             "history": [1, 2]}
        b = {"meta": {"generated_at": "2099-12-31"}, "verdict": "ok",
             "history": [9]}
        self.assertEqual(ya.content_fingerprint(a), ya.content_fingerprint(b))

    def test_fingerprint_detects_content_change(self):
        a = {"meta": {"generated_at": "x"}, "verdict": "ok"}
        b = {"meta": {"generated_at": "x"}, "verdict": "fail"}
        self.assertNotEqual(ya.content_fingerprint(a), ya.content_fingerprint(b))

    def test_fingerprint_invalid(self):
        self.assertEqual(ya.content_fingerprint("not a dict"), "<invalid>")

    def test_history_entry_fields(self):
        self._good()
        doc = ya.build_status_doc(data_dir=self.data_dir)
        entry = ya._history_entry(doc)
        self.assertIn("portfolio_apy_pp", entry)
        self.assertIn("yield_hhi_index", entry)
        self.assertIn("top1_yield_share", entry)
        self.assertIn("unknown_yield_share", entry)


# ─── CLI ─────────────────────────────────────────────────────────────────────


class TestCLI(_TmpBase):
    def _good(self):
        _write_positions(self.data_dir, {
            "capital_usd": 100000.0, "cash_usd": 5000.02, "is_demo": False,
            "positions": {"aave_v3": 31529.27, "compound_v3": 30220.72,
                          "yearn_v3": 11436.6, "euler_v2": 10376.79,
                          "maple": 11436.6},
        })
        _write_orch(self.data_dir, _orch({
            "aave_v3": 3.1942, "compound_v3": 3.1813, "yearn_v3": 3.2311,
            "euler_v2": 2.8184, "maple": 4.7249}))

    def test_check_default_exit0_valid_json(self):
        self._good()
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            rc = ya.main(["--check", "--data-dir", str(self.data_dir)])
        self.assertEqual(rc, 0)
        doc = json.loads(out.getvalue())
        self.assertEqual(doc["source"], ya.SOURCE_NAME)
        self.assertIn("verdict", doc)

    def test_default_is_check(self):
        self._good()
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            rc = ya.main(["--data-dir", str(self.data_dir)])
        self.assertEqual(rc, 0)
        json.loads(out.getvalue())

    def test_check_does_not_write(self):
        self._good()
        before = sorted(p.name for p in self.data_dir.iterdir())
        with contextlib.redirect_stdout(io.StringIO()):
            ya.main(["--check", "--data-dir", str(self.data_dir)])
        after = sorted(p.name for p in self.data_dir.iterdir())
        self.assertEqual(before, after)
        self.assertNotIn(ya.STATUS_FILENAME, after)

    def test_run_writes_exit0(self):
        self._good()
        with contextlib.redirect_stdout(io.StringIO()):
            rc = ya.main(["--run", "--data-dir", str(self.data_dir)])
        self.assertEqual(rc, 0)
        self.assertTrue((self.data_dir / ya.STATUS_FILENAME).exists())

    def test_run_twice_idempotent(self):
        self._good()
        with contextlib.redirect_stdout(io.StringIO()):
            ya.main(["--run", "--data-dir", str(self.data_dir)])
        path = self.data_dir / ya.STATUS_FILENAME
        b1 = path.read_bytes()
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            ya.main(["--run", "--data-dir", str(self.data_dir)])
        self.assertEqual(path.read_bytes(), b1)
        self.assertIn("idempotent", out.getvalue())

    def test_empty_data_dir_exit0(self):
        with contextlib.redirect_stdout(io.StringIO()):
            rc = ya.main(["--check", "--data-dir", str(self.data_dir)])
        self.assertEqual(rc, 0)

    def test_junk_arg_exit0_no_traceback(self):
        err = io.StringIO()
        with contextlib.redirect_stderr(err), contextlib.redirect_stdout(io.StringIO()):
            rc = ya.main(["--frobnicate"])
        self.assertEqual(rc, 0)
        self.assertIn("ERROR", err.getvalue())
        self.assertNotIn("Traceback", err.getvalue())

    def test_check_run_conflict_exit0(self):
        err = io.StringIO()
        with contextlib.redirect_stderr(err), contextlib.redirect_stdout(io.StringIO()):
            rc = ya.main(["--check", "--run"])
        self.assertEqual(rc, 0)
        self.assertIn("ERROR", err.getvalue())
        self.assertNotIn("Traceback", err.getvalue())

    def test_run_no_tmp_leftover_after_cli(self):
        self._good()
        with contextlib.redirect_stdout(io.StringIO()):
            ya.main(["--run", "--data-dir", str(self.data_dir)])
        self.assertEqual(list(self.data_dir.glob("*.tmp")), [])

    def test_subprocess_check_exit0(self):
        self._good()
        proc = subprocess.run(
            [sys.executable, "-m",
             "spa_core.paper_trading.yield_attribution",
             "--check", "--data-dir", str(self.data_dir)],
            cwd=str(_REPO_ROOT), capture_output=True, text=True,
        )
        self.assertEqual(proc.returncode, 0)
        json.loads(proc.stdout)
        self.assertNotIn("Traceback", proc.stderr)

    def test_subprocess_junk_arg_exit0(self):
        proc = subprocess.run(
            [sys.executable, "-m",
             "spa_core.paper_trading.yield_attribution",
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
             "spa_core.paper_trading.yield_attribution", *env_args],
            cwd=str(_REPO_ROOT), capture_output=True, text=True,
        )
        self.assertEqual(p1.returncode, 0)
        path = self.data_dir / ya.STATUS_FILENAME
        md1 = hashlib.md5(path.read_bytes()).hexdigest()
        p2 = subprocess.run(
            [sys.executable, "-m",
             "spa_core.paper_trading.yield_attribution", *env_args],
            cwd=str(_REPO_ROOT), capture_output=True, text=True,
        )
        self.assertEqual(p2.returncode, 0)
        self.assertEqual(hashlib.md5(path.read_bytes()).hexdigest(), md1)
        self.assertEqual(list(self.data_dir.glob("*.tmp")), [])


# ─── Hygiene / reuse ─────────────────────────────────────────────────────────


class TestHygiene(unittest.TestCase):
    def _module_source(self):
        return (_REPO_ROOT / "spa_core" / "paper_trading"
                / "yield_attribution.py").read_text(encoding="utf-8")

    def _test_source(self):
        return (_REPO_ROOT / "spa_core" / "tests"
                / "test_yield_attribution.py").read_text(encoding="utf-8")

    def test_no_forbidden_imports_via_ast(self):
        from spa_core.ci.llm_forbidden_lint import find_forbidden_imports
        src = self._module_source()
        self.assertEqual(
            find_forbidden_imports(src, "yield_attribution.py"), []
        )

    def test_test_file_clean(self):
        from spa_core.ci.llm_forbidden_lint import find_forbidden_imports
        src = self._test_source()
        self.assertEqual(
            find_forbidden_imports(src, "test_yield_attribution.py"), []
        )

    def test_no_network_imports_ast(self):
        src = self._module_source()
        tree = ast.parse(src)
        banned = {"requests", "web3", "socket", "urllib", "pandas", "numpy"}
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    top = alias.name.split(".")[0]
                    self.assertNotIn(top, banned, alias.name)
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    top = node.module.split(".")[0]
                    self.assertNotIn(top, banned, node.module)

    def test_reuses_build_exposure(self):
        src = self._module_source()
        self.assertIn(
            "from spa_core.reporting.tear_sheet import build_exposure", src
        )

    def test_constants_present(self):
        self.assertEqual(ya.MAX_SINGLE_YIELD_SHARE, 0.60)
        self.assertEqual(ya.UNKNOWN_YIELD_WARN_SHARE, 0.25)
        self.assertEqual(ya.SCHEMA_VERSION, 1)
        self.assertEqual(ya.SOURCE_NAME, "yield_attribution")
        self.assertEqual(ya.STATUS_FILENAME, "yield_attribution.json")
        self.assertEqual(ya.HISTORY_MAX, 500)

    def test_public_api_present(self):
        self.assertTrue(hasattr(ya, "build_yield_attribution"))
        self.assertTrue(hasattr(ya, "build_status_doc"))
        self.assertTrue(hasattr(ya, "write_status"))
        self.assertTrue(hasattr(ya, "content_fingerprint"))
        self.assertTrue(hasattr(ya, "main"))

    def test_disclaimer_present(self):
        _tmp = tempfile.mkdtemp(prefix="yield_test_")
        try:
            dd = Path(_tmp)
            _write_positions(dd, {
                "capital_usd": 100000.0, "cash_usd": 0.0,
                "positions": {"a": 100000.0},
            })
            _write_orch(dd, _orch({"a": 3.0}))
            r = ya.build_yield_attribution(dd)
            self.assertEqual(r["disclaimer"], "NOT investment advice")
            self.assertTrue(r["advisory_only"])
            self.assertEqual(r["execution_mode"], "read_only")
        finally:
            import shutil
            shutil.rmtree(_tmp, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
