#!/usr/bin/env python3
"""Tests for SPA-V413 strategy capacity & scalability analytics.

Pure stdlib ``unittest`` (pytest is not installed in this repo — mirrors the
sibling ``test_adapter_orchestrator.py`` / ``test_exit_latency.py`` style). No
network: the analytic core is exercised on hand-built structures, plus a smoke
test on the real ``data/`` files.

Run:  python3 -m unittest spa_core.tests.test_capacity_analytics -v
"""
from __future__ import annotations

import json
import math
import sys
import unittest
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from spa_core.paper_trading.capacity_analytics import (
    DAILY_LIQUIDITY_FRACTION,
    MAX_DAILY_VOLUME_SHARE,
    MAX_SLIPPAGE_PENALTY,
    MAX_TVL_SHARE,
    _Pool,
    build_capacity_report,
    capacity_adjusted_apy,
    compute_capacity_metrics,
    generate_capacity_report,
    grade_and_verdict,
    max_position_usd,
    pools_from_status,
    utilization,
)

_REPO_ROOT = Path(__file__).resolve().parents[2]


# ─── max_position_usd ─────────────────────────────────────────────────────────


class TestMaxPositionUsd(unittest.TestCase):
    def test_min_of_tvl_and_volume_cap(self):
        # TVL=1,000,000 -> tvl_cap = 1e6 * 0.02 = 20,000
        # explicit daily volume 100,000 -> vol_cap = 1e5 * 0.10 = 10,000
        # min = 10,000 (volume-bound)
        pool = _Pool("p", tvl_usd=1_000_000.0, base_apy=0.05, daily_volume_usd=100_000.0)
        cap, src = max_position_usd(pool)
        self.assertEqual(src, "provided")
        self.assertAlmostEqual(cap, 10_000.0)

    def test_tvl_bound_when_volume_large(self):
        # daily volume huge -> tvl-cap binds at 20,000
        pool = _Pool("p", tvl_usd=1_000_000.0, base_apy=0.05, daily_volume_usd=10_000_000.0)
        cap, _ = max_position_usd(pool)
        self.assertAlmostEqual(cap, 1_000_000.0 * MAX_TVL_SHARE)

    def test_proxy_volume_from_tvl(self):
        # no explicit volume -> proxy daily volume = TVL * 0.10 = 100,000
        # vol_cap = 100,000 * 0.10 = 10,000 ; tvl_cap = 20,000 -> min 10,000
        pool = _Pool("p", tvl_usd=1_000_000.0, base_apy=0.05, daily_volume_usd=None)
        cap, src = max_position_usd(pool)
        self.assertEqual(src, "proxy_from_tvl")
        expected = min(
            1_000_000.0 * MAX_TVL_SHARE,
            (1_000_000.0 * DAILY_LIQUIDITY_FRACTION) * MAX_DAILY_VOLUME_SHARE,
        )
        self.assertAlmostEqual(cap, expected)

    def test_no_tvl_no_volume_gives_none(self):
        pool = _Pool("p", tvl_usd=None, base_apy=0.05, daily_volume_usd=None)
        cap, src = max_position_usd(pool)
        self.assertIsNone(cap)
        self.assertEqual(src, "unknown")

    def test_zero_tvl_gives_none(self):
        pool = _Pool("p", tvl_usd=0.0, base_apy=0.05, daily_volume_usd=None)
        cap, _ = max_position_usd(pool)
        self.assertIsNone(cap)


# ─── capacity_adjusted_apy ────────────────────────────────────────────────────


class TestCapacityAdjustedApy(unittest.TestCase):
    def test_tiny_position_approx_base(self):
        cap = 1_000_000.0
        eff = capacity_adjusted_apy(0.05, position_usd=1.0, cap_usd=cap)
        self.assertAlmostEqual(eff, 0.05, places=6)

    def test_full_capacity_full_penalty(self):
        eff = capacity_adjusted_apy(0.05, position_usd=1_000.0, cap_usd=1_000.0)
        self.assertAlmostEqual(eff, 0.05 * (1.0 - MAX_SLIPPAGE_PENALTY))

    def test_half_capacity_half_penalty(self):
        eff = capacity_adjusted_apy(0.10, position_usd=500.0, cap_usd=1_000.0)
        self.assertAlmostEqual(eff, 0.10 * (1.0 - MAX_SLIPPAGE_PENALTY * 0.5))

    def test_monotonic_decreasing_in_utilization(self):
        base, cap = 0.08, 1_000.0
        prev = None
        for pos in (0.0, 100.0, 300.0, 600.0, 1_000.0):
            eff = capacity_adjusted_apy(base, pos, cap)
            if prev is not None:
                self.assertLessEqual(eff, prev + 1e-12)
            prev = eff

    def test_clamp_above_cap(self):
        # position above cap -> utilization clamps at 1.0, penalty maxes out
        eff = capacity_adjusted_apy(0.05, position_usd=5_000.0, cap_usd=1_000.0)
        self.assertAlmostEqual(eff, 0.05 * (1.0 - MAX_SLIPPAGE_PENALTY))

    def test_none_base_apy(self):
        self.assertIsNone(capacity_adjusted_apy(None, 100.0, 1_000.0))

    def test_unknown_cap_no_penalty(self):
        eff = capacity_adjusted_apy(0.05, position_usd=100.0, cap_usd=None)
        self.assertAlmostEqual(eff, 0.05)

    def test_utilization_clamp(self):
        self.assertEqual(utilization(2_000.0, 1_000.0), 1.0)
        self.assertEqual(utilization(0.0, 1_000.0), 0.0)
        self.assertEqual(utilization(500.0, 1_000.0), 0.5)
        self.assertEqual(utilization(100.0, None), 0.0)
        self.assertEqual(utilization(None, 1_000.0), 0.0)


# ─── Portfolio ceiling & blended APY ──────────────────────────────────────────


class TestPortfolioCeiling(unittest.TestCase):
    def _pools(self):
        # caps chosen so binding pool is computable by hand.
        # All explicit daily volumes so caps are deterministic.
        return {
            "a": {"tvl_usd": 100_000_000.0, "base_apy": 0.05,
                  "daily_volume_usd": 1_000_000_000.0},  # tvl_cap = 2,000,000
            "b": {"tvl_usd": 50_000_000.0, "base_apy": 0.04,
                  "daily_volume_usd": 1_000_000_000.0},   # tvl_cap = 1,000,000
        }

    def test_ceiling_is_min_cap_over_weight(self):
        # weights a=0.5, b=0.5
        # cap_a=2,000,000 -> aum_a = 4,000,000
        # cap_b=1,000,000 -> aum_b = 2,000,000 (binding)
        res = compute_capacity_metrics(
            self._pools(), weights={"a": 0.5, "b": 0.5}, current_aum_usd=1_000_000.0
        )
        pf = res["portfolio"]
        self.assertAlmostEqual(pf["max_aum_usd"], 2_000_000.0)
        self.assertEqual(pf["binding_pool"], "b")

    def test_blended_apy_finite_and_reasonable(self):
        res = compute_capacity_metrics(
            self._pools(), weights={"a": 0.5, "b": 0.5}, current_aum_usd=1_000_000.0
        )
        pf = res["portfolio"]
        cur = pf["blended_apy_at_current"]
        ceil = pf["blended_apy_at_ceiling"]
        self.assertTrue(math.isfinite(cur))
        self.assertTrue(math.isfinite(ceil))
        # blended APY is between the worst-haircut and base blend.
        self.assertGreater(cur, 0.0)
        self.assertLess(cur, 0.05)  # below max base apy
        # at ceiling utilisation is higher -> blended apy degrades vs current
        self.assertLessEqual(ceil, cur + 1e-9)

    def test_weight_zero_ignored(self):
        res = compute_capacity_metrics(
            self._pools(), weights={"a": 0.5, "b": 0.0}, current_aum_usd=1_000_000.0
        )
        pf = res["portfolio"]
        # only pool a is weighted -> aum = cap_a / 0.5 = 4,000,000
        self.assertAlmostEqual(pf["max_aum_usd"], 4_000_000.0)
        self.assertEqual(pf["binding_pool"], "a")


# ─── grade / verdict ──────────────────────────────────────────────────────────


class TestGradeVerdict(unittest.TestCase):
    def test_thresholds(self):
        self.assertEqual(grade_and_verdict(60_000_000.0), ("A", "scales_to_institutional"))
        self.assertEqual(grade_and_verdict(50_000_000.0), ("A", "scales_to_institutional"))
        self.assertEqual(grade_and_verdict(20_000_000.0), ("B", "scales_to_midsize"))
        self.assertEqual(grade_and_verdict(10_000_000.0), ("B", "scales_to_midsize"))
        self.assertEqual(grade_and_verdict(5_000_000.0), ("C", "capacity_constrained"))
        self.assertEqual(grade_and_verdict(1_000_000.0), ("C", "capacity_constrained"))
        self.assertEqual(grade_and_verdict(500_000.0), ("D", "capacity_constrained"))

    def test_none_is_insufficient(self):
        self.assertEqual(grade_and_verdict(None), (None, "insufficient_data"))
        self.assertEqual(grade_and_verdict(0.0), (None, "insufficient_data"))


# ─── Degenerate inputs ────────────────────────────────────────────────────────


class TestDegenerate(unittest.TestCase):
    def _assert_stable_schema(self, res):
        self.assertIn("num_pools", res)
        self.assertIn("pools", res)
        self.assertIn("portfolio", res)
        pf = res["portfolio"]
        for k in ("max_aum_usd", "binding_pool", "blended_apy_at_current",
                  "blended_apy_at_ceiling", "grade", "verdict"):
            self.assertIn(k, pf)

    def test_empty_pools(self):
        res = compute_capacity_metrics({}, weights={}, current_aum_usd=None)
        self._assert_stable_schema(res)
        self.assertEqual(res["num_pools"], 0)
        self.assertIsNone(res["portfolio"]["max_aum_usd"])
        self.assertEqual(res["portfolio"]["verdict"], "insufficient_data")
        self.assertIsNone(res["portfolio"]["grade"])

    def test_tvl_none_and_zero(self):
        pools = {
            "a": {"tvl_usd": None, "base_apy": 0.05},
            "b": {"tvl_usd": 0.0, "base_apy": 0.05},
        }
        res = compute_capacity_metrics(pools, weights={"a": 0.5, "b": 0.5},
                                       current_aum_usd=1_000_000.0)
        self._assert_stable_schema(res)
        for p in res["pools"]:
            self.assertIsNone(p["max_position_usd"])
        # no usable caps -> no ceiling
        self.assertIsNone(res["portfolio"]["max_aum_usd"])

    def test_apy_none(self):
        pools = {"a": {"tvl_usd": 1_000_000.0, "base_apy": None}}
        res = compute_capacity_metrics(pools, weights={"a": 1.0},
                                       current_aum_usd=10_000.0)
        self._assert_stable_schema(res)
        self.assertIsNone(res["pools"][0]["capacity_adjusted_apy_at_current"])
        # cap exists -> ceiling computable even without apy
        self.assertIsNotNone(res["portfolio"]["max_aum_usd"])
        # but blended apy undefined
        self.assertIsNone(res["portfolio"]["blended_apy_at_current"])

    def test_empty_allocation(self):
        pools = {"a": {"tvl_usd": 1_000_000.0, "base_apy": 0.05}}
        res = compute_capacity_metrics(pools, weights={}, current_aum_usd=None)
        self._assert_stable_schema(res)
        self.assertEqual(res["portfolio"]["num_weighted_pools"], 0)
        self.assertIsNone(res["portfolio"]["max_aum_usd"])
        self.assertEqual(res["portfolio"]["verdict"], "insufficient_data")

    def test_no_crash_on_garbage_rows(self):
        # sequence rows of varying length / bad types must not raise
        pools = [
            ("a", 1_000_000.0, 0.05),
            ("b",),                      # missing tvl/apy
            None,                        # garbage
            ("c", "bad", "bad"),         # non-numeric
        ]
        res = compute_capacity_metrics(pools, weights={"a": 1.0},
                                       current_aum_usd=10_000.0)
        self._assert_stable_schema(res)
        self.assertEqual(res["num_pools"], 3)  # a, b, c (None skipped)


# ─── Mapping vs Sequence equivalence ──────────────────────────────────────────


class TestInputShapeEquivalence(unittest.TestCase):
    def test_mapping_and_sequence_match(self):
        mapping = {
            "a": {"tvl_usd": 1_000_000.0, "base_apy": 0.05, "daily_volume_usd": 100_000.0},
            "b": {"tvl_usd": 2_000_000.0, "base_apy": 0.04, "daily_volume_usd": 200_000.0},
        }
        sequence = [
            ("a", 1_000_000.0, 0.05, 100_000.0),
            ("b", 2_000_000.0, 0.04, 200_000.0),
        ]
        weights = {"a": 0.5, "b": 0.5}
        r1 = compute_capacity_metrics(mapping, weights=weights, current_aum_usd=50_000.0)
        r2 = compute_capacity_metrics(sequence, weights=weights, current_aum_usd=50_000.0)
        self.assertEqual(json.dumps(r1, sort_keys=True), json.dumps(r2, sort_keys=True))


# ─── Finiteness of all non-null outputs ───────────────────────────────────────


class TestFiniteness(unittest.TestCase):
    def test_all_finite(self):
        pools = {
            "a": {"tvl_usd": 100_000_000.0, "base_apy": 0.05},
            "b": {"tvl_usd": 50_000_000.0, "base_apy": 0.04},
        }
        res = compute_capacity_metrics(pools, weights={"a": 0.6, "b": 0.4},
                                       current_aum_usd=1_000_000.0)

        def check(v):
            if isinstance(v, float):
                self.assertTrue(math.isfinite(v))
            elif isinstance(v, dict):
                for x in v.values():
                    check(x)
            elif isinstance(v, list):
                for x in v:
                    check(x)

        check(res)


# ─── pools_from_status conversion ─────────────────────────────────────────────


class TestPoolsFromStatus(unittest.TestCase):
    def test_apy_pct_to_fraction(self):
        status = {
            "adapters": [
                {"protocol": "x", "tvl_usd": 1_000.0, "apy_pct": 5.0},
                {"protocol": "y", "tvl_usd": 2_000.0, "apy_pct": None},
            ]
        }
        pools = pools_from_status(status)
        self.assertAlmostEqual(pools["x"]["base_apy"], 0.05)
        self.assertEqual(pools["x"]["tvl_usd"], 1_000.0)
        self.assertIsNone(pools["y"]["base_apy"])

    def test_garbage_status(self):
        self.assertEqual(pools_from_status(None), {})
        self.assertEqual(pools_from_status({}), {})
        self.assertEqual(pools_from_status({"adapters": "nope"}), {})


# ─── Atomic write ─────────────────────────────────────────────────────────────


class TestAtomicWrite(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name)
        self.status = self.dir / "status.json"
        self.alloc = self.dir / "alloc.json"
        self.status.write_text(json.dumps({
            "adapters": [
                {"protocol": "a", "tvl_usd": 100_000_000.0, "apy_pct": 5.0},
                {"protocol": "b", "tvl_usd": 50_000_000.0, "apy_pct": 4.0},
            ]
        }), encoding="utf-8")
        self.alloc.write_text(json.dumps({
            "target_weights": {"a": 0.5, "b": 0.5},
            "capital_usd": 100_000.0,
        }), encoding="utf-8")

    def tearDown(self):
        self._tmp.cleanup()

    def test_write_no_tmp_leftovers(self):
        out = self.dir / "capacity_analytics.json"
        generate_capacity_report(self.status, self.alloc, out)
        self.assertTrue(out.exists())
        leftovers = [p.name for p in self.dir.iterdir() if p.name.endswith(".tmp")]
        self.assertEqual(leftovers, [])
        doc = json.loads(out.read_text(encoding="utf-8"))
        self.assertEqual(doc["execution_mode"], "read_only_simulation")
        self.assertIn("assumptions", doc)
        self.assertIn("schema_version", doc)
        self.assertIn("generated_at", doc)

    def test_overwrite_clean(self):
        out = self.dir / "capacity_analytics.json"
        for _ in range(3):
            generate_capacity_report(self.status, self.alloc, out)
        files = [p.name for p in self.dir.iterdir()]
        self.assertFalse(any(f.endswith(".tmp") for f in files))

    def test_no_write_mode(self):
        report = generate_capacity_report(self.status, self.alloc, output_path=None)
        self.assertNotIn("capacity_analytics.json", [p.name for p in self.dir.iterdir()])
        self.assertIn("metrics", report)


# ─── Smoke on real data ───────────────────────────────────────────────────────


class TestRealDataSmoke(unittest.TestCase):
    def test_real_inputs(self):
        status_path = _REPO_ROOT / "data" / "adapter_orchestrator_status.json"
        alloc_path = _REPO_ROOT / "data" / "target_allocation.json"
        if not status_path.exists() or not alloc_path.exists():
            self.skipTest("real data files not present")
        report = build_capacity_report(status_path, alloc_path)
        self.assertEqual(report["execution_mode"], "read_only_simulation")
        pf = report["metrics"]["portfolio"]
        # with the real book a ceiling and a verdict should be produced
        self.assertIn(pf["verdict"], {
            "scales_to_institutional", "scales_to_midsize",
            "capacity_constrained", "insufficient_data",
        })
        # finiteness of headline figures
        for key in ("max_aum_usd", "blended_apy_at_current", "blended_apy_at_ceiling"):
            v = pf[key]
            if v is not None:
                self.assertTrue(math.isfinite(v))


if __name__ == "__main__":
    unittest.main(verbosity=2)
