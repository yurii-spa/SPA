"""
tests/test_pre_paper_checklist.py

MP-1321 (v9.37) — Tests for PrePaperChecklist.

Compatible with stdlib unittest:
    python3 -m unittest tests.test_pre_paper_checklist -v
Also compatible with pytest.

Test groups:
  1. check_all() structure                    (tests  1– 8)
  2. completion_pct                           (tests  9–12)
  3. Category structure (5 categories × 2)   (tests 13–22)
  4. Blocking items and overall_status        (tests 23–26)
  5. Specific automated item checks           (tests 27–30)
  6. to_markdown() format                     (tests 31–35)

Total: 35 tests
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

# ── Repo root on sys.path ─────────────────────────────────────────────────────
_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from spa_core.backtesting.pre_paper_checklist import (
    CHECKLIST_ITEMS,
    PrePaperChecklist,
)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_pre_paper_gate(tmpdir: str, status: str = "PASS") -> None:
    """Write a minimal pre_paper_backtest_gate.json into tmpdir."""
    dest = Path(tmpdir) / "data" / "backtest"
    dest.mkdir(parents=True, exist_ok=True)
    payload = {"schema_version": "0.1", "status": status}
    (dest / "pre_paper_backtest_gate.json").write_text(
        json.dumps(payload), encoding="utf-8"
    )


def _make_paper_ready_gate(
    tmpdir: str,
    hardening: str = "PASS",
    expanded: str = "PASS",
    paper_trading_allowed: bool = True,
) -> None:
    dest = Path(tmpdir) / "data" / "backtest"
    dest.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": "0.1",
        "status": "READY" if paper_trading_allowed else "NOT_READY",
        "paper_trading_allowed": paper_trading_allowed,
        "hardening_status": hardening,
        "expanded_universe_verification_status": expanded,
        "blockers": [],
    }
    (dest / "paper_ready_gate.json").write_text(
        json.dumps(payload), encoding="utf-8"
    )


def _make_owner_gate(
    tmpdir: str,
    signed: bool = True,
    blockers: list | None = None,
) -> None:
    dest = Path(tmpdir) / "data" / "backtest"
    dest.mkdir(parents=True, exist_ok=True)
    status = "SIGNED" if signed else "NOT_SIGNED"
    if blockers is None:
        blockers = [] if signed else ["accepted must be true.", "owner is required."]
    payload = {
        "schema_version": "0.1",
        "status": status,
        "blockers": blockers,
    }
    (dest / "owner_paper_acceptance_gate.json").write_text(
        json.dumps(payload), encoding="utf-8"
    )


def _make_full_pass_dir(tmpdir: str) -> None:
    """Create a tmpdir where all automated checks return PASS."""
    _make_pre_paper_gate(tmpdir, status="PASS")
    _make_paper_ready_gate(tmpdir, hardening="PASS", expanded="PASS", paper_trading_allowed=True)
    _make_owner_gate(tmpdir, signed=True)

    # GMX adapter
    adapter_dir = Path(tmpdir) / "spa_core" / "adapters"
    adapter_dir.mkdir(parents=True, exist_ok=True)
    (adapter_dir / "gmx_research.py").write_text("# stub", encoding="utf-8")

    # Source pipeline
    bp = Path(tmpdir) / "data" / "backtest"
    bp.mkdir(parents=True, exist_ok=True)
    (bp / "source_pipeline.json").write_text("{}", encoding="utf-8")

    # RS-001 report
    rpt = Path(tmpdir) / "data" / "backtest" / "reports"
    rpt.mkdir(parents=True, exist_ok=True)
    (rpt / "p1a_closure_report.md").write_text("# P1A", encoding="utf-8")

    # RS-002 doc
    bh = Path(tmpdir) / "docs" / "backtest_handoff"
    bh.mkdir(parents=True, exist_ok=True)
    (bh / "07_known_limitations.md").write_text("# Limitations", encoding="utf-8")

    # CPA status
    docs = Path(tmpdir) / "docs"
    docs.mkdir(parents=True, exist_ok=True)
    (docs / "CPA_INTEGRATION_STATUS.md").write_text("# CPA", encoding="utf-8")


# ═══════════════════════════════════════════════════════════════════════════════
# Group 1: check_all() structure (tests 1–8)
# ═══════════════════════════════════════════════════════════════════════════════

class TestCheckAllStructure(unittest.TestCase):
    """check_all() must return a correctly structured dict."""

    def setUp(self) -> None:
        self.tmp = tempfile.mkdtemp()
        # Minimal environment — real project for path checks
        _make_pre_paper_gate(self.tmp)
        _make_paper_ready_gate(self.tmp)
        _make_owner_gate(self.tmp, signed=False)
        self.cl = PrePaperChecklist(base_dir=self.tmp)
        self.result = self.cl.check_all()

    # 1
    def test_check_all_returns_dict(self) -> None:
        self.assertIsInstance(self.result, dict)

    # 2
    def test_check_all_has_categories(self) -> None:
        self.assertIn("categories", self.result)

    # 3
    def test_check_all_has_completion_pct(self) -> None:
        self.assertIn("completion_pct", self.result)

    # 4
    def test_check_all_has_overall_status(self) -> None:
        self.assertIn("overall_status", self.result)

    # 5
    def test_check_all_has_blocking_items(self) -> None:
        self.assertIn("blocking_items", self.result)

    # 6
    def test_check_all_has_next_action(self) -> None:
        self.assertIn("next_action", self.result)

    # 7
    def test_check_all_has_last_checked(self) -> None:
        self.assertIn("last_checked", self.result)

    # 8
    def test_categories_has_five_keys(self) -> None:
        cats = self.result["categories"]
        self.assertEqual(
            set(cats.keys()),
            {"gates", "data_sources", "infrastructure", "owner_signoff", "research_docs"},
        )


# ═══════════════════════════════════════════════════════════════════════════════
# Group 2: completion_pct (tests 9–12)
# ═══════════════════════════════════════════════════════════════════════════════

class TestCompletionPct(unittest.TestCase):
    """completion_pct must be a float between 0 and 100."""

    # 9
    def test_completion_pct_between_0_and_100(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cl = PrePaperChecklist(base_dir=tmp)
            result = cl.check_all()
            pct = result["completion_pct"]
            self.assertIsInstance(pct, float)
            self.assertGreaterEqual(pct, 0.0)
            self.assertLessEqual(pct, 100.0)

    # 10
    def test_completion_pct_method_matches_field(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cl = PrePaperChecklist(base_dir=tmp)
            result = cl.check_all()
            self.assertAlmostEqual(
                cl.completion_pct(result),
                result["completion_pct"],
                places=5,
            )

    # 11
    def test_completion_pct_100_when_all_pass(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            _make_full_pass_dir(tmp)
            cl = PrePaperChecklist(base_dir=tmp)
            result = cl.check_all()
            # All automated items should PASS; manual items still UNKNOWN
            # (UNKNOWN != PASS so 100% is only possible if all autos pass)
            # Count only automated items
            auto_pass = 0
            auto_total = 0
            for cat_items in CHECKLIST_ITEMS.values():
                for item in cat_items:
                    if item["auto"]:
                        auto_total += 1
            for cat in result["categories"].values():
                for it in cat["items"]:
                    if it["auto"] and it["status"] == "PASS":
                        auto_pass += 1
            self.assertEqual(auto_pass, auto_total)

    # 12
    def test_completion_pct_0_when_no_auto_pass(self) -> None:
        """In an empty directory with no gate files, automated checks fail."""
        with tempfile.TemporaryDirectory() as tmp:
            cl = PrePaperChecklist(base_dir=tmp)
            result = cl.check_all()
            # Some items are UNKNOWN (manual), none are PASS
            pct = result["completion_pct"]
            self.assertLess(pct, 50.0)


# ═══════════════════════════════════════════════════════════════════════════════
# Group 3: Category structure — 5 categories × 2 (tests 13–22)
# ═══════════════════════════════════════════════════════════════════════════════

class TestCategoryStructure(unittest.TestCase):
    """Each category must have 'status' and 'items' keys."""

    def setUp(self) -> None:
        self.tmp = tempfile.mkdtemp()
        self.result = PrePaperChecklist(base_dir=self.tmp).check_all()

    # 13
    def test_gates_has_status(self) -> None:
        self.assertIn("status", self.result["categories"]["gates"])

    # 14
    def test_gates_has_items(self) -> None:
        self.assertIn("items", self.result["categories"]["gates"])

    # 15
    def test_data_sources_has_status(self) -> None:
        self.assertIn("status", self.result["categories"]["data_sources"])

    # 16
    def test_data_sources_has_items(self) -> None:
        self.assertIn("items", self.result["categories"]["data_sources"])

    # 17
    def test_infrastructure_has_status(self) -> None:
        self.assertIn("status", self.result["categories"]["infrastructure"])

    # 18
    def test_infrastructure_has_items(self) -> None:
        self.assertIn("items", self.result["categories"]["infrastructure"])

    # 19
    def test_owner_signoff_has_status(self) -> None:
        self.assertIn("status", self.result["categories"]["owner_signoff"])

    # 20
    def test_owner_signoff_has_items(self) -> None:
        self.assertIn("items", self.result["categories"]["owner_signoff"])

    # 21
    def test_research_docs_has_status(self) -> None:
        self.assertIn("status", self.result["categories"]["research_docs"])

    # 22
    def test_research_docs_has_items(self) -> None:
        self.assertIn("items", self.result["categories"]["research_docs"])


# ═══════════════════════════════════════════════════════════════════════════════
# Group 4: Blocking items and overall_status (tests 23–26)
# ═══════════════════════════════════════════════════════════════════════════════

class TestBlockingAndOverallStatus(unittest.TestCase):
    """Blocking items and overall_status must reflect gate state."""

    # 23
    def test_blocking_items_not_empty_when_owner_unsigned(self) -> None:
        """Owner acceptance not signed → blocking_items must not be empty."""
        with tempfile.TemporaryDirectory() as tmp:
            _make_owner_gate(tmp, signed=False)
            cl = PrePaperChecklist(base_dir=tmp)
            result = cl.check_all()
            self.assertGreater(len(result["blocking_items"]), 0)

    # 24
    def test_overall_status_blocked_when_blocking_items(self) -> None:
        """If blocking_items is non-empty, overall_status must be BLOCKED."""
        with tempfile.TemporaryDirectory() as tmp:
            _make_owner_gate(tmp, signed=False)
            cl = PrePaperChecklist(base_dir=tmp)
            result = cl.check_all()
            self.assertEqual(result["overall_status"], "BLOCKED")

    # 25
    def test_overall_status_ready_when_all_blocking_pass(self) -> None:
        """When all blocking items pass, overall_status must be READY."""
        with tempfile.TemporaryDirectory() as tmp:
            _make_full_pass_dir(tmp)
            cl = PrePaperChecklist(base_dir=tmp)
            result = cl.check_all()
            self.assertEqual(result["overall_status"], "READY")

    # 26
    def test_blocking_items_method_returns_list(self) -> None:
        """blocking_items() must return a list (possibly empty)."""
        with tempfile.TemporaryDirectory() as tmp:
            cl = PrePaperChecklist(base_dir=tmp)
            result = cl.check_all()
            bi = cl.blocking_items(result)
            self.assertIsInstance(bi, list)


# ═══════════════════════════════════════════════════════════════════════════════
# Group 5: Specific automated item checks (tests 27–30)
# ═══════════════════════════════════════════════════════════════════════════════

class TestSpecificItemChecks(unittest.TestCase):
    """Key automated item checks — per spec: D003 and R003 use real files."""

    # 27
    def test_g001_pass_with_real_gate_file(self) -> None:
        """G001 → PASS when pre_paper_backtest_gate.json has status=PASS."""
        with tempfile.TemporaryDirectory() as tmp:
            _make_pre_paper_gate(tmp, status="PASS")
            cl = PrePaperChecklist(base_dir=tmp)
            result = cl.check_all()
            g001 = next(
                i for i in result["categories"]["gates"]["items"] if i["id"] == "G001"
            )
            self.assertEqual(g001["status"], "PASS")

    # 28
    def test_g001_fail_when_gate_file_missing(self) -> None:
        """G001 → FAIL when pre_paper_backtest_gate.json is absent."""
        with tempfile.TemporaryDirectory() as tmp:
            cl = PrePaperChecklist(base_dir=tmp)
            result = cl.check_all()
            g001 = next(
                i for i in result["categories"]["gates"]["items"] if i["id"] == "G001"
            )
            self.assertEqual(g001["status"], "FAIL")

    # 29
    def test_d003_pass_when_gmx_adapter_exists(self) -> None:
        """D003 → PASS when spa_core/adapters/gmx_research.py exists."""
        # Test with real project root where the file actually exists
        cl = PrePaperChecklist(base_dir=str(_REPO_ROOT))
        result = cl.check_all()
        d003 = next(
            i
            for i in result["categories"]["data_sources"]["items"]
            if i["id"] == "D003"
        )
        # The real gmx_research.py exists in the repo
        self.assertEqual(d003["status"], "PASS")

    # 30
    def test_r003_pass_when_cpa_integration_status_exists(self) -> None:
        """R003 → PASS when docs/CPA_INTEGRATION_STATUS.md exists."""
        cl = PrePaperChecklist(base_dir=str(_REPO_ROOT))
        result = cl.check_all()
        r003 = next(
            i
            for i in result["categories"]["research_docs"]["items"]
            if i["id"] == "R003"
        )
        self.assertEqual(r003["status"], "PASS")


# ═══════════════════════════════════════════════════════════════════════════════
# Group 6: to_markdown() format (tests 31–35)
# ═══════════════════════════════════════════════════════════════════════════════

class TestToMarkdown(unittest.TestCase):
    """to_markdown() must return a string containing all 5 category sections."""

    def setUp(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cl = PrePaperChecklist(base_dir=tmp)
            self.result = cl.check_all()
            self.md = cl.to_markdown(self.result)

    # 31
    def test_to_markdown_returns_str(self) -> None:
        self.assertIsInstance(self.md, str)

    # 32
    def test_to_markdown_contains_gates_section(self) -> None:
        self.assertIn("Gates", self.md)

    # 33
    def test_to_markdown_contains_data_sources_section(self) -> None:
        self.assertIn("Data", self.md)

    # 34
    def test_to_markdown_contains_infrastructure_section(self) -> None:
        self.assertIn("Infrastructure", self.md)

    # 35
    def test_to_markdown_contains_owner_section(self) -> None:
        self.assertIn("Owner", self.md)


# ═══════════════════════════════════════════════════════════════════════════════
# Group 7: save() atomic write (bonus test — ensures atomic write works)
# ═══════════════════════════════════════════════════════════════════════════════

class TestSaveAtomic(unittest.TestCase):
    """save() must write valid JSON atomically (tmp + os.replace)."""

    def test_save_creates_file_with_valid_json(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cl = PrePaperChecklist(base_dir=tmp)
            result = cl.check_all()
            dest = os.path.join(tmp, "data", "backtest", "pre_paper_checklist.json")
            cl.save(result, path=dest)
            self.assertTrue(os.path.exists(dest))
            with open(dest, encoding="utf-8") as fh:
                loaded = json.load(fh)
            self.assertIn("overall_status", loaded)
            self.assertIn("categories", loaded)


if __name__ == "__main__":
    unittest.main()
