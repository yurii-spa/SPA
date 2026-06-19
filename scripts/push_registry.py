#!/usr/bin/env python3
"""
scripts/push_registry.py

Tracks which push scripts have been executed.
Reads scripts/push_registry.json for state.

Usage:
  python3 scripts/push_registry.py --list          # show all scripts + status
  python3 scripts/push_registry.py --pending        # show not-yet-pushed
  python3 scripts/push_registry.py --mark-done v9.21 v9.22  # mark as done
  python3 scripts/push_registry.py --scan           # scan scripts/ for new push scripts
  python3 scripts/push_registry.py --summary        # count pushed/pending

Registry format: scripts/push_registry.json
{
  "last_updated": "2026-06-19",
  "scripts": {
    "push_v921.sh": {"status": "DONE", "date": "2026-06-19", "commit": ""},
    "push_v941.sh": {"status": "PENDING", "date": null, "commit": null},
    ...
  }
}
"""

import argparse
import json
import os
import re
import sys
from datetime import date

REGISTRY_PATH = "scripts/push_registry.json"


def scan_scripts(scripts_dir: str = "scripts") -> list:
    """Returns sorted list of push_vNNN.sh and push_audit*.sh files."""
    if not os.path.isdir(scripts_dir):
        return []
    results = []
    for fname in os.listdir(scripts_dir):
        if re.match(r"^push_v\d+\.sh$", fname) or re.match(r"^push_audit\w*\.sh$", fname):
            results.append(fname)
    return sorted(results)


def load_registry(path: str = REGISTRY_PATH) -> dict:
    """Load registry from JSON file. Returns empty registry if file doesn't exist."""
    if not os.path.exists(path):
        return {"last_updated": str(date.today()), "scripts": {}}
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_registry(registry: dict, path: str = REGISTRY_PATH) -> None:
    """Atomic save via tmp file + os.replace."""
    registry["last_updated"] = str(date.today())
    tmp_path = path + ".tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(registry, f, indent=2)
    os.replace(tmp_path, path)


def pending_scripts(registry: dict) -> list:
    """Returns sorted list of script names with status != DONE."""
    scripts = registry.get("scripts", {})
    return sorted(
        name for name, info in scripts.items()
        if info.get("status") != "DONE"
    )


def mark_done(scripts: list, registry: dict, commit: str = "") -> int:
    """
    Marks the given script names as DONE in the registry.
    Accepts bare names like 'push_v921.sh' or short-form 'v9.21'.
    Returns count of scripts actually marked (skips unknown).
    """
    today = str(date.today())
    count = 0
    all_scripts = registry.setdefault("scripts", {})
    for name in scripts:
        # Normalize: allow both 'push_v921.sh' and 'v921' style
        key = _normalize_name(name, all_scripts)
        if key and key in all_scripts:
            all_scripts[key]["status"] = "DONE"
            all_scripts[key]["date"] = today
            all_scripts[key]["commit"] = commit
            count += 1
    return count


def _normalize_name(name: str, all_scripts: dict) -> str:
    """Try to resolve a user-provided name to a registry key."""
    # Direct match
    if name in all_scripts:
        return name
    # Try adding .sh
    with_sh = name + ".sh"
    if with_sh in all_scripts:
        return with_sh
    # Try converting 'v9.21' → 'push_v921.sh'
    m = re.match(r"^v(\d+)\.(\d+)$", name)
    if m:
        key = f"push_v{m.group(1)}{m.group(2).zfill(2)}.sh"
        if key in all_scripts:
            return key
    return ""


def sync_scan(registry: dict, scripts_dir: str = "scripts") -> int:
    """
    Scans scripts_dir for push scripts and adds any not yet in registry as PENDING.
    Does NOT overwrite existing entries.
    Returns count of newly added scripts.
    """
    found = scan_scripts(scripts_dir)
    existing = registry.setdefault("scripts", {})
    count = 0
    for fname in found:
        if fname not in existing:
            existing[fname] = {"status": "PENDING", "date": None, "commit": None}
            count += 1
    return count


def summary(registry: dict) -> dict:
    """Returns {total, done, pending, pct_done}."""
    scripts = registry.get("scripts", {})
    total = len(scripts)
    done = sum(1 for info in scripts.values() if info.get("status") == "DONE")
    pending = total - done
    pct_done = round(done / total * 100, 1) if total > 0 else 0.0
    return {
        "total": total,
        "done": done,
        "pending": pending,
        "pct_done": pct_done,
    }


def render_table(registry: dict) -> str:
    """Human-readable table of all scripts and their statuses."""
    scripts = registry.get("scripts", {})
    if not scripts:
        return "Registry is empty. Run --scan to populate.\n"
    lines = [
        f"{'Script':<30} {'Status':<10} {'Date':<12} {'Commit'}",
        "-" * 70,
    ]
    for name in sorted(scripts):
        info = scripts[name]
        status = info.get("status", "PENDING")
        date_str = info.get("date") or ""
        commit = info.get("commit") or ""
        lines.append(f"{name:<30} {status:<10} {date_str:<12} {commit}")
    stats = summary(registry)
    lines.append("")
    lines.append(
        f"Total: {stats['total']}  DONE: {stats['done']}  "
        f"PENDING: {stats['pending']}  ({stats['pct_done']}%)"
    )
    return "\n".join(lines)


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="SPA push registry — track which push scripts have run"
    )
    p.add_argument("--list", action="store_true", help="Show all scripts + status")
    p.add_argument("--pending", action="store_true", help="Show PENDING scripts only")
    p.add_argument("--scan", action="store_true", help="Scan scripts/ for new push scripts")
    p.add_argument("--summary", action="store_true", help="Print summary counts")
    p.add_argument(
        "--mark-done",
        nargs="+",
        metavar="SCRIPT",
        help="Mark scripts as DONE (e.g. push_v921.sh or v9.21)",
    )
    p.add_argument(
        "--commit",
        default="",
        help="Commit hash to record when using --mark-done",
    )
    p.add_argument(
        "--registry",
        default=REGISTRY_PATH,
        help=f"Path to registry JSON (default: {REGISTRY_PATH})",
    )
    p.add_argument(
        "--scripts-dir",
        default="scripts",
        help="Directory to scan for push scripts (default: scripts)",
    )
    return p


def main(argv=None) -> int:
    p = _build_parser()
    args = p.parse_args(argv)

    registry = load_registry(args.registry)

    if args.scan:
        added = sync_scan(registry, args.scripts_dir)
        save_registry(registry, args.registry)
        print(f"Scan complete. Added {added} new script(s) to registry.")

    if args.mark_done:
        marked = mark_done(args.mark_done, registry, commit=args.commit)
        save_registry(registry, args.registry)
        print(f"Marked {marked} script(s) as DONE.")

    if args.pending:
        pend = pending_scripts(registry)
        if pend:
            print("\n".join(pend))
        else:
            print("No pending scripts.")

    if args.list:
        print(render_table(registry))

    if args.summary:
        s = summary(registry)
        print(
            f"Total: {s['total']}  DONE: {s['done']}  "
            f"PENDING: {s['pending']}  ({s['pct_done']}%)"
        )

    if not any([args.scan, args.mark_done, args.pending, args.list, args.summary]):
        p.print_help()

    return 0


if __name__ == "__main__":
    sys.exit(main())
