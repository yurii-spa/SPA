#!/usr/bin/env python3
"""
scripts/analytics_conformance.py

Checks that analytics modules conform to BaseAnalytics interface.
Reports which modules are conforming (inherit BaseAnalytics/BaseReport)
and which need migration.

Usage:
    python3 scripts/analytics_conformance.py
    python3 scripts/analytics_conformance.py --fix-list   # show migration commands
    python3 scripts/analytics_conformance.py --json       # machine-readable output

MP-1403 (v10.19) — AUDIT-002
stdlib only. Read-only advisory. LLM FORBIDDEN.
"""
from __future__ import annotations

import ast
import json
import os
from typing import List

_ANALYTICS_DIR = "spa_core/analytics"
_BASE_NAMES = {"BaseAnalytics", "BaseReport"}  # acceptable base classes


# ---------------------------------------------------------------------------
# AST parsing
# ---------------------------------------------------------------------------

def find_analytics_classes(filepath: str) -> List[dict]:
    """
    Parse Python file and find class definitions.

    Returns list of dicts:
        {
            class_name: str,
            bases: List[str],        # direct base class names (unqualified)
            has_save: bool,          # defines save() method
            has_load: bool,          # defines load() method
            has_to_dict: bool,       # defines to_dict() method
            inherits_base: bool,     # base is BaseAnalytics or BaseReport
            file: str,
            line: int,
        }
    """
    try:
        with open(filepath, "r", encoding="utf-8", errors="replace") as f:
            source = f.read()
        tree = ast.parse(source, filename=filepath)
    except SyntaxError:
        return []
    except OSError:
        return []

    results = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.ClassDef):
            continue

        # Collect base class names (handle dotted like spa_core.base.BaseAnalytics)
        bases: List[str] = []
        for base in node.bases:
            if isinstance(base, ast.Name):
                bases.append(base.id)
            elif isinstance(base, ast.Attribute):
                bases.append(base.attr)

        # Collect method names
        method_names = {
            n.name
            for n in ast.walk(node)
            if isinstance(n, ast.FunctionDef) or isinstance(n, ast.AsyncFunctionDef)
        }

        inherits_base = bool(_BASE_NAMES & set(bases))

        results.append({
            "class_name": node.name,
            "bases": bases,
            "has_save": "save" in method_names,
            "has_load": "load" in method_names,
            "has_to_dict": "to_dict" in method_names,
            "inherits_base": inherits_base,
            "file": filepath,
            "line": node.lineno,
        })

    return results


def check_base_analytics_conformance(filepath: str) -> dict:
    """
    Checks if file contains any class inheriting BaseAnalytics / BaseReport.

    Returns:
        {
            filepath: str,
            classes: List[dict],        # all classes found
            any_conforming: bool,
            non_conforming: List[str],  # class names NOT inheriting base
            conforming: List[str],      # class names inheriting base
            recommendation: str,
        }
    """
    classes = find_analytics_classes(filepath)

    conforming = [c["class_name"] for c in classes if c["inherits_base"]]
    non_conforming = [c["class_name"] for c in classes if not c["inherits_base"]]
    any_conforming = len(conforming) > 0

    if not classes:
        recommendation = "no_classes"
    elif any_conforming and not non_conforming:
        recommendation = "fully_conforming"
    elif any_conforming and non_conforming:
        recommendation = "partially_conforming"
    else:
        recommendation = "migrate_to_base_analytics"

    return {
        "filepath": filepath,
        "classes": classes,
        "any_conforming": any_conforming,
        "non_conforming": non_conforming,
        "conforming": conforming,
        "recommendation": recommendation,
    }


# ---------------------------------------------------------------------------
# Directory scanning
# ---------------------------------------------------------------------------

def scan_analytics_dir(base_dir: str = ".") -> List[dict]:
    """
    Scan spa_core/analytics/*.py (non-recursive, skip __init__ and _module_registry).

    Returns list of conformance check results.
    """
    analytics_dir = os.path.join(base_dir, _ANALYTICS_DIR)
    results = []

    if not os.path.isdir(analytics_dir):
        return results

    for fname in sorted(os.listdir(analytics_dir)):
        if not fname.endswith(".py"):
            continue
        if fname.startswith("__") or fname == "_module_registry.py":
            continue
        fpath = os.path.join(analytics_dir, fname)
        results.append(check_base_analytics_conformance(fpath))

    return results


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------

def conformance_report(results: List[dict]) -> str:
    """
    Human-readable conformance report with counts.
    """
    total = len(results)
    conforming_files = sum(1 for r in results if r["any_conforming"])
    non_conforming_files = sum(1 for r in results if not r["any_conforming"] and r["recommendation"] != "no_classes")
    no_class_files = sum(1 for r in results if r["recommendation"] == "no_classes")
    partial_files = sum(1 for r in results if r["recommendation"] == "partially_conforming")

    lines = [
        "=" * 70,
        "SPA Analytics Conformance Report (MP-1403 v10.19)",
        "=" * 70,
        f"Total files scanned:        {total}",
        f"Fully conforming:           {conforming_files - partial_files}",
        f"Partially conforming:       {partial_files}",
        f"Non-conforming (with class):{non_conforming_files}",
        f"No class definitions:       {no_class_files}",
        "",
    ]

    # Non-conforming list
    needs_migration = [
        r for r in results
        if r["recommendation"] in ("migrate_to_base_analytics", "partially_conforming")
    ]

    if needs_migration:
        lines.append(f"Files needing migration ({len(needs_migration)}):")
        lines.append("-" * 50)
        for r in needs_migration[:50]:
            short = os.path.basename(r["filepath"])
            classes = ", ".join(r["non_conforming"])
            lines.append(f"  {short:50s}  [{classes}]")
        if len(needs_migration) > 50:
            lines.append(f"  ... and {len(needs_migration) - 50} more")
        lines.append("")

    # Conforming list
    fully = [r for r in results if r["recommendation"] == "fully_conforming"]
    if fully:
        lines.append(f"Conforming files ({len(fully)}):")
        lines.append("-" * 50)
        for r in fully[:20]:
            short = os.path.basename(r["filepath"])
            lines.append(f"  {short}")
        if len(fully) > 20:
            lines.append(f"  ... and {len(fully) - 20} more")
        lines.append("")

    lines.append("=" * 70)
    return "\n".join(lines)


def fix_list_commands(results: List[dict]) -> str:
    """
    Generate suggested migration hints for non-conforming files.
    """
    lines = ["# Migration hints (MP-1403)", "# Add `from spa_core.base import BaseAnalytics` and inherit", ""]
    for r in results:
        if r["recommendation"] not in ("migrate_to_base_analytics", "partially_conforming"):
            continue
        for cls in r["non_conforming"]:
            short = r["filepath"]
            lines.append(f"# {short}  →  class {cls}(BaseAnalytics):")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Analytics conformance checker (MP-1403)")
    parser.add_argument("--fix-list", action="store_true", help="Show migration commands")
    parser.add_argument("--json", action="store_true", dest="as_json", help="Machine-readable JSON output")
    parser.add_argument("--dir", default=".", help="Base repo directory (default: .)")
    args = parser.parse_args()

    results = scan_analytics_dir(args.dir)

    if args.as_json:
        # Exclude 'classes' details for brevity
        slim = []
        for r in results:
            slim.append({
                "filepath": r["filepath"],
                "any_conforming": r["any_conforming"],
                "conforming": r["conforming"],
                "non_conforming": r["non_conforming"],
                "recommendation": r["recommendation"],
            })
        print(json.dumps({"results": slim, "total": len(results)}, indent=2))
    elif args.fix_list:
        print(fix_list_commands(results))
    else:
        print(conformance_report(results))


if __name__ == "__main__":
    main()
