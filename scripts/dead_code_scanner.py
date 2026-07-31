#!/usr/bin/env python3
"""
scripts/dead_code_scanner.py

Scans for dead code patterns in the SPA codebase.

Dead code categories:
1. unused_import   — imports defined but not referenced in the same file
                     (NOT counted: `__future__` directives, `__all__` re-exports,
                      string forward-ref annotations, `if TYPE_CHECKING:` imports
                      — see scan_unused_imports)
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
from collections import deque
from dataclasses import dataclass, asdict, field
from typing import Dict, List, Optional, Set, Tuple

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


def _collect_exported_names(tree: ast.AST) -> Set[str]:
    """
    Return names listed in a module-level ``__all__``.

    A re-export IS a use: ``from .x import Y`` + ``__all__ = ["Y"]`` is the
    documented way to publish ``Y`` as part of the package API. This mirrors
    pyflakes, which suppresses F401 for names present in ``__all__``
    (see ``scripts/tests/test_unused_import_ratchet.py`` — the money-path
    ratchet built on pyflakes relies on exactly this convention).
    """
    return _collect_file_facts(tree).exported


def _harvest_annotation_strings(node: ast.AST, out: Set[str]) -> None:
    """Recursively pull names out of STRING parts of an annotation expression."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        try:
            sub = ast.parse(node.value, mode="eval")
        except (SyntaxError, ValueError):
            return
        for inner in ast.walk(sub):
            if isinstance(inner, ast.Name):
                out.add(inner.id)
            elif isinstance(inner, ast.Attribute):
                root: ast.AST = inner
                while isinstance(root, ast.Attribute):
                    root = root.value
                if isinstance(root, ast.Name):
                    out.add(root.id)
    elif isinstance(node, ast.Subscript):
        _harvest_annotation_strings(node.value, out)
        _harvest_annotation_strings(node.slice, out)
    elif isinstance(node, (ast.Tuple, ast.List)):
        for elt in node.elts:
            _harvest_annotation_strings(elt, out)
    elif isinstance(node, ast.BinOp):
        _harvest_annotation_strings(node.left, out)
        _harvest_annotation_strings(node.right, out)


def _collect_string_annotation_names(tree: ast.AST) -> Set[str]:
    """
    Return names referenced from STRING annotations (PEP 484 forward references).

    ``def f() -> "Foo": ...`` parses the annotation as a str *constant*, so plain
    ``ast.Name`` collection never sees ``Foo`` — yet the import of ``Foo`` is used.
    Only annotation positions are inspected; arbitrary docstrings are NOT, because
    a name mentioned in prose is a coincidence, not a use.
    """
    return _collect_file_facts(tree).annotation_names


def _collect_type_checking_imports(tree: ast.AST) -> Set[str]:
    """
    Return local names imported inside an ``if TYPE_CHECKING:`` block.

    Such imports exist purely for type checkers and are, by construction, meant
    to be referenced only from annotations. The module docstring has always
    claimed these are skipped — this makes the claim true.
    """
    return _collect_file_facts(tree).type_checking


def _collect_names_used(tree: ast.AST, imported_names: List[str]) -> Set[str]:
    """Collect all Name / Attribute nodes to find which imports are referenced."""
    return _collect_file_facts(tree).used


# ---------------------------------------------------------------------------
# One traversal per file (was: five)
# ---------------------------------------------------------------------------

def _is_type_checking_guard(test: ast.AST) -> bool:
    """True for ``if TYPE_CHECKING:`` / ``if typing.TYPE_CHECKING:`` tests."""
    return (
        (isinstance(test, ast.Name) and test.id == "TYPE_CHECKING")
        or (isinstance(test, ast.Attribute) and test.attr == "TYPE_CHECKING")
    )


def _imported_names_in(node: ast.AST) -> Set[str]:
    """Local names bound by any import statement in ``node``'s subtree."""
    names: Set[str] = set()
    for sub in ast.walk(node):
        if isinstance(sub, ast.Import):
            names.update(_extract_import_names(sub))
        elif isinstance(sub, ast.ImportFrom):
            names.update(_extract_from_import_names(sub))
    return names


@dataclass
class _FileFacts:
    """Everything the unused-import heuristic needs from one module's AST."""

    imports: List[Tuple[int, str]] = field(default_factory=list)  # (lineno, local name)
    type_checking: Set[str] = field(default_factory=set)
    used: Set[str] = field(default_factory=set)
    exported: Set[str] = field(default_factory=set)
    annotation_names: Set[str] = field(default_factory=set)


def _collect_file_facts(tree: ast.AST) -> _FileFacts:
    """Gather every fact the import heuristic needs in a SINGLE tree traversal.

    ── 2026-07-31, cycle #60 — a speed fix, NOT a semantics change ─────────────
    The heuristic used to walk each file five times (``TYPE_CHECKING`` imports,
    import statements, referenced names, ``__all__``, string annotations). At
    3006 files under ``spa_core`` those walks measured **10.95s of the scanner's
    15.47s** on the host — and on a GitHub runner (~2x slower) the whole scan
    ran past the ``timeout=30`` of ``tests/test_dead_code_resolved.py``, which
    left ``main`` red for five cycles (card
    ``agent-task-ci-na-main-krasnyi-s-06-23z-skaner-mertv``).

    The traversal below is deliberately ``ast.walk``'s own algorithm — a FIFO
    queue, i.e. breadth-first — so the *order* in which imports are reported is
    byte-for-byte what five separate ``ast.walk`` calls produced. Nothing is
    counted, skipped, or ranked differently: the four exclusions documented in
    ``scan_unused_imports`` are computed from exactly the same nodes as before.
    The single-name helpers above are kept as thin wrappers over this function
    rather than as second copies of the logic — a twin implementation is how
    cycle #37 left a fixed bug alive in a sibling.
    """
    facts = _FileFacts()
    todo: deque = deque([tree])
    while todo:
        node = todo.popleft()
        todo.extend(ast.iter_child_nodes(node))

        # --- import statements + `if TYPE_CHECKING:` blocks ------------------
        if isinstance(node, ast.Import):
            for name in _extract_import_names(node):
                facts.imports.append((node.lineno, name))
        elif isinstance(node, ast.ImportFrom):
            if node.module != "__future__":  # compiler directive — never a name
                for name in _extract_from_import_names(node):
                    facts.imports.append((node.lineno, name))
        elif isinstance(node, ast.If) and _is_type_checking_guard(node.test):
            facts.type_checking |= _imported_names_in(node)

        # --- referenced names -------------------------------------------------
        if isinstance(node, ast.Name):
            facts.used.add(node.id)
        elif isinstance(node, ast.Attribute):
            # Catch dotted access like `os.path`
            root: ast.AST = node
            while isinstance(root, ast.Attribute):
                root = root.value
            if isinstance(root, ast.Name):
                facts.used.add(root.id)

        # --- module-level `__all__` re-exports ---------------------------------
        if isinstance(node, (ast.Assign, ast.AugAssign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            if any(isinstance(t, ast.Name) and t.id == "__all__" for t in targets):
                value = getattr(node, "value", None)
                if isinstance(value, (ast.List, ast.Tuple, ast.Set)):
                    for elt in value.elts:
                        if isinstance(elt, ast.Constant) and isinstance(elt.value, str):
                            facts.exported.add(elt.value)

        # --- names hiding inside STRING annotations (forward refs) -------------
        if isinstance(node, (ast.AnnAssign, ast.arg)):
            if node.annotation is not None:
                _harvest_annotation_strings(node.annotation, facts.annotation_names)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if node.returns is not None:
                _harvest_annotation_strings(node.returns, facts.annotation_names)

    return facts


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
        Skips `from X import *`.

        Four things are deliberately NOT counted, because in each of them the
        import is used (or cannot possibly be "referenced") — counting them made
        the number mean something other than what it promises (2026-07-31, cycle
        #52, card ``agent-unused-import-ceiling-at-its-limit``; measured shares of
        the then-current 4049: `__future__` 1753, `__all__` 137, string
        annotations 4, TYPE_CHECKING 1 — 1895 in total, 4049 → 2154, with zero
        items ADDED, i.e. this can only ever drop a false positive):

          * ``from __future__ import ...`` — a compiler directive, never a name
            the code can mention. It was 43% of the whole count, and it grew by
            one with every new module that opted into modern annotations.
          * names listed in ``__all__`` — a re-export IS the use (pyflakes does
            the same, see ``_collect_exported_names``).
          * names referenced from STRING annotations (forward refs) — the AST
            holds them as str constants, not ``ast.Name``.
          * imports inside ``if TYPE_CHECKING:`` — existed only for annotations;
            the docstring already claimed they were skipped, now they are.
        """
        try:
            with open(filepath, "r", encoding="utf-8", errors="replace") as f:
                source = f.read()
            tree = ast.parse(source, filename=filepath)
        except (SyntaxError, OSError):
            return []

        facts = _collect_file_facts(tree)

        import_nodes: List[tuple] = [
            (line, name) for (line, name) in facts.imports
            if name not in facts.type_checking
        ]

        if not import_nodes:
            return []

        used = facts.used | facts.exported | facts.annotation_names

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
