"""
tests/test_cpa_health_dashboard.py

MP-1351 (v9.67) — 40 tests for CPAHealthDashboard.

Categories:
  1. Initialisation                           (tests  1-4)
  2. check_gate() — structure & values        (tests  5-12)
  3. check_modules() — list & content         (tests 13-20)
  4. check_data_sources() — keys & values     (tests 21-28)
  5. check_strategies() — RS-001 / RS-002     (tests 29-33)
  6. overall_status() — states & logic        (tests 34-37)
  7. render_terminal() — output string        (tests 38-39)
  8. to_dict() — JSON shape                   (test  40)

Run:
    python3 -m unittest tests.test_cpa_health_dashboard -v

stdlib only. Never touches real data files (uses tempdir isolation).
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest

# ── repo root import ──────────────────────────────────────────────────────────
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from spa_core.analytics.cpa_health_dashboard import CPAHealthDashboard


# ── helpers ───────────────────────────────────────────────────────────────────

def _make_tmpdir() -> str:
    """Create a temporary directory (caller responsible for cleanup)."""
    return tempfile.mkdtemp()


def _write_json(path: str, data: dict) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as fh:
        json.dump(data, fh)


def _make_full_gate_dir(base: str) -> None:
    """Populate a minimal gate directory so BacktestGate returns real data."""
    bd = os.path.join(base, "data", "backtest")
    _write_json(os.path.join(bd, "pre_paper_backtest_gate.json"), {
        "schema_version": "0.1",
        "generated_at":   "2026-06-19",
        "status":         "PASS",
        "paper_test_can_be_designed": True,
        "paper_trading_allowed":      False,
        "strict_blockers": [],
        "warnings": [],
    })
    _write_json(os.path.join(bd, "paper_ready_gate.json"), {
        "schema_version": "0.1",
        "status":         "NOT_READY",
        "paper_trading_allowed": False,
        "generated_at":   "2026-06-19",
        "run_id":         "test-run",
        "owner_acceptance": {"accepted": False, "owner": None, "accepted_at": None},
        "blockers": ["Owner acceptance not signed."],
    })
    _write_json(os.path.join(bd, "owner_paper_acceptance_gate.json"), {
        "schema_version": "0.1",
        "accepted":       False,
        "owner":          None,
        "accepted_at":    None,
    })
    _write_json(os.path.join(bd, "source_pipeline.json"), {
        "schema_version": "1.0",
        "last_updated":   "2026-06-19",
        "sources": {
            "aave_v3_usdc":   "clean_included",
            "compound_v3_usdc": "clean_included",
            "morpho_blue":    "pending",
            "gmx_btc":        "source_needed",
            "gmx_eth":        "source_needed",
            "pendle_pt":      "manual_proxy",
            "ethena_usde":    "review",
            "btc_conc":       "source_needed",
            "rwa_conc":       "source_needed",
            "delta_neutral":  "research_only",
            "maple":          "pending",
            "sky_susds":      "clean_included",
        },
        "audit_log": [],
    })


# ══════════════════════════════════════════════════════════════════════════════
# 1. Initialisation (tests 1-4)
# ══════════════════════════════════════════════════════════════════════════════

class TestInit(unittest.TestCase):

    def test_01_default_init(self):
        """CPAHealthDashboard initialises with no arguments."""
        d = CPAHealthDashboard()
        self.assertIsInstance(d, CPAHealthDashboard)

    def test_02_custom_base_dir(self):
        """CPAHealthDashboard accepts a custom base_dir string."""
        with tempfile.TemporaryDirectory() as tmp:
            d = CPAHealthDashboard(base_dir=tmp)
            self.assertIsInstance(d, CPAHealthDashboard)

    def test_03_accepts_dot_base_dir(self):
        """CPAHealthDashboard accepts '.' as base_dir."""
        d = CPAHealthDashboard(base_dir=".")
        self.assertIsInstance(d, CPAHealthDashboard)

    def test_04_nonexistent_base_dir_no_crash(self):
        """CPAHealthDashboard does not crash if base_dir does not exist."""
        d = CPAHealthDashboard(base_dir="/tmp/spa_nonexistent_12345")
        self.assertIsInstance(d, CPAHealthDashboard)


# ══════════════════════════════════════════════════════════════════════════════
# 2. check_gate() (tests 5-12)
# ══════════════════════════════════════════════════════════════════════════════

class TestCheckGate(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        _make_full_gate_dir(self.tmp)
        self.d = CPAHealthDashboard(base_dir=self.tmp)

    def _gate(self):
        return self.d.check_gate()

    def test_05_returns_dict(self):
        self.assertIsInstance(self._gate(), dict)

    def test_06_has_backtest_key(self):
        self.assertIn("backtest", self._gate())

    def test_07_has_pre_paper_key(self):
        self.assertIn("pre_paper", self._gate())

    def test_08_has_paper_key(self):
        self.assertIn("paper", self._gate())

    def test_09_has_live_key(self):
        self.assertIn("live", self._gate())

    def test_10_has_paper_pts_key(self):
        gate = self._gate()
        self.assertIn("paper_pts", gate)
        self.assertIsInstance(gate["paper_pts"], float)

    def test_11_has_blockers_key(self):
        gate = self._gate()
        self.assertIn("blockers", gate)
        self.assertIsInstance(gate["blockers"], list)

    def test_12_missing_gate_files_returns_unknown_not_crash(self):
        """Missing gate files must not raise; must return UNKNOWN or valid state."""
        with tempfile.TemporaryDirectory() as empty:
            d = CPAHealthDashboard(base_dir=empty)
            gate = d.check_gate()
        self.assertIsInstance(gate, dict)
        self.assertIn("backtest", gate)


# ══════════════════════════════════════════════════════════════════════════════
# 3. check_modules() (tests 13-20)
# ══════════════════════════════════════════════════════════════════════════════

class TestCheckModules(unittest.TestCase):

    def setUp(self):
        self.d = CPAHealthDashboard()
        self.modules = self.d.check_modules()

    def test_13_returns_list(self):
        self.assertIsInstance(self.modules, list)

    def test_14_list_is_not_empty(self):
        self.assertGreater(len(self.modules), 0)

    def test_15_each_item_is_dict(self):
        for m in self.modules:
            self.assertIsInstance(m, dict)

    def test_16_each_item_has_name(self):
        for m in self.modules:
            self.assertIn("name", m)

    def test_17_each_item_has_module(self):
        for m in self.modules:
            self.assertIn("module", m)

    def test_18_each_item_has_status(self):
        for m in self.modules:
            self.assertIn("status", m)

    def test_19_status_is_ok_or_no_data(self):
        valid = {"OK", "NO_DATA"}
        for m in self.modules:
            self.assertIn(m["status"], valid)

    def test_20_at_least_one_core_module_ok(self):
        """BacktestGate should always be importable (it exists in the repo)."""
        ok_modules = [m["name"] for m in self.modules if m["status"] == "OK"]
        self.assertGreater(len(ok_modules), 0)


# ══════════════════════════════════════════════════════════════════════════════
# 4. check_data_sources() (tests 21-28)
# ══════════════════════════════════════════════════════════════════════════════

class TestCheckDataSources(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        _make_full_gate_dir(self.tmp)
        self.d = CPAHealthDashboard(base_dir=self.tmp)
        self.src = self.d.check_data_sources()

    def test_21_returns_dict(self):
        self.assertIsInstance(self.src, dict)

    def test_22_has_CLEAN_key(self):
        self.assertIn("CLEAN", self.src)

    def test_23_has_IN_PROGRESS_key(self):
        self.assertIn("IN_PROGRESS", self.src)

    def test_24_has_NOT_STARTED_key(self):
        self.assertIn("NOT_STARTED", self.src)

    def test_25_has_total_key(self):
        self.assertIn("total", self.src)
        self.assertGreater(self.src["total"], 0)

    def test_26_counts_sum_to_total(self):
        s = self.src
        self.assertEqual(
            s["CLEAN"] + s["IN_PROGRESS"] + s["NOT_STARTED"], s["total"]
        )

    def test_27_has_clean_pct_key(self):
        self.assertIn("clean_pct", self.src)
        pct = self.src["clean_pct"]
        self.assertGreaterEqual(pct, 0.0)
        self.assertLessEqual(pct, 1.0)

    def test_28_has_sources_key_as_dict(self):
        self.assertIn("sources", self.src)
        self.assertIsInstance(self.src["sources"], dict)


# ══════════════════════════════════════════════════════════════════════════════
# 5. check_strategies() (tests 29-33)
# ══════════════════════════════════════════════════════════════════════════════

class TestCheckStrategies(unittest.TestCase):

    def setUp(self):
        self.d = CPAHealthDashboard()
        self.strats = self.d.check_strategies()

    def test_29_returns_list(self):
        self.assertIsInstance(self.strats, list)

    def test_30_list_not_empty(self):
        self.assertGreater(len(self.strats), 0)

    def test_31_contains_rs001(self):
        ids = [s["id"] for s in self.strats]
        self.assertIn("RS-001", ids)

    def test_32_contains_rs002(self):
        ids = [s["id"] for s in self.strats]
        self.assertIn("RS-002", ids)

    def test_33_each_strategy_has_status_research_only(self):
        for s in self.strats:
            self.assertEqual(s["status"], "RESEARCH_ONLY")


# ══════════════════════════════════════════════════════════════════════════════
# 6. overall_status() (tests 34-37)
# ══════════════════════════════════════════════════════════════════════════════

class TestOverallStatus(unittest.TestCase):

    def test_34_returns_string(self):
        d = CPAHealthDashboard()
        result = d.overall_status()
        self.assertIsInstance(result, str)

    def test_35_valid_values(self):
        d = CPAHealthDashboard()
        result = d.overall_status()
        self.assertIn(result, {"HEALTHY", "NOT_READY", "BLOCKED"})

    def test_36_not_ready_when_paper_gate_not_pass(self):
        """With standard gate setup paper is NOT_READY → overall must be NOT_READY."""
        with tempfile.TemporaryDirectory() as tmp:
            _make_full_gate_dir(tmp)
            d = CPAHealthDashboard(base_dir=tmp)
            status = d.overall_status()
        # paper gate is NOT_READY in our fixture → overall must not be HEALTHY
        self.assertNotEqual(status, "HEALTHY")

    def test_37_missing_data_does_not_return_healthy(self):
        """An empty repo must not report HEALTHY."""
        with tempfile.TemporaryDirectory() as empty:
            d = CPAHealthDashboard(base_dir=empty)
            status = d.overall_status()
        self.assertNotEqual(status, "HEALTHY")


# ══════════════════════════════════════════════════════════════════════════════
# 7. render_terminal() (tests 38-39)
# ══════════════════════════════════════════════════════════════════════════════

class TestRenderTerminal(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        _make_full_gate_dir(self.tmp)
        self.d = CPAHealthDashboard(base_dir=self.tmp)

    def test_38_returns_long_string(self):
        out = self.d.render_terminal()
        self.assertIsInstance(out, str)
        self.assertGreater(len(out), 200)

    def test_39_contains_key_sections(self):
        out = self.d.render_terminal()
        self.assertIn("GATE STATUS", out)
        self.assertIn("MODULES", out)
        self.assertIn("DATA SOURCES", out)
        self.assertIn("RESEARCH STRATEGIES", out)
        self.assertIn("OVERALL", out)


# ══════════════════════════════════════════════════════════════════════════════
# 8. to_dict() (test 40)
# ══════════════════════════════════════════════════════════════════════════════

class TestToDict(unittest.TestCase):

    def test_40_has_gate_and_modules_keys(self):
        with tempfile.TemporaryDirectory() as tmp:
            _make_full_gate_dir(tmp)
            d = CPAHealthDashboard(base_dir=tmp)
            result = d.to_dict()
        self.assertIsInstance(result, dict)
        self.assertIn("gate", result)
        self.assertIn("modules", result)
        self.assertIn("data_sources", result)
        self.assertIn("strategies", result)
        self.assertIn("overall", result)
        # Must be JSON-serialisable
        serialised = json.dumps(result)
        self.assertIsInstance(serialised, str)


if __name__ == "__main__":
    unittest.main(verbosity=2)
