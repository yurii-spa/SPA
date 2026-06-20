#!/usr/bin/env python3
"""
scripts/generate_changelog.py
MP-1518 (v11.34): Auto-generate a changelog from git log.

Usage:
    python3 scripts/generate_changelog.py                    # print to stdout
    python3 scripts/generate_changelog.py --output docs/CHANGELOG_AUTO.md
    python3 scripts/generate_changelog.py --limit 50         # last 50 commits
    python3 scripts/generate_changelog.py --since 2026-06-01
"""

import argparse
import datetime
import os
import subprocess
import sys


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
DEFAULT_LIMIT = 100
OUTPUT_HEADER = "# SPA Engineering Changelog (Auto-Generated)\n\n"


# ---------------------------------------------------------------------------
# Git helpers
# ---------------------------------------------------------------------------

def _git_log_oneline(limit: int) -> list[str]:
    """Return last `limit` commits as one-line strings."""
    result = subprocess.run(
        ["git", "log", "--oneline", f"-{limit}"],
        capture_output=True,
        text=True,
        cwd=_repo_root(),
    )
    if result.returncode != 0:
        raise RuntimeError(f"git log failed: {result.stderr.strip()}")
    return [line for line in result.stdout.splitlines() if line.strip()]


def _git_log_full(limit: int) -> list[dict]:
    """Return last `limit` commits with hash, date, subject."""
    fmt = "%H%x09%ad%x09%s"
    result = subprocess.run(
        ["git", "log", f"--format={fmt}", "--date=short", f"-{limit}"],
        capture_output=True,
        text=True,
        cwd=_repo_root(),
    )
    if result.returncode != 0:
        raise RuntimeError(f"git log failed: {result.stderr.strip()}")

    commits = []
    for line in result.stdout.splitlines():
        if not line.strip():
            continue
        parts = line.split("\t", 2)
        if len(parts) == 3:
            commits.append({
                "hash": parts[0][:8],
                "date": parts[1],
                "subject": parts[2],
            })
    return commits


def _git_log_since(since_date: str) -> list[dict]:
    """Return commits since a given date (YYYY-MM-DD)."""
    fmt = "%H%x09%ad%x09%s"
    result = subprocess.run(
        ["git", "log", f"--format={fmt}", "--date=short", f"--since={since_date}"],
        capture_output=True,
        text=True,
        cwd=_repo_root(),
    )
    if result.returncode != 0:
        raise RuntimeError(f"git log failed: {result.stderr.strip()}")

    commits = []
    for line in result.stdout.splitlines():
        if not line.strip():
            continue
        parts = line.split("\t", 2)
        if len(parts) == 3:
            commits.append({
                "hash": parts[0][:8],
                "date": parts[1],
                "subject": parts[2],
            })
    return commits


def _repo_root() -> str:
    """Return the absolute path to the git repo root."""
    result = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        # Fallback: use the directory containing this script
        return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return result.stdout.strip()


# ---------------------------------------------------------------------------
# Parsing / grouping
# ---------------------------------------------------------------------------

def _extract_sprint(subject: str) -> str | None:
    """Try to extract 'Sprint vX.Y' from a commit subject."""
    import re
    m = re.search(r"Sprint\s+(v[\d.]+)", subject, re.IGNORECASE)
    return m.group(1) if m else None


def _extract_mp(subject: str) -> str | None:
    """Try to extract 'MP-NNN' from a commit subject."""
    import re
    m = re.search(r"MP-(\d+)", subject, re.IGNORECASE)
    return f"MP-{m.group(1)}" if m else None


def _group_by_date(commits: list[dict]) -> dict[str, list[dict]]:
    """Group commits by date string."""
    groups: dict[str, list[dict]] = {}
    for c in commits:
        groups.setdefault(c["date"], []).append(c)
    return groups


# ---------------------------------------------------------------------------
# Formatting
# ---------------------------------------------------------------------------

def _format_commit(commit: dict) -> str:
    sprint = _extract_sprint(commit["subject"])
    mp = _extract_mp(commit["subject"])

    tags = []
    if sprint:
        tags.append(sprint)
    if mp:
        tags.append(mp)

    tag_str = f" `{'` `'.join(tags)}`" if tags else ""
    return f"- `{commit['hash']}`{tag_str} — {commit['subject']}"


def _render_changelog(commits: list[dict], title: str = "") -> str:
    lines = [OUTPUT_HEADER]
    if title:
        lines.append(f"> {title}\n\n")

    lines.append(
        f"> Generated: {datetime.datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}"
        f"  |  Commits: {len(commits)}\n\n"
    )
    lines.append("---\n\n")

    grouped = _group_by_date(commits)
    for date in sorted(grouped.keys(), reverse=True):
        lines.append(f"## {date}\n\n")
        for c in grouped[date]:
            lines.append(_format_commit(c) + "\n")
        lines.append("\n")

    return "".join(lines)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate SPA engineering changelog from git log."
    )
    parser.add_argument(
        "--output", "-o",
        help="Output file path. If omitted, prints to stdout.",
        default=None,
    )
    parser.add_argument(
        "--limit", "-n",
        type=int,
        default=DEFAULT_LIMIT,
        help=f"Max number of commits to include (default: {DEFAULT_LIMIT}).",
    )
    parser.add_argument(
        "--since",
        help="Include only commits since this date (YYYY-MM-DD).",
        default=None,
    )
    parser.add_argument(
        "--title",
        help="Optional title line to include in the header.",
        default="",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print to stdout even if --output is specified.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    try:
        if args.since:
            commits = _git_log_since(args.since)
        else:
            commits = _git_log_full(args.limit)
    except RuntimeError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    if not commits:
        print("No commits found.", file=sys.stderr)
        return 0

    changelog = _render_changelog(commits, title=args.title)

    if args.output and not args.dry_run:
        # Atomic write
        tmp_path = args.output + ".tmp"
        with open(tmp_path, "w", encoding="utf-8") as f:
            f.write(changelog)
        os.replace(tmp_path, args.output)
        print(f"Changelog written to: {args.output} ({len(commits)} commits)")
    else:
        sys.stdout.write(changelog)

    return 0


if __name__ == "__main__":
    sys.exit(main())
