#!/usr/bin/env python3
"""Tests for spa_core.paper_trading.concentration_analytics (SPA-V435 / MP-116).

Plain unittest, NO pytest, NO network, ALL persistence in a tempdir. Covers:
hand-computed HHI math (whole-AUM + deployed-only), the 0–10000 index scale,
effective number of positions, top1/top3 shares, DOJ/FTC concentration-class
boundaries, the max-single-position policy boundary, the reuse-by-import proof
(breakdown shares == build_exposure share_pct/100), is_demo honesty, tolerance
of missing/broken/garbage inputs, idempotent persistence + history rotation, the
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

from spa_core.paper_trading import concentration_analytics as ca
from spa_core.reporting.tear_sheet import build_exposure

_REPO_ROOT = Path(__file__).resolve().parents[2]


def _write_json(data_dir: Path, name: str, doc) -> Path:
    data_dir.mkdir(parents=True, exist_ok=True)
    p = data_dir / name
    p.write_text(json.dumps(doc), encoding="utf-8")
    return p


def _write_positions(data_dir: Path, doc) -> Path:
    return _write_json(data_dir, ca.POSITIONS_FILENAME, doc)


def _write_orch(data_dir: Path, doc) -> Path:
    return _write_json(data_dir, ca.ORCHESTRATOR_FILENAME, doc)


def _orch(tiers: dict) -> dict:
    return {"adapters": [{"protocol": p, "tier": t} for p, t in tiers.items()]}


class _TmpBase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.mkdtemp(prefix="conc_test_")
        self.data_dir = Path(self._tmp)

    def tearDown(self):
        import shutil
        shutil.rmtree(self._tmp, ignore_errors=True)


# ─── HHI math (hand-computed) ────────────────────────────────────────────────


class TestHHIMath(_TmpBase):
    def test_two_equal_5050_deployed(self):
        _write_positions(self.data_dir, {
            "capital_usd": 100000.0, "cash_usd": 0.0, "is_demo": False,
            "positions": {"aave_v3": 50000.0, "compound_v3": 50000.0},
        })
        r = ca.build_concentration(self.data_dir)
        self.assertTrue(r["available"])
        self.assertAlmostEqual(r["hhi_protocol_deployed"], 0.5)
        self.assertEqual(r["hhi_protocol_deployed_index"], 5000)
        self.assertAlmostEqual(r["effective_num_positions"], 2.0)
        self.assertEqual(r["concentration_class"], "concentrated")

    def test_four_equal_25pct(self):
        _write_positions(self.data_dir, {
            "capital_usd": 100000.0, "cash_usd": 0.0,
            "positions": {"a": 25000.0, "b": 25000.0,
                          "c": 25000.0, "d": 25000.0},
        })
        r = ca.build_concentration(self.data_dir)
        self.assertAlmostEqual(r["hhi_protocol_deployed"], 0.25)
        self.assertEqual(r["hhi_protocol_deployed_index"], 2500)
        # boundary: 2500 is moderate, not concentrated
        self.assertEqual(r["concentration_class"], "moderate")
        self.assertAlmostEqual(r["effective_num_positions"], 4.0)

    def test_five_equal_20pct(self):
        _write_positions(self.data_dir, {
            "capital_usd": 100000.0, "cash_usd": 0.0,
            "positions": {f"p{i}": 20000.0 for i in range(5)},
        })
        r = ca.build_concentration(self.data_dir)
        self.assertAlmostEqual(r["hhi_protocol_deployed"], 0.20)
        self.assertEqual(r["hhi_protocol_deployed_index"], 2000)
        self.assertEqual(r["concentration_class"], "moderate")
        self.assertAlmostEqual(r["effective_num_positions"], 5.0)

    def test_ten_equal_10pct(self):
        _write_positions(self.data_dir, {
            "capital_usd": 100000.0, "cash_usd": 0.0,
            "positions": {f"p{i}": 10000.0 for i in range(10)},
        })
        r = ca.build_concentration(self.data_dir)
        self.assertAlmostEqual(r["hhi_protocol_deployed"], 0.10)
        self.assertEqual(r["hhi_protocol_deployed_index"], 1000)
        self.assertEqual(r["concentration_class"], "diversified")
        self.assertAlmostEqual(r["effective_num_positions"], 10.0)

    def test_single_position(self):
        _write_positions(self.data_dir, {
            "capital_usd": 100000.0, "cash_usd": 0.0,
            "positions": {"aave_v3": 100000.0},
        })
        r = ca.build_concentration(self.data_dir)
        self.assertAlmostEqual(r["hhi_protocol_deployed"], 1.0)
        self.assertEqual(r["hhi_protocol_deployed_index"], 10000)
        self.assertAlmostEqual(r["effective_num_positions"], 1.0)
        self.assertEqual(r["concentration_class"], "concentrated")

    def test_index_is_fraction_times_10000(self):
        _write_positions(self.data_dir, {
            "capital_usd": 100000.0, "cash_usd": 0.0,
            "positions": {"a": 60000.0, "b": 40000.0},
        })
        r = ca.build_concentration(self.data_dir)
        self.assertEqual(r["hhi_protocol_deployed_index"],
                         round(r["hhi_protocol_deployed"] * 10000))
        self.assertEqual(r["hhi_protocol_index"],
                         round(r["hhi_protocol"] * 10000))

    def test_effective_num_is_inverse_hhi(self):
        _write_positions(self.data_dir, {
            "capital_usd": 100000.0, "cash_usd": 0.0,
            "positions": {"a": 60000.0, "b": 30000.0, "c": 10000.0},
        })
        r = ca.build_concentration(self.data_dir)
        self.assertAlmostEqual(r["effective_num_positions"],
                               round(1.0 / r["hhi_protocol_deployed"], 4))

    def test_whole_aum_hhi_diluted_by_cash(self):
        # 50/50 deployed but on 200k AUM (cash 100k): whole-AUM shares 0.25 each
        # → whole HHI = 2*0.0625 = 0.125; deployed HHI = 0.5.
        _write_positions(self.data_dir, {
            "capital_usd": 200000.0, "cash_usd": 100000.0,
            "positions": {"a": 50000.0, "b": 50000.0},
        })
        r = ca.build_concentration(self.data_dir)
        self.assertAlmostEqual(r["hhi_protocol"], 0.125)
        self.assertEqual(r["hhi_protocol_index"], 1250)
        self.assertAlmostEqual(r["hhi_protocol_deployed"], 0.5)
        self.assertEqual(r["hhi_protocol_deployed_index"], 5000)
        # class derives from DEPLOYED-only → concentrated (not diversified)
        self.assertEqual(r["concentration_class"], "concentrated")

    def test_hhi_protocol_deployed_le_whole_when_cash(self):
        _write_positions(self.data_dir, {
            "capital_usd": 100000.0, "cash_usd": 40000.0,
            "positions": {"a": 30000.0, "b": 30000.0},
        })
        r = ca.build_concentration(self.data_dir)
        self.assertGreater(r["hhi_protocol_deployed"], r["hhi_protocol"])


# ─── Concentration-class boundaries ──────────────────────────────────────────


class TestClassBoundaries(_TmpBase):
    def _class_for_index(self, idx):
        return ca._classify(idx)

    def test_just_below_1500_diversified(self):
        self.assertEqual(self._class_for_index(1499), "diversified")

    def test_exactly_1500_moderate(self):
        self.assertEqual(self._class_for_index(1500), "moderate")

    def test_exactly_2500_moderate(self):
        self.assertEqual(self._class_for_index(2500), "moderate")

    def test_just_above_2500_concentrated(self):
        self.assertEqual(self._class_for_index(2501), "concentrated")

    def test_none_index_none_class(self):
        self.assertIsNone(self._class_for_index(None))

    def test_constants(self):
        self.assertEqual(ca.HHI_MODERATE_FLOOR, 1500)
        self.assertEqual(ca.HHI_CONCENTRATED_FLOOR, 2500)

    def test_zero_index_diversified(self):
        self.assertEqual(self._class_for_index(0), "diversified")

    def test_full_pipeline_diversified_boundary(self):
        # 10 equal positions → index 1000 → diversified
        _write_positions(self.data_dir, {
            "capital_usd": 100000.0, "cash_usd": 0.0,
            "positions": {f"p{i}": 10000.0 for i in range(10)},
        })
        r = ca.build_concentration(self.data_dir)
        self.assertEqual(r["concentration_class"], "diversified")


# ─── top1 / top3 ─────────────────────────────────────────────────────────────


class TestTopShares(_TmpBase):
    def test_top1_top3_hand_checked(self):
        # AUM 100k: aave 40k, comp 30k, yearn 20k, euler 10k (no cash).
        _write_positions(self.data_dir, {
            "capital_usd": 100000.0, "cash_usd": 0.0,
            "positions": {"aave_v3": 40000.0, "compound_v3": 30000.0,
                          "yearn_v3": 20000.0, "euler_v2": 10000.0},
        })
        r = ca.build_concentration(self.data_dir)
        self.assertAlmostEqual(r["top1_share"], 0.40)
        self.assertEqual(r["top1_protocol"], "aave_v3")
        # top3 = 0.4 + 0.3 + 0.2 = 0.9
        self.assertAlmostEqual(r["top3_share"], 0.90)
        self.assertEqual(r["num_positions"], 4)

    def test_top1_with_cash(self):
        # 80k aave on 100k AUM (20k cash) → top1 share 0.8 of full AUM.
        _write_positions(self.data_dir, {
            "capital_usd": 100000.0, "cash_usd": 20000.0,
            "positions": {"aave_v3": 80000.0},
        })
        r = ca.build_concentration(self.data_dir)
        self.assertAlmostEqual(r["top1_share"], 0.80)
        self.assertEqual(r["top1_protocol"], "aave_v3")
        self.assertAlmostEqual(r["top3_share"], 0.80)  # only one position

    def test_breakdown_sorted_desc(self):
        _write_positions(self.data_dir, {
            "capital_usd": 100000.0, "cash_usd": 0.0,
            "positions": {"small": 10000.0, "big": 90000.0},
        })
        r = ca.build_concentration(self.data_dir)
        shares = [b["share"] for b in r["breakdown"]]
        self.assertEqual(shares, sorted(shares, reverse=True))
        self.assertEqual(r["breakdown"][0]["protocol"], "big")


# ─── Max-single-position policy boundary ─────────────────────────────────────


class TestPolicy(_TmpBase):
    def test_exactly_40pct_not_breach(self):
        # aave exactly 0.40 of full AUM → policy_ok true.
        _write_positions(self.data_dir, {
            "capital_usd": 100000.0, "cash_usd": 0.0,
            "positions": {"aave_v3": 40000.0, "b": 30000.0, "c": 30000.0},
        })
        r = ca.build_concentration(self.data_dir)
        self.assertAlmostEqual(r["top1_share"], 0.40)
        self.assertTrue(r["policy_ok"])
        self.assertEqual(r["policy_breaches"], [])

    def test_above_40pct_breach_fail(self):
        # aave 40.01k on 100k = 0.4001 > 0.40 → breach, verdict fail.
        _write_positions(self.data_dir, {
            "capital_usd": 100000.0, "cash_usd": 0.0,
            "positions": {"aave_v3": 40010.0, "b": 30000.0, "c": 29990.0},
        })
        r = ca.build_concentration(self.data_dir)
        self.assertFalse(r["policy_ok"])
        self.assertEqual(len(r["policy_breaches"]), 1)
        self.assertEqual(r["policy_breaches"][0]["protocol"], "aave_v3")
        self.assertEqual(r["verdict"], "fail")

    def test_constant_value(self):
        self.assertEqual(ca.MAX_SINGLE_POSITION_SHARE, 0.40)

    def test_breach_share_recorded(self):
        _write_positions(self.data_dir, {
            "capital_usd": 100000.0, "cash_usd": 0.0,
            "positions": {"aave_v3": 60000.0, "b": 40000.0},
        })
        r = ca.build_concentration(self.data_dir)
        self.assertAlmostEqual(r["policy_breaches"][0]["share"], 0.60)
        self.assertEqual(r["counts"]["policy_breaches"], 1)

    def test_multiple_breaches_sorted(self):
        # two breaches: 0.5 and 0.45; should sort desc.
        _write_positions(self.data_dir, {
            "capital_usd": 100000.0, "cash_usd": 0.0,
            "positions": {"big": 50000.0, "mid": 45000.0, "small": 5000.0},
        })
        r = ca.build_concentration(self.data_dir)
        shares = [b["share"] for b in r["policy_breaches"]]
        self.assertEqual(shares, sorted(shares, reverse=True))
        self.assertEqual(r["policy_breaches"][0]["protocol"], "big")


# ─── Verdict ─────────────────────────────────────────────────────────────────


class TestVerdict(_TmpBase):
    def test_ok_diversified_no_breach(self):
        _write_positions(self.data_dir, {
            "capital_usd": 100000.0, "cash_usd": 0.0,
            "positions": {f"p{i}": 10000.0 for i in range(10)},
        })
        _write_orch(self.data_dir, _orch({f"p{i}": "T1" for i in range(10)}))
        r = ca.build_concentration(self.data_dir)
        self.assertEqual(r["verdict"], "ok")

    def test_warn_moderate(self):
        # 4 equal → index 2500 moderate → warn (no breach)
        _write_positions(self.data_dir, {
            "capital_usd": 100000.0, "cash_usd": 0.0,
            "positions": {"a": 25000.0, "b": 25000.0,
                          "c": 25000.0, "d": 25000.0},
        })
        _write_orch(self.data_dir, _orch({"a": "T1", "b": "T1",
                                          "c": "T1", "d": "T1"}))
        r = ca.build_concentration(self.data_dir)
        self.assertEqual(r["verdict"], "warn")

    def test_warn_unknown_tier(self):
        # diversified but a protocol has no tier (unknown) → warn
        _write_positions(self.data_dir, {
            "capital_usd": 100000.0, "cash_usd": 0.0,
            "positions": {f"p{i}": 10000.0 for i in range(10)},
        })
        # no orchestrator at all → all unknown
        r = ca.build_concentration(self.data_dir)
        self.assertEqual(r["verdict"], "warn")
        self.assertIn("unknown", r["by_tier"])

    def test_fail_concentrated(self):
        _write_positions(self.data_dir, {
            "capital_usd": 100000.0, "cash_usd": 0.0,
            "positions": {"a": 30000.0, "b": 30000.0, "c": 40000.0},
        })
        _write_orch(self.data_dir, _orch({"a": "T1", "b": "T1", "c": "T1"}))
        r = ca.build_concentration(self.data_dir)
        # deployed HHI = .09+.09+.16 = .34 → 3400 concentrated → fail
        self.assertEqual(r["concentration_class"], "concentrated")
        self.assertEqual(r["verdict"], "fail")

    def test_fail_breach_beats_diversified(self):
        # spread thin but one breach → fail regardless of class
        _write_positions(self.data_dir, {
            "capital_usd": 100000.0, "cash_usd": 0.0,
            "positions": {"big": 45000.0, **{f"p{i}": 5500.0 for i in range(10)}},
        })
        _write_orch(self.data_dir, _orch({"big": "T1"}))
        r = ca.build_concentration(self.data_dir)
        self.assertFalse(r["policy_ok"])
        self.assertEqual(r["verdict"], "fail")


# ─── Tier HHI ────────────────────────────────────────────────────────────────


class TestTierHHI(_TmpBase):
    def test_single_tier(self):
        # all T1 → tier HHI over by_tier; deployed-only=100% → but by_tier is
        # percent-of-AUM. With no cash both T1=100% → hhi_tier=1.0
        _write_positions(self.data_dir, {
            "capital_usd": 100000.0, "cash_usd": 0.0,
            "positions": {"a": 50000.0, "b": 50000.0},
        })
        _write_orch(self.data_dir, _orch({"a": "T1", "b": "T1"}))
        r = ca.build_concentration(self.data_dir)
        self.assertAlmostEqual(r["hhi_tier"], 1.0)
        self.assertEqual(r["hhi_tier_index"], 10000)

    def test_two_tiers_5050(self):
        _write_positions(self.data_dir, {
            "capital_usd": 100000.0, "cash_usd": 0.0,
            "positions": {"a": 50000.0, "b": 50000.0},
        })
        _write_orch(self.data_dir, _orch({"a": "T1", "b": "T2"}))
        r = ca.build_concentration(self.data_dir)
        self.assertAlmostEqual(r["hhi_tier"], 0.5)
        self.assertEqual(r["hhi_tier_index"], 5000)

    def test_tier_echo_present(self):
        _write_positions(self.data_dir, {
            "capital_usd": 100000.0, "cash_usd": 0.0,
            "positions": {"a": 50000.0, "b": 50000.0},
        })
        _write_orch(self.data_dir, _orch({"a": "T1", "b": "T2"}))
        r = ca.build_concentration(self.data_dir)
        self.assertIn("T1", r["by_tier"])
        self.assertIn("T2", r["by_tier"])


# ─── Reuse-by-import proof ───────────────────────────────────────────────────


class TestReuseByImport(_TmpBase):
    def test_breakdown_shares_equal_build_exposure(self):
        positions_doc = {
            "capital_usd": 100000.0, "cash_usd": 5000.0, "is_demo": False,
            "positions": {"aave_v3": 31529.27, "compound_v3": 30220.72,
                          "yearn_v3": 11436.6, "euler_v2": 10376.79,
                          "maple": 11436.6},
        }
        orch_doc = _orch({"aave_v3": "T1", "compound_v3": "T1",
                          "yearn_v3": "T2", "euler_v2": "T2", "maple": "T2"})
        _write_positions(self.data_dir, positions_doc)
        _write_orch(self.data_dir, orch_doc)
        r = ca.build_concentration(self.data_dir)
        exposure = build_exposure(positions_doc, orch_doc)
        # Every per-protocol whole-AUM share == build_exposure share_pct / 100.
        for b in r["breakdown"]:
            p = b["protocol"]
            self.assertAlmostEqual(
                b["share"], exposure["by_protocol"][p]["share_pct"] / 100.0,
                places=6, msg=p,
            )

    def test_tiers_match_exposure(self):
        positions_doc = {
            "capital_usd": 100000.0, "cash_usd": 0.0,
            "positions": {"aave_v3": 60000.0, "maple": 40000.0},
        }
        orch_doc = _orch({"aave_v3": "T1", "maple": "T2"})
        _write_positions(self.data_dir, positions_doc)
        _write_orch(self.data_dir, orch_doc)
        r = ca.build_concentration(self.data_dir)
        exposure = build_exposure(positions_doc, orch_doc)
        for b in r["breakdown"]:
            self.assertEqual(b["tier"],
                             exposure["by_protocol"][b["protocol"]]["tier"])

    def test_source_contains_import(self):
        src = (_REPO_ROOT / "spa_core" / "paper_trading"
               / "concentration_analytics.py").read_text(encoding="utf-8")
        self.assertIn(
            "from spa_core.reporting.tear_sheet import build_exposure", src
        )


# ─── is_demo honesty ─────────────────────────────────────────────────────────


class TestIsDemo(_TmpBase):
    def test_is_demo_true(self):
        _write_positions(self.data_dir, {
            "capital_usd": 100000.0, "cash_usd": 0.0, "is_demo": True,
            "positions": {"aave_v3": 100000.0},
        })
        r = ca.build_concentration(self.data_dir)
        self.assertTrue(r["is_demo"])

    def test_is_demo_false(self):
        _write_positions(self.data_dir, {
            "capital_usd": 100000.0, "cash_usd": 0.0, "is_demo": False,
            "positions": {"aave_v3": 100000.0},
        })
        r = ca.build_concentration(self.data_dir)
        self.assertFalse(r["is_demo"])

    def test_is_demo_absent_null(self):
        _write_positions(self.data_dir, {
            "capital_usd": 100000.0, "cash_usd": 0.0,
            "positions": {"aave_v3": 100000.0},
        })
        r = ca.build_concentration(self.data_dir)
        self.assertIsNone(r["is_demo"])
        self.assertTrue(any("is_demo" in n for n in r["notes"]))

    def test_is_demo_nonbool_null(self):
        _write_positions(self.data_dir, {
            "capital_usd": 100000.0, "cash_usd": 0.0, "is_demo": "yes",
            "positions": {"aave_v3": 100000.0},
        })
        r = ca.build_concentration(self.data_dir)
        self.assertIsNone(r["is_demo"])


# ─── Tolerance / missing / broken ────────────────────────────────────────────


class TestTolerance(_TmpBase):
    def test_missing_positions(self):
        r = ca.build_concentration(self.data_dir)  # empty dir
        self.assertFalse(r["available"])
        self.assertTrue(any("missing" in n for n in r["notes"]))
        self.assertEqual(r["breakdown"], [])

    def test_broken_json_positions(self):
        self.data_dir.mkdir(parents=True, exist_ok=True)
        (self.data_dir / ca.POSITIONS_FILENAME).write_text("{not json",
                                                            encoding="utf-8")
        r = ca.build_concentration(self.data_dir)  # must not raise
        self.assertFalse(r["available"])

    def test_top_level_not_dict(self):
        self.data_dir.mkdir(parents=True, exist_ok=True)
        (self.data_dir / ca.POSITIONS_FILENAME).write_text("[1,2,3]",
                                                            encoding="utf-8")
        r = ca.build_concentration(self.data_dir)
        self.assertFalse(r["available"])

    def test_empty_positions(self):
        _write_positions(self.data_dir, {
            "capital_usd": 100000.0, "cash_usd": 100000.0, "positions": {},
        })
        r = ca.build_concentration(self.data_dir)
        self.assertFalse(r["available"])

    def test_zero_aum(self):
        _write_positions(self.data_dir, {
            "capital_usd": 0.0, "cash_usd": 0.0, "positions": {},
        })
        r = ca.build_concentration(self.data_dir)
        self.assertFalse(r["available"])

    def test_missing_orchestrator_still_works(self):
        for missing in ("orch",):
            with self.subTest(missing=missing):
                _write_positions(self.data_dir, {
                    "capital_usd": 100000.0, "cash_usd": 0.0,
                    "positions": {"aave_v3": 60000.0, "maple": 40000.0},
                })
                # no orchestrator file written
                r = ca.build_concentration(self.data_dir)
                self.assertTrue(r["available"])
                # all tiers unknown
                self.assertIn("unknown", r["by_tier"])
                for b in r["breakdown"]:
                    self.assertEqual(b["tier"], "unknown")

    def test_broken_orchestrator_tolerated(self):
        _write_positions(self.data_dir, {
            "capital_usd": 100000.0, "cash_usd": 0.0,
            "positions": {"aave_v3": 60000.0, "maple": 40000.0},
        })
        (self.data_dir / ca.ORCHESTRATOR_FILENAME).write_text("{broken",
                                                              encoding="utf-8")
        r = ca.build_concentration(self.data_dir)
        self.assertTrue(r["available"])
        self.assertIn("unknown", r["by_tier"])

    def test_garbage_positions_values(self):
        _write_positions(self.data_dir, {
            "capital_usd": 100000.0, "cash_usd": 0.0,
            "positions": {"aave_v3": "oops", "maple": None, "good": 100000.0},
        })
        r = ca.build_concentration(self.data_dir)  # must not raise
        self.assertTrue(r["available"])
        protos = [b["protocol"] for b in r["breakdown"]]
        self.assertIn("good", protos)

    def test_never_raises_on_junk_dir(self):
        r = ca.build_concentration("/nonexistent/path/xyz123")
        self.assertFalse(r["available"])

    def test_garbage_top_level_never_raises(self):
        self.data_dir.mkdir(parents=True, exist_ok=True)
        (self.data_dir / ca.POSITIONS_FILENAME).write_text('"a string"',
                                                            encoding="utf-8")
        r = ca.build_concentration(self.data_dir)
        self.assertFalse(r["available"])

    def test_negative_positions_dropped(self):
        _write_positions(self.data_dir, {
            "capital_usd": 100000.0, "cash_usd": 0.0,
            "positions": {"aave_v3": 100000.0, "bad": -5.0},
        })
        r = ca.build_concentration(self.data_dir)
        protos = [b["protocol"] for b in r["breakdown"]]
        self.assertNotIn("bad", protos)


# ─── Persistence + idempotency ───────────────────────────────────────────────


class TestPersistence(_TmpBase):
    def _good(self):
        _write_positions(self.data_dir, {
            "capital_usd": 100000.0, "cash_usd": 5000.0, "is_demo": False,
            "positions": {"aave_v3": 31529.27, "compound_v3": 30220.72,
                          "yearn_v3": 11436.6, "euler_v2": 10376.79,
                          "maple": 11436.6},
        })
        _write_orch(self.data_dir, _orch({
            "aave_v3": "T1", "compound_v3": "T1",
            "yearn_v3": "T2", "euler_v2": "T2", "maple": "T2"}))

    def test_run_writes(self):
        self._good()
        doc = ca.build_status_doc(data_dir=self.data_dir)
        out = ca.write_status(doc, data_dir=self.data_dir)
        self.assertTrue(out["changed"])
        path = self.data_dir / ca.STATUS_FILENAME
        self.assertTrue(path.exists())
        loaded = json.loads(path.read_text())
        self.assertEqual(loaded["source"], ca.SOURCE_NAME)
        self.assertIn("history", loaded)
        self.assertEqual(len(loaded["history"]), 1)

    def test_run_twice_byte_identical(self):
        self._good()
        doc1 = ca.build_status_doc(data_dir=self.data_dir,
                                   now=datetime(2026, 6, 12, tzinfo=timezone.utc))
        ca.write_status(doc1, data_dir=self.data_dir)
        path = self.data_dir / ca.STATUS_FILENAME
        bytes1 = path.read_bytes()
        md1 = hashlib.md5(bytes1).hexdigest()
        # second run, DIFFERENT timestamp — content unchanged → no rewrite
        doc2 = ca.build_status_doc(data_dir=self.data_dir,
                                   now=datetime(2026, 6, 13, tzinfo=timezone.utc))
        out2 = ca.write_status(doc2, data_dir=self.data_dir)
        self.assertFalse(out2["changed"])
        self.assertEqual(path.read_bytes(), bytes1)
        self.assertEqual(hashlib.md5(path.read_bytes()).hexdigest(), md1)

    def test_history_does_not_grow_on_idempotent(self):
        self._good()
        ca.write_status(ca.build_status_doc(data_dir=self.data_dir,
                        now=datetime(2026, 6, 12, tzinfo=timezone.utc)),
                        data_dir=self.data_dir)
        path = self.data_dir / ca.STATUS_FILENAME
        n1 = len(json.loads(path.read_text())["history"])
        ca.write_status(ca.build_status_doc(data_dir=self.data_dir,
                        now=datetime(2026, 7, 1, tzinfo=timezone.utc)),
                        data_dir=self.data_dir)
        n2 = len(json.loads(path.read_text())["history"])
        self.assertEqual(n1, n2)

    def test_generated_at_stable_when_unchanged(self):
        self._good()
        ca.write_status(ca.build_status_doc(data_dir=self.data_dir,
                        now=datetime(2026, 6, 12, tzinfo=timezone.utc)),
                        data_dir=self.data_dir)
        path = self.data_dir / ca.STATUS_FILENAME
        ga1 = json.loads(path.read_text())["meta"]["generated_at"]
        ca.write_status(ca.build_status_doc(data_dir=self.data_dir,
                        now=datetime(2026, 7, 1, tzinfo=timezone.utc)),
                        data_dir=self.data_dir)
        ga2 = json.loads(path.read_text())["meta"]["generated_at"]
        self.assertEqual(ga1, ga2)

    def test_history_grows_on_change(self):
        self._good()
        ca.write_status(ca.build_status_doc(data_dir=self.data_dir,
                        now=datetime(2026, 6, 12, tzinfo=timezone.utc)),
                        data_dir=self.data_dir)
        _write_positions(self.data_dir, {
            "capital_usd": 100000.0, "cash_usd": 5000.0, "is_demo": False,
            "positions": {"aave_v3": 95000.0},
        })
        out2 = ca.write_status(ca.build_status_doc(data_dir=self.data_dir,
                               now=datetime(2026, 6, 13, tzinfo=timezone.utc)),
                               data_dir=self.data_dir)
        self.assertTrue(out2["changed"])
        loaded = json.loads((self.data_dir / ca.STATUS_FILENAME).read_text())
        self.assertEqual(len(loaded["history"]), 2)

    def test_history_rotation_exactly_500(self):
        self._good()
        path = self.data_dir / ca.STATUS_FILENAME
        seed = {"history": [{"generated_at": f"t{i}"} for i in range(600)]}
        path.write_text(json.dumps(seed), encoding="utf-8")
        ca.write_status(ca.build_status_doc(data_dir=self.data_dir),
                        data_dir=self.data_dir)
        loaded = json.loads(path.read_text())
        self.assertEqual(len(loaded["history"]), ca.HISTORY_MAX)
        self.assertEqual(ca.HISTORY_MAX, 500)

    def test_no_tmp_leftovers(self):
        self._good()
        ca.write_status(ca.build_status_doc(data_dir=self.data_dir),
                        data_dir=self.data_dir)
        leftovers = list(self.data_dir.glob("*.tmp")) + \
            list(self.data_dir.glob(".*tmp"))
        self.assertEqual(leftovers, [])

    def test_broken_prior_status_tolerated(self):
        self._good()
        path = self.data_dir / ca.STATUS_FILENAME
        path.write_text("{broken", encoding="utf-8")
        out = ca.write_status(ca.build_status_doc(data_dir=self.data_dir),
                              data_dir=self.data_dir)
        self.assertTrue(out["changed"])
        loaded = json.loads(path.read_text())
        self.assertEqual(len(loaded["history"]), 1)

    def test_fingerprint_excludes_volatile(self):
        a = {"meta": {"generated_at": "2026-01-01"}, "verdict": "ok",
             "history": [1, 2]}
        b = {"meta": {"generated_at": "2099-12-31"}, "verdict": "ok",
             "history": [9]}
        self.assertEqual(ca.content_fingerprint(a), ca.content_fingerprint(b))

    def test_fingerprint_detects_content_change(self):
        a = {"meta": {"generated_at": "x"}, "verdict": "ok"}
        b = {"meta": {"generated_at": "x"}, "verdict": "fail"}
        self.assertNotEqual(ca.content_fingerprint(a), ca.content_fingerprint(b))

    def test_fingerprint_invalid(self):
        self.assertEqual(ca.content_fingerprint("not a dict"), "<invalid>")

    def test_history_entry_uses_deployed_index(self):
        self._good()
        doc = ca.build_status_doc(data_dir=self.data_dir)
        entry = ca._history_entry(doc)
        self.assertEqual(entry["hhi_protocol_index"],
                         doc["hhi_protocol_deployed_index"])
        self.assertIn("effective_num_positions", entry)
        self.assertIn("top1_share", entry)


# ─── CLI ─────────────────────────────────────────────────────────────────────


class TestCLI(_TmpBase):
    def _good(self):
        _write_positions(self.data_dir, {
            "capital_usd": 100000.0, "cash_usd": 5000.0, "is_demo": False,
            "positions": {"aave_v3": 31529.27, "compound_v3": 30220.72,
                          "yearn_v3": 11436.6, "euler_v2": 10376.79,
                          "maple": 11436.6},
        })
        _write_orch(self.data_dir, _orch({
            "aave_v3": "T1", "compound_v3": "T1",
            "yearn_v3": "T2", "euler_v2": "T2", "maple": "T2"}))

    def test_check_default_exit0_valid_json(self):
        self._good()
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            rc = ca.main(["--check", "--data-dir", str(self.data_dir)])
        self.assertEqual(rc, 0)
        doc = json.loads(out.getvalue())
        self.assertEqual(doc["source"], ca.SOURCE_NAME)
        self.assertIn("verdict", doc)

    def test_default_is_check(self):
        self._good()
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            rc = ca.main(["--data-dir", str(self.data_dir)])
        self.assertEqual(rc, 0)
        json.loads(out.getvalue())

    def test_check_does_not_write(self):
        self._good()
        before = sorted(p.name for p in self.data_dir.iterdir())
        with contextlib.redirect_stdout(io.StringIO()):
            ca.main(["--check", "--data-dir", str(self.data_dir)])
        after = sorted(p.name for p in self.data_dir.iterdir())
        self.assertEqual(before, after)
        self.assertNotIn(ca.STATUS_FILENAME, after)

    def test_run_writes_exit0(self):
        self._good()
        with contextlib.redirect_stdout(io.StringIO()):
            rc = ca.main(["--run", "--data-dir", str(self.data_dir)])
        self.assertEqual(rc, 0)
        self.assertTrue((self.data_dir / ca.STATUS_FILENAME).exists())

    def test_run_twice_idempotent(self):
        self._good()
        with contextlib.redirect_stdout(io.StringIO()):
            ca.main(["--run", "--data-dir", str(self.data_dir)])
        path = self.data_dir / ca.STATUS_FILENAME
        b1 = path.read_bytes()
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            ca.main(["--run", "--data-dir", str(self.data_dir)])
        self.assertEqual(path.read_bytes(), b1)
        self.assertIn("idempotent", out.getvalue())

    def test_empty_data_dir_exit0(self):
        with contextlib.redirect_stdout(io.StringIO()):
            rc = ca.main(["--check", "--data-dir", str(self.data_dir)])
        self.assertEqual(rc, 0)

    def test_junk_arg_exit0_no_traceback(self):
        err = io.StringIO()
        with contextlib.redirect_stderr(err), contextlib.redirect_stdout(io.StringIO()):
            rc = ca.main(["--frobnicate"])
        self.assertEqual(rc, 0)
        self.assertIn("ERROR", err.getvalue())
        self.assertNotIn("Traceback", err.getvalue())

    def test_check_run_conflict_exit0(self):
        err = io.StringIO()
        with contextlib.redirect_stderr(err), contextlib.redirect_stdout(io.StringIO()):
            rc = ca.main(["--check", "--run"])
        self.assertEqual(rc, 0)
        self.assertIn("ERROR", err.getvalue())
        self.assertNotIn("Traceback", err.getvalue())

    def test_run_no_tmp_leftover_after_cli(self):
        self._good()
        with contextlib.redirect_stdout(io.StringIO()):
            ca.main(["--run", "--data-dir", str(self.data_dir)])
        self.assertEqual(list(self.data_dir.glob("*.tmp")), [])

    def test_subprocess_check_exit0(self):
        self._good()
        proc = subprocess.run(
            [sys.executable, "-m",
             "spa_core.paper_trading.concentration_analytics",
             "--check", "--data-dir", str(self.data_dir)],
            cwd=str(_REPO_ROOT), capture_output=True, text=True,
        )
        self.assertEqual(proc.returncode, 0)
        json.loads(proc.stdout)
        self.assertNotIn("Traceback", proc.stderr)

    def test_subprocess_junk_arg_exit0(self):
        proc = subprocess.run(
            [sys.executable, "-m",
             "spa_core.paper_trading.concentration_analytics",
             "--no-such-flag"],
            cwd=str(_REPO_ROOT), capture_output=True, text=True,
        )
        self.assertEqual(proc.returncode, 0)
        self.assertNotIn("Traceback", proc.stderr)
        self.assertIn("ERROR", proc.stderr)


# ─── Hygiene / reuse ─────────────────────────────────────────────────────────


class TestHygiene(unittest.TestCase):
    def _module_source(self):
        return (_REPO_ROOT / "spa_core" / "paper_trading"
                / "concentration_analytics.py").read_text(encoding="utf-8")

    def _test_source(self):
        return (_REPO_ROOT / "spa_core" / "tests"
                / "test_concentration_analytics.py").read_text(encoding="utf-8")

    def test_no_forbidden_imports_via_ast(self):
        from spa_core.ci.llm_forbidden_lint import find_forbidden_imports
        src = self._module_source()
        self.assertEqual(
            find_forbidden_imports(src, "concentration_analytics.py"), []
        )

    def test_test_file_clean(self):
        from spa_core.ci.llm_forbidden_lint import find_forbidden_imports
        src = self._test_source()
        self.assertEqual(
            find_forbidden_imports(src, "test_concentration_analytics.py"), []
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
        self.assertEqual(ca.HHI_MODERATE_FLOOR, 1500)
        self.assertEqual(ca.HHI_CONCENTRATED_FLOOR, 2500)
        self.assertEqual(ca.MAX_SINGLE_POSITION_SHARE, 0.40)
        self.assertEqual(ca.SCHEMA_VERSION, 1)
        self.assertEqual(ca.SOURCE_NAME, "concentration_analytics")
        self.assertEqual(ca.STATUS_FILENAME, "concentration_analytics.json")
        self.assertEqual(ca.HISTORY_MAX, 500)

    def test_public_api_present(self):
        self.assertTrue(hasattr(ca, "build_concentration"))
        self.assertTrue(hasattr(ca, "build_status_doc"))
        self.assertTrue(hasattr(ca, "write_status"))
        self.assertTrue(hasattr(ca, "content_fingerprint"))
        self.assertTrue(hasattr(ca, "main"))

    def test_disclaimer_present(self):
        _tmp = tempfile.mkdtemp(prefix="conc_test_")
        try:
            dd = Path(_tmp)
            _write_positions(dd, {
                "capital_usd": 100000.0, "cash_usd": 0.0,
                "positions": {"aave_v3": 100000.0},
            })
            r = ca.build_concentration(dd)
            self.assertEqual(r["disclaimer"], "NOT investment advice")
            self.assertTrue(r["advisory_only"])
            self.assertEqual(r["execution_mode"], "read_only")
        finally:
            import shutil
            shutil.rmtree(_tmp, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
