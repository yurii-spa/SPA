"""
tests/test_documentation_completeness.py

Sprint v10.33 — MP-1417 Documentation gaps filled.
20 tests verifying:
  - Required documentation files exist
  - Files are non-empty (> 500 chars)
  - ADR files exist in docs/adr/ or docs/
  - SECURITY_CHECKLIST.md exists
  - assess_documentation() in GoLiveReadinessReport works correctly

stdlib only — unittest, no external dependencies.
"""

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

# Ensure repo root is on path
_REPO_ROOT = Path(__file__).parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from spa_core.analytics.golive_readiness_report import (
    CategoryScore,
    GoLiveReadinessReport,
)

# ── helpers ────────────────────────────────────────────────────────────────────

DOCS_DIR = _REPO_ROOT / "docs"
ADR_DIR = DOCS_DIR / "adr"
MIN_CHARS = 500

REQUIRED_DOCS = [
    "RISK_MANAGEMENT_POLICY.md",
    "DEPLOYMENT_RUNBOOK.md",
    "DATA_SOURCES_REGISTRY.md",
    "FAMILY_FUND_ONBOARDING.md",
    "API_REFERENCE.md",
    "SECURITY_CHECKLIST.md",
    "DISASTER_RECOVERY.md",
    "TOKEN_ROTATION_RUNBOOK.md",
]


def _write(path: Path, data: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(data, fh)


def _make_full_doc_env(base: Path) -> None:
    """Create a temp SPA dir with all required documentation files."""
    docs = base / "docs"
    docs.mkdir(parents=True, exist_ok=True)
    adr = docs / "adr"
    adr.mkdir(parents=True, exist_ok=True)
    data = base / "data"
    (data / "backtest").mkdir(parents=True, exist_ok=True)

    # Required doc files
    content = "x" * 600  # > 500 chars
    for fname in REQUIRED_DOCS:
        (docs / fname).write_text(f"# {fname}\n\n" + content, encoding="utf-8")

    # ADR files
    for i in range(1, 5):
        (adr / f"ADR-0{i:02d}-test.md").write_text(
            f"# ADR-0{i:02d}\n\n" + content, encoding="utf-8"
        )

    # Minimal data fixtures so GoLiveReadinessReport can instantiate
    _write(data / "backtest" / "pre_paper_backtest_gate.json", {"status": "PASS"})
    _write(data / "backtest" / "paper_ready_gate.json", {"status": "NOT_READY"})
    _write(data / "backtest" / "owner_paper_acceptance_gate.json", {"status": "NOT_SIGNED"})
    _write(data / "backtest" / "source_pipeline.json", {"sources": {}})
    _write(data / "golive_status.json", {"ready": False, "checks": {}, "blockers": []})
    _write(data / "paper_trading_status.json", {"is_demo": True})
    _write(data / "equity_curve_daily.json", [])
    _write(data / "current_positions.json", {})


# ── Tests: required docs exist on disk ────────────────────────────────────────

class TestRequiredDocsExist(unittest.TestCase):
    """Tests T01–T08: each required document exists."""

    # T01
    def test_risk_management_policy_exists(self):
        self.assertTrue((DOCS_DIR / "RISK_MANAGEMENT_POLICY.md").exists(),
                        "RISK_MANAGEMENT_POLICY.md must exist in docs/")

    # T02
    def test_deployment_runbook_exists(self):
        self.assertTrue((DOCS_DIR / "DEPLOYMENT_RUNBOOK.md").exists(),
                        "DEPLOYMENT_RUNBOOK.md must exist in docs/")

    # T03
    def test_data_sources_registry_exists(self):
        self.assertTrue((DOCS_DIR / "DATA_SOURCES_REGISTRY.md").exists(),
                        "DATA_SOURCES_REGISTRY.md must exist in docs/")

    # T04
    def test_family_fund_onboarding_exists(self):
        self.assertTrue((DOCS_DIR / "FAMILY_FUND_ONBOARDING.md").exists(),
                        "FAMILY_FUND_ONBOARDING.md must exist in docs/")

    # T05
    def test_api_reference_exists(self):
        self.assertTrue((DOCS_DIR / "API_REFERENCE.md").exists(),
                        "API_REFERENCE.md must exist in docs/")

    # T06
    def test_security_checklist_exists(self):
        self.assertTrue((DOCS_DIR / "SECURITY_CHECKLIST.md").exists(),
                        "SECURITY_CHECKLIST.md must exist in docs/")

    # T07
    def test_disaster_recovery_exists(self):
        self.assertTrue((DOCS_DIR / "DISASTER_RECOVERY.md").exists(),
                        "DISASTER_RECOVERY.md must exist in docs/")

    # T08
    def test_token_rotation_runbook_exists(self):
        self.assertTrue((DOCS_DIR / "TOKEN_ROTATION_RUNBOOK.md").exists(),
                        "TOKEN_ROTATION_RUNBOOK.md must exist in docs/")


# ── Tests: required docs non-empty ────────────────────────────────────────────

class TestRequiredDocsNonEmpty(unittest.TestCase):
    """Tests T09–T12: key documents are above the minimum size threshold."""

    def _size(self, fname: str) -> int:
        path = DOCS_DIR / fname
        return path.stat().st_size if path.exists() else 0

    # T09
    def test_risk_management_policy_non_empty(self):
        self.assertGreater(self._size("RISK_MANAGEMENT_POLICY.md"), MIN_CHARS,
                           f"RISK_MANAGEMENT_POLICY.md must be > {MIN_CHARS} chars")

    # T10
    def test_deployment_runbook_non_empty(self):
        self.assertGreater(self._size("DEPLOYMENT_RUNBOOK.md"), MIN_CHARS,
                           f"DEPLOYMENT_RUNBOOK.md must be > {MIN_CHARS} chars")

    # T11
    def test_data_sources_registry_non_empty(self):
        self.assertGreater(self._size("DATA_SOURCES_REGISTRY.md"), MIN_CHARS,
                           f"DATA_SOURCES_REGISTRY.md must be > {MIN_CHARS} chars")

    # T12
    def test_family_fund_onboarding_non_empty(self):
        self.assertGreater(self._size("FAMILY_FUND_ONBOARDING.md"), MIN_CHARS,
                           f"FAMILY_FUND_ONBOARDING.md must be > {MIN_CHARS} chars")


# ── Tests: ADR files ───────────────────────────────────────────────────────────

class TestADRFiles(unittest.TestCase):
    """Tests T13–T15: ADR files present in docs/adr/."""

    # T13
    def test_adr_directory_exists(self):
        self.assertTrue(ADR_DIR.exists() and ADR_DIR.is_dir(),
                        "docs/adr/ directory must exist")

    # T14
    def test_adr_directory_has_files(self):
        if not ADR_DIR.exists():
            self.fail("docs/adr/ does not exist")
        adr_files = [f for f in ADR_DIR.iterdir() if f.suffix == ".md"]
        self.assertGreaterEqual(len(adr_files), 3,
                                f"docs/adr/ must have ≥3 .md files (found {len(adr_files)})")

    # T15
    def test_adr_golive_transfer_rule_exists(self):
        """ADR-002 is a core governance document."""
        found = any("ADR-002" in f.name or "adr-002" in f.name.lower()
                    for f in ADR_DIR.iterdir() if f.is_file())
        self.assertTrue(found, "docs/adr/ must contain ADR-002 (go-live transfer rule)")


# ── Tests: assess_documentation() ─────────────────────────────────────────────

class TestAssessDocumentation(unittest.TestCase):
    """Tests T16–T20: GoLiveReadinessReport.assess_documentation() behaviour."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        _make_full_doc_env(Path(self.tmp))
        self.report = GoLiveReadinessReport(base_dir=self.tmp)

    # T16
    def test_assess_documentation_returns_category_score(self):
        cs = self.report.assess_documentation()
        self.assertIsInstance(cs, CategoryScore)

    # T17
    def test_assess_documentation_name(self):
        cs = self.report.assess_documentation()
        self.assertEqual(cs.name, "documentation")

    # T18
    def test_assess_documentation_all_docs_full_score(self):
        """With all docs present, score should equal max_score."""
        cs = self.report.assess_documentation()
        self.assertAlmostEqual(cs.score, cs.max_score, places=1,
                               msg="Full doc env should score max")

    # T19
    def test_assess_documentation_missing_docs_lower_score(self):
        """Without docs, score should be below max."""
        empty_tmp = tempfile.mkdtemp()
        _make_full_doc_env(Path(empty_tmp))
        # Remove all doc files
        docs_dir = Path(empty_tmp) / "docs"
        for fname in REQUIRED_DOCS:
            p = docs_dir / fname
            if p.exists():
                p.unlink()
        r = GoLiveReadinessReport(base_dir=empty_tmp)
        cs = r.assess_documentation()
        self.assertLess(cs.score, cs.max_score)

    # T20
    def test_documentation_in_categories(self):
        """assess_documentation should be included in _get_categories()."""
        cats = self.report._get_categories()
        names = [c.name for c in cats]
        self.assertIn("documentation", names,
                      "documentation must be in _get_categories()")


if __name__ == "__main__":
    unittest.main(verbosity=2)
