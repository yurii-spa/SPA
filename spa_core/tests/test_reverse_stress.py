#!/usr/bin/env python3
"""Tests for spa_core.backtesting.tier1.reverse_stress.

Pure stdlib, no network, no LLM. Covers the reverse (inverse) stress test:
  - depeg breakpoint is SMALLER (more fragile) for more-deployed allocations
  - a 100%-cash allocation never breaches (infinite/None depeg breakpoint)
  - exploit_sleeves_to_breach correct for a known T2-heavy allocation
  - most_fragile_scenario is the smallest shock
  - determinism (same input → same output)
  - build_report structure + atomic write to a tempdir
  - import hygiene (no forbidden / network imports)
"""
from __future__ import annotations

import ast
import json
import tempfile
import unittest
from pathlib import Path

from spa_core.backtesting.tier1 import reverse_stress as rs

_REPO_ROOT = Path(__file__).resolve().parents[2]


class TestDepegBreakpoint(unittest.TestCase):

    def test_closed_form(self):
        # deployed weight 0.5 → depeg breakpoint = 10 / 0.5 = 20%
        alloc = {"aave_v3": 0.5, "cash": 0.5}
        bp = rs.depeg_breakpoint_pct(alloc, -10.0)
        self.assertAlmostEqual(bp, 20.0)

    def test_fully_deployed_breakpoint_equals_tolerance(self):
        # deployed weight 1.0 → depeg breakpoint = 10 / 1.0 = 10%
        alloc = {"aave_v3": 0.6, "maple": 0.4}
        bp = rs.depeg_breakpoint_pct(alloc, -10.0)
        self.assertAlmostEqual(bp, 10.0)

    def test_more_deployed_is_more_fragile(self):
        """More-deployed allocation → SMALLER depeg breakpoint (more fragile)."""
        less_deployed = {"aave_v3": 0.3, "cash": 0.7}
        more_deployed = {"aave_v3": 0.9, "cash": 0.1}
        bp_less = rs.depeg_breakpoint_pct(less_deployed, -10.0)
        bp_more = rs.depeg_breakpoint_pct(more_deployed, -10.0)
        self.assertLess(bp_more, bp_less)

    def test_all_cash_never_breaches(self):
        alloc = {"cash": 1.0}
        bp = rs.depeg_breakpoint_pct(alloc, -10.0)
        self.assertEqual(bp, rs.INF)

    def test_empty_allocation_never_breaches(self):
        self.assertEqual(rs.depeg_breakpoint_pct({}, -10.0), rs.INF)


class TestExploitBreakpoint(unittest.TestCase):

    def test_known_t2_heavy_alloc(self):
        # Three equal T2 sleeves at 0.30 each. Each exploit = 50% * 0.30 = 15% of book.
        # To breach -10%: 1 sleeve (15% >= 10%). So sleeves_to_breach == 1.
        alloc = {"maple": 0.30, "euler_v2": 0.30, "morpho_blue": 0.30, "cash": 0.10}
        res = rs.exploit_breakpoint(alloc, -10.0)
        self.assertTrue(res["breaches"])
        self.assertEqual(res["sleeves_to_breach"], 1)
        # Worst-first: all equal weight → first by name tie-break.
        self.assertEqual(len(res["protocols"]), 1)

    def test_needs_multiple_small_sleeves(self):
        # Small T2 sleeves: 0.08 each → exploit = 50%*0.08 = 4% per sleeve.
        # To breach -10%: need ceil(10/4) = 3 sleeves (4+4+4 = 12% >= 10%).
        alloc = {
            "maple": 0.08, "euler_v2": 0.08, "morpho_blue": 0.08,
            "yearn_v3": 0.08, "cash": 0.68,
        }
        res = rs.exploit_breakpoint(alloc, -10.0)
        self.assertTrue(res["breaches"])
        self.assertEqual(res["sleeves_to_breach"], 3)

    def test_t2_book_too_small_cannot_breach(self):
        # One tiny T2 sleeve 0.05 → max exploit loss = 2.5% < 10% → cannot breach.
        alloc = {"aave_v3": 0.9, "maple": 0.05, "cash": 0.05}
        res = rs.exploit_breakpoint(alloc, -10.0)
        self.assertFalse(res["breaches"])
        self.assertIsNone(res["sleeves_to_breach"])

    def test_t1_only_no_exploitable_sleeves(self):
        # aave_v3 / compound_v3 are T1 → not counted as T2/T3 exploit sleeves.
        alloc = {"aave_v3": 0.5, "compound_v3": 0.5}
        res = rs.exploit_breakpoint(alloc, -10.0)
        self.assertFalse(res["breaches"])
        self.assertIsNone(res["sleeves_to_breach"])

    def test_worst_first_ordering(self):
        # Larger sleeve should be selected first.
        alloc = {"maple": 0.25, "euler_v2": 0.05, "cash": 0.70}
        res = rs.exploit_breakpoint(alloc, -10.0)
        # maple alone: 50%*0.25 = 12.5% >= 10% → 1 sleeve, the big one.
        self.assertEqual(res["sleeves_to_breach"], 1)
        self.assertEqual(res["protocols"], ["maple"])


class TestReverseStress(unittest.TestCase):

    def test_keys_present(self):
        out = rs.reverse_stress({"aave_v3": 0.5, "maple": 0.3, "cash": 0.2}, -10.0)
        for k in (
            "depeg_breakpoint_pct", "exploit_sleeves_to_breach",
            "exploit_breakpoint_protocols", "most_fragile_scenario", "breaches_at",
        ):
            self.assertIn(k, out)

    def test_all_cash_breakpoint_none(self):
        out = rs.reverse_stress({"cash": 1.0}, -10.0)
        self.assertIsNone(out["depeg_breakpoint_pct"])
        self.assertIsNone(out["exploit_sleeves_to_breach"])
        self.assertIsNone(out["most_fragile_scenario"])

    def test_most_fragile_is_smallest_shock(self):
        # T2-heavy book: one big exploit (50%*0.5=25% of book) is a smaller *shock*
        # (only 50% of book exploited) than a full depeg needed.
        # Here a concentrated T2 sleeve breaches with a small fraction of the book.
        alloc = {"maple": 0.5, "aave_v3": 0.5}
        out = rs.reverse_stress(alloc, -10.0)
        # depeg breakpoint = 10 / 1.0 = 10% depeg → shock 0.10
        # exploit: maple 0.5 → 25% loss breaches with 1 sleeve → shock = 0.5 weight
        # depeg shock (0.10) < exploit shock (0.5) → depeg is most fragile.
        self.assertEqual(out["most_fragile_scenario"], "depeg")

    def test_most_fragile_exploit_when_concentrated_small_book(self):
        # Mostly cash, but a single big T2 sleeve. Depeg needs a big % (book lightly
        # deployed) while one exploit on a small fraction breaches → exploit smaller shock.
        alloc = {"maple": 0.25, "cash": 0.75}
        out = rs.reverse_stress(alloc, -10.0)
        # depeg breakpoint = 10 / 0.25 = 40% → shock 0.40
        # exploit: maple 0.25 → 12.5% breaches → exploited weight 0.25 → shock 0.25
        # 0.25 < 0.40 → exploit is the most fragile.
        self.assertEqual(out["most_fragile_scenario"], "exploit")

    def test_smallest_shock_invariant(self):
        """most_fragile_scenario's shock must be <= the other scenario's shock."""
        alloc = {"maple": 0.4, "aave_v3": 0.3, "cash": 0.3}
        out = rs.reverse_stress(alloc, -10.0)
        depeg_bp = out["depeg_breakpoint_pct"]
        depeg_shock = (depeg_bp / 100.0) if depeg_bp is not None else rs.INF
        # exploit shock = exploited weight
        w = rs._weights(alloc)
        ex_protos = out["exploit_breakpoint_protocols"]
        exploit_shock = sum(w.get(p, 0.0) for p in ex_protos) if ex_protos else rs.INF
        smallest = min(depeg_shock, exploit_shock)
        chosen = depeg_shock if out["most_fragile_scenario"] == "depeg" else exploit_shock
        self.assertAlmostEqual(chosen, smallest, places=9)

    def test_rate_breakpoint_na(self):
        out = rs.reverse_stress({"aave_v3": 1.0}, -10.0)
        self.assertEqual(out["rate_breakpoint"], "N/A")

    def test_tolerance_scales_depeg(self):
        # Tighter tolerance → smaller depeg breakpoint.
        alloc = {"aave_v3": 1.0}
        bp5 = rs.reverse_stress(alloc, -5.0)["depeg_breakpoint_pct"]
        bp10 = rs.reverse_stress(alloc, -10.0)["depeg_breakpoint_pct"]
        self.assertLess(bp5, bp10)


class TestDeterminism(unittest.TestCase):

    def test_same_input_same_output(self):
        alloc = {"maple": 0.3, "aave_v3": 0.4, "euler_v2": 0.2, "cash": 0.1}
        a = rs.reverse_stress(alloc, -10.0)
        b = rs.reverse_stress(alloc, -10.0)
        self.assertEqual(json.dumps(a, sort_keys=True), json.dumps(b, sort_keys=True))

    def test_protocol_order_deterministic(self):
        # Same equal-weight sleeves always selected in the same (name) order.
        alloc = {"euler_v2": 0.1, "maple": 0.1, "morpho_blue": 0.1, "cash": 0.7}
        r1 = rs.exploit_breakpoint(alloc, -10.0)["protocols"]
        r2 = rs.exploit_breakpoint(alloc, -10.0)["protocols"]
        self.assertEqual(r1, r2)


class TestBuildReport(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.mkdtemp(prefix="revstress_test_")
        self.data_dir = Path(self._tmp)

    def tearDown(self):
        import shutil
        shutil.rmtree(self._tmp, ignore_errors=True)

    def _write_positions(self, positions, cash=None):
        doc = {"positions": positions}
        if cash is not None:
            doc["cash_usd"] = cash
        (self.data_dir / rs.POSITIONS_FILENAME).write_text(
            json.dumps(doc), encoding="utf-8"
        )

    def test_report_structure(self):
        self._write_positions({"aave_v3": 50000.0, "maple": 30000.0}, cash=20000.0)
        report = rs.build_report(write=True, tolerance=-10.0, data_dir=self.data_dir)
        self.assertEqual(report["model"], "tier1_reverse_stress")
        self.assertTrue(report["llm_forbidden"])
        self.assertIn("strategies", report)
        self.assertIn("live_portfolio", report["strategies"])
        live = report["strategies"]["live_portfolio"]
        self.assertIn("allocation", live)
        self.assertIn("reverse_stress", live)
        self.assertIn("depeg_breakpoint_pct", live["reverse_stress"])

    def test_report_written_atomically(self):
        self._write_positions({"aave_v3": 70000.0, "maple": 30000.0})
        rs.build_report(write=True, tolerance=-10.0, data_dir=self.data_dir)
        out_path = self.data_dir / rs.REPORT_FILENAME
        self.assertTrue(out_path.exists())
        # Valid JSON, no stray tmp files.
        json.loads(out_path.read_text(encoding="utf-8"))
        self.assertEqual(list(self.data_dir.glob("*.tmp")), [])
        self.assertEqual(list(self.data_dir.glob(".reverse_stress_*")), [])

    def test_report_no_write(self):
        self._write_positions({"aave_v3": 100000.0})
        rs.build_report(write=False, tolerance=-10.0, data_dir=self.data_dir)
        self.assertFalse((self.data_dir / rs.REPORT_FILENAME).exists())

    def test_report_no_positions(self):
        # No current_positions.json → no live_portfolio entry, still valid report.
        report = rs.build_report(write=False, tolerance=-10.0, data_dir=self.data_dir)
        self.assertNotIn("live_portfolio", report["strategies"])

    def test_live_allocation_normalised(self):
        self._write_positions({"aave_v3": 60000.0, "maple": 40000.0})
        report = rs.build_report(write=False, tolerance=-10.0, data_dir=self.data_dir)
        alloc = report["strategies"]["live_portfolio"]["allocation"]
        self.assertAlmostEqual(sum(alloc.values()), 1.0, places=6)


class TestImportHygiene(unittest.TestCase):

    FORBIDDEN = frozenset([
        "numpy", "scipy", "pandas", "requests", "web3", "socket",
        "urllib", "aiohttp", "httpx", "anthropic", "openai",
    ])

    def test_no_forbidden_imports(self):
        path = (_REPO_ROOT / "spa_core" / "backtesting" / "tier1"
                / "reverse_stress.py")
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    self.assertNotIn(alias.name.split(".")[0], self.FORBIDDEN)
            elif isinstance(node, ast.ImportFrom) and node.module:
                self.assertNotIn(node.module.split(".")[0], self.FORBIDDEN)

    def test_no_execution_imports(self):
        path = (_REPO_ROOT / "spa_core" / "backtesting" / "tier1"
                / "reverse_stress.py")
        src = path.read_text(encoding="utf-8")
        self.assertNotIn("spa_core.execution", src)

    def test_llm_forbidden_marker(self):
        path = (_REPO_ROOT / "spa_core" / "backtesting" / "tier1"
                / "reverse_stress.py")
        self.assertIn("# LLM_FORBIDDEN", path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
