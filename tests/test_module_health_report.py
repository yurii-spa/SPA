"""
tests/test_module_health_report.py

25 тестов для scripts/module_health_report.py
Sprint v10.6 — MP-1390 AUDIT-001
"""
import os
import sys
import json
import shutil
import tempfile
import textwrap
import unittest
from pathlib import Path

# Убеждаемся, что корень проекта в sys.path
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from scripts.module_health_report import (
    generate_report,
    save_report,
    render_markdown,
)


# ---------------------------------------------------------------------------
# Fixtures: minimal fake repo
# ---------------------------------------------------------------------------

def _make_fake_repo() -> str:
    """
    Creates a minimal repo structure in a temp dir.
    Returns the path to the repo root.
    """
    d = tempfile.mkdtemp()
    spa = Path(d) / "spa_core"

    # adapters module with local atomic write
    (spa / "adapters").mkdir(parents=True)
    (spa / "adapters" / "__init__.py").write_text('"""adapters package"""\n')
    (spa / "adapters" / "aave.py").write_text(textwrap.dedent('''\
        """Aave adapter."""
        import os, json, tempfile

        def _atomic_write(path, data):
            tmp = path + ".tmp"
            with open(tmp, "w") as f:
                json.dump(data, f)
            os.replace(tmp, path)

        def fetch():
            return {"apy": 3.5}
    '''))

    # already-migrated module
    (spa / "utils").mkdir(parents=True)
    (spa / "utils" / "__init__.py").write_text("")
    (spa / "utils" / "atomic.py").write_text(textwrap.dedent('''\
        """Atomic utils."""
        from spa_core.utils.atomic import atomic_save, atomic_load

        def save(data, path):
            atomic_save(data, path)
    '''))

    # strategy module without test
    (spa / "strategies").mkdir(parents=True)
    (spa / "strategies" / "__init__.py").write_text("")
    (spa / "strategies" / "base.py").write_text(textwrap.dedent('''\
        """Base strategy."""
        class BaseStrategy:
            def run(self):
                pass
    '''))

    # tests dir
    tests = Path(d) / "tests"
    tests.mkdir()
    (tests / "__init__.py").write_text("")
    (tests / "test_aave.py").write_text(textwrap.dedent('''\
        """Test aave adapter."""
        import unittest
        class TestAave(unittest.TestCase):
            def test_fetch(self): pass
    '''))

    # KANBAN.json
    kanban = {
        "sprint_current": "v10.6",
        "sprint_completed": "v10.5",
        "done_count": 1111,
        "last_updated": "2026-06-19",
        "columns": {
            "in_progress": [{"id": "MP-1390"}],
            "backlog": [],
            "done": [{"id": f"MP-{i}"} for i in range(10)],
        },
    }
    (Path(d) / "KANBAN.json").write_text(json.dumps(kanban, indent=2))

    # data/golive_status.json
    (Path(d) / "data").mkdir()
    (Path(d) / "data" / "golive_status.json").write_text(json.dumps({
        "ready": False,
        "passed": 16,
        "total": 26,
        "consecutive_ready_days": 0,
    }))

    return d


class FakeRepoBase(unittest.TestCase):
    """Base class that sets up and tears down a fake repo."""

    def setUp(self):
        self.repo = _make_fake_repo()

    def tearDown(self):
        shutil.rmtree(self.repo, ignore_errors=True)


# ═══════════════════════════════════════════════════════════════════════════════
# 1–5: generate_report() top-level
# ═══════════════════════════════════════════════════════════════════════════════

class TestGenerateReport(FakeRepoBase):

    def test_01_returns_dict(self):
        """generate_report() возвращает dict"""
        report = generate_report(self.repo)
        self.assertIsInstance(report, dict)

    def test_02_contains_summary(self):
        """report содержит ключ summary"""
        report = generate_report(self.repo)
        self.assertIn("summary", report)

    def test_03_contains_critical_issues(self):
        """report содержит ключ critical_issues"""
        report = generate_report(self.repo)
        self.assertIn("critical_issues", report)

    def test_04_contains_test_coverage(self):
        """report содержит ключ test_coverage"""
        report = generate_report(self.repo)
        self.assertIn("test_coverage", report)

    def test_05_summary_total_modules_positive(self):
        """report['summary']['total_modules'] > 0"""
        report = generate_report(self.repo)
        self.assertGreater(report["summary"]["total_modules"], 0)


# ═══════════════════════════════════════════════════════════════════════════════
# 6–10: summary section
# ═══════════════════════════════════════════════════════════════════════════════

class TestSummarySection(FakeRepoBase):

    def test_06_summary_has_required_keys(self):
        """summary содержит все обязательные ключи"""
        report = generate_report(self.repo)
        s = report["summary"]
        for key in ("total_modules", "total_lines", "test_files",
                    "covered_modules", "coverage_pct", "violations_count"):
            self.assertIn(key, s, f"Missing key in summary: {key}")

    def test_07_summary_total_lines_positive(self):
        """summary['total_lines'] > 0"""
        report = generate_report(self.repo)
        self.assertGreater(report["summary"]["total_lines"], 0)

    def test_08_summary_coverage_pct_range(self):
        """coverage_pct в диапазоне [0, 100]"""
        report = generate_report(self.repo)
        pct = report["summary"]["coverage_pct"]
        self.assertGreaterEqual(pct, 0)
        self.assertLessEqual(pct, 100)

    def test_09_summary_test_files_non_negative(self):
        """test_files >= 0"""
        report = generate_report(self.repo)
        self.assertGreaterEqual(report["summary"]["test_files"], 0)

    def test_10_summary_violations_count_non_negative(self):
        """violations_count >= 0"""
        report = generate_report(self.repo)
        self.assertGreaterEqual(report["summary"]["violations_count"], 0)


# ═══════════════════════════════════════════════════════════════════════════════
# 11–15: critical_issues section
# ═══════════════════════════════════════════════════════════════════════════════

class TestCriticalIssues(FakeRepoBase):

    def test_11_critical_contains_checks_list(self):
        """critical_issues['checks'] — список"""
        report = generate_report(self.repo)
        self.assertIsInstance(report["critical_issues"]["checks"], list)

    def test_12_critical_three_checks(self):
        """critical_issues содержит ровно 3 проверки (CRIT-001/002/003)"""
        report = generate_report(self.repo)
        self.assertEqual(len(report["critical_issues"]["checks"]), 3)

    def test_13_each_check_has_id_and_status(self):
        """Каждая проверка содержит id и status"""
        report = generate_report(self.repo)
        for check in report["critical_issues"]["checks"]:
            self.assertIn("id", check)
            self.assertIn("status", check)
            self.assertIn(check["status"], ("PASS", "WARN", "FAIL"))

    def test_14_crit003_detects_local_atomic(self):
        """CRIT-003 обнаруживает локальный _atomic_write в aave.py"""
        report = generate_report(self.repo)
        checks = {c["id"]: c for c in report["critical_issues"]["checks"]}
        crit3 = checks.get("CRIT-003", {})
        # Our fake repo has aave.py with _atomic_write
        self.assertGreater(crit3.get("needs_migration", 0), 0)

    def test_15_critical_overall_present(self):
        """critical_issues['overall'] присутствует"""
        report = generate_report(self.repo)
        self.assertIn("overall", report["critical_issues"])


# ═══════════════════════════════════════════════════════════════════════════════
# 16–18: test_coverage section
# ═══════════════════════════════════════════════════════════════════════════════

class TestCoverageSection(FakeRepoBase):

    def test_16_coverage_has_required_keys(self):
        """test_coverage содержит нужные ключи"""
        report = generate_report(self.repo)
        tc = report["test_coverage"]
        for key in ("total_modules", "covered", "missing_tests", "coverage_pct"):
            self.assertIn(key, tc)

    def test_17_missing_tests_is_list_or_int(self):
        """missing_tests count >= 0"""
        report = generate_report(self.repo)
        self.assertGreaterEqual(report["test_coverage"]["missing_tests"], 0)

    def test_18_coverage_pct_float(self):
        """coverage_pct — число"""
        report = generate_report(self.repo)
        pct = report["test_coverage"]["coverage_pct"]
        self.assertIsInstance(pct, (int, float))


# ═══════════════════════════════════════════════════════════════════════════════
# 19–21: render_markdown()
# ═══════════════════════════════════════════════════════════════════════════════

class TestRenderMarkdown(FakeRepoBase):

    def test_19_render_markdown_returns_string(self):
        """render_markdown() возвращает строку"""
        report = generate_report(self.repo)
        md = render_markdown(report)
        self.assertIsInstance(md, str)

    def test_20_render_markdown_longer_than_200_chars(self):
        """render_markdown() длиннее 200 символов"""
        report = generate_report(self.repo)
        md = render_markdown(report)
        self.assertGreater(len(md), 200)

    def test_21_render_markdown_contains_summary_header(self):
        """render_markdown() содержит заголовок Summary"""
        report = generate_report(self.repo)
        md = render_markdown(report)
        self.assertIn("Summary", md)


# ═══════════════════════════════════════════════════════════════════════════════
# 22–23: save_report()
# ═══════════════════════════════════════════════════════════════════════════════

class TestSaveReport(FakeRepoBase):

    def test_22_save_report_creates_two_files(self):
        """save_report() создаёт два файла (.json и .md)"""
        report = generate_report(self.repo)
        json_path, md_path = save_report(report, "2026-06-19")
        self.assertTrue(os.path.exists(json_path), f"JSON file not found: {json_path}")
        self.assertTrue(os.path.exists(md_path), f"MD file not found: {md_path}")

    def test_23_save_report_json_valid(self):
        """save_report() JSON файл содержит валидный JSON"""
        report = generate_report(self.repo)
        json_path, _ = save_report(report, "2026-06-19")
        with open(json_path, "r", encoding="utf-8") as fh:
            loaded = json.load(fh)
        self.assertIsInstance(loaded, dict)
        self.assertIn("summary", loaded)


# ═══════════════════════════════════════════════════════════════════════════════
# 24–25: recommendations + kanban
# ═══════════════════════════════════════════════════════════════════════════════

class TestRecommendationsAndKanban(FakeRepoBase):

    def test_24_recommendations_is_list(self):
        """report['recommendations'] — список"""
        report = generate_report(self.repo)
        self.assertIsInstance(report["recommendations"], list)

    def test_25_kanban_status_sprint_present(self):
        """kanban_status содержит sprint_current из KANBAN.json"""
        report = generate_report(self.repo)
        kb = report["kanban_status"]
        self.assertIn("sprint_current", kb)
        self.assertEqual(kb["sprint_current"], "v10.6")


if __name__ == "__main__":
    unittest.main(verbosity=2)
