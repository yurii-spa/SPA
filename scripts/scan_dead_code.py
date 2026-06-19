#!/usr/bin/env python3
"""
scripts/scan_dead_code.py

Scans for orphan modules and missing tests in SPA codebase.

Usage:
  python3 scripts/scan_dead_code.py
  python3 scripts/scan_dead_code.py --no-tests    # modules without tests
  python3 scripts/scan_dead_code.py --orphans     # modules not imported anywhere
  python3 scripts/scan_dead_code.py --stubs       # files < 50 lines
  python3 scripts/scan_dead_code.py --save        # saves to data/dead_code_report.json
"""

import argparse
import ast
import json
import os
import re
import sys
from datetime import date

_DEFAULT_SAVE_PATH = "data/dead_code_report.json"


# ---------------------------------------------------------------------------
# Core analysis functions
# ---------------------------------------------------------------------------

def find_modules(spa_dir: str = "spa_core") -> list:
    """
    Returns sorted list of all .py file paths (relative to repo root)
    found recursively under spa_dir.
    """
    modules = []
    if not os.path.isdir(spa_dir):
        return modules
    for root, dirs, files in os.walk(spa_dir):
        # Skip __pycache__
        dirs[:] = [d for d in dirs if d != "__pycache__"]
        for fname in files:
            if fname.endswith(".py"):
                rel_path = os.path.join(root, fname)
                modules.append(rel_path)
    return sorted(modules)


def _module_stem(path: str) -> str:
    """
    Convert a file path like 'spa_core/analytics/foo.py' to module stem 'foo'
    and also a dotted name 'spa_core.analytics.foo'.
    Returns (stem, dotted).
    """
    no_ext = path[:-3]  # strip .py
    dotted = no_ext.replace(os.sep, ".")
    stem = os.path.basename(no_ext)
    return stem, dotted


def find_tests(tests_dir: str = "tests") -> set:
    """
    Returns set of module stems covered by test files in tests_dir.
    E.g. 'tests/test_foo.py' → 'foo' is in the set.
    Pass multiple dirs by calling find_tests() per dir and unioning the results.
    """
    tested = set()
    dirs_to_check = [tests_dir]
    for d in dirs_to_check:
        if not os.path.isdir(d):
            continue
        for root, dirs, files in os.walk(d):
            dirs[:] = [x for x in dirs if x != "__pycache__"]
            for fname in files:
                m = re.match(r"^test_(.+)\.py$", fname)
                if m:
                    tested.add(m.group(1))
    return tested


def modules_without_tests(modules: list, tests: set) -> list:
    """
    Returns module paths (from modules list) that have no matching test file.
    __init__.py files are excluded (they rarely have dedicated tests).
    """
    result = []
    for path in modules:
        stem, _ = _module_stem(path)
        if stem == "__init__":
            continue
        if stem not in tests:
            result.append(path)
    return result


def find_all_imports(spa_dir: str = "spa_core") -> dict:
    """
    Scans all .py files under spa_dir (and scripts/) and returns
    {module_stem: [list_of_files_that_import_it]}.

    Uses both AST-based import parsing and simple regex fallback.
    """
    import_map: dict = {}
    search_dirs = [spa_dir, "scripts", "tests"]

    def _record(stem: str, src_file: str):
        import_map.setdefault(stem, [])
        if src_file not in import_map[stem]:
            import_map[stem].append(src_file)

    def _parse_file(path: str):
        try:
            with open(path, "r", encoding="utf-8", errors="ignore") as f:
                src = f.read()
        except OSError:
            return
        # AST parse
        try:
            tree = ast.parse(src, filename=path)
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        parts = alias.name.split(".")
                        _record(parts[-1], path)
                        _record(parts[0], path)
                elif isinstance(node, ast.ImportFrom):
                    if node.module:
                        parts = node.module.split(".")
                        _record(parts[-1], path)
                        _record(parts[0], path)
                    for alias in node.names:
                        _record(alias.name, path)
        except SyntaxError:
            # Fallback: regex
            for m in re.finditer(r"^\s*(?:from|import)\s+([\w.]+)", src, re.MULTILINE):
                for part in m.group(1).split("."):
                    _record(part, path)

    for d in search_dirs:
        if not os.path.isdir(d):
            continue
        for root, dirs, files in os.walk(d):
            dirs[:] = [x for x in dirs if x != "__pycache__"]
            for fname in files:
                if fname.endswith(".py"):
                    _parse_file(os.path.join(root, fname))

    return import_map


def orphan_modules(modules: list, import_map: dict) -> list:
    """
    Returns module paths that are imported by nobody else.
    __init__.py files are always excluded (they're never directly imported
    by name but are loaded implicitly — they're not truly orphans).
    """
    result = []
    for path in modules:
        stem, dotted = _module_stem(path)
        if stem == "__init__":
            continue
        if stem not in import_map and dotted not in import_map:
            result.append(path)
    return result


def stub_modules(modules: list, min_lines: int = 50) -> list:
    """
    Returns module paths with fewer than min_lines of non-blank, non-comment
    lines. These are likely stubs or placeholder files.
    """
    result = []
    for path in modules:
        try:
            with open(path, "r", encoding="utf-8", errors="ignore") as f:
                lines = f.readlines()
        except OSError:
            continue
        count = sum(
            1 for line in lines
            if line.strip() and not line.strip().startswith("#")
        )
        if count < min_lines:
            result.append(path)
    return result


def report(spa_dir: str = "spa_core", tests_dir: str = "tests") -> dict:
    """
    Full report: {no_tests, orphans, stubs, summary, generated_at}.
    """
    mods = find_modules(spa_dir)
    tests_set = find_tests(tests_dir)
    imp_map = find_all_imports(spa_dir)

    no_tests_list = modules_without_tests(mods, tests_set)
    orphans_list = orphan_modules(mods, imp_map)
    stubs_list = stub_modules(mods)

    return {
        "generated_at": str(date.today()),
        "no_tests": no_tests_list,
        "orphans": orphans_list,
        "stubs": stubs_list,
        "summary": {
            "total_modules": len(mods),
            "no_tests_count": len(no_tests_list),
            "orphans_count": len(orphans_list),
            "stubs_count": len(stubs_list),
        },
    }


def save(report_data: dict, path: str = _DEFAULT_SAVE_PATH) -> str:
    """Atomic save of report to JSON. Returns path."""
    os.makedirs(os.path.dirname(path) if os.path.dirname(path) else ".", exist_ok=True)
    tmp_path = path + ".tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(report_data, f, indent=2)
    os.replace(tmp_path, path)
    return path


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="SPA dead code scanner — find orphans, stubs, untested modules"
    )
    p.add_argument("--no-tests", action="store_true", help="Show modules without tests")
    p.add_argument("--orphans", action="store_true", help="Show modules not imported anywhere")
    p.add_argument("--stubs", action="store_true", help="Show stub files (< 50 lines)")
    p.add_argument("--save", action="store_true",
                   help=f"Save report to {_DEFAULT_SAVE_PATH}")
    p.add_argument("--spa-dir", default="spa_core", help="SPA source directory (default: spa_core)")
    p.add_argument("--tests-dir", default="tests", help="Tests directory (default: tests)")
    p.add_argument("--min-lines", type=int, default=50,
                   help="Stub threshold (default: 50)")
    p.add_argument("--output", default=_DEFAULT_SAVE_PATH,
                   help=f"Output path for --save (default: {_DEFAULT_SAVE_PATH})")
    return p


def main(argv=None) -> int:
    p = _build_parser()
    args = p.parse_args(argv)

    show_all = not any([args.no_tests, args.orphans, args.stubs, args.save])

    mods = find_modules(args.spa_dir)
    tests_set = find_tests(args.tests_dir)
    imp_map = find_all_imports(args.spa_dir)

    if args.no_tests or show_all:
        no_tests_list = modules_without_tests(mods, tests_set)
        print(f"\n=== Modules without tests ({len(no_tests_list)}) ===")
        for m in no_tests_list:
            print(f"  {m}")

    if args.orphans or show_all:
        orphans_list = orphan_modules(mods, imp_map)
        print(f"\n=== Orphan modules — not imported anywhere ({len(orphans_list)}) ===")
        for m in orphans_list:
            print(f"  {m}")

    if args.stubs or show_all:
        stubs_list = stub_modules(mods, min_lines=args.min_lines)
        print(f"\n=== Stub files < {args.min_lines} lines ({len(stubs_list)}) ===")
        for m in stubs_list:
            print(f"  {m}")

    if args.save or show_all:
        r = report(args.spa_dir, args.tests_dir)
        out = save(r, args.output)
        print(f"\nReport saved → {out}")
        s = r["summary"]
        print(
            f"Total modules: {s['total_modules']} | "
            f"No tests: {s['no_tests_count']} | "
            f"Orphans: {s['orphans_count']} | "
            f"Stubs: {s['stubs_count']}"
        )

    return 0


if __name__ == "__main__":
    sys.exit(main())
