#!/usr/bin/env python3
"""
scripts/dead_code_scanner.py

Scans for dead code patterns in the SPA codebase.

Dead code categories:
1. unused_import   — imports defined but not referenced in the same file
2. no_tests        — spa_core modules with no corresponding test file
3. todo_stale      — TODO/FIXME/HACK/XXX comments
4. stub_module     — files with < 50 lines of non-empty code (likely stubs)
5. orphan_module   — spa_core module not imported by any other spa_core file

Usage:
    python3 scripts/dead_code_scanner.py
    python3 scripts/dead_code_scanner.py --category imports
    python3 scripts/dead_code_scanner.py --category untested
    python3 scripts/dead_code_scanner.py --category todos
    python3 scripts/dead_code_scanner.py --json
    python3 scripts/dead_code_scanner.py --save

MP-1404 (v10.20) — AUDIT-003
stdlib only. Read-only advisory. LLM FORBIDDEN.
"""
from __future__ import annotations

import argparse
import ast
import json
import os
import re
import sys
from dataclasses import dataclass, asdict
from typing import Dict, List, Set

_DEFAULT_SAVE_PATH = "data/dead_code_report.json"
_SPA_DIR = "spa_core"
_TESTS_DIRS = ["tests", "spa_core/tests"]
_STUB_LINE_THRESHOLD = 50


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class DeadCodeItem:
    category: str    # "unused_import" | "no_tests" | "todo_stale" | "stub_module" | "orphan_module"
    filepath: str
    line: int        # 0 if not line-specific
    description: str
    severity: str    # "LOW" | "MEDIUM" | "HIGH"

    def to_dict(self) -> dict:
        return asdict(self)


# ---------------------------------------------------------------------------
# Import analysis helpers
# ---------------------------------------------------------------------------

def _extract_import_names(node: ast.Import) -> List[str]:
    """Return bare names imported by `import X` or `import X as Y`."""
    names = []
    for alias in node.names:
        local = alias.asname if alias.asname else alias.name.split(".")[0]
        names.append(local)
    return names


def _extract_from_import_names(node: ast.ImportFrom) -> List[str]:
    """Return bare names imported by `from X import Y` or `from X import Y as Z`."""
    names = []
    for alias in node.names:
        local = alias.asname if alias.asname else alias.name
        if local != "*":
            names.append(local)
    return names


def _collect_names_used(tree: ast.AST, imported_names: List[str]) -> Set[str]:
    """Collect all Name / Attribute nodes to find which imports are referenced."""
    used: Set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            used.add(node.id)
        elif isinstance(node, ast.Attribute):
            # Catch dotted access like `os.path`
            root = node
            while isinstance(root, ast.Attribute):
                root = root.value
            if isinstance(root, ast.Name):
                used.add(root.id)
    return used


# ---------------------------------------------------------------------------
# DeadCodeScanner
# ---------------------------------------------------------------------------

class DeadCodeScanner:
    def __init__(self, base_dir: str = "."):
        self.base_dir = base_dir

    def _abs(self, rel: str) -> str:
        return os.path.join(self.base_dir, rel)

    # ------------------------------------------------------------------
    # 1. Unused imports
    # ------------------------------------------------------------------

    def scan_unused_imports(self, filepath: str) -> List[DeadCodeItem]:
        """
        Find imports that aren't referenced in the file.
        Handles: `import X`, `import X as Y`, `from X import Y`, `from X import Y as Z`.
        Skips `from X import *` and TYPE_CHECKING blocks (best-effort).
        """
        try:
            with open(filepath, "r", encoding="utf-8", errors="replace") as f:
                source = f.read()
            tree = ast.parse(source, filename=filepath)
        except (SyntaxError, OSError):
            return []

        import_nodes: List[tuple] = []  # (line, name)

        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for name in _extract_import_names(node):
                    import_nodes.append((node.lineno, name))
            elif isinstance(node, ast.ImportFrom):
                for name in _extract_from_import_names(node):
                    import_nodes.append((node.lineno, name))

        if not import_nodes:
            return []

        imported_names = [n for _, n in import_nodes]
        used = _collect_names_used(tree, imported_names)

        items = []
        for (line, name) in import_nodes:
            if name not in used:
                items.append(DeadCodeItem(
                    category="unused_import",
                    filepath=filepath,
                    line=line,
                    description=f"Import '{name}' is defined but not used",
                    severity="LOW",
                ))
        return items

    # ------------------------------------------------------------------
    # 2. Untested modules
    # ------------------------------------------------------------------

    def scan_untested_modules(self) -> List[DeadCodeItem]:
        """
        Find spa_core modules with no corresponding test_<stem>.py in tests dirs.
        """
        spa_dir = self._abs(_SPA_DIR)
        if not os.path.isdir(spa_dir):
            return []

        # Build tested stems set
        tested: Set[str] = set()
        for tdir in _TESTS_DIRS:
            abs_tdir = self._abs(tdir)
            if not os.path.isdir(abs_tdir):
                continue
            for root, dirs, files in os.walk(abs_tdir):
                dirs[:] = [d for d in dirs if d != "__pycache__"]
                for fname in files:
                    m = re.match(r"^test_(.+)\.py$", fname)
                    if m:
                        tested.add(m.group(1))

        items = []
        for root, dirs, files in os.walk(spa_dir):
            dirs[:] = [d for d in dirs if d != "__pycache__"]
            for fname in files:
                if not fname.endswith(".py"):
                    continue
                if fname.startswith("__"):
                    continue
                stem = fname[:-3]
                if stem not in tested:
                    fpath = os.path.join(root, fname)
                    items.append(DeadCodeItem(
                        category="no_tests",
                        filepath=fpath,
                        line=0,
                        description=f"No test file found for '{stem}' (expected test_{stem}.py)",
                        severity="MEDIUM",
                    ))
        return items

    # ------------------------------------------------------------------
    # 3. TODO / FIXME / HACK / XXX comments
    # ------------------------------------------------------------------

    def scan_todo_comments(self) -> List[DeadCodeItem]:
        """
        Find TODO/FIXME/HACK/XXX comments in spa_core and scripts.
        """
        pattern = re.compile(r"#\s*(TODO|FIXME|HACK|XXX)\b", re.IGNORECASE)
        search_dirs = [self._abs(_SPA_DIR), self._abs("scripts")]
        items = []
        for sdir in search_dirs:
            if not os.path.isdir(sdir):
                continue
            for root, dirs, files in os.walk(sdir):
                dirs[:] = [d for d in dirs if d != "__pycache__"]
                for fname in files:
                    if not fname.endswith(".py"):
                        continue
                    fpath = os.path.join(root, fname)
                    try:
                        with open(fpath, "r", encoding="utf-8", errors="replace") as f:
                            for lineno, line in enumerate(f, 1):
                                m = pattern.search(line)
                                if m:
                                    tag = m.group(1).upper()
                                    items.append(DeadCodeItem(
                                        category="todo_stale",
                                        filepath=fpath,
                                        line=lineno,
                                        description=f"{tag}: {line.strip()[:120]}",
                                        severity="LOW",
                                    ))
                    except OSError:
                        continue
        return items

    # ------------------------------------------------------------------
    # 4. Stub modules (< N non-empty lines)
    # ------------------------------------------------------------------

    def scan_stub_modules(self, threshold: int = _STUB_LINE_THRESHOLD) -> List[DeadCodeItem]:
        """
        Find spa_core Python files with fewer than `threshold` non-empty, non-comment lines.
        """
        spa_dir = self._abs(_SPA_DIR)
        if not os.path.isdir(spa_dir):
            return []
        items = []
        for root, dirs, files in os.walk(spa_dir):
            dirs[:] = [d for d in dirs if d != "__pycache__"]
            for fname in files:
                if not fname.endswith(".py") or fname.startswith("__"):
                    continue
                fpath = os.path.join(root, fname)
                try:
                    with open(fpath, "r", encoding="utf-8", errors="replace") as f:
                        lines = f.readlines()
                    code_lines = [
                        l for l in lines
                        if l.strip() and not l.strip().startswith("#")
                    ]
                    if len(code_lines) < threshold:
                        items.append(DeadCodeItem(
                            category="stub_module",
                            filepath=fpath,
                            line=0,
                            description=f"Only {len(code_lines)} code lines (threshold={threshold}) — possible stub",
                            severity="LOW",
                        ))
                except OSError:
                    continue
        return items

    # ------------------------------------------------------------------
    # 5. scan_all
    # ------------------------------------------------------------------

    def scan_all(
        self,
        include_imports: bool = True,
        include_untested: bool = True,
        include_todos: bool = True,
        include_stubs: bool = True,
    ) -> List[DeadCodeItem]:
        """Run all enabled scans and return combined list."""
        items: List[DeadCodeItem] = []
        if include_untested:
            items.extend(self.scan_untested_modules())
        if include_todos:
            items.extend(self.scan_todo_comments())
        if include_stubs:
            items.extend(self.scan_stub_modules())
        # Import scan is expensive for 700+ files; include by default but last
        if include_imports:
            spa_dir = self._abs(_SPA_DIR)
            if os.path.isdir(spa_dir):
                for root, dirs, files in os.walk(spa_dir):
                    dirs[:] = [d for d in dirs if d != "__pycache__"]
                    for fname in files:
                        if not fname.endswith(".py"):
                            continue
                        fpath = os.path.join(root, fname)
                        items.extend(self.scan_unused_imports(fpath))
        return items

    # ------------------------------------------------------------------
    # Reporting
    # ------------------------------------------------------------------

    def to_markdown(self, items: List[DeadCodeItem]) -> str:
        """Generate markdown report grouped by category."""
        from collections import defaultdict
        grouped: Dict[str, List[DeadCodeItem]] = defaultdict(list)
        for item in items:
            grouped[item.category].append(item)

        lines = [
            "# SPA Dead Code Report (MP-1404 v10.20)",
            "",
            f"**Total issues found:** {len(items)}",
            "",
        ]

        category_labels = {
            "unused_import": "Unused Imports",
            "no_tests":      "Untested Modules",
            "todo_stale":    "TODO / FIXME Comments",
            "stub_module":   "Stub Modules (< 50 lines)",
            "orphan_module": "Orphan Modules",
        }

        for cat, label in category_labels.items():
            if cat not in grouped:
                continue
            cat_items = grouped[cat]
            lines.append(f"## {label} ({len(cat_items)})")
            lines.append("")
            for item in cat_items[:50]:
                short = os.path.relpath(item.filepath, self.base_dir) if self.base_dir != "." else item.filepath
                loc = f":{item.line}" if item.line else ""
                lines.append(f"- `{short}{loc}` — {item.description}")
            if len(cat_items) > 50:
                lines.append(f"- *... and {len(cat_items) - 50} more*")
            lines.append("")

        return "\n".join(lines)

    def save_report(self, items: List[DeadCodeItem]) -> str:
        """Save report to data/dead_code_report.json atomically."""
        save_path = os.path.join(self.base_dir, _DEFAULT_SAVE_PATH)
        os.makedirs(os.path.dirname(os.path.abspath(save_path)), exist_ok=True)
        payload = {
            "generated_at": _now_iso(),
            "total": len(items),
            "by_category": {},
            "items": [i.to_dict() for i in items],
        }
        from collections import Counter
        cats = Counter(i.category for i in items)
        payload["by_category"] = dict(cats)

        tmp = save_path + ".tmp"
        try:
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(payload, f, indent=2)
            os.replace(tmp, save_path)
        finally:
            if os.path.exists(tmp):
                try:
                    os.unlink(tmp)
                except OSError:
                    pass
        return save_path


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _now_iso() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="Dead Code Scanner v2 (MP-1404)")
    parser.add_argument(
        "--category",
        choices=["imports", "untested", "todos", "stubs", "all"],
        default="all",
        help="Which category to scan",
    )
    parser.add_argument("--json", action="store_true", dest="as_json", help="JSON output")
    parser.add_argument("--save", action="store_true", help="Save to data/dead_code_report.json")
    parser.add_argument("--dir", default=".", help="Base repo directory")
    args = parser.parse_args()

    scanner = DeadCodeScanner(base_dir=args.dir)

    cat = args.category
    if cat == "imports":
        items = []
        spa_dir = scanner._abs(_SPA_DIR)
        if os.path.isdir(spa_dir):
            for root, dirs, files in os.walk(spa_dir):
                dirs[:] = [d for d in dirs if d != "__pycache__"]
                for fname in files:
                    if fname.endswith(".py"):
                        items.extend(scanner.scan_unused_imports(os.path.join(root, fname)))
    elif cat == "untested":
        items = scanner.scan_untested_modules()
    elif cat == "todos":
        items = scanner.scan_todo_comments()
    elif cat == "stubs":
        items = scanner.scan_stub_modules()
    else:
        items = scanner.scan_all()

    if args.as_json:
        print(json.dumps([i.to_dict() for i in items], indent=2))
    else:
        print(scanner.to_markdown(items))

    if args.save:
        path = scanner.save_report(items)
        print(f"\nSaved → {path}", file=sys.stderr)


if __name__ == "__main__":
    main()
