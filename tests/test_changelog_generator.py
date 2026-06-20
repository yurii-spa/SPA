"""
tests/test_changelog_generator.py
MP-1518 (v11.34): 15 tests for scripts/generate_changelog.py.
"""

import importlib.util
import os
import sys
import tempfile
import unittest
from unittest.mock import MagicMock, patch

# ---------------------------------------------------------------------------
# Load generate_changelog module without executing main()
# ---------------------------------------------------------------------------
SCRIPT_PATH = os.path.join(
    os.path.dirname(__file__), "..", "scripts", "generate_changelog.py"
)

spec = importlib.util.spec_from_file_location("generate_changelog", SCRIPT_PATH)
gc = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gc)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_commits(n=5):
    return [
        {
            "hash": f"abc{i:05d}",
            "date": f"2026-06-{10 + i:02d}",
            "subject": f"Sprint v11.{i} — MP-{1500 + i} some task",
        }
        for i in range(n)
    ]


# ---------------------------------------------------------------------------
# Tests: module-level helpers
# ---------------------------------------------------------------------------

class TestExtractSprint(unittest.TestCase):
    def test_extracts_sprint_version(self):
        result = gc._extract_sprint("Sprint v11.31 — MP-1515 ADR docs")
        self.assertEqual(result, "v11.31")

    def test_returns_none_for_no_sprint(self):
        result = gc._extract_sprint("Fix typo in RUNBOOK.md")
        self.assertIsNone(result)

    def test_case_insensitive(self):
        result = gc._extract_sprint("sprint v9.94 bugfix")
        self.assertIsNotNone(result)


class TestExtractMP(unittest.TestCase):
    def test_extracts_mp_number(self):
        result = gc._extract_mp("Sprint v11.31 — MP-1515 ADR docs")
        self.assertEqual(result, "MP-1515")

    def test_returns_none_for_no_mp(self):
        result = gc._extract_mp("Fix typo in README")
        self.assertIsNone(result)


class TestGroupByDate(unittest.TestCase):
    def test_groups_correctly(self):
        commits = [
            {"hash": "a", "date": "2026-06-10", "subject": "first"},
            {"hash": "b", "date": "2026-06-10", "subject": "second"},
            {"hash": "c", "date": "2026-06-11", "subject": "third"},
        ]
        grouped = gc._group_by_date(commits)
        self.assertIn("2026-06-10", grouped)
        self.assertEqual(len(grouped["2026-06-10"]), 2)
        self.assertIn("2026-06-11", grouped)
        self.assertEqual(len(grouped["2026-06-11"]), 1)

    def test_empty_commits(self):
        grouped = gc._group_by_date([])
        self.assertEqual(grouped, {})


class TestFormatCommit(unittest.TestCase):
    def test_includes_hash(self):
        commit = {"hash": "abc12345", "date": "2026-06-20", "subject": "Fix bug"}
        result = gc._format_commit(commit)
        self.assertIn("abc12345", result)

    def test_includes_subject(self):
        commit = {"hash": "abc12345", "date": "2026-06-20", "subject": "Fix bug"}
        result = gc._format_commit(commit)
        self.assertIn("Fix bug", result)

    def test_includes_sprint_tag_when_present(self):
        commit = {
            "hash": "abc12345",
            "date": "2026-06-20",
            "subject": "Sprint v11.31 — MP-1515 ADR docs",
        }
        result = gc._format_commit(commit)
        self.assertIn("v11.31", result)


class TestRenderChangelog(unittest.TestCase):
    def test_renders_header(self):
        commits = _make_commits(3)
        rendered = gc._render_changelog(commits)
        self.assertIn("# SPA Engineering Changelog", rendered)

    def test_renders_dates(self):
        commits = _make_commits(3)
        rendered = gc._render_changelog(commits)
        self.assertIn("2026-06-10", rendered)

    def test_renders_commit_hashes(self):
        commits = _make_commits(2)
        rendered = gc._render_changelog(commits)
        self.assertIn("abc00000", rendered)

    def test_includes_title_when_given(self):
        commits = _make_commits(1)
        rendered = gc._render_changelog(commits, title="Test Title")
        self.assertIn("Test Title", rendered)

    def test_renders_generated_timestamp(self):
        commits = _make_commits(1)
        rendered = gc._render_changelog(commits)
        self.assertIn("Generated:", rendered)


class TestChangelogDocumentExists(unittest.TestCase):
    """The curated CHANGELOG_ENGINEERING.md must exist."""

    CHANGELOG_PATH = os.path.join(
        os.path.dirname(__file__), "..", "docs", "CHANGELOG_ENGINEERING.md"
    )

    def test_file_exists(self):
        self.assertTrue(os.path.isfile(self.CHANGELOG_PATH),
                        "docs/CHANGELOG_ENGINEERING.md must exist")

    def test_file_not_empty(self):
        self.assertGreater(os.path.getsize(self.CHANGELOG_PATH), 200)

    def test_mentions_v11_34(self):
        with open(self.CHANGELOG_PATH, encoding="utf-8") as f:
            content = f.read()
        self.assertIn("v11.34", content)


if __name__ == "__main__":
    unittest.main()
