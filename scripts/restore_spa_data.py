#!/usr/bin/env python3
"""
Restore SPA data files from a backup created by backup_spa_data.py.

Usage:
  python3 scripts/restore_spa_data.py --from ~/Documents/SPA_Backups/backup_20260620_080000
  python3 scripts/restore_spa_data.py --latest
  python3 scripts/restore_spa_data.py --from <dir> --dry-run
  python3 scripts/restore_spa_data.py --from <dir> --files data/golive_status.json KANBAN.json

All stdlib — no external dependencies.
Atomic writes (tmp + os.replace) for each restored file.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import tempfile
from typing import List, Optional

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _REPO_ROOT)

# Import backup_spa_data for shared constants
sys.path.insert(0, os.path.join(_REPO_ROOT, "scripts"))
try:
    from backup_spa_data import (
        DEFAULT_BACKUP_ROOT,
        BACKUP_FILES,
        _atomic_write_json,
        list_backups,
    )
except ImportError:
    DEFAULT_BACKUP_ROOT = os.path.expanduser("~/Documents/SPA_Backups")
    BACKUP_FILES: List[str] = []

    def _atomic_write_json(data: dict, path: str) -> None:  # type: ignore[misc]
        dir_name = os.path.dirname(path) or "."
        fd, tmp_path = tempfile.mkstemp(dir=dir_name, suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
            os.replace(tmp_path, path)
        except Exception:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise

    def list_backups(backup_root: str = DEFAULT_BACKUP_ROOT) -> List[dict]:  # type: ignore[misc]
        return []


# ---------------------------------------------------------------------------
# Core restore function
# ---------------------------------------------------------------------------

def restore(
    backup_dir: str,
    target_dir: str = _REPO_ROOT,
    dry_run: bool = False,
    files: Optional[List[str]] = None,
) -> dict:
    """
    Restore files from *backup_dir* into *target_dir*.

    If *files* is given, only those relative paths are restored.
    Otherwise all files listed in the backup's manifest.json are restored.

    Returns a dict with keys: restored, skipped, errors.
    Atomic copy: write to tmp file first, then os.replace.
    """
    # Load manifest
    manifest_path = os.path.join(backup_dir, "manifest.json")
    if os.path.exists(manifest_path):
        with open(manifest_path, encoding="utf-8") as f:
            manifest = json.load(f)
        to_restore = manifest.get("files_copied", BACKUP_FILES)
    else:
        # Fallback: scan the backup dir for all files (exclude manifest)
        to_restore = []
        for root, _, filenames in os.walk(backup_dir):
            for fname in filenames:
                if fname == "manifest.json":
                    continue
                full = os.path.join(root, fname)
                rel = os.path.relpath(full, backup_dir)
                to_restore.append(rel)

    if files:
        to_restore = [f for f in to_restore if f in files]

    restored: List[str] = []
    skipped: List[str] = []
    errors: List[str] = []

    for rel_path in to_restore:
        src = os.path.join(backup_dir, rel_path)
        if not os.path.exists(src):
            skipped.append(rel_path)
            continue

        dst = os.path.join(target_dir, rel_path)
        if dry_run:
            restored.append(rel_path)
            continue

        try:
            dst_dir = os.path.dirname(dst)
            if dst_dir:
                os.makedirs(dst_dir, exist_ok=True)
            # Atomic copy: tmp sibling → os.replace
            dst_dir_actual = os.path.dirname(dst) or "."
            fd, tmp_path = tempfile.mkstemp(dir=dst_dir_actual, suffix=".restore_tmp")
            try:
                os.close(fd)
                shutil.copy2(src, tmp_path)
                os.replace(tmp_path, dst)
            except Exception:
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass
                raise
            restored.append(rel_path)
        except Exception as exc:
            errors.append(f"{rel_path}: {exc}")

    result = {
        "backup_dir": backup_dir,
        "target_dir": target_dir,
        "dry_run": dry_run,
        "restored": restored,
        "skipped": skipped,
        "errors": errors,
    }

    _print_result(result)
    return result


def _print_result(result: dict) -> None:
    prefix = "[DRY-RUN] " if result["dry_run"] else ""
    print(f"{prefix}Restore from: {result['backup_dir']}")
    print(f"{prefix}Restored    : {len(result['restored'])} files")
    if result["skipped"]:
        print(f"{prefix}Skipped     : {len(result['skipped'])} (not in backup)")
    if result["errors"]:
        print(f"{prefix}Errors      : {len(result['errors'])}")
        for e in result["errors"]:
            print(f"  ❌ {e}")


def _find_latest_backup(backup_root: str) -> Optional[str]:
    """Return the path of the most-recent backup, or None."""
    backups = list_backups(backup_root)
    if not backups:
        return None
    return backups[0].get("backup_dir")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(description="SPA data restore tool")
    src_group = parser.add_mutually_exclusive_group(required=True)
    src_group.add_argument(
        "--from", dest="backup_dir",
        help="Backup directory to restore from",
    )
    src_group.add_argument(
        "--latest",
        action="store_true",
        help="Restore from the most-recent backup in the default location",
    )
    parser.add_argument(
        "--dest",
        default=_REPO_ROOT,
        help=f"Restore target directory (default: repo root {_REPO_ROOT})",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be restored, without writing files",
    )
    parser.add_argument(
        "--files",
        nargs="*",
        help="Restore only specific files (relative paths)",
    )
    parser.add_argument(
        "--backup-root",
        default=DEFAULT_BACKUP_ROOT,
        help=f"Root directory containing backups (default: {DEFAULT_BACKUP_ROOT})",
    )
    args = parser.parse_args()

    if args.latest:
        bdir = _find_latest_backup(args.backup_root)
        if not bdir:
            print(f"ERROR: no backups found in {args.backup_root}")
            return 1
        print(f"Using latest backup: {bdir}")
    else:
        bdir = args.backup_dir

    if not os.path.isdir(bdir):
        print(f"ERROR: backup directory not found: {bdir}")
        return 1

    result = restore(
        backup_dir=bdir,
        target_dir=args.dest,
        dry_run=args.dry_run,
        files=args.files if args.files else None,
    )
    return 1 if result["errors"] else 0


if __name__ == "__main__":
    sys.exit(main())
