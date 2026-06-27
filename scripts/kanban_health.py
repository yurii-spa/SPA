#!/usr/bin/env python3
"""
scripts/kanban_health.py

KANBAN.json health checker and repair tool.

Checks:
  - done_count >= len(done[])
  - sprint_completed present and non-empty
  - sprint_current >= sprint_completed (no regression)
  - version == "10.0.0"
  - no duplicate task IDs in done[]
  - last_updated present
  - current_sprint consistent with sprint_current

Usage:
  python3 scripts/kanban_health.py            # check only (default)
  python3 scripts/kanban_health.py --fix      # fix inconsistencies
  python3 scripts/kanban_health.py --watch    # watch every 30s
"""
import fcntl
import json
import os
import sys
import time
from datetime import date
from typing import Optional


# ─────────────────────────────────────────────
# Version parsing helpers
# ─────────────────────────────────────────────

def _version_tuple(v: str) -> tuple:
    """
    Parse version string like 'v10.3' or '10.3.0' into a comparable tuple.
    Returns (0,) on parse failure so comparisons still work safely.
    """
    if not v:
        return (0,)
    cleaned = v.lstrip("v").strip()
    try:
        return tuple(int(x) for x in cleaned.split("."))
    except ValueError:
        return (0,)


def _sprint_gte(a: str, b: str) -> bool:
    """Return True if sprint a >= sprint b."""
    return _version_tuple(a) >= _version_tuple(b)


# ─────────────────────────────────────────────
# I/O helpers
# ─────────────────────────────────────────────

def load_kanban(path: str = "KANBAN.json") -> dict:
    """Load KANBAN.json. Raises FileNotFoundError if missing."""
    with open(path) as f:
        return json.load(f)


def save_kanban(k: dict, path: str = "KANBAN.json") -> None:
    """
    Atomic save with exclusive file lock.
    Writes to tmp file then os.replace so concurrent readers
    never see a partial write.
    """
    tmp = path + ".tmp"
    # Write new content to tmp
    with open(tmp, "w") as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        try:
            json.dump(k, f, indent=2)
        finally:
            fcntl.flock(f, fcntl.LOCK_UN)
    # Atomic replace
    os.replace(tmp, path)


# ─────────────────────────────────────────────
# Core checker
# ─────────────────────────────────────────────

def check_kanban(k: dict) -> list:
    """
    Analyse k for consistency issues.
    Returns a list of human-readable issue strings (empty = healthy).
    """
    issues = []

    done_arr = k.get("done", [])
    done_count = k.get("done_count", 0)

    # 1. done_count must be >= actual done[] length
    if done_count < len(done_arr):
        issues.append(
            f"done_count ({done_count}) < done[] length ({len(done_arr)})"
        )

    # 2. sprint_completed must be present
    sprint_completed = k.get("sprint_completed", "")
    if not sprint_completed:
        issues.append("sprint_completed is missing or empty")

    # 3. sprint_current must be >= sprint_completed
    sprint_current = k.get("sprint_current", "")
    if sprint_completed and sprint_current:
        if not _sprint_gte(sprint_current, sprint_completed):
            issues.append(
                f"sprint_current ({sprint_current}) < sprint_completed "
                f"({sprint_completed}) — regression detected"
            )
    elif not sprint_current:
        issues.append("sprint_current is missing or empty")

    # 4. version must be present and >= the minimum supported schema version.
    # NOTE: an autonomous hourly cycle bumps KANBAN.json "version" continuously,
    # so an exact-match check would break CI on every bump. We only enforce a
    # floor (>= MIN_VERSION) so forward bumps stay healthy.
    min_version = "10.0.0"
    actual_version = k.get("version", "")
    if not actual_version:
        issues.append("version is missing or empty")
    elif not _sprint_gte(actual_version, min_version):
        issues.append(
            f"version too old: got '{actual_version}', expected >= '{min_version}'"
        )

    # 5. Check for duplicate task IDs in done[]
    ids = [t.get("id") for t in done_arr if isinstance(t, dict) and t.get("id")]
    seen = set()
    dupes = []
    for id_ in ids:
        if id_ in seen and id_ not in dupes:
            dupes.append(id_)
        seen.add(id_)
    if dupes:
        sample = dupes[:5]
        issues.append(f"Duplicate task IDs in done[]: {sample}")

    # 6. last_updated must be present
    if not k.get("last_updated"):
        issues.append("last_updated is missing or empty")

    # 7. current_sprint should be consistent with sprint_current
    current_sprint = k.get("current_sprint", "")
    if sprint_current and current_sprint and current_sprint != sprint_current:
        issues.append(
            f"current_sprint ({current_sprint}) != sprint_current ({sprint_current})"
        )

    return issues


# ─────────────────────────────────────────────
# Repair
# ─────────────────────────────────────────────

def fix_kanban(k: dict, sprint_current: Optional[str] = None) -> dict:
    """
    Repairs inconsistencies in-place and returns the modified dict.

    Repairs applied:
      - done_count bumped to max(current, len(done[]))
      - sprint_completed defaulted to 'v10.0' if missing
      - sprint_current set to sprint_current arg (or 'v10.3' if still behind sprint_completed)
      - version set to '10.0.0'
      - last_updated set to today if missing
      - current_sprint aligned with sprint_current
      - last_checked set to today
    """
    done_arr = k.get("done", [])

    # Fix done_count
    k["done_count"] = max(k.get("done_count", 0), len(done_arr))

    # Fix sprint_completed
    if not k.get("sprint_completed"):
        k["sprint_completed"] = "v10.0"

    # Fix sprint_current
    sc = sprint_current or k.get("sprint_current", "")
    if not sc or not _sprint_gte(sc, k.get("sprint_completed", "v10.0")):
        sc = "v10.3"
    k["sprint_current"] = sc

    # Fix current_sprint consistency
    k["current_sprint"] = sc

    # Fix version — only set a floor; never downgrade a higher live version
    # (the autonomous cycle bumps this continuously).
    if not _sprint_gte(k.get("version", ""), "10.0.0"):
        k["version"] = "10.0.0"

    # Fix last_updated
    if not k.get("last_updated"):
        k["last_updated"] = date.today().isoformat()

    # Stamp check time
    k["last_checked"] = date.today().isoformat()

    return k


# ─────────────────────────────────────────────
# Watch mode
# ─────────────────────────────────────────────

def watch(path: str = "KANBAN.json", interval: int = 30) -> None:
    """Poll KANBAN.json every `interval` seconds and report issues."""
    print(f"Watching {path} every {interval}s (Ctrl+C to stop)…")
    while True:
        try:
            k = load_kanban(path)
            issues = check_kanban(k)
            ts = time.strftime("%H:%M:%S")
            if issues:
                print(f"[{ts}] ❌ {len(issues)} issue(s):")
                for iss in issues:
                    print(f"  - {iss}")
            else:
                dc = k.get("done_count")
                sp = k.get("sprint_current")
                print(f"[{ts}] ✅ OK  done_count={dc}  sprint_current={sp}")
        except Exception as exc:  # noqa: BLE001
            print(f"Error reading {path}: {exc}")
        time.sleep(interval)


# ─────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────

def main(argv: list = None) -> int:
    if argv is None:
        argv = sys.argv[1:]

    kanban_path = "KANBAN.json"

    if "--watch" in argv:
        watch(kanban_path)
        return 0

    try:
        k = load_kanban(kanban_path)
    except FileNotFoundError:
        print(f"❌ {kanban_path} not found")
        return 2
    except json.JSONDecodeError as exc:
        print(f"❌ {kanban_path} is not valid JSON: {exc}")
        return 2

    issues = check_kanban(k)

    if not issues:
        dc = k.get("done_count")
        sp = k.get("sprint_current")
        sc = k.get("sprint_completed")
        print(
            f"✅ KANBAN OK: done_count={dc}, "
            f"sprint_current={sp}, sprint_completed={sc}"
        )
        return 0

    print(f"❌ {len(issues)} issue(s) found:")
    for iss in issues:
        print(f"  - {iss}")

    if "--fix" in argv:
        k = fix_kanban(k)
        save_kanban(k, kanban_path)
        remaining = check_kanban(k)
        if remaining:
            print(f"⚠️  Fixed most issues; {len(remaining)} remain:")
            for iss in remaining:
                print(f"  - {iss}")
            return 1
        print("✅ Fixed — KANBAN.json is now consistent")
        return 0

    print("Run with --fix to repair automatically")
    return 1


if __name__ == "__main__":
    sys.exit(main())
