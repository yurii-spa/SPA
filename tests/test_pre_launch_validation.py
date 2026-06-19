"""
tests/test_pre_launch_validation.py

MP-1367 (v9.83) — Tests for PreLaunchValidation.

Compatible with stdlib unittest:
    python3 -m unittest tests.test_pre_launch_validation -v
Also compatible with pytest.

Test groups:
  1.  Class instantiation (tests 1–3)
  2.  VALIDATION_GROUPS constant (tests 4–6)
  3.  ValidationCheck dataclass (tests 7–10)
  4.  ValidationReport dataclass (tests 11–14)
  5.  run_group() (tests 15–19)
  6.  run_all() basic structure (tests 20–26)
  7.  blocking_checks() (tests 27–30)
  8.  launch_ready logic (tests 31–34)
  9.  save() (tests 35–38)
  10. to_markdown() (tests 39–45)

Total: 45 tests
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from spa_core.backtesting.pre_launch_validation import (
    VALIDATION_GROUPS,
    ValidationCheck,
    ValidationReport,
    PreLaunchValidation,
)


# ── Helpers ────────────────────────────────────────────────────────────────────

def _make_valid_env(tmpdir: str) -> None:
    """
    Populate a temp directory with the minimal files needed so that
    as many checks as possible pass (makes testing launch_ready=True feasible).
    """
    root = Path(tmpdir)

    # --- backtest gate files ---
    bt_dir = root / "data" / "backtest"
    bt_dir.mkdir(parents=True, exist_ok=True)
    (bt_dir / "pre_paper_backtest_gate.json").write_text(
        json.dumps({"status": "PASS", "paper_trading_allowed": True}),
        encoding="utf-8",
    )
    (bt_dir / "paper_ready_gate.json").write_text(
        json.dumps({"status": "READY", "paper_trading_allowed": True}),
        encoding="utf-8",
    )
    (bt_dir / "owner_paper_acceptance_gate.json").write_text(
        json.dumps({"accepted": True, "owner": "Yurii", "accepted_at": "2026-07-10"}),
        encoding="utf-8",
    )

    # --- golive_status.json (24/26 pass) ---
    (root / "data" / "golive_status.json").write_text(
        json.dumps({"ready": True, "passed": 24, "total": 26, "checks": {}}),
        encoding="utf-8",
    )

    # --- equity_curve_daily.json (30 days) ---
    entries = [{"date": f"2026-06-{i+1:02d}", "nav": 100_000 + i * 10} for i in range(30)]
    (root / "data" / "equity_curve_daily.json").write_text(
        json.dumps({"entries": entries}), encoding="utf-8",
    )

    # --- trades.json (all real) ---
    trades = [{"id": f"t{i}", "is_demo": False, "amount": 1000} for i in range(5)]
    (root / "data" / "trades.json").write_text(
        json.dumps({"trades": trades}), encoding="utf-8",
    )

    # --- paper_trading_status.json ---
    (root / "data" / "paper_trading_status.json").write_text(
        json.dumps({"is_demo": False, "portfolio_nav": 100_500.0, "current_apy": 0.055}),
        encoding="utf-8",
    )

    # --- gap_monitor.json (30 real days, 0 gaps) ---
    (root / "data" / "gap_monitor.json").write_text(
        json.dumps({"gaps": [], "real_track_days": 30}), encoding="utf-8",
    )

    # --- adapters ---
    adapters_dir = root / "spa_core" / "adapters"
    adapters_dir.mkdir(parents=True, exist_ok=True)
    for fname in ["aave_v3.py", "compound_v3.py", "morpho_steakhouse_adapter.py",
                  "defillama_feed.py"]:
        (adapters_dir / fname).write_text("# adapter\n", encoding="utf-8")
    (adapters_dir / "__init__.py").write_text(
        "ADAPTER_REGISTRY = {}\n", encoding="utf-8"
    )

    # --- strategies ---
    strategies_dir = root / "spa_core" / "strategies"
    strategies_dir.mkdir(parents=True, exist_ok=True)
    (strategies_dir / "strategy_registry.py").write_text("# registry\n", encoding="utf-8")

    # --- paper_trading ---
    pt_dir = root / "spa_core" / "paper_trading"
    pt_dir.mkdir(parents=True, exist_ok=True)
    (pt_dir / "tournament_evaluator.py").write_text("# eval\n", encoding="utf-8")
    (pt_dir / "multi_strategy_runner.py").write_text("# runner\n", encoding="utf-8")
    (pt_dir / "cycle_runner.py").write_text("# cycle\n", encoding="utf-8")

    # --- analytics ---
    analytics_dir = root / "spa_core" / "analytics"
    analytics_dir.mkdir(parents=True, exist_ok=True)
    (analytics_dir / "rs001_live_apy_engine.py").write_text("# rs001\n", encoding="utf-8")
    (analytics_dir / "rs002_live_apy_engine.py").write_text("# rs002\n", encoding="utf-8")
    (analytics_dir / "investment_memo_generator.py").write_text("# memo\n", encoding="utf-8")

    # --- family_fund ---
    ff_dir = root / "spa_core" / "family_fund"
    ff_dir.mkdir(parents=True, exist_ok=True)
    (ff_dir / "registry.py").write_text("# registry\n", encoding="utf-8")

    # --- risk ---
    risk_dir = root / "spa_core" / "risk"
    risk_dir.mkdir(parents=True, exist_ok=True)
    (risk_dir / "policy.py").write_text(
        'version = "v1.0"\n', encoding="utf-8"
    )

    # --- scripts ---
    scripts_dir = root / "scripts"
    scripts_dir.mkdir(parents=True, exist_ok=True)
    for fname in ["kill_switch_drill.py", "gnosis_safe_checklist.py",
                  "com.spa.autopush.plist", "com.spa.httpserver.plist",
                  "com.spa.cloudflared.plist"]:
        (scripts_dir / fname).write_text("# script\n", encoding="utf-8")

    # --- docs ---
    docs_dir = root / "docs"
    adr_dir = docs_dir / "adr"
    adr_dir.mkdir(parents=True, exist_ok=True)
    (adr_dir / "ADR-002-golive-transfer-rule.md").write_text("# ADR-002\n", encoding="utf-8")
    legal_dir = docs_dir / "legal"
    legal_dir.mkdir(parents=True, exist_ok=True)
    (legal_dir / "investor_agreement.md").write_text("# Agreement\n", encoding="utf-8")

    # --- top-level docs ---
    (root / "MASTER_PLAN_v1.md").write_text("# Master Plan\n", encoding="utf-8")
    (root / "DR_PROCEDURE_v2.md").write_text("# DR\n", encoding="utf-8")
    (root / "push_to_github.py").write_text("# push\n", encoding="utf-8")

    # --- unit tests (50+) ---
    core_tests_dir = root / "spa_core" / "tests"
    core_tests_dir.mkdir(parents=True, exist_ok=True)
    for i in range(60):
        (core_tests_dir / f"test_module_{i:03d}.py").write_text(
            f"# test {i}\n", encoding="utf-8"
        )

    # --- integration tests ---
    int_tests_dir = root / "tests"
    int_tests_dir.mkdir(parents=True, exist_ok=True)
    for i in range(5):
        (int_tests_dir / f"test_integration_{i}.py").write_text(
            f"# test {i}\n", encoding="utf-8"
        )


# ═══════════════════════════════════════════════════════════════════════════════
# Tests 1–3: Class instantiation
# ═══════════════════════════════════════════════════════════════════════════════

class TestInstantiation(unittest.TestCase):

    def test_01_instantiate_default(self):
        """PreLaunchValidation instantiates with default base_dir='.'."""
        v = PreLaunchValidation()
        self.assertIsNotNone(v)

    def test_02_instantiate_custom_base_dir(self):
        """PreLaunchValidation accepts a custom base_dir."""
        with tempfile.TemporaryDirectory() as tmpdir:
            v = PreLaunchValidation(base_dir=tmpdir)
            self.assertEqual(str(v.base_dir), tmpdir)

    def test_03_base_dir_is_path(self):
        """v.base_dir is a pathlib.Path."""
        v = PreLaunchValidation(base_dir="/tmp")
        self.assertIsInstance(v.base_dir, Path)


# ═══════════════════════════════════════════════════════════════════════════════
# Tests 4–6: VALIDATION_GROUPS constant
# ═══════════════════════════════════════════════════════════════════════════════

class TestValidationGroups(unittest.TestCase):

    def test_04_validation_groups_is_list(self):
        """VALIDATION_GROUPS is a list."""
        self.assertIsInstance(VALIDATION_GROUPS, list)

    def test_05_validation_groups_has_8_entries(self):
        """VALIDATION_GROUPS contains exactly 8 entries."""
        self.assertEqual(len(VALIDATION_GROUPS), 8)

    def test_06_validation_groups_content(self):
        """VALIDATION_GROUPS contains all expected group names."""
        expected = {
            "gates", "evidence", "infrastructure", "financial",
            "data_sources", "strategy", "documentation", "technical",
        }
        self.assertEqual(set(VALIDATION_GROUPS), expected)


# ═══════════════════════════════════════════════════════════════════════════════
# Tests 7–10: ValidationCheck dataclass
# ═══════════════════════════════════════════════════════════════════════════════

class TestValidationCheck(unittest.TestCase):

    def _make_check(self, **kwargs):
        defaults = {
            "group": "gates",
            "name": "test_check",
            "passed": True,
            "blocking": True,
            "message": "All good",
        }
        defaults.update(kwargs)
        return ValidationCheck(**defaults)

    def test_07_check_has_required_fields(self):
        """ValidationCheck has group, name, passed, blocking, message."""
        c = self._make_check()
        self.assertTrue(hasattr(c, "group"))
        self.assertTrue(hasattr(c, "name"))
        self.assertTrue(hasattr(c, "passed"))
        self.assertTrue(hasattr(c, "blocking"))
        self.assertTrue(hasattr(c, "message"))

    def test_08_check_group_in_validation_groups(self):
        """ValidationCheck.group must be in VALIDATION_GROUPS."""
        for group in VALIDATION_GROUPS:
            c = self._make_check(group=group)
            self.assertIn(c.group, VALIDATION_GROUPS)

    def test_09_check_to_dict(self):
        """ValidationCheck.to_dict() returns a dict with all fields."""
        c = self._make_check(passed=False, blocking=True)
        d = c.to_dict()
        self.assertIsInstance(d, dict)
        for key in ("group", "name", "passed", "blocking", "message"):
            self.assertIn(key, d)

    def test_10_check_passed_false(self):
        """ValidationCheck correctly stores passed=False."""
        c = self._make_check(passed=False)
        self.assertFalse(c.passed)


# ═══════════════════════════════════════════════════════════════════════════════
# Tests 11–14: ValidationReport dataclass
# ═══════════════════════════════════════════════════════════════════════════════

class TestValidationReport(unittest.TestCase):

    def _make_report(self, **kwargs):
        defaults = {
            "checks": [],
            "blocking_count": 0,
            "warning_count": 0,
            "passed_count": 0,
            "total_count": 0,
            "launch_ready": False,
            "generated_at": "2026-06-19T00:00:00+00:00",
        }
        defaults.update(kwargs)
        return ValidationReport(**defaults)

    def test_11_report_has_required_fields(self):
        """ValidationReport has all required fields."""
        r = self._make_report()
        for field in ("checks", "blocking_count", "warning_count",
                      "passed_count", "total_count", "launch_ready", "generated_at"):
            self.assertTrue(hasattr(r, field))

    def test_12_report_to_dict(self):
        """ValidationReport.to_dict() returns a serialisable dict."""
        r = self._make_report(passed_count=5, total_count=5)
        d = r.to_dict()
        self.assertIsInstance(d, dict)
        self.assertIn("launch_ready", d)
        self.assertIn("checks", d)
        # Must be JSON-serialisable
        json.dumps(d)

    def test_13_report_launch_ready_field(self):
        """ValidationReport.launch_ready is a bool."""
        r = self._make_report(launch_ready=True)
        self.assertIsInstance(r.launch_ready, bool)
        self.assertTrue(r.launch_ready)

    def test_14_report_schema_version(self):
        """ValidationReport.schema_version is set."""
        r = self._make_report()
        self.assertTrue(hasattr(r, "schema_version"))
        self.assertIsInstance(r.schema_version, str)


# ═══════════════════════════════════════════════════════════════════════════════
# Tests 15–19: run_group()
# ═══════════════════════════════════════════════════════════════════════════════

class TestRunGroup(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.v = PreLaunchValidation(base_dir=self.tmpdir)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_15_run_group_returns_list(self):
        """run_group('gates') returns a list."""
        result = self.v.run_group("gates")
        self.assertIsInstance(result, list)

    def test_16_run_group_checks_are_validation_checks(self):
        """Each item from run_group() is a ValidationCheck."""
        for group in VALIDATION_GROUPS:
            checks = self.v.run_group(group)
            for c in checks:
                self.assertIsInstance(c, ValidationCheck)

    def test_17_run_group_check_groups_match(self):
        """Every check returned by run_group(g) has check.group == g."""
        for group in VALIDATION_GROUPS:
            checks = self.v.run_group(group)
            for c in checks:
                self.assertEqual(c.group, group)

    def test_18_run_group_all_groups_return_checks(self):
        """Every group returns at least one check."""
        for group in VALIDATION_GROUPS:
            checks = self.v.run_group(group)
            self.assertGreater(len(checks), 0, f"Group {group!r} returned 0 checks")

    def test_19_run_group_invalid_group_raises(self):
        """run_group() raises ValueError for an unknown group."""
        with self.assertRaises(ValueError):
            self.v.run_group("nonexistent_group")


# ═══════════════════════════════════════════════════════════════════════════════
# Tests 20–26: run_all() basic structure
# ═══════════════════════════════════════════════════════════════════════════════

class TestRunAll(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.v = PreLaunchValidation(base_dir=self.tmpdir)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_20_run_all_returns_validation_report(self):
        """run_all() returns a ValidationReport."""
        report = self.v.run_all()
        self.assertIsInstance(report, ValidationReport)

    def test_21_report_total_count_gte_20(self):
        """report.total_count >= 20 (enough checks)."""
        report = self.v.run_all()
        self.assertGreaterEqual(report.total_count, 20)

    def test_22_report_checks_length_matches_total(self):
        """len(report.checks) == report.total_count."""
        report = self.v.run_all()
        self.assertEqual(len(report.checks), report.total_count)

    def test_23_report_counts_are_consistent(self):
        """passed + blocking_failures + warnings <= total."""
        report = self.v.run_all()
        self.assertLessEqual(
            report.passed_count + report.blocking_count + report.warning_count,
            report.total_count,
        )

    def test_24_report_generated_at_is_string(self):
        """report.generated_at is a non-empty string."""
        report = self.v.run_all()
        self.assertIsInstance(report.generated_at, str)
        self.assertTrue(report.generated_at)

    def test_25_all_check_groups_in_validation_groups(self):
        """Every check in report.checks has a group in VALIDATION_GROUPS."""
        report = self.v.run_all()
        for c in report.checks:
            self.assertIn(c.group, VALIDATION_GROUPS)

    def test_26_all_eight_groups_represented(self):
        """All 8 groups appear at least once in report.checks."""
        report = self.v.run_all()
        found_groups = {c.group for c in report.checks}
        for g in VALIDATION_GROUPS:
            self.assertIn(g, found_groups, f"Group {g!r} has no checks in report")


# ═══════════════════════════════════════════════════════════════════════════════
# Tests 27–30: blocking_checks()
# ═══════════════════════════════════════════════════════════════════════════════

class TestBlockingChecks(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.v = PreLaunchValidation(base_dir=self.tmpdir)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_27_blocking_checks_returns_list(self):
        """blocking_checks() returns a list."""
        result = self.v.blocking_checks()
        self.assertIsInstance(result, list)

    def test_28_blocking_checks_all_are_validation_checks(self):
        """All items in blocking_checks() are ValidationCheck instances."""
        for c in self.v.blocking_checks():
            self.assertIsInstance(c, ValidationCheck)

    def test_29_blocking_checks_none_passed(self):
        """Every check in blocking_checks() has passed=False."""
        for c in self.v.blocking_checks():
            self.assertFalse(c.passed)

    def test_30_blocking_checks_all_blocking_true(self):
        """Every check in blocking_checks() has blocking=True."""
        for c in self.v.blocking_checks():
            self.assertTrue(c.blocking)


# ═══════════════════════════════════════════════════════════════════════════════
# Tests 31–34: launch_ready logic
# ═══════════════════════════════════════════════════════════════════════════════

class TestLaunchReady(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_31_launch_ready_false_empty_env(self):
        """launch_ready=False when no gate files exist."""
        v = PreLaunchValidation(base_dir=self.tmpdir)
        report = v.run_all()
        self.assertFalse(report.launch_ready)

    def test_32_launch_ready_false_when_blocking_count_gt_0(self):
        """launch_ready=False when blocking_count > 0."""
        v = PreLaunchValidation(base_dir=self.tmpdir)
        report = v.run_all()
        if report.blocking_count > 0:
            self.assertFalse(report.launch_ready)

    def test_33_launch_ready_true_with_valid_env(self):
        """launch_ready=True when all blocking checks pass."""
        _make_valid_env(self.tmpdir)
        v = PreLaunchValidation(base_dir=self.tmpdir)
        report = v.run_all()
        self.assertEqual(report.blocking_count, 0)
        self.assertTrue(report.launch_ready)

    def test_34_blocking_count_zero_means_launch_ready(self):
        """blocking_count==0 implies launch_ready==True."""
        _make_valid_env(self.tmpdir)
        v = PreLaunchValidation(base_dir=self.tmpdir)
        report = v.run_all()
        if report.blocking_count == 0:
            self.assertTrue(report.launch_ready)


# ═══════════════════════════════════════════════════════════════════════════════
# Tests 35–38: save()
# ═══════════════════════════════════════════════════════════════════════════════

class TestSave(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.v = PreLaunchValidation(base_dir=self.tmpdir)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_35_save_creates_file(self):
        """save() creates a file in data/validation/."""
        report = self.v.run_all()
        path = self.v.save(report)
        self.assertTrue(Path(path).exists())

    def test_36_save_returns_string_path(self):
        """save() returns a string path."""
        report = self.v.run_all()
        path = self.v.save(report)
        self.assertIsInstance(path, str)

    def test_37_save_file_is_valid_json(self):
        """The saved file is valid JSON."""
        report = self.v.run_all()
        path = self.v.save(report)
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        self.assertIn("launch_ready", data)
        self.assertIn("checks", data)

    def test_38_save_path_in_validation_dir(self):
        """The saved file is under data/validation/."""
        report = self.v.run_all()
        path = self.v.save(report)
        self.assertIn("validation", path)


# ═══════════════════════════════════════════════════════════════════════════════
# Tests 39–45: to_markdown()
# ═══════════════════════════════════════════════════════════════════════════════

class TestToMarkdown(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.v = PreLaunchValidation(base_dir=self.tmpdir)
        self.report = self.v.run_all()

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_39_to_markdown_returns_string(self):
        """to_markdown() returns a non-empty string."""
        md = self.v.to_markdown(self.report)
        self.assertIsInstance(md, str)
        self.assertTrue(md)

    def test_40_to_markdown_contains_all_8_groups(self):
        """to_markdown() output references all 8 group names."""
        md = self.v.to_markdown(self.report)
        for group in VALIDATION_GROUPS:
            self.assertIn(group, md, f"Group {group!r} not in markdown output")

    def test_41_to_markdown_contains_status_header(self):
        """to_markdown() contains a status line (LAUNCH_READY or NOT_READY)."""
        md = self.v.to_markdown(self.report)
        self.assertTrue(
            "LAUNCH_READY" in md or "NOT_READY" in md,
            "Markdown must include LAUNCH_READY or NOT_READY",
        )

    def test_42_to_markdown_contains_summary_table(self):
        """to_markdown() includes a summary table."""
        md = self.v.to_markdown(self.report)
        self.assertIn("Total checks", md)
        self.assertIn("Passed", md)

    def test_43_to_markdown_contains_gates_section(self):
        """to_markdown() contains a gates section."""
        md = self.v.to_markdown(self.report)
        self.assertIn("gates", md.lower())

    def test_44_to_markdown_contains_technical_section(self):
        """to_markdown() contains a technical section."""
        md = self.v.to_markdown(self.report)
        self.assertIn("technical", md.lower())

    def test_45_to_markdown_contains_mp_reference(self):
        """to_markdown() references MP-1367."""
        md = self.v.to_markdown(self.report)
        self.assertIn("MP-1367", md)


# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    unittest.main(verbosity=2)
