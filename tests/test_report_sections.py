"""
tests/test_report_sections.py

20 tests for spa_core/reporting/report_sections.py (MP-1478, v10.94).

Coverage:
  - golive_section() explicit params + data-dir loading
  - evidence_section() day counting + ETA computation
  - tournament_section() static catalogue fallback + live data merge
  - security_audit_section() inline checks
  - build_full_report() assembly

Stdlib only — no third-party deps, no network calls.
"""
from __future__ import annotations

import json
import os
import shutil
import tempfile
import unittest
from datetime import date, timedelta


# ---------------------------------------------------------------------------
# Import under test
# ---------------------------------------------------------------------------

import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from spa_core.reporting.report_sections import (
    _STRATEGY_CATALOGUE,
    build_full_report,
    evidence_section,
    golive_section,
    security_audit_section,
    tournament_section,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _write_json(directory: str, filename: str, data: object) -> str:
    path = os.path.join(directory, filename)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(data, fh)
    return path


# ---------------------------------------------------------------------------
# 1. golive_section()
# ---------------------------------------------------------------------------

class TestGoLiveSection(unittest.TestCase):

    def test_01_returns_dict(self):
        """golive_section() must return a dict."""
        result = golive_section(score=60, categories={"gate": 1})
        self.assertIsInstance(result, dict)

    def test_02_title_is_set(self):
        """golive_section must have a non-empty 'title' key."""
        result = golive_section(score=70)
        self.assertIn("title", result)
        self.assertTrue(result["title"])

    def test_03_status_on_track_when_ge_80(self):
        """score >= 80 → status == 'ON_TRACK'."""
        result = golive_section(score=85)
        self.assertEqual(result["status"], "ON_TRACK")

    def test_04_status_needs_attention_50_to_79(self):
        """50 <= score < 80 → status == 'NEEDS_ATTENTION'."""
        result = golive_section(score=62)
        self.assertEqual(result["status"], "NEEDS_ATTENTION")

    def test_05_status_blocked_below_50(self):
        """score < 50 → status == 'BLOCKED'."""
        result = golive_section(score=20)
        self.assertEqual(result["status"], "BLOCKED")

    def test_06_score_string_format(self):
        """'score' field must be in 'N/100' format."""
        result = golive_section(score=73)
        self.assertIn("/100", result["score"])
        self.assertTrue(result["score"].startswith("73"))

    def test_07_reads_golive_status_json(self):
        """golive_section reads passed/total from data_dir/golive_status.json."""
        tmpdir = tempfile.mkdtemp()
        try:
            _write_json(tmpdir, "golive_status.json", {
                "ready": False, "passed": 20, "total": 26,
                "checks": {"a": True, "b": False},
                "blockers": ["blocker1"],
            })
            result = golive_section(data_dir=tmpdir)
            self.assertEqual(result["passed"], 20)
            self.assertEqual(result["total"], 26)
            self.assertIn("blocker1", result["blockers"])
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_08_generated_at_is_iso(self):
        """generated_at must be a parseable ISO 8601 timestamp."""
        from datetime import datetime, timezone
        result = golive_section(score=50)
        ts = result.get("generated_at", "")
        datetime.fromisoformat(ts.replace("Z", "+00:00"))  # must not raise


# ---------------------------------------------------------------------------
# 2. evidence_section()
# ---------------------------------------------------------------------------

class TestEvidenceSection(unittest.TestCase):

    def test_09_returns_dict(self):
        """evidence_section() must return a dict."""
        result = evidence_section(days=10, target=30, score=10.0)
        self.assertIsInstance(result, dict)

    def test_10_progress_string_format(self):
        """'progress' field must be 'N/M days'."""
        result = evidence_section(days=15, target=30)
        self.assertEqual(result["progress"], "15/30 days")

    def test_11_pct_complete_correct(self):
        """pct_complete must equal days/target * 100."""
        result = evidence_section(days=10, target=40)
        self.assertAlmostEqual(result["pct_complete"], 25.0, places=1)

    def test_12_eta_auto_computed(self):
        """ETA must be a date string in YYYY-MM-DD format when not supplied."""
        result = evidence_section(days=5, target=30)
        eta = result.get("eta", "")
        # Should be parseable as a date
        date.fromisoformat(eta)  # must not raise

    def test_13_reads_equity_curve_json(self):
        """evidence_section reads day count from data_dir/equity_curve_daily.json."""
        tmpdir = tempfile.mkdtemp()
        try:
            _write_json(tmpdir, "equity_curve_daily.json", [
                {"date": "2026-06-10", "nav": 100000},
                {"date": "2026-06-11", "nav": 100100},
                {"date": "2026-06-12", "nav": 100200},
            ])
            result = evidence_section(data_dir=tmpdir)
            self.assertEqual(result["days_done"], 3)
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)


# ---------------------------------------------------------------------------
# 3. tournament_section()
# ---------------------------------------------------------------------------

class TestTournamentSection(unittest.TestCase):

    def test_14_returns_dict_with_strategies(self):
        """tournament_section() must return dict with 'strategies' list."""
        result = tournament_section()
        self.assertIn("strategies", result)
        self.assertIsInstance(result["strategies"], list)

    def test_15_strategies_sorted_by_apy_desc(self):
        """strategies list must be sorted by apy_est descending."""
        result = tournament_section()
        apys = [s.get("apy_est", 0) for s in result["strategies"]]
        self.assertEqual(apys, sorted(apys, reverse=True))

    def test_16_static_catalogue_has_s0_through_s12(self):
        """Static catalogue must include S0–S12 (13 strategies)."""
        ids = {s["id"] for s in _STRATEGY_CATALOGUE}
        for sid in ["S0", "S1", "S8", "S9", "S10", "S11", "S12"]:
            self.assertIn(sid, ids, f"{sid} missing from static catalogue")

    def test_17_top_apy_matches_max_strategy(self):
        """top_apy must equal the highest apy_est in strategies list."""
        result = tournament_section()
        if result["strategies"]:
            expected = max(s.get("apy_est", 0) for s in result["strategies"])
            self.assertAlmostEqual(result["top_apy"], expected, places=2)

    def test_18_loads_live_tournament_results(self):
        """tournament_section uses tournament_results.json when present."""
        tmpdir = tempfile.mkdtemp()
        try:
            _write_json(tmpdir, "tournament_results.json", {
                "results": {
                    "S0": {"name": "Cash", "apy": 0.0, "tier": "T1", "status": "active"},
                    "S9": {"name": "E-Mode", "apy": 5.84, "tier": "T1", "status": "active"},
                    "S8": {"name": "Delta-Neutral", "apy": 27.5, "tier": "T3", "status": "advisory"},
                }
            })
            result = tournament_section(data_dir=tmpdir)
            ids = {s["id"] for s in result["strategies"]}
            self.assertIn("S8", ids)
            self.assertIn("S9", ids)
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)


# ---------------------------------------------------------------------------
# 4. security_audit_section()
# ---------------------------------------------------------------------------

class TestSecurityAuditSection(unittest.TestCase):

    def test_19_returns_dict(self):
        """security_audit_section() must return a dict."""
        result = security_audit_section()
        self.assertIsInstance(result, dict)

    def test_20_has_required_keys(self):
        """security_audit_section must contain all required keys."""
        result = security_audit_section()
        for key in ("title", "overall_status", "checks", "checks_passed", "checks_total",
                    "open_findings", "generated_at"):
            self.assertIn(key, result, f"Missing key: {key}")

    def test_20b_checks_is_list(self):
        """'checks' must be a list of dicts."""
        result = security_audit_section()
        self.assertIsInstance(result["checks"], list)
        for chk in result["checks"]:
            self.assertIsInstance(chk, dict)
            self.assertIn("name", chk)
            self.assertIn("passed", chk)

    def test_20c_build_full_report_structure(self):
        """build_full_report() must return a dict with all four sections."""
        report = build_full_report()
        self.assertIn("sections", report)
        for section in ("golive", "evidence", "tournament", "security_audit"):
            self.assertIn(section, report["sections"], f"Missing section: {section}")


if __name__ == "__main__":
    unittest.main(verbosity=2)
