#!/usr/bin/env python3
"""
scripts/migrate_atomic_writes.py

Migrates local _atomic_write patterns to spa_core.utils.atomic.

Detects patterns:
  1. tmp = path + ".tmp"; open(tmp, "w"); os.replace(tmp, path)
  2. _write_json(data, path) local function
  3. def _atomic_save(data, path): ...
  4. def _save_json(data, path): ...
  5. def _atomic_write(path, data): ...

Usage:
  python3 scripts/migrate_atomic_writes.py --scan      # show affected files
  python3 scripts/migrate_atomic_writes.py --dry-run   # show what would change
  python3 scripts/migrate_atomic_writes.py --apply     # apply changes
  python3 scripts/migrate_atomic_writes.py --module spa_core/analytics/foo.py
"""
import re
import os
import sys
import json
import argparse
from pathlib import Path
from typing import Optional
# stdlib contract guard integration
try:
    from stdlib_contract_guard import is_stdlib_contract as _is_stdlib_contract
except ImportError:
    def _is_stdlib_contract(filepath):
        return False


# ---------------------------------------------------------------------------
# Detection patterns (regex, applied line-by-line or on full source)
# ---------------------------------------------------------------------------

PATTERNS = [
    r'tmp\s*=\s*.+\+\s*["\']\.tmp["\']',                          # tmp = path + ".tmp"
    r'def\s+_(?:atomic_save|write_json|atomic_write|save_json)',   # local def variants
    r'os\.replace\(tmp,\s*\S+\)',                                  # os.replace(tmp, ...)
    r'tempfile\.mkstemp\(',                                        # tempfile usage (local copy)
]

# Pattern to detect already-migrated files
ALREADY_MIGRATED_PATTERN = re.compile(
    r'from\s+spa_core\.utils\.atomic\s+import|'
    r'from\s+spa_core\.utils\s+import\s+atomic'
)

# Compiled detection regexes
_COMPILED = [re.compile(p) for p in PATTERNS]

# Local function names we can replace
_LOCAL_DEF_RE = re.compile(
    r'^def\s+(_atomic_write|_atomic_save|_write_json|_save_json)\s*\('
    r'([^)]*)\)\s*:',
    re.MULTILINE,
)

# The import line we inject
IMPORT_LINE = "from spa_core.utils.atomic import atomic_save, atomic_load\n"


# ---------------------------------------------------------------------------
# Core helpers
# ---------------------------------------------------------------------------

def _read_source(filepath: str) -> Optional[str]:
    """Reads file source, returns None on error."""
    try:
        with open(filepath, "r", encoding="utf-8", errors="replace") as fh:
            return fh.read()
    except (OSError, IOError):
        return None


def _has_local_pattern(source: str) -> bool:
    """Returns True if source contains at least one migration-relevant pattern."""
    for rx in _COMPILED:
        if rx.search(source):
            return True
    return False


def _find_patterns(source: str) -> list:
    """Returns list of pattern descriptions found in source."""
    found = []
    for i, rx in enumerate(_COMPILED):
        matches = rx.findall(source)
        if matches:
            found.append(PATTERNS[i])
    return found


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def scan_file(filepath: str) -> dict:
    """
    Scans a single Python file for atomic-write patterns.

    Returns:
        {
            "filepath": str,
            "has_pattern": bool,
            "already_migrated": bool,
            "patterns_found": list[str],   # matched pattern strings
            "local_defs": list[str],        # local function names found
            "lines": list[int],             # 1-based line numbers with matches
        }
    """
    result = {
        "filepath": filepath,
        "has_pattern": False,
        "already_migrated": False,
        "patterns_found": [],
        "local_defs": [],
        "lines": [],
    }

    source = _read_source(filepath)
    if source is None:
        return result

    # Check already migrated
    if ALREADY_MIGRATED_PATTERN.search(source):
        result["already_migrated"] = True

    # Check patterns
    patterns_found = _find_patterns(source)
    if patterns_found:
        result["has_pattern"] = True
        result["patterns_found"] = patterns_found

        # Collect matching line numbers
        for i, line in enumerate(source.splitlines(), start=1):
            for rx in _COMPILED:
                if rx.search(line):
                    if i not in result["lines"]:
                        result["lines"].append(i)

    # Collect local def names
    for m in _LOCAL_DEF_RE.finditer(source):
        fname = m.group(1)
        if fname not in result["local_defs"]:
            result["local_defs"].append(fname)

    return result


def scan_all(base_dir: str = "spa_core") -> list:
    """
    Recursively scans base_dir for Python files with atomic-write patterns.

    Returns:
        list of file paths (str) that need migration.
    """
    affected = []
    base = Path(base_dir)
    if not base.exists():
        return affected

    for py_file in sorted(base.rglob("*.py")):
        filepath = str(py_file)
        # Skip stdlib contract files
        if _is_stdlib_contract(filepath):
            print(f"  [SKIP] stdlib contract: {filepath}")
            continue
        result = scan_file(filepath)
        if result["has_pattern"] and not result["already_migrated"]:
            affected.append(filepath)

    return affected


def generate_migration(filepath: str) -> str:
    """
    Returns suggested migration patch as a human-readable string.
    Shows the import line to add and lists local defs to remove.
    Does NOT write to file.

    Returns "" if file cannot be read or has no patterns.
    """
    source = _read_source(filepath)
    if source is None:
        return ""

    result = scan_file(filepath)
    if not result["has_pattern"]:
        return ""

    lines = []
    lines.append(f"# Migration suggestion for: {filepath}")
    lines.append("")
    lines.append("# 1. Add this import (if not present):")
    lines.append(f"   {IMPORT_LINE.rstrip()}")
    lines.append("")

    if result["local_defs"]:
        lines.append("# 2. Remove local function definitions:")
        for fname in result["local_defs"]:
            lines.append(f"   def {fname}(...): ...  → delete, use atomic_save() instead")
        lines.append("")

    lines.append("# 3. Replace calls:")
    lines.append("   _write_json(data, path)   → atomic_save(data, path)")
    lines.append("   _atomic_write(path, data) → atomic_save(data, path)")
    lines.append("   _atomic_save(data, path)  → atomic_save(data, path)")
    lines.append("   _save_json(data, path)    → atomic_save(data, path)")
    lines.append("")
    lines.append(f"# Lines with patterns: {result['lines'][:20]}")

    return "\n".join(lines)


def apply_migration(filepath: str, dry_run: bool = True) -> bool:
    """
    Applies migration to a single file:
      - Adds import from spa_core.utils.atomic
      - Replaces local function definitions with a stub comment
      - Replaces call-sites of local defs

    Args:
        filepath: Path to .py file.
        dry_run:  If True, prints diff but does NOT write.

    Returns:
        True if migration was applied (or would be in dry_run).
        False if file has no patterns or cannot be processed.
    """
    source = _read_source(filepath)
    if source is None:
        return False

    result = scan_file(filepath)
    if not result["has_pattern"]:
        return False

    # Already migrated → skip
    if result["already_migrated"]:
        if dry_run:
            print(f"[SKIP] {filepath} — already uses spa_core.utils.atomic")
        return False

    new_source = source

    # Step 1: add import after last existing import block or at top
    if IMPORT_LINE.strip() not in new_source:
        # Find insertion point: after last "import " line in header
        lines = new_source.splitlines(keepends=True)
        insert_at = 0
        for i, line in enumerate(lines):
            stripped = line.lstrip()
            if stripped.startswith("import ") or stripped.startswith("from "):
                insert_at = i + 1
            elif stripped and not stripped.startswith("#") and insert_at > 0:
                break
        lines.insert(insert_at, IMPORT_LINE)
        new_source = "".join(lines)

    # Step 2: replace local def bodies
    # We do a simple approach: comment out the def and insert a delegation comment
    def _replace_local_def(m: re.Match) -> str:
        fname = m.group(1)
        return (
            f"# MIGRATED: {fname} → use atomic_save / atomic_load from spa_core.utils.atomic\n"
            f"# Original signature: def {fname}({m.group(2)}):\n"
            f"#   (body removed — call atomic_save(data, path) directly)\n"
        )

    new_source = _LOCAL_DEF_RE.sub(_replace_local_def, new_source)

    # Step 3: replace call sites (only the function-call pattern, not def lines)
    _call_patterns = [
        (re.compile(r'\b_write_json\s*\(([^,)]+),\s*([^)]+)\)'), r'atomic_save(\1, \2)'),
        (re.compile(r'\b_atomic_save\s*\(([^,)]+),\s*([^)]+)\)'), r'atomic_save(\1, \2)'),
        (re.compile(r'\b_save_json\s*\(([^,)]+),\s*([^)]+)\)'), r'atomic_save(\1, \2)'),
        (re.compile(r'\b_atomic_write\s*\(([^,)]+),\s*([^)]+)\)'), r'atomic_save(\2, \1)'),
    ]
    for rx, repl in _call_patterns:
        new_source = rx.sub(repl, new_source)

    if new_source == source:
        if dry_run:
            print(f"[NO-CHANGE] {filepath} — patterns detected but no automatic substitution possible")
        return False

    if dry_run:
        # Print unified-style diff summary
        orig_lines = source.splitlines()
        new_lines = new_source.splitlines()
        print(f"\n--- {filepath} (dry-run) ---")
        changed = [(i, o, n) for i, (o, n) in enumerate(zip(orig_lines, new_lines), 1) if o != n]
        added_count = len(new_lines) - len(orig_lines)
        print(f"  Lines changed: {len(changed)}, net new lines: {added_count}")
        for ln, old, new in changed[:5]:
            print(f"  Line {ln}:")
            print(f"    - {old}")
            print(f"    + {new}")
        if len(changed) > 5:
            print(f"  ... ({len(changed) - 5} more changes)")
        return True

    # Atomic write (using stdlib only — no self-referential import yet)
    import tempfile
    dir_ = os.path.dirname(os.path.abspath(filepath)) or "."
    fd, tmp = tempfile.mkstemp(dir=dir_, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(new_source)
        os.replace(tmp, filepath)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise

    print(f"[MIGRATED] {filepath}")
    return True


def migration_report(files: list) -> dict:
    """
    Generates a summary report for a list of file paths.

    Returns:
        {
            "total_files": int,
            "already_using_utils": int,
            "needs_migration": int,
            "skipped": int,          # files that couldn't be read
            "local_defs_found": dict, # {fname: count}
            "patterns_summary": dict, # {pattern: count}
        }
    """
    report = {
        "total_files": len(files),
        "already_using_utils": 0,
        "needs_migration": 0,
        "skipped": 0,
        "local_defs_found": {},
        "patterns_summary": {},
    }

    for filepath in files:
        result = scan_file(filepath)

        if result["filepath"] and _read_source(filepath) is None:
            report["skipped"] += 1
            continue

        if result["already_migrated"]:
            report["already_using_utils"] += 1
        elif result["has_pattern"]:
            report["needs_migration"] += 1

        for fname in result["local_defs"]:
            report["local_defs_found"][fname] = report["local_defs_found"].get(fname, 0) + 1

        for pattern in result["patterns_found"]:
            report["patterns_summary"][pattern] = report["patterns_summary"].get(pattern, 0) + 1

    return report


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _collect_py_files(base_dir: str) -> list:
    """Returns all .py files under base_dir."""
    result = []
    base = Path(base_dir)
    if base.exists():
        for f in sorted(base.rglob("*.py")):
            result.append(str(f))
    return result


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Migrate local _atomic_write patterns → spa_core.utils.atomic"
    )
    parser.add_argument("--scan", action="store_true",
                        help="Show all files with patterns (no changes)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Show what would change without writing")
    parser.add_argument("--apply", action="store_true",
                        help="Apply migrations to affected files")
    parser.add_argument("--module", metavar="PATH",
                        help="Operate on a single file instead of scan_all")
    parser.add_argument("--base-dir", default="spa_core",
                        help="Base directory for scan (default: spa_core)")
    parser.add_argument("--report", action="store_true",
                        help="Print JSON migration report")
    args = parser.parse_args(argv)

    if args.module:
        files = [args.module]
    else:
        if args.scan or args.dry_run or args.apply:
            files = scan_all(args.base_dir)
        else:
            files = _collect_py_files(args.base_dir)

    if args.scan:
        print(f"Files with migration-relevant patterns ({len(files)}):")
        for f in files:
            print(f"  {f}")
        return 0

    if args.report:
        rpt = migration_report(files)
        print(json.dumps(rpt, indent=2))
        return 0

    if args.dry_run:
        print(f"DRY RUN — {len(files)} files to process\n")
        applied = 0
        for f in files:
            # Skip stdlib contract files
            if _is_stdlib_contract(f):
                print(f"  [SKIP] stdlib contract: {f}")
                continue
            if apply_migration(f, dry_run=True):
                applied += 1
        print(f"\nWould migrate: {applied}/{len(files)} files")
        return 0

    if args.apply:
        print(f"APPLY — {len(files)} files\n")
        applied = 0
        for f in files:
            # Skip stdlib contract files
            if _is_stdlib_contract(f):
                print(f"  [SKIP] stdlib contract: {f}")
                continue
            if apply_migration(f, dry_run=False):
                applied += 1
        print(f"\nMigrated: {applied}/{len(files)} files")
        return 0

    # Default: show report
    rpt = migration_report(files)
    print("Migration Report")
    print(f"  Total files scanned:    {rpt['total_files']}")
    print(f"  Already using utils:    {rpt['already_using_utils']}")
    print(f"  Needs migration:        {rpt['needs_migration']}")
    print(f"  Skipped (unreadable):   {rpt['skipped']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
