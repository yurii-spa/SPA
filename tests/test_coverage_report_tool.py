"""
tests/test_coverage_report_tool.py
Tests for scripts/test_coverage_report.py — MP-1519 (v11.35)

20 tests covering: coverage analysis, markdown formatting, CLI, edge cases.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

# Make scripts/ importable
sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
from test_coverage_report import (
    analyze_coverage,
    count_tests_in_file,
    format_markdown,
    main,
)


# ─────────────────────────────────────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────────────────────────────────────


@pytest.fixture()
def tmp_repo(tmp_path: Path) -> Path:
    """Create a minimal repo structure: spa_core/ + tests/."""
    spa = tmp_path / "spa_core"
    tests = tmp_path / "tests"
    spa.mkdir()
    tests.mkdir()
    return tmp_path


def _make_module(spa: Path, subpkg: str, name: str, content: str = "") -> Path:
    pkg = spa / subpkg
    pkg.mkdir(exist_ok=True)
    (pkg / "__init__.py").write_text("")
    f = pkg / f"{name}.py"
    f.write_text(content)
    return f


def _make_test(tests: Path, name: str, test_defs: int = 3) -> Path:
    body = "\n".join(f"def test_{name}_{i}():\n    pass" for i in range(test_defs))
    f = tests / f"test_{name}.py"
    f.write_text(body)
    return f


# ─────────────────────────────────────────────────────────────────────────────
# 1. count_tests_in_file — basic
# ─────────────────────────────────────────────────────────────────────────────


def test_count_tests_basic(tmp_path: Path) -> None:
    f = tmp_path / "test_foo.py"
    f.write_text("def test_a():\n    pass\ndef test_b():\n    pass\n")
    assert count_tests_in_file(f) == 2


def test_count_tests_zero(tmp_path: Path) -> None:
    f = tmp_path / "test_empty.py"
    f.write_text("import os\n\ndef helper():\n    pass\n")
    assert count_tests_in_file(f) == 0


def test_count_tests_missing_file(tmp_path: Path) -> None:
    f = tmp_path / "nonexistent.py"
    assert count_tests_in_file(f) == 0


def test_count_tests_ignores_comments(tmp_path: Path) -> None:
    f = tmp_path / "test_x.py"
    f.write_text("# def test_commented():\n    pass\ndef test_real():\n    pass\n")
    assert count_tests_in_file(f) == 1


# ─────────────────────────────────────────────────────────────────────────────
# 2. analyze_coverage — structure & values
# ─────────────────────────────────────────────────────────────────────────────


def test_analyze_coverage_all_keys(tmp_repo: Path) -> None:
    result = analyze_coverage(
        spa_dir=str(tmp_repo / "spa_core"),
        test_dir=str(tmp_repo / "tests"),
    )
    required = {
        "total_modules", "tested", "untested", "coverage_pct",
        "total_tests", "test_files_total", "top_untested",
        "all_untested_count", "tested_detail", "by_package",
    }
    assert required.issubset(result.keys()), f"Missing keys: {required - result.keys()}"


def test_analyze_coverage_empty_spa(tmp_repo: Path) -> None:
    result = analyze_coverage(
        spa_dir=str(tmp_repo / "spa_core"),
        test_dir=str(tmp_repo / "tests"),
    )
    assert result["total_modules"] == 0
    assert result["coverage_pct"] == 0.0
    assert result["tested"] == 0


def test_analyze_coverage_fully_tested(tmp_repo: Path) -> None:
    spa = tmp_repo / "spa_core"
    tests = tmp_repo / "tests"
    _make_module(spa, "utils", "atomic", "def save(): pass")
    _make_test(tests, "atomic", test_defs=5)
    result = analyze_coverage(str(spa), str(tests))
    assert result["total_modules"] == 1
    assert result["tested"] == 1
    assert result["untested"] == 0
    assert result["coverage_pct"] == 100.0
    assert result["total_tests"] == 5


def test_analyze_coverage_partial(tmp_repo: Path) -> None:
    spa = tmp_repo / "spa_core"
    tests = tmp_repo / "tests"
    _make_module(spa, "utils", "atomic")
    _make_module(spa, "utils", "errors")
    _make_test(tests, "atomic", 3)
    result = analyze_coverage(str(spa), str(tests))
    assert result["total_modules"] == 2
    assert result["tested"] == 1
    assert result["untested"] == 1
    assert abs(result["coverage_pct"] - 50.0) < 0.01


def test_analyze_coverage_untested_list(tmp_repo: Path) -> None:
    spa = tmp_repo / "spa_core"
    _make_module(spa, "risk", "policy")
    _make_module(spa, "risk", "engine")
    result = analyze_coverage(str(spa), str(tmp_repo / "tests"))
    assert len(result["top_untested"]) == 2
    assert all("risk" in m for m in result["top_untested"])


def test_analyze_coverage_by_package(tmp_repo: Path) -> None:
    spa = tmp_repo / "spa_core"
    tests = tmp_repo / "tests"
    _make_module(spa, "risk", "policy")
    _make_module(spa, "adapters", "aave")
    _make_test(tests, "aave", 2)
    result = analyze_coverage(str(spa), str(tests))
    assert "risk" in result["by_package"]
    assert "adapters" in result["by_package"]
    assert result["by_package"]["adapters"]["tested"] == 1
    assert result["by_package"]["risk"]["tested"] == 0


def test_analyze_coverage_init_excluded(tmp_repo: Path) -> None:
    """__init__.py files must not appear in module count."""
    spa = tmp_repo / "spa_core"
    pkg = spa / "utils"
    pkg.mkdir(parents=True)
    (pkg / "__init__.py").write_text("")
    result = analyze_coverage(str(spa), str(tmp_repo / "tests"))
    assert result["total_modules"] == 0


def test_analyze_coverage_pycache_excluded(tmp_repo: Path) -> None:
    """__pycache__ must not be walked."""
    spa = tmp_repo / "spa_core"
    cache = spa / "__pycache__"
    cache.mkdir(parents=True)
    (cache / "something.py").write_text("def test_x(): pass")
    result = analyze_coverage(str(spa), str(tmp_repo / "tests"))
    assert result["total_modules"] == 0


# ─────────────────────────────────────────────────────────────────────────────
# 3. format_markdown
# ─────────────────────────────────────────────────────────────────────────────


def _sample_result() -> dict:
    return {
        "total_modules": 10,
        "tested": 6,
        "untested": 4,
        "coverage_pct": 60.0,
        "total_tests": 120,
        "test_files_total": 6,
        "top_untested": ["spa_core/risk/policy.py", "spa_core/data_pipeline/sky.py"],
        "all_untested_count": 4,
        "tested_detail": [
            {"module": "spa_core/utils/atomic.py", "test_count": 42, "test_files": []},
        ],
        "by_package": {
            "utils": {"total": 5, "tested": 5},
            "risk": {"total": 5, "tested": 1},
        },
    }


def test_format_markdown_is_string() -> None:
    md = format_markdown(_sample_result(), "spa_core", "tests")
    assert isinstance(md, str)
    assert len(md) > 100


def test_format_markdown_has_header() -> None:
    md = format_markdown(_sample_result(), "spa_core", "tests")
    assert "# SPA Test Coverage Report" in md


def test_format_markdown_has_summary_table() -> None:
    md = format_markdown(_sample_result(), "spa_core", "tests")
    assert "60.0%" in md
    assert "10" in md  # total modules


def test_format_markdown_by_package_section() -> None:
    md = format_markdown(_sample_result(), "spa_core", "tests")
    assert "utils" in md
    assert "risk" in md


def test_format_markdown_untested_listed() -> None:
    md = format_markdown(_sample_result(), "spa_core", "tests")
    assert "spa_core/risk/policy.py" in md


# ─────────────────────────────────────────────────────────────────────────────
# 4. CLI integration
# ─────────────────────────────────────────────────────────────────────────────


def test_main_no_args_runs(tmp_path: Path, capsys) -> None:
    """main() with nonexistent dirs should not crash."""
    with patch("sys.argv", ["test_coverage_report.py",
                            "--spa-dir", str(tmp_path / "spa_core"),
                            "--test-dir", str(tmp_path / "tests")]):
        main()
    captured = capsys.readouterr()
    assert "Coverage:" in captured.out


def test_main_json_flag(tmp_path: Path, capsys) -> None:
    spa = tmp_path / "spa_core"
    tests = tmp_path / "tests"
    spa.mkdir()
    tests.mkdir()
    with patch("sys.argv", ["test_coverage_report.py",
                            "--spa-dir", str(spa),
                            "--test-dir", str(tests),
                            "--json"]):
        main()
    captured = capsys.readouterr()
    data = json.loads(captured.out)
    assert "coverage_pct" in data


def test_main_writes_markdown_output(tmp_path: Path) -> None:
    spa = tmp_path / "spa_core"
    tests = tmp_path / "tests"
    spa.mkdir()
    tests.mkdir()
    out_file = tmp_path / "docs" / "TEST_COVERAGE_REPORT.md"
    with patch("sys.argv", ["test_coverage_report.py",
                            "--spa-dir", str(spa),
                            "--test-dir", str(tests),
                            "--output", str(out_file)]):
        main()
    assert out_file.exists()
    content = out_file.read_text()
    assert "# SPA Test Coverage Report" in content


def test_main_real_codebase(capsys) -> None:
    """Smoke-test against the real SPA codebase (non-zero modules expected)."""
    with patch("sys.argv", ["test_coverage_report.py"]):
        main()
    captured = capsys.readouterr()
    # Expect at least some modules
    assert "Coverage:" in captured.out
    import re
    m = re.search(r"(\d+)/(\d+) modules", captured.out)
    assert m is not None, f"Pattern not found in: {captured.out}"
    tested, total = int(m.group(1)), int(m.group(2))
    assert total > 100, "Expected >100 spa_core modules"
    assert tested > 0, "Expected at least some tested modules"
