#!/usr/bin/env python3
"""
scripts/lint_kanban_usage.py

Finds scripts that write KANBAN.json without using the approved
safe helpers (spa_core/utils/kanban.py or save_kanban_atomic pattern).

A violation is flagged when a file:
  1. References "KANBAN.json" (meaning it touches the file), AND
  2. Contains a direct write pattern (open+w, json.dump to KANBAN, etc.)
     WITHOUT importing the approved helper.

Safe patterns (NOT flagged):
  - from spa_core.utils.kanban import increment_done
  - import kanban_health
  - kanban_health.save_kanban
  - save_kanban_atomic

Usage:
  python3 scripts/lint_kanban_usage.py             # scan repo root
  python3 scripts/lint_kanban_usage.py --dir /path # scan custom dir
  python3 scripts/lint_kanban_usage.py --quiet     # only print violations
"""
import os
import re
import sys
from typing import Optional


# ─────────────────────────────────────────────
# Patterns
# ─────────────────────────────────────────────

# Patterns indicating a direct, potentially unsafe write to KANBAN
VIOLATION_PATTERNS = [
    # open("KANBAN.json", "w")  or  open('KANBAN.json','w')
    re.compile(r'open\s*\(\s*["\']KANBAN\.json["\'].*["\']w["\']', re.IGNORECASE),
    # json.dump(...) followed later on the same line by "KANBAN"
    re.compile(r'json\.dump\b.*KANBAN', re.IGNORECASE),
    # Direct key assignment like k["done_count"] = X  near "KANBAN" context
    # We catch this only when KANBAN.json is also referenced in the same file
    re.compile(r'k\s*\[\s*["\']done_count["\']\s*\]\s*=\s*\d'),
    # shell: echo/printf to KANBAN.json
    re.compile(r'(?:echo|printf)\b.*>\s*KANBAN\.json', re.IGNORECASE),
    # shell: cat ... > KANBAN.json
    re.compile(r'\bcat\b.*>\s*KANBAN\.json', re.IGNORECASE),
]

# Patterns that indicate the file IS using the approved helpers
SAFE_PATTERNS = [
    re.compile(r'from\s+spa_core\.utils\.kanban\s+import'),
    re.compile(r'import\s+spa_core\.utils\.kanban'),
    re.compile(r'increment_done\s*\('),
    re.compile(r'import\s+kanban_health'),
    re.compile(r'kanban_health\.save_kanban'),
    re.compile(r'save_kanban_atomic\s*\('),
    # If the file IS kanban.py / kanban_health.py itself — it's exempt
    re.compile(r'#\s*spa_core/utils/kanban\.py'),
    re.compile(r'#\s*scripts/kanban_health\.py'),
]

# Extensions to scan
SCAN_EXTENSIONS = {".py", ".sh", ".command"}

# Paths / substrings to skip entirely
SKIP_PATHS = {
    "spa_core/utils/kanban.py",
    "scripts/kanban_health.py",
    "scripts/lint_kanban_usage.py",
    ".git",
    "__pycache__",
    "node_modules",
}


# ─────────────────────────────────────────────
# Core logic
# ─────────────────────────────────────────────

def _should_skip(rel_path: str) -> bool:
    for skip in SKIP_PATHS:
        if skip in rel_path:
            return True
    return False


def _uses_safe_helper(content: str) -> bool:
    return any(p.search(content) for p in SAFE_PATTERNS)


def _has_violation(content: str) -> list:
    """
    Returns list of (line_no, line_text) tuples for lines matching
    a violation pattern.  Empty list = no violation.
    """
    hits = []
    for lineno, line in enumerate(content.splitlines(), 1):
        for pat in VIOLATION_PATTERNS:
            if pat.search(line):
                hits.append((lineno, line.rstrip()))
                break
    return hits


def _references_kanban(content: str) -> bool:
    return "KANBAN.json" in content or "KANBAN" in content


def scan_file(path: str) -> Optional[dict]:
    """
    Returns a violation report dict if the file is a violator, else None.
    """
    try:
        with open(path, encoding="utf-8", errors="ignore") as f:
            content = f.read()
    except OSError:
        return None

    if not _references_kanban(content):
        return None

    hits = _has_violation(content)
    if not hits:
        return None

    if _uses_safe_helper(content):
        # File uses approved helper AND also has direct writes — warn but don't fail
        return {
            "path": path,
            "violations": hits,
            "uses_helper": True,
            "severity": "warning",
        }

    return {
        "path": path,
        "violations": hits,
        "uses_helper": False,
        "severity": "error",
    }


def scan_directory(root: str = ".") -> list:
    """
    Walk `root` recursively and return list of violation dicts.
    """
    results = []
    for dirpath, dirnames, filenames in os.walk(root):
        # Prune skip dirs in-place
        dirnames[:] = [
            d for d in dirnames
            if not any(s in os.path.join(dirpath, d) for s in SKIP_PATHS)
        ]
        for fname in filenames:
            ext = os.path.splitext(fname)[1]
            if ext not in SCAN_EXTENSIONS:
                continue
            full_path = os.path.join(dirpath, fname)
            rel_path = os.path.relpath(full_path, root)
            if _should_skip(rel_path):
                continue
            report = scan_file(full_path)
            if report:
                results.append(report)
    return results


# ─────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────

def main(argv: list = None) -> int:
    if argv is None:
        argv = sys.argv[1:]

    quiet = "--quiet" in argv

    scan_root = "."
    if "--dir" in argv:
        idx = argv.index("--dir")
        if idx + 1 < len(argv):
            scan_root = argv[idx + 1]

    violations = scan_directory(scan_root)

    errors = [v for v in violations if v["severity"] == "error"]
    warnings = [v for v in violations if v["severity"] == "warning"]

    if not violations:
        if not quiet:
            print("✅ No KANBAN write violations found")
        return 0

    for report in errors:
        print(f"❌ ERROR  {report['path']}")
        for lineno, line in report["violations"][:3]:
            print(f"   line {lineno}: {line[:120]}")

    for report in warnings:
        print(f"⚠️  WARN  {report['path']} (uses helper but also has direct write)")
        for lineno, line in report["violations"][:2]:
            print(f"   line {lineno}: {line[:120]}")

    if not quiet:
        print(
            f"\n{len(errors)} error(s), {len(warnings)} warning(s). "
            f"See docs/KANBAN_GUIDELINES.md for the correct approach."
        )

    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
