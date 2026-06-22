"""
Tests for spa_core.dev_agents — Architect and Tester agents.

These tests are fully offline (no LLM calls, no subprocess, no Telegram).
They cover:
  - SpaTester._parse_output with passing pytest output
  - SpaTester._parse_output with failing pytest output (failed_tests captured)
  - SpaArchitect._load_kanban with KANBAN.json on disk (if present)
  - SpaArchitect.promote_idea — idea moves from 'ideas' to 'backlog'
"""

import json
import os
import tempfile
from datetime import datetime
from unittest.mock import patch, MagicMock

import pytest

# The Architect tests below patch ``anthropic.Anthropic`` via ``unittest.mock.patch``,
# which requires the ``anthropic`` package to be importable.  In sandboxed CI envs
# the optional dep is not installed — skip only the Architect tests cleanly in
# that case (Tester tests have no such dependency and continue to run).
# Sprint v3.21 (bookkeeping): replaces the previous hard ImportError failure.
try:  # pragma: no cover - import-side detection only
    import anthropic as _anthropic  # noqa: F401
    _HAS_ANTHROPIC = True
except Exception:  # ModuleNotFoundError or any partial-install failure
    _HAS_ANTHROPIC = False

requires_anthropic = pytest.mark.skipif(
    not _HAS_ANTHROPIC,
    reason="dev_agents.Architect tests require the optional 'anthropic' SDK",
)


# ── helpers ───────────────────────────────────────────────────────────────────

def make_tester():
    """Return a SpaTester instance with results_file in a temp dir."""
    from dev_agents.tester import SpaTester

    t = SpaTester()
    t.results_file = os.path.join(tempfile.mkdtemp(), "test_results.json")
    return t


# ── Tester: passing output ────────────────────────────────────────────────────

def test_tester_parses_passing_output():
    """Feed mock pytest stdout with 5 passed — verify summary fields."""
    tester = make_tester()

    mock_output = (
        "tests/test_foo.py::test_a PASSED\n"
        "tests/test_foo.py::test_b PASSED\n"
        "tests/test_foo.py::test_c PASSED\n"
        "tests/test_bar.py::test_d PASSED\n"
        "tests/test_bar.py::test_e PASSED\n"
        "========================= 5 passed in 0.42s ========================="
    )

    summary = tester._parse_output(mock_output, returncode=0, duration=0.42)

    assert summary["status"] == "PASS"
    assert summary["passed"] == 5
    assert summary["failed"] == 0
    assert summary["errors"] == 0
    assert summary["skipped"] == 0
    assert summary["total"] == 5
    assert summary["failed_tests"] == []
    assert summary["duration_seconds"] == 0.4  # round(0.42, 1)
    # timestamp should be a valid ISO string
    datetime.fromisoformat(summary["timestamp"])


# ── Tester: failing output ────────────────────────────────────────────────────

def test_tester_parses_failing_output():
    """Feed mock pytest stdout with 3 passed + 2 failed — verify failed_tests captured."""
    tester = make_tester()

    mock_output = (
        "tests/test_foo.py::test_a PASSED\n"
        "tests/test_foo.py::test_b PASSED\n"
        "tests/test_foo.py::test_c PASSED\n"
        "tests/test_bar.py::test_d FAILED\n"
        "tests/test_bar.py::test_e FAILED\n"
        "FAILED tests/test_bar.py::test_d - AssertionError: expected 1 got 2\n"
        "FAILED tests/test_bar.py::test_e - KeyError: 'missing'\n"
        "=================== 3 passed, 2 failed in 1.23s ===================="
    )

    summary = tester._parse_output(mock_output, returncode=1, duration=1.23)

    assert summary["status"] == "FAIL"
    assert summary["passed"] == 3
    assert summary["failed"] == 2
    assert summary["errors"] == 0
    assert summary["total"] == 5
    assert len(summary["failed_tests"]) == 2
    assert "tests/test_bar.py::test_d" in summary["failed_tests"]
    assert "tests/test_bar.py::test_e" in summary["failed_tests"]
    assert summary["duration_seconds"] == 1.2


# ── Architect: loads KANBAN ───────────────────────────────────────────────────

@requires_anthropic
def test_architect_loads_kanban(tmp_path, monkeypatch):
    """
    Write a minimal KANBAN.json to disk, point Architect at it,
    and verify it loads without error and has the expected columns.
    """
    kanban_data = {
        "columns": {
            "backlog": [{"id": "B1", "title": "Write docs"}],
            "in_progress": [],
            "done": [{"id": "D1", "title": "Setup repo"}],
            "ideas": [{"id": "I1", "title": "Add Pendle support"}],
            "features": [],
            "review": [],
        }
    }

    kanban_path = tmp_path / "KANBAN.json"
    kanban_path.write_text(json.dumps(kanban_data))

    # Patch the module-level constant so Architect reads our temp file
    monkeypatch.chdir(tmp_path)

    # Patch anthropic.Anthropic so no real API client is created
    with patch("anthropic.Anthropic") as mock_anthropic:
        mock_anthropic.return_value = MagicMock()
        from dev_agents.architect import SpaArchitect

        arch = SpaArchitect()

    assert "backlog" in arch.kanban["columns"]
    assert arch.kanban["columns"]["backlog"][0]["id"] == "B1"
    assert arch.kanban["columns"]["done"][0]["id"] == "D1"
    assert len(arch.kanban["columns"]["ideas"]) == 1


# ── Architect: promote idea ───────────────────────────────────────────────────

@requires_anthropic
def test_architect_promote_idea(tmp_path, monkeypatch):
    """
    Seed KANBAN with a test idea, call promote_idea(), verify the idea
    has moved from 'ideas' to 'backlog' and KANBAN.json is updated on disk.
    """
    idea_card = {
        "id": "IDEA-99",
        "title": "Add Morpho Blue integration",
        "description": "Fetch Morpho Blue vaults from DeFiLlama",
    }

    kanban_data = {
        "columns": {
            "backlog": [],
            "in_progress": [],
            "done": [],
            "ideas": [idea_card],
            "features": [],
            "review": [],
        }
    }

    kanban_path = tmp_path / "KANBAN.json"
    kanban_path.write_text(json.dumps(kanban_data))

    monkeypatch.chdir(tmp_path)

    with patch("anthropic.Anthropic") as mock_anthropic:
        mock_anthropic.return_value = MagicMock()
        from dev_agents.architect import SpaArchitect

        arch = SpaArchitect()

    # Idea should start in 'ideas'
    assert any(i["id"] == "IDEA-99" for i in arch.kanban["columns"]["ideas"])

    arch.promote_idea("IDEA-99", "backlog")

    # After promotion: idea gone from 'ideas', present in 'backlog'
    assert not any(i["id"] == "IDEA-99" for i in arch.kanban["columns"]["ideas"])
    assert any(i["id"] == "IDEA-99" for i in arch.kanban["columns"]["backlog"])

    # KANBAN.json on disk should reflect the change
    persisted = json.loads(kanban_path.read_text())
    assert not any(i["id"] == "IDEA-99" for i in persisted["columns"]["ideas"])
    assert any(i["id"] == "IDEA-99" for i in persisted["columns"]["backlog"])
    assert persisted["updated_by"] == "Architect"
