"""
tests/test_weekly_paper_report_v2.py

40 unit tests for spa_core.analytics.weekly_paper_report_v2.
MP-1312, Sprint v9.28.

Coverage:
  - gate_section() — 4-state gate status
  - research_exclusions_section()
  - paper_performance_section() — APY computation, drift
  - research_shadow_section() — graceful empty when files missing
  - source_quality_section() — with and without source_pipeline.json
  - generate_full_report() — top-level structure
  - to_markdown() — non-empty string with headings
  - save() — atomic write
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Dict

# Ensure project root on path
sys.path.insert(0, str(Path(__file__).parent.parent))

from spa_core.analytics.weekly_paper_report_v2 import (
    WeeklyPaperReportV2,
    _compute_apy,
    _load_json,
)


# ─── Helpers ─────────────────────────────────────────────────────────────────

def _make_reporter(backtest_dir: str = "data/backtest") -> WeeklyPaperReportV2:
    return WeeklyPaperReportV2(initial_capital=100_000.0, backtest_dir=backtest_dir)


def _make_fake_backtest_dir(tmpdir: str, pre_paper: Dict, paper_ready: Dict, owner: Dict) -> str:
    bd = os.path.join(tmpdir, "backtest")
    os.makedirs(bd, exist_ok=True)
    for name, data in (
        ("pre_paper_backtest_gate.json", pre_paper),
        ("paper_ready_gate.json", paper_ready),
        ("owner_paper_acceptance_gate.json", owner),
    ):
        with open(os.path.join(bd, name), "w") as f:
            json.dump(data, f)
    return bd


# ─── _compute_apy Tests ───────────────────────────────────────────────────────

class TestComputeApy(unittest.TestCase):

    def test_01_flat_nav_returns_zero(self):
        apy = _compute_apy(100_000.0, 100_000.0, 365)
        self.assertAlmostEqual(apy, 0.0, places=4)

    def test_02_zero_days_returns_none(self):
        self.assertIsNone(_compute_apy(110_000.0, 100_000.0, 0))

    def test_03_zero_initial_returns_none(self):
        self.assertIsNone(_compute_apy(110_000.0, 0.0, 30))

    def test_04_positive_return(self):
        # 10% gain over 365 days → ~10% APY
        apy = _compute_apy(110_000.0, 100_000.0, 365)
        self.assertAlmostEqual(apy, 10.0, places=1)

    def test_05_short_period_annualises(self):
        # 1% gain in 36.5 days → ~10% APY
        apy = _compute_apy(101_000.0, 100_000.0, 36)
        self.assertIsNotNone(apy)
        self.assertGreater(apy, 0.0)


# ─── _load_json Tests ─────────────────────────────────────────────────────────

class TestLoadJson(unittest.TestCase):

    def test_06_returns_none_for_missing(self):
        self.assertIsNone(_load_json("/nonexistent/path/file.json"))

    def test_07_loads_valid_json(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump({"key": "value"}, f)
            fname = f.name
        try:
            data = _load_json(fname)
            self.assertEqual(data["key"], "value")
        finally:
            os.unlink(fname)


# ─── gate_section Tests ───────────────────────────────────────────────────────

class TestGateSection(unittest.TestCase):

    def test_08_gate_section_has_four_states(self):
        reporter = _make_reporter("/nonexistent_dir")
        result = reporter.gate_section()
        for key in ("backtest", "pre_paper", "paper", "live"):
            self.assertIn(key, result)

    def test_09_missing_files_return_unknown(self):
        reporter = _make_reporter("/nonexistent_dir")
        result = reporter.gate_section()
        # Missing files should produce UNKNOWN-like statuses, not raise
        self.assertIsInstance(result["pre_paper"], str)
        self.assertIsInstance(result["paper"], str)

    def test_10_gate_section_has_blockers_list(self):
        reporter = _make_reporter("/nonexistent_dir")
        result = reporter.gate_section()
        self.assertIn("blockers", result)
        self.assertIsInstance(result["blockers"], list)

    def test_11_gate_section_live_not_ready_without_owner(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            bd = _make_fake_backtest_dir(
                tmpdir,
                pre_paper={"status": "PASS"},
                paper_ready={"status": "READY"},
                owner={"accepted": False},
            )
            reporter = WeeklyPaperReportV2(backtest_dir=bd)
            result = reporter.gate_section()
            self.assertEqual(result["live"], "NOT_READY")

    def test_12_gate_section_live_ready_with_owner(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            bd = _make_fake_backtest_dir(
                tmpdir,
                pre_paper={"status": "PASS"},
                paper_ready={"status": "READY"},
                owner={"accepted": True},
            )
            reporter = WeeklyPaperReportV2(backtest_dir=bd)
            result = reporter.gate_section()
            self.assertEqual(result["live"], "READY")

    def test_13_section_key_is_gate_status(self):
        reporter = _make_reporter("/nonexistent_dir")
        result = reporter.gate_section()
        self.assertEqual(result["section"], "gate_status")


# ─── research_exclusions_section Tests ───────────────────────────────────────

class TestResearchExclusionsSection(unittest.TestCase):

    def setUp(self):
        self.reporter = _make_reporter()
        self.result = self.reporter.research_exclusions_section()

    def test_14_contains_rs001_and_rs002(self):
        codes = {s["code"] for s in self.result["strategies"]}
        self.assertIn("RS001", codes)
        self.assertIn("RS002", codes)

    def test_15_count_is_2(self):
        self.assertEqual(self.result["count"], 2)

    def test_16_all_excluded(self):
        for strat in self.result["strategies"]:
            self.assertTrue(strat["excluded_from_strict_evidence"])

    def test_17_has_note(self):
        self.assertIn("note", self.result)
        self.assertIsInstance(self.result["note"], str)
        self.assertGreater(len(self.result["note"]), 0)

    def test_18_section_key(self):
        self.assertEqual(self.result["section"], "research_exclusions")


# ─── paper_performance_section Tests ─────────────────────────────────────────

class TestPaperPerformanceSection(unittest.TestCase):

    def setUp(self):
        self.reporter = _make_reporter()

    def test_19_flat_nav_zero_pnl(self):
        result = self.reporter.paper_performance_section(100_000.0, 9)
        self.assertAlmostEqual(result["pnl_usd"], 0.0, places=4)
        self.assertAlmostEqual(result["pnl_pct"], 0.0, places=4)

    def test_20_positive_pnl(self):
        result = self.reporter.paper_performance_section(105_000.0, 9)
        self.assertGreater(result["pnl_usd"], 0)
        self.assertGreater(result["pnl_pct"], 0)

    def test_21_apy_computed(self):
        result = self.reporter.paper_performance_section(110_000.0, 365)
        apy = result["annualised_return_pct"]
        self.assertIsNotNone(apy)
        self.assertAlmostEqual(apy, 10.0, places=1)

    def test_22_days_zero_returns_none_apy(self):
        result = self.reporter.paper_performance_section(110_000.0, 0)
        self.assertIsNone(result["annualised_return_pct"])

    def test_23_section_key(self):
        result = self.reporter.paper_performance_section(100_000.0, 9)
        self.assertEqual(result["section"], "paper_performance")

    def test_24_weekly_snapshots_default_empty(self):
        result = self.reporter.paper_performance_section(100_000.0, 9)
        self.assertEqual(result["weekly_snapshots"], [])

    def test_25_weekly_snapshots_passed_through(self):
        snaps = [{"date": "2026-06-12", "nav": 100_100.0}]
        result = self.reporter.paper_performance_section(100_000.0, 9, snaps)
        self.assertEqual(result["weekly_snapshots"], snaps)


# ─── research_shadow_section Tests ───────────────────────────────────────────

class TestResearchShadowSection(unittest.TestCase):

    def test_26_graceful_empty_without_shadow_files(self):
        reporter = _make_reporter()
        result = reporter.research_shadow_section()
        # Should not raise; RS001/RS002 should be present but not available
        self.assertIn("RS001", result["strategies"])
        self.assertIn("RS002", result["strategies"])
        self.assertFalse(result["strategies"]["RS001"]["available"])
        self.assertFalse(result["strategies"]["RS002"]["available"])

    def test_27_section_key(self):
        result = _make_reporter().research_shadow_section()
        self.assertEqual(result["section"], "research_shadow")

    def test_28_available_false_when_no_files(self):
        result = _make_reporter().research_shadow_section()
        self.assertFalse(result["available"])

    def test_29_available_true_when_shadow_file_exists(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            research_dir = os.path.join(tmpdir, "research")
            os.makedirs(research_dir, exist_ok=True)
            shadow_path = os.path.join(research_dir, "rs001_shadow.json")
            with open(shadow_path, "w") as f:
                json.dump({"shadow_nav": 101_000.0}, f)

            # Monkey-patch the research base dir
            reporter = _make_reporter()
            import unittest.mock as mock
            original_load = reporter.research_shadow_section.__func__

            # Directly test by calling with modified path via monkeypatching _load_json
            import spa_core.analytics.weekly_paper_report_v2 as mod
            original = mod._load_json

            def patched_load(path):
                # Redirect data/research/* to our tmpdir/research/*
                if "research" in path:
                    fname = os.path.basename(path)
                    return original(os.path.join(research_dir, fname))
                return original(path)

            mod._load_json = patched_load
            try:
                result = reporter.research_shadow_section()
                self.assertTrue(result["strategies"]["RS001"]["available"])
            finally:
                mod._load_json = original

    def test_30_note_present(self):
        result = _make_reporter().research_shadow_section()
        self.assertIn("note", result)


# ─── source_quality_section Tests ────────────────────────────────────────────

class TestSourceQualitySection(unittest.TestCase):

    def test_31_graceful_when_no_pipeline(self):
        reporter = _make_reporter("/nonexistent_dir")
        result = reporter.source_quality_section()
        self.assertFalse(result["available"])
        self.assertIn("note", result)

    def test_32_section_key(self):
        result = _make_reporter("/nonexistent_dir").source_quality_section()
        self.assertEqual(result["section"], "source_quality")

    def test_33_reads_pipeline_correctly(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            bd = os.path.join(tmpdir, "backtest")
            os.makedirs(bd)
            pipeline = {
                "sources": {
                    "aave_v3": "clean_included",
                    "compound": "clean_included",
                    "gmx": "source_needed",
                    "yearn": "pending",
                }
            }
            with open(os.path.join(bd, "source_pipeline.json"), "w") as f:
                json.dump(pipeline, f)

            reporter = WeeklyPaperReportV2(backtest_dir=bd)
            result = reporter.source_quality_section()
            self.assertTrue(result["available"])
            self.assertEqual(result["total_sources"], 4)
            self.assertEqual(result["clean_included"], 2)
            # Coverage = 2/4 = 50%
            self.assertAlmostEqual(result["strict_coverage_pct"], 50.0, places=1)


# ─── generate_full_report Tests ──────────────────────────────────────────────

class TestGenerateFullReport(unittest.TestCase):

    def setUp(self):
        self.reporter = _make_reporter()
        self.report = self.reporter.generate_full_report()

    def test_34_contains_all_sections(self):
        for key in (
            "gate_section",
            "research_exclusions_section",
            "paper_performance_section",
            "research_shadow_section",
            "source_quality_section",
        ):
            self.assertIn(key, self.report)

    def test_35_report_type(self):
        self.assertEqual(self.report["report_type"], "weekly_paper_report_v2")

    def test_36_generated_at_present(self):
        self.assertIn("generated_at", self.report)

    def test_37_default_nav_is_initial_capital(self):
        perf = self.report["paper_performance_section"]
        self.assertAlmostEqual(perf["pnl_usd"], 0.0, places=4)


# ─── to_markdown Tests ────────────────────────────────────────────────────────

class TestToMarkdown(unittest.TestCase):

    def setUp(self):
        self.reporter = _make_reporter()
        self.report = self.reporter.generate_full_report(paper_nav=101_000.0, days_elapsed=9)
        self.md = self.reporter.to_markdown(self.report)

    def test_38_returns_non_empty_string(self):
        self.assertIsInstance(self.md, str)
        self.assertGreater(len(self.md), 0)

    def test_39_contains_headings(self):
        self.assertIn("# SPA Weekly Paper Report v2", self.md)
        self.assertIn("## Gate Status", self.md)
        self.assertIn("## Research Exclusions", self.md)
        self.assertIn("## Paper Performance", self.md)

    # ─── save() ───────────────────────────────────────────────────────────────

    def test_40_save_atomic_and_valid_json(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            out = os.path.join(tmpdir, "paper", "weekly_report_v2.json")
            self.reporter.save(self.report, out)

            self.assertTrue(os.path.exists(out))
            with open(out, "r", encoding="utf-8") as fh:
                loaded = json.load(fh)

            self.assertEqual(loaded["report_type"], "weekly_paper_report_v2")
            self.assertIn("gate_section", loaded)


if __name__ == "__main__":
    unittest.main(verbosity=2)
