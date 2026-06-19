"""
tests/test_analytics_conformance.py

30 tests for MP-1403: analytics_conformance.py
"""
import ast
import json
import os
import sys
import tempfile
import textwrap
import pytest

# Ensure repo root is in path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from scripts.analytics_conformance import (
    find_analytics_classes,
    check_base_analytics_conformance,
    scan_analytics_dir,
    conformance_report,
    fix_list_commands,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _write_tmp(content: str, suffix=".py") -> str:
    """Write content to a temp file, return path."""
    fd, path = tempfile.mkstemp(suffix=suffix)
    with os.fdopen(fd, "w") as f:
        f.write(textwrap.dedent(content))
    return path


# ---------------------------------------------------------------------------
# find_analytics_classes
# ---------------------------------------------------------------------------

def test_find_analytics_classes_empty_file():
    path = _write_tmp("")
    try:
        result = find_analytics_classes(path)
        assert result == []
    finally:
        os.unlink(path)


def test_find_analytics_classes_no_class():
    path = _write_tmp("x = 1\ndef foo(): pass\n")
    try:
        result = find_analytics_classes(path)
        assert result == []
    finally:
        os.unlink(path)


def test_find_analytics_classes_inherits_base_analytics():
    path = _write_tmp("""
        class MyAnalytics(BaseAnalytics):
            def to_dict(self): return {}
    """)
    try:
        result = find_analytics_classes(path)
        assert len(result) == 1
        assert result[0]["class_name"] == "MyAnalytics"
        assert "BaseAnalytics" in result[0]["bases"]
        assert result[0]["inherits_base"] is True
    finally:
        os.unlink(path)


def test_find_analytics_classes_inherits_base_report():
    path = _write_tmp("""
        class MyReport(BaseReport):
            def to_dict(self): return {}
            def to_markdown(self): return ""
    """)
    try:
        result = find_analytics_classes(path)
        assert result[0]["inherits_base"] is True
        assert "BaseReport" in result[0]["bases"]
    finally:
        os.unlink(path)


def test_find_analytics_classes_non_conforming():
    path = _write_tmp("""
        class FooTracker:
            def run(self): pass
    """)
    try:
        result = find_analytics_classes(path)
        assert len(result) == 1
        assert result[0]["inherits_base"] is False
        assert result[0]["class_name"] == "FooTracker"
    finally:
        os.unlink(path)


def test_find_analytics_classes_multiple_classes():
    path = _write_tmp("""
        class A(BaseAnalytics):
            def to_dict(self): return {}
        class B:
            pass
        class C(BaseReport):
            def to_dict(self): return {}
            def to_markdown(self): return ""
    """)
    try:
        result = find_analytics_classes(path)
        assert len(result) == 3
        names = {r["class_name"] for r in result}
        assert names == {"A", "B", "C"}
        conforming = [r for r in result if r["inherits_base"]]
        assert len(conforming) == 2
    finally:
        os.unlink(path)


def test_find_analytics_classes_detects_has_save():
    path = _write_tmp("""
        class Foo(BaseAnalytics):
            def save(self, data=None): pass
            def to_dict(self): return {}
    """)
    try:
        result = find_analytics_classes(path)
        assert result[0]["has_save"] is True
    finally:
        os.unlink(path)


def test_find_analytics_classes_detects_has_load():
    path = _write_tmp("""
        class Foo(BaseAnalytics):
            def load(self): return {}
            def to_dict(self): return {}
    """)
    try:
        result = find_analytics_classes(path)
        assert result[0]["has_load"] is True
    finally:
        os.unlink(path)


def test_find_analytics_classes_detects_has_to_dict():
    path = _write_tmp("""
        class Foo(BaseAnalytics):
            def to_dict(self): return {}
    """)
    try:
        result = find_analytics_classes(path)
        assert result[0]["has_to_dict"] is True
    finally:
        os.unlink(path)


def test_find_analytics_classes_syntax_error_returns_empty():
    path = _write_tmp("class Foo(\n    # broken syntax")
    try:
        result = find_analytics_classes(path)
        assert result == []
    finally:
        os.unlink(path)


def test_find_analytics_classes_dotted_base():
    path = _write_tmp("""
        import spa_core.base
        class Foo(spa_core.base.BaseAnalytics):
            def to_dict(self): return {}
    """)
    try:
        result = find_analytics_classes(path)
        assert result[0]["inherits_base"] is True  # picks up BaseAnalytics attr
    finally:
        os.unlink(path)


def test_find_analytics_classes_returns_file_path():
    path = _write_tmp("""
        class Foo(BaseAnalytics):
            def to_dict(self): return {}
    """)
    try:
        result = find_analytics_classes(path)
        assert result[0]["file"] == path
    finally:
        os.unlink(path)


def test_find_analytics_classes_returns_line_number():
    path = _write_tmp("""
        class Foo(BaseAnalytics):
            def to_dict(self): return {}
    """)
    try:
        result = find_analytics_classes(path)
        assert result[0]["line"] >= 1
    finally:
        os.unlink(path)


# ---------------------------------------------------------------------------
# check_base_analytics_conformance
# ---------------------------------------------------------------------------

def test_conformance_check_conforming():
    path = _write_tmp("""
        class Good(BaseAnalytics):
            def to_dict(self): return {}
    """)
    try:
        result = check_base_analytics_conformance(path)
        assert result["any_conforming"] is True
        assert "Good" in result["conforming"]
        assert result["non_conforming"] == []
    finally:
        os.unlink(path)


def test_conformance_check_non_conforming():
    path = _write_tmp("""
        class Bad:
            def run(self): pass
    """)
    try:
        result = check_base_analytics_conformance(path)
        assert result["any_conforming"] is False
        assert "Bad" in result["non_conforming"]
        assert result["conforming"] == []
    finally:
        os.unlink(path)


def test_conformance_check_recommendation_fully_conforming():
    path = _write_tmp("""
        class A(BaseAnalytics):
            def to_dict(self): return {}
    """)
    try:
        result = check_base_analytics_conformance(path)
        assert result["recommendation"] == "fully_conforming"
    finally:
        os.unlink(path)


def test_conformance_check_recommendation_migrate():
    path = _write_tmp("""
        class A:
            pass
    """)
    try:
        result = check_base_analytics_conformance(path)
        assert result["recommendation"] == "migrate_to_base_analytics"
    finally:
        os.unlink(path)


def test_conformance_check_recommendation_partially_conforming():
    path = _write_tmp("""
        class Good(BaseAnalytics):
            def to_dict(self): return {}
        class Bad:
            pass
    """)
    try:
        result = check_base_analytics_conformance(path)
        assert result["recommendation"] == "partially_conforming"
        assert "Good" in result["conforming"]
        assert "Bad" in result["non_conforming"]
    finally:
        os.unlink(path)


def test_conformance_check_recommendation_no_classes():
    path = _write_tmp("x = 1\n")
    try:
        result = check_base_analytics_conformance(path)
        assert result["recommendation"] == "no_classes"
        assert result["any_conforming"] is False
    finally:
        os.unlink(path)


def test_conformance_check_filepath_in_result():
    path = _write_tmp("class A(BaseAnalytics): pass\n")
    try:
        result = check_base_analytics_conformance(path)
        assert result["filepath"] == path
    finally:
        os.unlink(path)


def test_conformance_check_classes_list_present():
    path = _write_tmp("""
        class A(BaseAnalytics):
            def to_dict(self): return {}
        class B:
            pass
    """)
    try:
        result = check_base_analytics_conformance(path)
        assert isinstance(result["classes"], list)
        assert len(result["classes"]) == 2
    finally:
        os.unlink(path)


# ---------------------------------------------------------------------------
# scan_analytics_dir
# ---------------------------------------------------------------------------

def test_scan_analytics_dir_empty_tmpdir():
    with tempfile.TemporaryDirectory() as tmp:
        result = scan_analytics_dir(tmp)
        # No spa_core/analytics/ → empty list
        assert result == []


def test_scan_analytics_dir_returns_list():
    with tempfile.TemporaryDirectory() as tmp:
        analytics = os.path.join(tmp, "spa_core", "analytics")
        os.makedirs(analytics)
        result = scan_analytics_dir(tmp)
        assert isinstance(result, list)


def test_scan_analytics_dir_finds_py_files():
    with tempfile.TemporaryDirectory() as tmp:
        analytics = os.path.join(tmp, "spa_core", "analytics")
        os.makedirs(analytics)
        with open(os.path.join(analytics, "foo_tracker.py"), "w") as f:
            f.write("class FooTracker: pass\n")
        result = scan_analytics_dir(tmp)
        assert len(result) == 1
        assert result[0]["filepath"].endswith("foo_tracker.py")


def test_scan_analytics_dir_skips_init():
    with tempfile.TemporaryDirectory() as tmp:
        analytics = os.path.join(tmp, "spa_core", "analytics")
        os.makedirs(analytics)
        with open(os.path.join(analytics, "__init__.py"), "w") as f:
            f.write("")
        result = scan_analytics_dir(tmp)
        assert result == []


def test_scan_analytics_dir_skips_module_registry():
    with tempfile.TemporaryDirectory() as tmp:
        analytics = os.path.join(tmp, "spa_core", "analytics")
        os.makedirs(analytics)
        with open(os.path.join(analytics, "_module_registry.py"), "w") as f:
            f.write("REGISTRY = {}\n")
        result = scan_analytics_dir(tmp)
        assert result == []


# ---------------------------------------------------------------------------
# conformance_report
# ---------------------------------------------------------------------------

def test_conformance_report_contains_word_conforming():
    results = [
        {
            "filepath": "/fake/foo.py",
            "any_conforming": True,
            "conforming": ["Foo"],
            "non_conforming": [],
            "recommendation": "fully_conforming",
            "classes": [],
        }
    ]
    report = conformance_report(results)
    assert "conforming" in report.lower()


def test_conformance_report_shows_counts():
    results = [
        {
            "filepath": "/fake/foo.py",
            "any_conforming": False,
            "conforming": [],
            "non_conforming": ["Foo"],
            "recommendation": "migrate_to_base_analytics",
            "classes": [],
        },
        {
            "filepath": "/fake/bar.py",
            "any_conforming": True,
            "conforming": ["Bar"],
            "non_conforming": [],
            "recommendation": "fully_conforming",
            "classes": [],
        },
    ]
    report = conformance_report(results)
    assert "2" in report  # total files
    assert isinstance(report, str)
    assert len(report) > 0


def test_conformance_report_empty_results():
    report = conformance_report([])
    assert "conforming" in report.lower()
    assert "0" in report


def test_fix_list_commands_contains_class_names():
    results = [
        {
            "filepath": "/fake/foo.py",
            "any_conforming": False,
            "conforming": [],
            "non_conforming": ["MyTracker"],
            "recommendation": "migrate_to_base_analytics",
            "classes": [],
        }
    ]
    out = fix_list_commands(results)
    assert "MyTracker" in out
    assert "BaseAnalytics" in out
