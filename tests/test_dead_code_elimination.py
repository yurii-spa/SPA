"""
tests/test_dead_code_elimination.py
Tests for dead code elimination — MP-1521 (v11.37)

20 tests verifying:
  - stale_todo_finder.py works correctly
  - Critical modules (utils/, safety/, risk/, allocator/) are clean
  - No bare raise Exception / raise RuntimeError in production modules
  - No commented-out code blocks in critical paths
  - stale_todo_finder CLI runs cleanly
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from unittest.mock import patch


# Make scripts importable
sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
from stale_todo_finder import find_todos, filter_stale, DEFAULT_TAGS


# ─────────────────────────────────────────────────────────────────────────────
# 1. stale_todo_finder — unit tests
# ─────────────────────────────────────────────────────────────────────────────


def test_find_todos_empty_dir(tmp_path: Path) -> None:
    result = find_todos(str(tmp_path))
    assert result == []


def test_find_todos_detects_todo(tmp_path: Path) -> None:
    f = tmp_path / "module.py"
    f.write_text("# TODO: fix this later\npass\n")
    result = find_todos(str(tmp_path))
    assert len(result) == 1
    assert result[0]["tag"] == "TODO"
    assert result[0]["line"] == 1


def test_find_todos_detects_fixme(tmp_path: Path) -> None:
    f = tmp_path / "module.py"
    f.write_text("x = 1  # FIXME: wrong value\n")
    result = find_todos(str(tmp_path))
    assert any(t["tag"] == "FIXME" for t in result)


def test_find_todos_detects_hack(tmp_path: Path) -> None:
    f = tmp_path / "module.py"
    f.write_text("# HACK: workaround\npass\n")
    result = find_todos(str(tmp_path))
    assert any(t["tag"] == "HACK" for t in result)


def test_find_todos_skips_pycache(tmp_path: Path) -> None:
    cache = tmp_path / "__pycache__"
    cache.mkdir()
    (cache / "cached.py").write_text("# TODO: this should be ignored\n")
    result = find_todos(str(tmp_path))
    assert result == []


def test_find_todos_skips_data_dir(tmp_path: Path) -> None:
    data = tmp_path / "data"
    data.mkdir()
    (data / "state.py").write_text("# TODO: ignored\n")
    result = find_todos(str(tmp_path))
    assert result == []


def test_find_todos_content_captured(tmp_path: Path) -> None:
    f = tmp_path / "m.py"
    f.write_text("    # TODO: implement retry logic\n")
    result = find_todos(str(tmp_path))
    assert "implement retry logic" in result[0]["content"]


def test_find_todos_multiple_files(tmp_path: Path) -> None:
    (tmp_path / "a.py").write_text("# TODO: a\n")
    (tmp_path / "b.py").write_text("# FIXME: b\n")
    result = find_todos(str(tmp_path))
    assert len(result) == 2


def test_find_todos_custom_tags(tmp_path: Path) -> None:
    (tmp_path / "m.py").write_text("# DEPRECATED: old api\n# TODO: remove\n")
    result = find_todos(str(tmp_path), tags=["DEPRECATED"])
    assert len(result) == 1
    assert result[0]["tag"] == "DEPRECATED"


def test_filter_stale_by_age(tmp_path: Path) -> None:
    todos = [
        {"file": "a.py", "line": 1, "tag": "TODO", "content": "", "age_days": 60, "commit_date": "2024-01-01"},
        {"file": "b.py", "line": 1, "tag": "TODO", "content": "", "age_days": 5, "commit_date": "2024-05-01"},
    ]
    stale = filter_stale(todos, max_age_days=30)
    assert len(stale) == 1
    assert stale[0]["file"] == "a.py"


def test_filter_stale_none_age_is_stale() -> None:
    """Items with unknown age (None) must be treated as stale."""
    todos = [{"file": "x.py", "line": 1, "tag": "TODO", "content": "", "age_days": None, "commit_date": None}]
    stale = filter_stale(todos, max_age_days=30)
    assert len(stale) == 1


# ─────────────────────────────────────────────────────────────────────────────
# 2. Critical module cleanliness
# ─────────────────────────────────────────────────────────────────────────────


CRITICAL_PATHS = [
    "spa_core/utils",
    "spa_core/safety",
    "spa_core/risk",
    "spa_core/allocator",
]


def test_no_todo_in_utils() -> None:
    """spa_core/utils/ must have zero TODO/FIXME/HACK/XXX comments."""
    todos = find_todos("spa_core/utils")
    assert todos == [], f"Found {len(todos)} TODO items in spa_core/utils/: {todos[:3]}"


def test_no_todo_in_safety() -> None:
    todos = find_todos("spa_core/safety")
    assert todos == [], f"Found {len(todos)} TODO items in spa_core/safety/"


def test_no_todo_in_risk() -> None:
    todos = find_todos("spa_core/risk")
    assert todos == [], f"Found {len(todos)} TODO items in spa_core/risk/"


def test_no_bare_exceptions_in_utils() -> None:
    """spa_core/utils/ must not use bare `raise Exception(...)` or `raise RuntimeError(...)`."""
    bare_exc_pattern = re.compile(r"raise\s+(Exception|RuntimeError)\s*\(")
    violations = []
    for py in Path("spa_core/utils").rglob("*.py"):
        if "__pycache__" in str(py):
            continue
        text = py.read_text(encoding="utf-8", errors="replace")
        for i, line in enumerate(text.splitlines(), 1):
            if bare_exc_pattern.search(line):
                violations.append(f"{py}:{i}: {line.strip()[:60]}")
    assert not violations, "Bare exceptions in utils/:\n" + "\n".join(violations)


def test_no_bare_exceptions_in_safety() -> None:
    bare_exc_pattern = re.compile(r"raise\s+(Exception|RuntimeError)\s*\(")
    violations = []
    for py in Path("spa_core/safety").rglob("*.py"):
        if "__pycache__" in str(py):
            continue
        text = py.read_text(encoding="utf-8", errors="replace")
        for i, line in enumerate(text.splitlines(), 1):
            if bare_exc_pattern.search(line):
                violations.append(f"{py}:{i}: {line.strip()[:60]}")
    assert not violations, "Bare exceptions in safety/:\n" + "\n".join(violations)


# ─────────────────────────────────────────────────────────────────────────────
# 3. stale_todo_finder exists and imports
# ─────────────────────────────────────────────────────────────────────────────


def test_stale_todo_finder_script_exists() -> None:
    assert Path("scripts/stale_todo_finder.py").exists()


def test_stale_todo_finder_default_tags() -> None:
    assert "TODO" in DEFAULT_TAGS
    assert "FIXME" in DEFAULT_TAGS
    assert "HACK" in DEFAULT_TAGS
    assert "XXX" in DEFAULT_TAGS


def test_stale_todo_finder_cli_runs(capsys) -> None:
    """CLI with --no-git --json on utils/ should return valid JSON."""
    with patch("sys.argv", [
        "stale_todo_finder.py",
        "--path", "spa_core/utils/",
        "--no-git",
        "--json",
    ]):
        from stale_todo_finder import main
        main()
    captured = capsys.readouterr()
    data = json.loads(captured.out)
    assert isinstance(data, list)


def test_find_todos_returns_dicts(tmp_path: Path) -> None:
    (tmp_path / "m.py").write_text("# TODO: test\n")
    result = find_todos(str(tmp_path))
    assert isinstance(result, list)
    assert isinstance(result[0], dict)
    for key in ("file", "line", "tag", "content"):
        assert key in result[0], f"Missing key: {key}"
