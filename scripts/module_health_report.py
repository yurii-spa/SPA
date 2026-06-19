#!/usr/bin/env python3
"""
scripts/module_health_report.py

Comprehensive codebase health report.
Aggregates all audit tools into one dashboard.

Output: data/health/module_health_YYYY-MM-DD.json + .md

Sections:
  1. Summary: total modules, test coverage %, violations
  2. Critical Issues: CRIT-001/002/003 status
  3. Test Coverage: modules with/without tests
  4. Dead Code: orphans, stubs, unused imports
  5. Architecture: violations, anti-patterns
  6. Push Status: registry summary
  7. Recommendations: prioritized action list

MP-1390 (v10.6) — AUDIT-001
stdlib only. Read-only advisory. LLM FORBIDDEN.
"""

from __future__ import annotations

import ast
import json
import os
import re
import sys
import tempfile
from datetime import date, datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# ── Repo root ─────────────────────────────────────────────────────────────────

_SCRIPT_DIR = Path(__file__).resolve().parent
_REPO_ROOT = _SCRIPT_DIR.parent


# ═══════════════════════════════════════════════════════════════════════════════
# Section 1: Summary helpers
# ═══════════════════════════════════════════════════════════════════════════════

def _collect_py_modules(base_dir: Path) -> List[Path]:
    """Returns all .py files under base_dir (excluding __pycache__)."""
    result = []
    for p in sorted(base_dir.rglob("*.py")):
        if "__pycache__" not in str(p):
            result.append(p)
    return result


def _count_lines(path: Path) -> int:
    """Returns line count of a file, 0 on error."""
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            return sum(1 for _ in fh)
    except (OSError, IOError):
        return 0


def _build_summary(base_dir: Path, tests_dir: Path) -> dict:
    """
    Returns summary section:
      total_modules, total_lines, test_files,
      coverage_pct, violations_count
    """
    modules = _collect_py_modules(base_dir)
    test_files = _collect_py_modules(tests_dir) if tests_dir.exists() else []

    total_lines = sum(_count_lines(m) for m in modules)

    # Count modules that have a corresponding test file
    module_names = {m.stem for m in modules}
    tested = {t.stem.replace("test_", "") for t in test_files if t.stem.startswith("test_")}
    covered = module_names & tested
    coverage_pct = round(len(covered) / max(len(module_names), 1) * 100, 1)

    return {
        "total_modules": len(modules),
        "total_lines": total_lines,
        "test_files": len(test_files),
        "covered_modules": len(covered),
        "coverage_pct": coverage_pct,
        "violations_count": 0,  # filled later by architecture check
    }


# ═══════════════════════════════════════════════════════════════════════════════
# Section 2: Critical Issues
# ═══════════════════════════════════════════════════════════════════════════════

def _check_crit_001(base_dir: Path, repo_root: Path = None) -> dict:
    """
    CRIT-001: Execution-domain imports in read-only code.
    Checks for 'from spa_core.execution' in non-execution modules.
    """
    if repo_root is None:
        repo_root = _REPO_ROOT
    violations = []
    for py in _collect_py_modules(base_dir):
        if "execution" in py.parts:
            continue  # skip execution domain itself
        try:
            src = py.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if "from spa_core.execution" in src or "import spa_core.execution" in src:
            try:
                rel = str(py.relative_to(repo_root))
            except ValueError:
                rel = str(py)
            violations.append(rel)

    return {
        "id": "CRIT-001",
        "description": "Execution-domain imports in read-only code",
        "status": "PASS" if not violations else "FAIL",
        "violations": violations,
        "count": len(violations),
    }


def _check_crit_002(base_dir: Path, repo_root: Path = None) -> dict:
    """
    CRIT-002: External dependencies in runtime code.
    Checks for non-stdlib imports in spa_core/ (runtime must be stdlib only).
    """
    if repo_root is None:
        repo_root = _REPO_ROOT
    ALLOWED_STDLIB = {
        "os", "sys", "re", "json", "time", "math", "copy", "enum", "abc",
        "ast", "csv", "io", "http", "urllib", "logging", "datetime", "pathlib",
        "typing", "functools", "itertools", "collections", "contextlib",
        "dataclasses", "threading", "subprocess", "tempfile", "hashlib",
        "hmac", "base64", "struct", "socket", "ssl", "email", "uuid",
        "decimal", "fractions", "random", "statistics", "heapq", "bisect",
        "textwrap", "string", "pprint", "traceback", "inspect", "importlib",
        "unittest", "argparse", "shutil", "glob", "fnmatch", "platform",
        "signal", "queue", "weakref", "array", "operator", "calendar",
        "locale", "codecs", "unicodedata", "difflib", "dis", "token",
        "tokenize", "keyword", "types", "__future__",
        # spa_core itself is allowed
        "spa_core",
    }

    violations = []
    for py in _collect_py_modules(base_dir):
        if "test" in py.stem or "test" in str(py.parts):
            continue  # skip test files
        try:
            src = py.read_text(encoding="utf-8", errors="replace")
            tree = ast.parse(src, filename=str(py))
        except (OSError, SyntaxError):
            continue

        for node in ast.walk(tree):
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                if isinstance(node, ast.Import):
                    names = [alias.name.split(".")[0] for alias in node.names]
                else:
                    module = (node.module or "").split(".")[0]
                    names = [module] if module else []
                for name in names:
                    if name and name not in ALLOWED_STDLIB:
                        try:
                            rel = str(py.relative_to(repo_root))
                        except ValueError:
                            rel = str(py)
                        entry = f"{rel}: import {name}"
                        if entry not in violations:
                            violations.append(entry)

    return {
        "id": "CRIT-002",
        "description": "External (non-stdlib) imports in runtime code",
        "status": "PASS" if not violations else "WARN",
        "violations": violations[:20],  # cap at 20
        "count": len(violations),
    }


def _check_crit_003(base_dir: Path, repo_root: Path = None) -> dict:
    """
    CRIT-003: Local atomic-write patterns not migrated.
    Counts files with local _atomic_write / _write_json defs.
    """
    if repo_root is None:
        repo_root = _REPO_ROOT
    _LOCAL_ATOMIC_RE = re.compile(
        r'def\s+_(?:atomic_write|atomic_save|write_json|save_json)\s*\('
    )
    _MIGRATED_RE = re.compile(
        r'from\s+spa_core\.utils\.atomic\s+import|from\s+spa_core\.utils\s+import\s+atomic'
    )

    needs_migration = []
    already_migrated = []

    for py in _collect_py_modules(base_dir):
        try:
            src = py.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        try:
            rel = str(py.relative_to(repo_root))
        except ValueError:
            rel = str(py)
        if _MIGRATED_RE.search(src):
            already_migrated.append(rel)
        elif _LOCAL_ATOMIC_RE.search(src):
            needs_migration.append(rel)

    return {
        "id": "CRIT-003",
        "description": "Local atomic-write patterns not migrated to spa_core.utils.atomic",
        "status": "PASS" if len(needs_migration) == 0 else "FAIL",
        "needs_migration": len(needs_migration),
        "already_migrated": len(already_migrated),
        "sample_files": needs_migration[:5],
        "count": len(needs_migration),
    }


def _build_critical_issues(base_dir: Path, repo_root: Path = None) -> dict:
    if repo_root is None:
        repo_root = _REPO_ROOT
    c1 = _check_crit_001(base_dir, repo_root)
    c2 = _check_crit_002(base_dir, repo_root)
    c3 = _check_crit_003(base_dir, repo_root)
    issues = [c1, c2, c3]
    fail_count = sum(1 for i in issues if i["status"] == "FAIL")
    warn_count = sum(1 for i in issues if i["status"] == "WARN")
    return {
        "checks": issues,
        "fail_count": fail_count,
        "warn_count": warn_count,
        "overall": "PASS" if fail_count == 0 and warn_count == 0 else
                   "FAIL" if fail_count > 0 else "WARN",
    }


# ═══════════════════════════════════════════════════════════════════════════════
# Section 3: Test Coverage
# ═══════════════════════════════════════════════════════════════════════════════

def _build_test_coverage(base_dir: Path, tests_dirs: List[Path],
                         repo_root: Path = None) -> dict:
    """Returns per-subpackage test coverage breakdown."""
    if repo_root is None:
        repo_root = _REPO_ROOT
    modules = _collect_py_modules(base_dir)
    all_tests = []
    for td in tests_dirs:
        if td.exists():
            all_tests.extend(_collect_py_modules(td))

    tested_stems = {t.stem.replace("test_", "") for t in all_tests
                    if t.stem.startswith("test_")}

    missing_tests = []
    covered = []

    for m in modules:
        if m.stem in ("__init__", "conftest"):
            continue
        try:
            rel = str(m.relative_to(repo_root))
        except ValueError:
            rel = str(m)
        if m.stem in tested_stems:
            covered.append(rel)
        else:
            missing_tests.append(rel)

    total = len(covered) + len(missing_tests)
    pct = round(len(covered) / max(total, 1) * 100, 1)

    return {
        "total_modules": total,
        "covered": len(covered),
        "missing_tests": len(missing_tests),
        "coverage_pct": pct,
        "sample_missing": missing_tests[:10],
    }


# ═══════════════════════════════════════════════════════════════════════════════
# Section 4: Dead Code
# ═══════════════════════════════════════════════════════════════════════════════

def _build_dead_code(base_dir: Path, repo_root: Path = None) -> dict:
    """
    Detects potential dead code:
    - Stub functions (only `pass` or `...` in body)
    - Empty modules (<= 3 non-comment lines)
    - __init__.py files with no exports
    """
    if repo_root is None:
        repo_root = _REPO_ROOT
    stubs = []
    empty_modules = []
    empty_inits = []

    _STUB_RE = re.compile(
        r'def\s+\w+\s*\([^)]*\)\s*(?:->[^:]+)?\s*:\s*\n\s+(?:pass|\.\.\.)\s*$',
        re.MULTILINE,
    )

    for py in _collect_py_modules(base_dir):
        try:
            src = py.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue

        try:
            rel = str(py.relative_to(repo_root))
        except ValueError:
            rel = str(py)

        # Empty module check
        real_lines = [l.strip() for l in src.splitlines()
                      if l.strip() and not l.strip().startswith("#")]
        if len(real_lines) <= 3 and py.stem != "__init__":
            empty_modules.append(rel)

        # Stub check
        stubs_in_file = _STUB_RE.findall(src)
        if stubs_in_file:
            stubs.append({"file": rel, "stub_count": len(stubs_in_file)})

        # Empty __init__ check
        if py.stem == "__init__" and len(real_lines) == 0:
            empty_inits.append(rel)

    return {
        "stub_files": len(stubs),
        "stub_details": stubs[:10],
        "empty_modules": len(empty_modules),
        "empty_modules_sample": empty_modules[:10],
        "empty_inits": len(empty_inits),
    }


# ═══════════════════════════════════════════════════════════════════════════════
# Section 5: Architecture
# ═══════════════════════════════════════════════════════════════════════════════

def _build_architecture(base_dir: Path, repo_root: Path = None) -> dict:
    """
    Detects architecture violations:
    - Non-atomic writes (direct open(..., 'w') on state files)
    - LLM calls in forbidden domains
    - Missing module docstrings
    """
    if repo_root is None:
        repo_root = _REPO_ROOT
    _DIRECT_WRITE_RE = re.compile(r'open\s*\([^,)]+,\s*["\']w["\']')
    _STATE_FILE_RE = re.compile(r'data/\w+\.json')
    _LLM_RE = re.compile(r'anthropic|openai|llm|ChatCompletion|claude\.messages', re.I)
    _FORBIDDEN_DOMAINS = {"risk", "execution", "monitoring"}

    direct_writes = []
    llm_violations = []
    missing_docstrings = []

    for py in _collect_py_modules(base_dir):
        try:
            rel = str(py.relative_to(repo_root))
        except ValueError:
            rel = str(py)
        try:
            src = py.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue

        # Direct writes on potential state files
        if _DIRECT_WRITE_RE.search(src) and _STATE_FILE_RE.search(src):
            direct_writes.append(rel)

        # LLM in forbidden domain
        domain = py.parts[1] if len(py.parts) > 2 else ""
        if domain in _FORBIDDEN_DOMAINS and _LLM_RE.search(src):
            llm_violations.append(rel)

        # Missing module docstring
        try:
            tree = ast.parse(src)
            if not (tree.body and isinstance(tree.body[0], ast.Expr)
                    and isinstance(tree.body[0].value, ast.Constant)
                    and isinstance(tree.body[0].value.value, str)):
                if py.stem != "__init__" and len(src.strip()) > 20:
                    missing_docstrings.append(rel)
        except SyntaxError:
            pass

    total_violations = len(direct_writes) + len(llm_violations)
    return {
        "direct_write_violations": len(direct_writes),
        "direct_write_sample": direct_writes[:5],
        "llm_forbidden_violations": len(llm_violations),
        "llm_violations": llm_violations,
        "missing_docstrings": len(missing_docstrings),
        "missing_docstrings_sample": missing_docstrings[:5],
        "total_violations": total_violations,
    }


# ═══════════════════════════════════════════════════════════════════════════════
# Section 6: KANBAN / Push Status
# ═══════════════════════════════════════════════════════════════════════════════

def _build_kanban_status(repo_root: Path) -> dict:
    """Reads KANBAN.json and returns summary."""
    kanban_path = repo_root / "KANBAN.json"
    if not kanban_path.exists():
        return {"error": "KANBAN.json not found"}

    try:
        with open(kanban_path, "r", encoding="utf-8") as fh:
            kanban = json.load(fh)
    except (OSError, json.JSONDecodeError) as e:
        return {"error": str(e)}

    columns = kanban.get("columns", {})
    return {
        "sprint_current": kanban.get("sprint_current", "unknown"),
        "sprint_completed": kanban.get("sprint_completed", "unknown"),
        "done_count": kanban.get("done_count", 0),
        "in_progress": len(columns.get("in_progress", [])),
        "backlog": len(columns.get("backlog", [])),
        "done_column": len(columns.get("done", [])),
        "last_updated": kanban.get("last_updated", "unknown"),
    }


def _build_golive_status(repo_root: Path) -> dict:
    """Reads golive_status.json."""
    path = repo_root / "data" / "golive_status.json"
    if not path.exists():
        return {"error": "golive_status.json not found"}
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        return {
            "ready": data.get("ready", False),
            "passed": data.get("passed", 0),
            "total": data.get("total", 0),
            "consecutive_ready_days": data.get("consecutive_ready_days", 0),
        }
    except (OSError, json.JSONDecodeError) as e:
        return {"error": str(e)}


# ═══════════════════════════════════════════════════════════════════════════════
# Section 7: Recommendations
# ═══════════════════════════════════════════════════════════════════════════════

def _build_recommendations(
    summary: dict,
    critical: dict,
    coverage: dict,
    dead: dict,
    arch: dict,
) -> list:
    """Returns prioritized list of action items."""
    items = []

    # CRIT failures → P0
    for check in critical.get("checks", []):
        if check["status"] == "FAIL":
            items.append({
                "priority": "P0",
                "category": "critical",
                "action": f"Fix {check['id']}: {check['description']} ({check['count']} violations)",
            })

    # CRIT warnings → P1
    for check in critical.get("checks", []):
        if check["status"] == "WARN":
            items.append({
                "priority": "P1",
                "category": "critical",
                "action": f"Investigate {check['id']}: {check['description']} ({check['count']} cases)",
            })

    # Test coverage < 50% → P1
    if coverage.get("coverage_pct", 100) < 50:
        items.append({
            "priority": "P1",
            "category": "test_coverage",
            "action": f"Add tests for {coverage['missing_tests']} uncovered modules "
                      f"(currently {coverage['coverage_pct']}%)",
        })

    # Arch violations → P1
    if arch.get("direct_write_violations", 0) > 0:
        items.append({
            "priority": "P1",
            "category": "architecture",
            "action": f"Migrate {arch['direct_write_violations']} direct-write violations "
                      f"to atomic_save()",
        })

    if arch.get("llm_forbidden_violations", 0) > 0:
        items.append({
            "priority": "P0",
            "category": "architecture",
            "action": f"Remove LLM calls from forbidden domains ({arch['llm_forbidden_violations']} files)",
        })

    # Dead code → P2
    if dead.get("stub_files", 0) > 5:
        items.append({
            "priority": "P2",
            "category": "dead_code",
            "action": f"Clean up {dead['stub_files']} files with stub-only functions",
        })

    if dead.get("empty_modules", 0) > 0:
        items.append({
            "priority": "P2",
            "category": "dead_code",
            "action": f"Remove or fill {dead['empty_modules']} near-empty modules",
        })

    # Missing docstrings → P2
    if arch.get("missing_docstrings", 0) > 10:
        items.append({
            "priority": "P2",
            "category": "documentation",
            "action": f"Add docstrings to {arch['missing_docstrings']} modules",
        })

    # Sort by priority
    order = {"P0": 0, "P1": 1, "P2": 2, "P3": 3}
    items.sort(key=lambda x: order.get(x["priority"], 99))

    return items


# ═══════════════════════════════════════════════════════════════════════════════
# Public API
# ═══════════════════════════════════════════════════════════════════════════════

def generate_report(base_dir: str = ".") -> dict:
    """
    Runs all checks and returns combined health report dict.

    Args:
        base_dir: Repository root (default: current directory).

    Returns:
        Full report dict with all sections.
    """
    root = Path(base_dir).resolve()
    spa_dir = root / "spa_core"
    tests_dirs = [root / "tests", root / "spa_core" / "tests"]

    # Run all sections
    summary = _build_summary(spa_dir, root / "tests")
    critical = _build_critical_issues(spa_dir, root)
    coverage = _build_test_coverage(spa_dir, tests_dirs, root)
    dead = _build_dead_code(spa_dir, root)
    arch = _build_architecture(spa_dir, root)

    # Update violations count in summary
    summary["violations_count"] = (
        critical.get("fail_count", 0) * 10 + arch.get("total_violations", 0)
    )

    kanban = _build_kanban_status(root)
    golive = _build_golive_status(root)
    recommendations = _build_recommendations(summary, critical, coverage, dead, arch)

    report = {
        "generated_at": datetime.utcnow().isoformat() + "Z",
        "base_dir": str(root),
        "summary": summary,
        "critical_issues": critical,
        "test_coverage": coverage,
        "dead_code": dead,
        "architecture": arch,
        "kanban_status": kanban,
        "golive_status": golive,
        "recommendations": recommendations,
        "version": "v10.6",
    }

    return report


def save_report(report: dict, date_str: str = None) -> Tuple[str, str]:
    """
    Saves report as JSON + Markdown.

    Args:
        report: Report dict from generate_report().
        date_str: Date string (YYYY-MM-DD). Defaults to today.

    Returns:
        Tuple of (json_path, md_path).
    """
    if date_str is None:
        date_str = date.today().isoformat()

    # Determine output directory
    base = Path(report.get("base_dir", "."))
    health_dir = base / "data" / "health"
    health_dir.mkdir(parents=True, exist_ok=True)

    json_path = health_dir / f"module_health_{date_str}.json"
    md_path = health_dir / f"module_health_{date_str}.md"

    # Atomic write JSON
    _atomic_write_json(report, json_path)

    # Write Markdown
    md_content = render_markdown(report)
    _atomic_write_text(md_content, md_path)

    return str(json_path), str(md_path)


def render_markdown(report: dict) -> str:
    """
    Renders report dict as human-readable Markdown with emoji status indicators.

    Returns:
        Markdown string (always > 200 chars for any non-trivial report).
    """
    lines = []
    gen_at = report.get("generated_at", "unknown")
    version = report.get("version", "")

    lines.append(f"# 🏥 Module Health Report {version}")
    lines.append(f"")
    lines.append(f"**Generated:** {gen_at}")
    lines.append(f"")

    # ── Summary ───────────────────────────────────────────────────────────────
    s = report.get("summary", {})
    lines.append("## 📊 Summary")
    lines.append("")
    lines.append(f"| Metric | Value |")
    lines.append(f"|--------|-------|")
    lines.append(f"| Total modules | {s.get('total_modules', 0)} |")
    lines.append(f"| Total lines | {s.get('total_lines', 0):,} |")
    lines.append(f"| Test files | {s.get('test_files', 0)} |")
    lines.append(f"| Covered modules | {s.get('covered_modules', 0)} |")
    lines.append(f"| Coverage % | {s.get('coverage_pct', 0)}% |")
    lines.append(f"| Violations | {s.get('violations_count', 0)} |")
    lines.append("")

    # ── Critical Issues ───────────────────────────────────────────────────────
    ci = report.get("critical_issues", {})
    overall = ci.get("overall", "UNKNOWN")
    emoji = {"PASS": "✅", "WARN": "⚠️", "FAIL": "❌"}.get(overall, "❓")
    lines.append(f"## {emoji} Critical Issues — {overall}")
    lines.append("")
    for check in ci.get("checks", []):
        st = check.get("status", "?")
        st_emoji = {"PASS": "✅", "WARN": "⚠️", "FAIL": "❌"}.get(st, "❓")
        lines.append(f"### {st_emoji} {check['id']}: {check['description']}")
        lines.append(f"- **Status:** {st}")
        lines.append(f"- **Count:** {check.get('count', 0)}")
        if check.get("sample_files"):
            lines.append(f"- **Sample files:**")
            for f in check["sample_files"][:3]:
                lines.append(f"  - `{f}`")
        if check.get("violations"):
            for v in check["violations"][:3]:
                lines.append(f"  - `{v}`")
        lines.append("")

    # ── Test Coverage ─────────────────────────────────────────────────────────
    tc = report.get("test_coverage", {})
    cov_pct = tc.get("coverage_pct", 0)
    cov_emoji = "✅" if cov_pct >= 70 else "⚠️" if cov_pct >= 40 else "❌"
    lines.append(f"## {cov_emoji} Test Coverage — {cov_pct}%")
    lines.append("")
    lines.append(f"- **Total modules:** {tc.get('total_modules', 0)}")
    lines.append(f"- **Covered:** {tc.get('covered', 0)}")
    lines.append(f"- **Missing tests:** {tc.get('missing_tests', 0)}")
    if tc.get("sample_missing"):
        lines.append(f"- **Sample uncovered (first 5):**")
        for f in tc["sample_missing"][:5]:
            lines.append(f"  - `{f}`")
    lines.append("")

    # ── Dead Code ─────────────────────────────────────────────────────────────
    dc = report.get("dead_code", {})
    lines.append("## 🪦 Dead Code")
    lines.append("")
    lines.append(f"- **Stub-only files:** {dc.get('stub_files', 0)}")
    lines.append(f"- **Empty modules:** {dc.get('empty_modules', 0)}")
    lines.append(f"- **Empty `__init__.py`:** {dc.get('empty_inits', 0)}")
    lines.append("")

    # ── Architecture ──────────────────────────────────────────────────────────
    ar = report.get("architecture", {})
    arch_ok = ar.get("total_violations", 0) == 0
    arch_emoji = "✅" if arch_ok else "❌"
    lines.append(f"## {arch_emoji} Architecture")
    lines.append("")
    lines.append(f"- **Direct-write violations:** {ar.get('direct_write_violations', 0)}")
    lines.append(f"- **LLM forbidden violations:** {ar.get('llm_forbidden_violations', 0)}")
    lines.append(f"- **Missing docstrings:** {ar.get('missing_docstrings', 0)}")
    lines.append("")

    # ── KANBAN ────────────────────────────────────────────────────────────────
    kb = report.get("kanban_status", {})
    lines.append("## 📋 KANBAN Status")
    lines.append("")
    lines.append(f"- **Sprint current:** {kb.get('sprint_current', '?')}")
    lines.append(f"- **Sprint completed:** {kb.get('sprint_completed', '?')}")
    lines.append(f"- **Done count:** {kb.get('done_count', 0)}")
    lines.append(f"- **In progress:** {kb.get('in_progress', 0)}")
    lines.append(f"- **Backlog:** {kb.get('backlog', 0)}")
    lines.append("")

    # ── GoLive ────────────────────────────────────────────────────────────────
    gl = report.get("golive_status", {})
    gl_ready = gl.get("ready", False)
    gl_emoji = "✅" if gl_ready else "🔴"
    lines.append(f"## {gl_emoji} GoLive Status")
    lines.append("")
    lines.append(f"- **Ready:** {gl_ready}")
    lines.append(f"- **Passed:** {gl.get('passed', 0)} / {gl.get('total', 0)}")
    lines.append(f"- **Consecutive ready days:** {gl.get('consecutive_ready_days', 0)}")
    lines.append("")

    # ── Recommendations ───────────────────────────────────────────────────────
    recs = report.get("recommendations", [])
    if recs:
        lines.append("## 🎯 Recommendations")
        lines.append("")
        for r in recs:
            p_emoji = {"P0": "🚨", "P1": "⚠️", "P2": "📌", "P3": "💡"}.get(r["priority"], "•")
            lines.append(f"- {p_emoji} **[{r['priority']}]** `{r['category']}` — {r['action']}")
        lines.append("")

    lines.append("---")
    lines.append(f"*Generated by scripts/module_health_report.py {version}*")

    return "\n".join(lines)


# ── Atomic write helpers (stdlib only, no self-import) ────────────────────────

def _atomic_write_json(data: Any, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2, default=str)
        os.replace(tmp, str(path))
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _atomic_write_text(text: str, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(text)
        os.replace(tmp, str(path))
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


# ═══════════════════════════════════════════════════════════════════════════════
# CLI
# ═══════════════════════════════════════════════════════════════════════════════

def main(argv=None) -> int:
    import argparse
    parser = argparse.ArgumentParser(
        description="Generate comprehensive codebase health report"
    )
    parser.add_argument("--base-dir", default=".",
                        help="Repository root (default: current directory)")
    parser.add_argument("--save", action="store_true",
                        help="Save JSON + MD to data/health/")
    parser.add_argument("--json", action="store_true",
                        help="Print JSON report to stdout")
    parser.add_argument("--md", action="store_true",
                        help="Print Markdown report to stdout")
    parser.add_argument("--date", default=None,
                        help="Override date (YYYY-MM-DD) for file naming")
    args = parser.parse_args(argv)

    print(f"Generating module health report for: {Path(args.base_dir).resolve()}")
    report = generate_report(args.base_dir)

    if args.json:
        print(json.dumps(report, indent=2, default=str))
        return 0

    if args.md:
        print(render_markdown(report))
        return 0

    if args.save:
        json_path, md_path = save_report(report, args.date)
        print(f"Saved JSON: {json_path}")
        print(f"Saved MD:   {md_path}")
        return 0

    # Default: human summary
    s = report["summary"]
    ci = report["critical_issues"]
    tc = report["test_coverage"]
    kb = report["kanban_status"]

    print(f"\n{'='*60}")
    print(f"  Module Health Report  {report['version']}")
    print(f"{'='*60}")
    print(f"  Modules:       {s['total_modules']} ({s['total_lines']:,} lines)")
    print(f"  Test coverage: {tc['coverage_pct']}% ({tc['covered']}/{tc['total_modules']})")
    print(f"  Critical:      {ci['overall']}  (F:{ci['fail_count']} W:{ci['warn_count']})")
    print(f"  Sprint:        {kb.get('sprint_current', '?')}")
    print(f"  Done count:    {kb.get('done_count', 0)}")
    print(f"  Recommendations: {len(report['recommendations'])}")
    print(f"{'='*60}\n")

    recs = report["recommendations"]
    if recs:
        print("Top recommendations:")
        for r in recs[:5]:
            print(f"  [{r['priority']}] {r['action']}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
