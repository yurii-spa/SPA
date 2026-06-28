"""
spa_core.database.migrate_callsites — BL-008 Phase 2 verification utility.

Scans the spa_core source tree for raw ``sqlite3.connect`` *calls* (AST-level)
that should have been migrated to
``spa_core.database.connection.get_connection``.

AST parsing is used so that the pattern occurring only in comments or string
literals (including this file's own docstrings) is never reported as a hit.

Usage (CLI):
    python3 -m spa_core.database.migrate_callsites

Exit codes:
    0 — no raw connects found (Phase 2 complete)
    1 — raw connects remain (migration incomplete)

Excluded from scan (intentionally keep raw sqlite3):
    * ``spa_core/database/connection.py`` — the abstraction itself
    * ``spa_core/persistence/pg_migration.py`` — migration utility, both backends
    * ``spa_core/persistence/track_store.py`` — scratch DBs, intentionally raw
    * Any file under ``spa_core/tests/`` — test helpers may use raw sqlite3
"""
from __future__ import annotations

import ast
import os
import sys
from pathlib import Path
from typing import List, Tuple

# ─── Constants ───────────────────────────────────────────────────────────────

#: Root of the spa_core package relative to this file.
_SPA_CORE_ROOT = Path(__file__).resolve().parent.parent  # → spa_core/

#: Files whose raw sqlite3.connect calls are intentional and must be
#: excluded from the scan.
_EXCLUDED_FILES: frozenset[str] = frozenset(
    {
        "spa_core/database/connection.py",
        "spa_core/database/sqlite_manager.py",  # abstraction layer — uses sqlite3 directly by design
        "spa_core/persistence/pg_migration.py",
        "spa_core/persistence/track_store.py",
        # dr_backup.py uses the SQLite-native online .backup() API + `mode=ro` URI to snapshot and
        # integrity-verify a (possibly mid-write) track.db. That API and the read-only URI only
        # exist on raw sqlite3 connections — it cannot route through the postgres-capable abstraction.
        "spa_core/backtesting/tier1/dr_backup.py",
    }
)

#: Inline opt-out marker. A ``sqlite3.connect(...)`` call on a line carrying this
#: comment is an INTENTIONAL sqlite-native call (e.g. a ``PRAGMA integrity_check``
#: on the local mirror, which has no postgres equivalent). Finer-grained than a
#: whole-file exclusion so the rest of the file stays under scrutiny.
_ALLOW_MARKER = "allow-raw-sqlite-connect"

#: Directory subtrees that should never be scanned (tests, caches, etc.).
_EXCLUDED_DIRS: frozenset[str] = frozenset(
    {
        "spa_core/tests",
        "spa_core/__pycache__",
    }
)


# ─── Public API ──────────────────────────────────────────────────────────────


def _sqlite_connect_linenos(source: str) -> List[int]:
    """Return line numbers of actual ``sqlite3.connect(...)`` AST call nodes.

    Uses Python's ``ast`` module so that occurrences inside comments or string
    literals are never reported.

    Returns an empty list if the source cannot be parsed (syntax errors, etc.).
    """
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return []

    src_lines = source.splitlines()

    def _is_allowed(lineno: int) -> bool:
        # 1-based lineno → 0-based index; an inline marker exempts that line.
        if 1 <= lineno <= len(src_lines):
            return _ALLOW_MARKER in src_lines[lineno - 1]
        return False

    hits: List[int] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if (
            isinstance(func, ast.Attribute)
            and func.attr == "connect"
            and isinstance(func.value, ast.Name)
            and func.value.id == "sqlite3"
            and not _is_allowed(node.lineno)
        ):
            hits.append(node.lineno)
    return hits


def find_raw_sqlite_connects(
    scan_dir: str | Path | None = None,
) -> List[Tuple[str, int, str]]:
    """Search *scan_dir* for ``sqlite3.connect(...)`` call-sites at the AST level.

    Parameters
    ----------
    scan_dir:
        Directory to scan.  Defaults to the ``spa_core/`` package root derived
        from this file's location.

    Returns
    -------
    list of ``(relative_path, line_number, stripped_line)`` tuples for every
    call node that is not excluded by :data:`_EXCLUDED_FILES` or
    :data:`_EXCLUDED_DIRS`.  Only real Python call expressions are detected —
    occurrences in comments or string literals are ignored.
    """
    root = Path(scan_dir).resolve() if scan_dir is not None else _SPA_CORE_ROOT
    # The "repo root" is the parent of spa_core/ so relative paths look like
    # "spa_core/database/init_db.py".
    repo_root = root.parent

    results: List[Tuple[str, int, str]] = []

    for dirpath, dirnames, filenames in os.walk(root):
        dir_obj = Path(dirpath)
        rel_dir = dir_obj.relative_to(repo_root).as_posix()

        # Prune excluded directories in-place so os.walk skips them.
        dirnames[:] = [
            d for d in dirnames
            if not _is_excluded_dir(rel_dir + "/" + d)
        ]

        for fname in filenames:
            if not fname.endswith(".py"):
                continue
            rel_file = (dir_obj / fname).relative_to(repo_root).as_posix()
            if _is_excluded_file(rel_file):
                continue

            abs_file = dir_obj / fname
            try:
                source = abs_file.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue

            hit_lines = _sqlite_connect_linenos(source)
            if not hit_lines:
                continue

            # Retrieve the actual source lines for reporting.
            src_lines = source.splitlines()
            for lineno in hit_lines:
                line_text = src_lines[lineno - 1].strip() if lineno <= len(src_lines) else ""
                results.append((rel_file, lineno, line_text))

    return results


def run_verification(scan_dir: str | Path | None = None) -> dict:
    """Run a full verification pass and return a summary dict.

    Returns
    -------
    ``{"ok": bool, "raw_connects_remaining": int, "files_checked": int,
       "hits": list[dict]}``

    ``ok`` is ``True`` iff ``raw_connects_remaining == 0``.
    """
    root = Path(scan_dir).resolve() if scan_dir is not None else _SPA_CORE_ROOT
    repo_root = root.parent

    # Count how many .py files were checked.
    files_checked = 0
    for dirpath, dirnames, filenames in os.walk(root):
        dir_obj = Path(dirpath)
        rel_dir = dir_obj.relative_to(repo_root).as_posix()
        dirnames[:] = [
            d for d in dirnames
            if not _is_excluded_dir(rel_dir + "/" + d)
        ]
        for fname in filenames:
            if not fname.endswith(".py"):
                continue
            rel_file = (dir_obj / fname).relative_to(repo_root).as_posix()
            if not _is_excluded_file(rel_file):
                files_checked += 1

    hits = find_raw_sqlite_connects(scan_dir)
    return {
        "ok": len(hits) == 0,
        "raw_connects_remaining": len(hits),
        "files_checked": files_checked,
        "hits": [
            {"file": h[0], "line": h[1], "text": h[2]} for h in hits
        ],
    }


# ─── Internal helpers ────────────────────────────────────────────────────────


def _is_excluded_file(rel_path: str) -> bool:
    """Return True if *rel_path* matches one of the exclusion rules."""
    # Exact file exclusions.
    if rel_path in _EXCLUDED_FILES:
        return True
    # Test directory exclusion.
    for excl_dir in _EXCLUDED_DIRS:
        if rel_path.startswith(excl_dir + "/") or rel_path == excl_dir:
            return True
    return False


def _is_excluded_dir(rel_dir: str) -> bool:
    """Return True if *rel_dir* is an excluded directory or sub-directory."""
    for excl in _EXCLUDED_DIRS:
        if rel_dir == excl or rel_dir.startswith(excl + "/"):
            return True
    return False


# ─── CLI entry-point ─────────────────────────────────────────────────────────


def _main() -> int:  # pragma: no cover
    result = run_verification()
    remaining = result["raw_connects_remaining"]
    files_checked = result["files_checked"]

    print(f"BL-008 Phase 2 — call-site migration verification")
    print(f"  Files checked : {files_checked}")
    print(f"  Raw connects  : {remaining}")

    if remaining == 0:
        print("  Status        : ✓ Phase 2 complete — no raw sqlite3.connect() found")
        return 0

    print(f"  Status        : ✗ {remaining} raw sqlite3.connect() call(s) still present:")
    for hit in result["hits"]:
        print(f"    {hit['file']}:{hit['line']}  {hit['text']}")
    return 1


if __name__ == "__main__":
    sys.exit(_main())
