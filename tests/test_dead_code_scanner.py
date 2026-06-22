"""
tests/test_dead_code_scanner.py

30 tests for MP-1404: dead_code_scanner.py
"""
import json
import os
import sys
import textwrap

import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from scripts.dead_code_scanner import (
    DeadCodeItem,
    DeadCodeScanner,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _write(directory: str, relpath: str, content: str) -> str:
    """Write content to directory/relpath, create parents. Returns abs path."""
    path = os.path.join(directory, relpath)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.write(textwrap.dedent(content))
    return path


# ---------------------------------------------------------------------------
# DeadCodeItem
# ---------------------------------------------------------------------------

def test_dead_code_item_creates():
    item = DeadCodeItem(
        category="unused_import",
        filepath="/fake/foo.py",
        line=3,
        description="Import 'os' is defined but not used",
        severity="LOW",
    )
    assert item.category == "unused_import"
    assert item.severity == "LOW"


def test_dead_code_item_severity_values():
    for sev in ("LOW", "MEDIUM", "HIGH"):
        item = DeadCodeItem("no_tests", "/fake/foo.py", 0, "desc", sev)
        assert item.severity in ("LOW", "MEDIUM", "HIGH")


def test_dead_code_item_to_dict():
    item = DeadCodeItem("stub_module", "/fake/bar.py", 0, "only 5 code lines", "LOW")
    d = item.to_dict()
    assert isinstance(d, dict)
    assert d["category"] == "stub_module"
    assert d["severity"] == "LOW"


# ---------------------------------------------------------------------------
# DeadCodeScanner construction
# ---------------------------------------------------------------------------

def test_dead_code_scanner_creates():
    scanner = DeadCodeScanner()
    assert scanner.base_dir == "."


def test_dead_code_scanner_custom_dir():
    with tempfile.TemporaryDirectory() as tmp:
        scanner = DeadCodeScanner(base_dir=tmp)
        assert scanner.base_dir == tmp


# ---------------------------------------------------------------------------
# scan_unused_imports
# ---------------------------------------------------------------------------

def test_scan_unused_imports_unused_os():
    with tempfile.TemporaryDirectory() as tmp:
        path = _write(tmp, "foo.py", "import os\nx = 1\n")
        scanner = DeadCodeScanner(base_dir=tmp)
        items = scanner.scan_unused_imports(path)
        assert any(i.category == "unused_import" and "os" in i.description for i in items)


def test_scan_unused_imports_used_os():
    with tempfile.TemporaryDirectory() as tmp:
        path = _write(tmp, "foo.py", "import os\nx = os.getcwd()\n")
        scanner = DeadCodeScanner(base_dir=tmp)
        items = scanner.scan_unused_imports(path)
        assert not any("os" in i.description for i in items)


def test_scan_unused_imports_from_import_unused():
    with tempfile.TemporaryDirectory() as tmp:
        path = _write(tmp, "foo.py", "from os.path import join\nx = 1\n")
        scanner = DeadCodeScanner(base_dir=tmp)
        items = scanner.scan_unused_imports(path)
        assert any("join" in i.description for i in items)


def test_scan_unused_imports_from_import_used():
    with tempfile.TemporaryDirectory() as tmp:
        path = _write(tmp, "foo.py", "from os.path import join\nx = join('a', 'b')\n")
        scanner = DeadCodeScanner(base_dir=tmp)
        items = scanner.scan_unused_imports(path)
        assert not any("join" in i.description for i in items)


def test_scan_unused_imports_empty_file():
    with tempfile.TemporaryDirectory() as tmp:
        path = _write(tmp, "foo.py", "")
        scanner = DeadCodeScanner(base_dir=tmp)
        items = scanner.scan_unused_imports(path)
        assert items == []


def test_scan_unused_imports_no_imports():
    with tempfile.TemporaryDirectory() as tmp:
        path = _write(tmp, "foo.py", "x = 1\ny = 2\n")
        scanner = DeadCodeScanner(base_dir=tmp)
        items = scanner.scan_unused_imports(path)
        assert items == []


def test_scan_unused_imports_syntax_error_returns_empty():
    with tempfile.TemporaryDirectory() as tmp:
        path = _write(tmp, "foo.py", "class Foo(\n    # broken\n")
        scanner = DeadCodeScanner(base_dir=tmp)
        items = scanner.scan_unused_imports(path)
        assert items == []


def test_scan_unused_imports_alias():
    with tempfile.TemporaryDirectory() as tmp:
        path = _write(tmp, "foo.py", "import os as operating_system\nx = 1\n")
        scanner = DeadCodeScanner(base_dir=tmp)
        items = scanner.scan_unused_imports(path)
        # alias 'operating_system' is not used
        assert any("operating_system" in i.description for i in items)


# ---------------------------------------------------------------------------
# scan_untested_modules
# ---------------------------------------------------------------------------

def test_scan_untested_modules_finds_untested():
    with tempfile.TemporaryDirectory() as tmp:
        _write(tmp, "spa_core/analytics/my_tracker.py", "class MyTracker: pass\n")
        # No test file
        scanner = DeadCodeScanner(base_dir=tmp)
        items = scanner.scan_untested_modules()
        assert any("my_tracker" in i.description for i in items)


def test_scan_untested_modules_covered_module_not_flagged():
    with tempfile.TemporaryDirectory() as tmp:
        _write(tmp, "spa_core/analytics/my_tracker.py", "class MyTracker: pass\n")
        _write(tmp, "tests/test_my_tracker.py", "def test_x(): pass\n")
        scanner = DeadCodeScanner(base_dir=tmp)
        items = scanner.scan_untested_modules()
        assert not any("my_tracker" in i.description for i in items)


def test_scan_untested_modules_category():
    with tempfile.TemporaryDirectory() as tmp:
        _write(tmp, "spa_core/foo.py", "x = 1\n")
        scanner = DeadCodeScanner(base_dir=tmp)
        items = scanner.scan_untested_modules()
        for i in items:
            assert i.category == "no_tests"


def test_scan_untested_modules_empty_dir():
    with tempfile.TemporaryDirectory() as tmp:
        scanner = DeadCodeScanner(base_dir=tmp)
        items = scanner.scan_untested_modules()
        assert items == []


def test_scan_untested_modules_skips_init():
    with tempfile.TemporaryDirectory() as tmp:
        _write(tmp, "spa_core/__init__.py", "")
        scanner = DeadCodeScanner(base_dir=tmp)
        items = scanner.scan_untested_modules()
        assert items == []


def test_scan_untested_modules_severity_medium():
    with tempfile.TemporaryDirectory() as tmp:
        _write(tmp, "spa_core/bar.py", "x = 1\n")
        scanner = DeadCodeScanner(base_dir=tmp)
        items = scanner.scan_untested_modules()
        assert all(i.severity == "MEDIUM" for i in items)


# ---------------------------------------------------------------------------
# scan_todo_comments
# ---------------------------------------------------------------------------

def test_scan_todo_comments_finds_todo():
    with tempfile.TemporaryDirectory() as tmp:
        _write(tmp, "spa_core/foo.py", "x = 1  # TODO: fix this\n")
        scanner = DeadCodeScanner(base_dir=tmp)
        items = scanner.scan_todo_comments()
        assert any(i.category == "todo_stale" for i in items)


def test_scan_todo_comments_finds_fixme():
    with tempfile.TemporaryDirectory() as tmp:
        _write(tmp, "spa_core/foo.py", "# FIXME: broken\nx = 1\n")
        scanner = DeadCodeScanner(base_dir=tmp)
        items = scanner.scan_todo_comments()
        assert any("FIXME" in i.description for i in items)


def test_scan_todo_comments_finds_hack():
    with tempfile.TemporaryDirectory() as tmp:
        _write(tmp, "spa_core/foo.py", "# HACK: workaround\n")
        scanner = DeadCodeScanner(base_dir=tmp)
        items = scanner.scan_todo_comments()
        assert any("HACK" in i.description for i in items)


def test_scan_todo_comments_no_comments():
    with tempfile.TemporaryDirectory() as tmp:
        _write(tmp, "spa_core/foo.py", "x = 1\ny = 2\n")
        scanner = DeadCodeScanner(base_dir=tmp)
        items = scanner.scan_todo_comments()
        assert items == []


def test_scan_todo_comments_line_number():
    with tempfile.TemporaryDirectory() as tmp:
        _write(tmp, "spa_core/foo.py", "x = 1\n# TODO: fix\ny = 2\n")
        scanner = DeadCodeScanner(base_dir=tmp)
        items = scanner.scan_todo_comments()
        assert items[0].line == 2


# ---------------------------------------------------------------------------
# scan_all
# ---------------------------------------------------------------------------

def test_scan_all_returns_list():
    with tempfile.TemporaryDirectory() as tmp:
        scanner = DeadCodeScanner(base_dir=tmp)
        items = scanner.scan_all()
        assert isinstance(items, list)


def test_scan_all_collects_multiple_categories():
    with tempfile.TemporaryDirectory() as tmp:
        # untested module
        _write(tmp, "spa_core/my_mod.py", "import os\n# TODO: fix\nx = 1\n")
        scanner = DeadCodeScanner(base_dir=tmp)
        items = scanner.scan_all()
        cats = {i.category for i in items}
        # At least no_tests and todo_stale should be found
        assert "no_tests" in cats
        assert "todo_stale" in cats


# ---------------------------------------------------------------------------
# to_markdown
# ---------------------------------------------------------------------------

def test_to_markdown_returns_string():
    scanner = DeadCodeScanner()
    items = [
        DeadCodeItem("no_tests", "/fake/foo.py", 0, "no test for foo", "MEDIUM"),
    ]
    md = scanner.to_markdown(items)
    assert isinstance(md, str)
    assert len(md) > 0


def test_to_markdown_contains_category_header():
    scanner = DeadCodeScanner()
    items = [
        DeadCodeItem("no_tests", "/fake/foo.py", 0, "no test for foo", "MEDIUM"),
        DeadCodeItem("todo_stale", "/fake/bar.py", 5, "TODO: fix", "LOW"),
    ]
    md = scanner.to_markdown(items)
    assert "Untested" in md
    assert "TODO" in md


def test_to_markdown_total_count():
    scanner = DeadCodeScanner()
    items = [
        DeadCodeItem("unused_import", "/fake/a.py", 1, "Import 'os' unused", "LOW"),
        DeadCodeItem("unused_import", "/fake/b.py", 2, "Import 'sys' unused", "LOW"),
    ]
    md = scanner.to_markdown(items)
    assert "2" in md


# ---------------------------------------------------------------------------
# save_report
# ---------------------------------------------------------------------------

def test_save_report_creates_json_file():
    with tempfile.TemporaryDirectory() as tmp:
        os.makedirs(os.path.join(tmp, "data"), exist_ok=True)
        scanner = DeadCodeScanner(base_dir=tmp)
        items = [DeadCodeItem("no_tests", "/fake/foo.py", 0, "desc", "MEDIUM")]
        path = scanner.save_report(items)
        assert os.path.isfile(path)
        with open(path) as f:
            data = json.load(f)
        assert data["total"] == 1
        assert "items" in data


def test_save_report_json_structure():
    with tempfile.TemporaryDirectory() as tmp:
        os.makedirs(os.path.join(tmp, "data"), exist_ok=True)
        scanner = DeadCodeScanner(base_dir=tmp)
        items = [
            DeadCodeItem("stub_module", "/fake/bar.py", 0, "only 3 lines", "LOW"),
        ]
        path = scanner.save_report(items)
        with open(path) as f:
            data = json.load(f)
        assert "generated_at" in data
        assert "by_category" in data
        assert data["by_category"].get("stub_module") == 1
