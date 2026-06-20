"""
scripts/build_dependency_map.py

Scans spa_core/ and builds import dependency map.

Output:
  data/dependency_map.json — {module: [imports]}
  docs/DEPENDENCY_MAP.md   — human-readable table

Usage:
  python3 scripts/build_dependency_map.py
  python3 scripts/build_dependency_map.py --cycles   # detect circular imports
  python3 scripts/build_dependency_map.py --module spa_core.analytics.cpa_health_dashboard

MP-1373 (v9.89)
stdlib only. Read-only advisory. LLM FORBIDDEN.
"""

from __future__ import annotations

import argparse
import ast
import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Dict, List, Tuple
from spa_core.utils.atomic import atomic_save

# ── Repo-root resolution ──────────────────────────────────────────────────────

_SCRIPT_DIR = Path(__file__).resolve().parent
_REPO_ROOT = _SCRIPT_DIR.parent  # scripts/../ → repo root


# ── Core scanning functions ───────────────────────────────────────────────────

def scan_module(filepath: str) -> List[str]:
    """Extract 'from spa_core...' and 'import spa_core...' imports from a Python file.

    Args:
        filepath: Absolute or relative path to a .py file.

    Returns:
        Sorted list of fully-qualified module names that are imported
        from the spa_core namespace (e.g. ['spa_core.adapters.aave_v3']).
        Returns [] if the file has no spa_core imports or cannot be parsed.
    """
    try:
        with open(filepath, encoding="utf-8", errors="replace") as fh:
            source = fh.read()
    except OSError:
        return []

    try:
        tree = ast.parse(source, filename=filepath)
    except SyntaxError:
        return []

    imports: List[str] = []

    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            module = node.module or ""
            if module.startswith("spa_core"):
                imports.append(module)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.startswith("spa_core"):
                    # Take just the module part (no 'as' alias)
                    imports.append(alias.name)

    # Deduplicate and sort
    return sorted(set(imports))


def _filepath_to_module(filepath: str, base_dir: str) -> str:
    """Convert a filesystem path to a dotted module name.

    Example:
        spa_core/adapters/aave_v3.py → spa_core.adapters.aave_v3
    """
    path = Path(filepath)
    base = Path(base_dir)

    # Make relative to repo root (base_dir is spa_core/)
    try:
        rel = path.relative_to(base.parent)  # relative to repo root
    except ValueError:
        # Fall back: use the path relative to cwd
        rel = Path(os.path.relpath(filepath))

    parts = list(rel.parts)
    if parts and parts[-1].endswith(".py"):
        parts[-1] = parts[-1][:-3]  # strip .py
    if parts and parts[-1] == "__init__":
        parts = parts[:-1]

    return ".".join(parts)


def scan_all(base_dir: str = "spa_core") -> Dict[str, List[str]]:
    """Scan all Python files under base_dir and build dependency map.

    Args:
        base_dir: Directory to scan (relative or absolute path).

    Returns:
        {module_name: [imported_spa_core_modules]} for every .py file
        found under base_dir (excluding __pycache__ directories).
    """
    base_path = Path(base_dir)
    if not base_path.is_absolute():
        # Try relative to repo root first, then cwd
        candidate = _REPO_ROOT / base_dir
        if candidate.exists():
            base_path = candidate
        else:
            base_path = Path(os.getcwd()) / base_dir

    dep_map: Dict[str, List[str]] = {}

    for root, dirs, files in os.walk(base_path):
        # Skip __pycache__ and hidden directories
        dirs[:] = sorted(
            d for d in dirs
            if d != "__pycache__" and not d.startswith(".")
        )

        for fname in sorted(files):
            if not fname.endswith(".py"):
                continue

            fpath = os.path.join(root, fname)
            module_name = _filepath_to_module(fpath, str(base_path))
            imports = scan_module(fpath)
            dep_map[module_name] = imports

    return dep_map


# ── Cycle detection ───────────────────────────────────────────────────────────

def find_cycles(dep_map: Dict[str, List[str]]) -> List[List[str]]:
    """Detect circular import chains using iterative DFS.

    Args:
        dep_map: {module: [imported_modules]} mapping.

    Returns:
        List of cycles, where each cycle is a list of module names
        forming the circular chain (the first element equals the last).
        Returns [] if no cycles are found.
    """
    # Normalize imports to only include modules that appear in dep_map
    known = set(dep_map.keys())

    # Build adjacency: only edges within the known module set
    adj: Dict[str, List[str]] = {}
    for mod, imports in dep_map.items():
        adj[mod] = [imp for imp in imports if imp in known]

    # Tarjan-like DFS for cycle detection
    WHITE, GRAY, BLACK = 0, 1, 2
    color: Dict[str, int] = {m: WHITE for m in known}
    parent: Dict[str, str | None] = {m: None for m in known}
    cycles: List[List[str]] = []

    def _dfs(start: str) -> None:
        stack = [(start, iter(adj.get(start, [])))]
        path: List[str] = [start]
        color[start] = GRAY

        while stack:
            node, children = stack[-1]
            try:
                child = next(children)
                if color.get(child, BLACK) == GRAY:
                    # Found a back edge → reconstruct cycle
                    cycle_start = path.index(child)
                    cycle = path[cycle_start:] + [child]
                    # Deduplicate: use canonical form (smallest-index start)
                    canonical = tuple(sorted(
                        [tuple(cycle[i:] + cycle[:i])
                         for i in range(len(cycle) - 1)]
                    )[0]) + (cycle[0],)
                    if list(canonical) not in cycles:
                        cycles.append(list(canonical))
                elif color.get(child, BLACK) == WHITE:
                    color[child] = GRAY
                    parent[child] = node
                    path.append(child)
                    stack.append((child, iter(adj.get(child, []))))
            except StopIteration:
                color[node] = BLACK
                stack.pop()
                if path and path[-1] == node:
                    path.pop()

    for mod in sorted(known):
        if color[mod] == WHITE:
            _dfs(mod)

    return cycles


# ── Query helpers ─────────────────────────────────────────────────────────────

def modules_that_import(target: str, dep_map: Dict[str, List[str]]) -> List[str]:
    """Return list of modules that import the given target module.

    Args:
        target: Fully-qualified module name to look for.
        dep_map: {module: [imported_modules]} mapping.

    Returns:
        Sorted list of module names that list target in their imports.
    """
    return sorted(
        module for module, imports in dep_map.items()
        if target in imports
    )


def most_imported(
    dep_map: Dict[str, List[str]],
    top_n: int = 10,
) -> List[Tuple[str, int]]:
    """Return the most-imported modules, sorted by import count descending.

    Args:
        dep_map: {module: [imported_modules]} mapping.
        top_n:   Maximum number of results to return.

    Returns:
        [(module_name, import_count), ...] sorted descending by count.
    """
    counts: Dict[str, int] = {}
    for imports in dep_map.values():
        for imp in imports:
            counts[imp] = counts.get(imp, 0) + 1

    ranked = sorted(counts.items(), key=lambda x: (-x[1], x[0]))
    return ranked[:top_n]


# ── Reporting ─────────────────────────────────────────────────────────────────

def to_markdown(dep_map: Dict[str, List[str]]) -> str:
    """Build a human-readable Markdown table of the dependency map.

    Columns: Module | Depends On | Imported By

    Args:
        dep_map: {module: [imported_modules]} mapping.

    Returns:
        Markdown string with a summary header and a dependency table.
    """
    imported_by: Dict[str, List[str]] = {}
    for mod, imports in dep_map.items():
        for imp in imports:
            imported_by.setdefault(imp, []).append(mod)

    lines: List[str] = [
        "# SPA Module Dependency Map",
        "",
        f"Total modules scanned: **{len(dep_map)}**",
        "",
        "## Dependency Table",
        "",
        "| Module | Depends On (spa_core) | Imported By |",
        "|--------|----------------------|-------------|",
    ]

    for mod in sorted(dep_map.keys()):
        depends_on = dep_map[mod]
        imp_by = imported_by.get(mod, [])

        depends_str = (
            "<br>".join(f"`{d}`" for d in sorted(depends_on))
            if depends_on else "—"
        )
        imp_by_str = (
            "<br>".join(f"`{d}`" for d in sorted(imp_by))
            if imp_by else "—"
        )

        lines.append(f"| `{mod}` | {depends_str} | {imp_by_str} |")

    # Most-imported section
    top = most_imported(dep_map, top_n=10)
    if top:
        lines += [
            "",
            "## Most Imported Modules (Top 10)",
            "",
            "| Module | Import Count |",
            "|--------|-------------|",
        ]
        for mod, cnt in top:
            lines.append(f"| `{mod}` | {cnt} |")

    return "\n".join(lines) + "\n"


# ── Persistence ───────────────────────────────────────────────────────────────

def save(
    dep_map: Dict[str, List[str]],
    path: str = "data/dependency_map.json",
) -> str:
    """Atomically write dep_map as JSON.

    Args:
        dep_map: {module: [imported_modules]} mapping.
        path:    Output file path (relative to repo root or absolute).

    Returns:
        Absolute path where the file was written.
    """
    out_path = Path(path)
    if not out_path.is_absolute():
        out_path = _REPO_ROOT / path

    out_path.parent.mkdir(parents=True, exist_ok=True)

    payload = {
        "generated_at": _now_iso(),
        "total_modules": len(dep_map),
        "dependency_map": dep_map,
    }

    atomic_save(payload, str(out_path))
    return str(out_path)


def _now_iso() -> str:
    """Return current UTC timestamp in ISO-8601 format."""
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()


# ── CLI ───────────────────────────────────────────────────────────────────────

def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Build import dependency map for spa_core/",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--cycles",
        action="store_true",
        help="Detect and print circular import chains",
    )
    parser.add_argument(
        "--module",
        metavar="MODULE",
        help="Show who imports this module and what it imports",
    )
    parser.add_argument(
        "--base-dir",
        default="spa_core",
        help="Directory to scan (default: spa_core)",
    )
    parser.add_argument(
        "--output",
        default="data/dependency_map.json",
        help="JSON output path (default: data/dependency_map.json)",
    )
    parser.add_argument(
        "--md-output",
        default="docs/DEPENDENCY_MAP.md",
        help="Markdown output path (default: docs/DEPENDENCY_MAP.md)",
    )
    parser.add_argument(
        "--no-save",
        action="store_true",
        help="Print results only, do not write files",
    )
    return parser


def main() -> None:
    parser = _build_parser()
    args = parser.parse_args()

    print(f"[build_dependency_map] Scanning {args.base_dir!r} …", flush=True)
    dep_map = scan_all(args.base_dir)
    print(f"  Found {len(dep_map)} modules", flush=True)

    if args.module:
        target = args.module
        dependents = dep_map.get(target, [])
        importers = modules_that_import(target, dep_map)
        print(f"\nModule: {target}")
        print(f"  Depends on ({len(dependents)}):")
        for d in dependents:
            print(f"    {d}")
        print(f"  Imported by ({len(importers)}):")
        for i in importers:
            print(f"    {i}")

    if args.cycles:
        print("\n[cycle detection] Running DFS …", flush=True)
        cycles = find_cycles(dep_map)
        if cycles:
            print(f"  ⚠️  Found {len(cycles)} circular import chain(s):")
            for i, cycle in enumerate(cycles, 1):
                print(f"    {i}. {' → '.join(cycle)}")
        else:
            print("  ✅  No circular imports detected")

    top = most_imported(dep_map, top_n=10)
    print("\nTop imported modules:")
    for mod, cnt in top:
        print(f"  {cnt:4d}×  {mod}")

    if not args.no_save:
        json_path = save(dep_map, args.output)
        print(f"\nSaved JSON → {json_path}", flush=True)

        md_content = to_markdown(dep_map)
        md_path = Path(args.md_output)
        if not md_path.is_absolute():
            md_path = _REPO_ROOT / args.md_output
        md_path.parent.mkdir(parents=True, exist_ok=True)

        tmp_fd, tmp_path = tempfile.mkstemp(
            dir=str(md_path.parent), suffix=".tmp"
        )
        try:
            with os.fdopen(tmp_fd, "w", encoding="utf-8") as fh:
                fh.write(md_content)
            os.replace(tmp_path, str(md_path))
        except Exception:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise
        print(f"Saved MD  → {md_path}", flush=True)


if __name__ == "__main__":
    main()
