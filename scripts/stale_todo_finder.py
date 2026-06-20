#!/usr/bin/env python3
"""
scripts/stale_todo_finder.py
Finds TODO/FIXME/HACK/XXX comments in the codebase.

For each comment, tries to determine age via git blame.
Reports "stale" TODOs older than --max-age-days (default 30).

MP-1521 (v11.37) — stdlib only, no external dependencies.

Usage:
    python3 scripts/stale_todo_finder.py
    python3 scripts/stale_todo_finder.py --max-age-days 60 --path spa_core/
    python3 scripts/stale_todo_finder.py --tags TODO FIXME
    python3 scripts/stale_todo_finder.py --no-git   # skip blame, show all
    python3 scripts/stale_todo_finder.py --json
"""

from __future__ import annotations

import argparse
import datetime
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Optional

# Tags to scan
DEFAULT_TAGS: list[str] = ["TODO", "FIXME", "HACK", "XXX"]

# Directories / patterns to skip
SKIP_DIRS: set[str] = {"__pycache__", ".git", ".venv", ".venv_test", "node_modules", "data"}
SKIP_PATH_FRAGMENTS: list[str] = ["alembic/versions", ".pyc"]


def _git_blame_date(filepath: str, lineno: int) -> Optional[datetime.date]:
    """
    Return the commit date for a specific line via git blame.
    Returns None if git is unavailable or the line can't be blamed.
    """
    try:
        result = subprocess.run(
            ["git", "blame", "-L", f"{lineno},{lineno}", "--date=short", "-p", filepath],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode != 0:
            return None
        for line in result.stdout.splitlines():
            if line.startswith("author-time"):
                ts = int(line.split()[1])
                return datetime.date.fromtimestamp(ts)
        # Fallback: look for 'committer-date'
        for line in result.stdout.splitlines():
            if line.startswith("committer-date"):
                return datetime.date.fromisoformat(line.split()[1])
        return None
    except (subprocess.TimeoutExpired, FileNotFoundError, ValueError, OSError):
        return None


def find_todos(
    path: str = ".",
    tags: Optional[list[str]] = None,
) -> list[dict]:
    """
    Walk *path* and return a list of found TODO items.

    Each item dict contains:
      file     — relative file path
      line     — line number (1-based)
      tag      — matched tag (TODO, FIXME, etc.)
      content  — full line content (stripped)
    """
    if tags is None:
        tags = DEFAULT_TAGS

    pattern = re.compile(
        r"#\s*(" + "|".join(re.escape(t) for t in tags) + r")\b(.*)",
        re.IGNORECASE,
    )

    results: list[dict] = []
    base = Path(path)

    for root, dirs, files in os.walk(base):
        # Prune skip dirs in-place
        dirs[:] = sorted(d for d in dirs if d not in SKIP_DIRS and not d.startswith("."))

        for fname in sorted(files):
            if not fname.endswith(".py"):
                continue
            fpath = Path(root) / fname
            rel = str(fpath.relative_to(base) if base != Path(".") else fpath)

            # Skip alembic versions, pycache, etc.
            if any(frag in rel for frag in SKIP_PATH_FRAGMENTS):
                continue

            try:
                text = fpath.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue

            for lineno, line in enumerate(text.splitlines(), 1):
                m = pattern.search(line)
                if m:
                    results.append({
                        "file": rel,
                        "line": lineno,
                        "tag": m.group(1).upper(),
                        "content": line.strip(),
                    })

    return results


def annotate_ages(
    todos: list[dict],
    use_git: bool = True,
) -> list[dict]:
    """Add commit_date and age_days to each todo entry."""
    today = datetime.date.today()

    for item in todos:
        if use_git:
            d = _git_blame_date(item["file"], item["line"])
        else:
            d = None

        item["commit_date"] = d.isoformat() if d else None
        item["age_days"] = (today - d).days if d else None

    return todos


def filter_stale(todos: list[dict], max_age_days: int) -> list[dict]:
    """Return only items older than max_age_days (unknown age → always stale)."""
    stale = []
    for item in todos:
        age = item.get("age_days")
        if age is None or age >= max_age_days:
            stale.append(item)
    return stale


def main() -> None:
    parser = argparse.ArgumentParser(
        description="SPA stale TODO/FIXME finder",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--path", default="spa_core", help="Root path to scan (default: spa_core)"
    )
    parser.add_argument(
        "--max-age-days", type=int, default=30,
        help="Report TODOs older than this many days (default: 30)",
    )
    parser.add_argument(
        "--tags", nargs="+", default=DEFAULT_TAGS,
        help=f"Tags to search for (default: {DEFAULT_TAGS})",
    )
    parser.add_argument(
        "--no-git", action="store_true",
        help="Skip git blame; show all TODOs without age info",
    )
    parser.add_argument(
        "--json", action="store_true", dest="as_json",
        help="Output JSON",
    )
    parser.add_argument(
        "--stale-only", action="store_true",
        help="Only show stale items (older than --max-age-days)",
    )
    args = parser.parse_args()

    todos = find_todos(path=args.path, tags=args.tags)

    if not args.no_git:
        todos = annotate_ages(todos, use_git=True)
    else:
        for t in todos:
            t["commit_date"] = None
            t["age_days"] = None

    if args.stale_only:
        todos = filter_stale(todos, args.max_age_days)

    if args.as_json:
        print(json.dumps(todos, indent=2))
        return

    print(f"Found {len(todos)} {'/'.join(args.tags)} item(s) in {args.path!r}")
    if not todos:
        print("✅ No TODO/FIXME items found — codebase is clean")
        return

    print("")
    for item in todos[:20]:
        age_str = f"  age={item['age_days']}d" if item["age_days"] is not None else ""
        print(f"  {item['file']}:{item['line']} [{item['tag']}]{age_str}")
        print(f"    {item['content'][:80]}")

    if len(todos) > 20:
        print(f"  ... and {len(todos) - 20} more")

    stale_count = len([t for t in todos if (t["age_days"] or 0) >= args.max_age_days or t["age_days"] is None])
    if stale_count:
        print(f"\n⚠️  {stale_count} item(s) may be stale (>{args.max_age_days} days or unknown age)")
        print("   Action: implement, remove, or create an ADR entry for each.")
    else:
        print(f"\n✅ All items are within {args.max_age_days} days")


if __name__ == "__main__":
    main()
