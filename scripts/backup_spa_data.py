#!/usr/bin/env python3
"""
Backup critical SPA data files to ~/Documents/SPA_Backups/<timestamp>/.

Usage:
  python3 scripts/backup_spa_data.py
  python3 scripts/backup_spa_data.py --dest ~/my/backups
  python3 scripts/backup_spa_data.py --dry-run
  python3 scripts/backup_spa_data.py --list-backups

All stdlib — no external dependencies.
Atomic manifest write (tmp + os.replace).
"""
from __future__ import annotations

import argparse
import datetime
import json
import os
import shutil
import sys
import tempfile
from typing import List, Optional

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _REPO_ROOT)

# ---------------------------------------------------------------------------
# Files to back up
# ---------------------------------------------------------------------------

BACKUP_FILES: List[str] = [
    # Project state
    "KANBAN.json",
    "CURRENT_STATE.md",
    # Gate / capital
    "data/gate_status.json",
    "data/capital_config.json",
    # Paper trading
    "data/paper_evidence_history.json",
    "data/paper_trading_status.json",
    "data/equity_curve_daily.json",
    # GoLive
    "data/golive_status.json",
    "data/gap_monitor.json",
    # Trades
    "data/trades.json",
    # Risk
    "data/risk_limits_check.json",
    "data/risk_scores.json",
    "data/risk_alerts.json",
    # Current positions
    "data/current_positions.json",
]

DEFAULT_BACKUP_ROOT = os.path.expanduser("~/Documents/SPA_Backups")


# ---------------------------------------------------------------------------
# Core functions
# ---------------------------------------------------------------------------

def backup(
    base_dir: str = _REPO_ROOT,
    backup_root: str = DEFAULT_BACKUP_ROOT,
    dry_run: bool = False,
    extra_files: Optional[List[str]] = None,
) -> str:
    """
    Back up BACKUP_FILES from *base_dir* to *backup_root/<timestamp>/*.

    Returns the backup directory path (even in dry-run mode).
    Writes a manifest.json with the list of copied files and metadata.
    Atomic write for the manifest (tmp + os.replace).
    """
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_dir = os.path.join(backup_root, f"backup_{timestamp}")

    all_files = list(BACKUP_FILES)
    if extra_files:
        all_files.extend(extra_files)

    if not dry_run:
        os.makedirs(backup_dir, exist_ok=True)

    copied: List[str] = []
    skipped: List[str] = []

    for rel_path in all_files:
        src = os.path.join(base_dir, rel_path)
        if not os.path.exists(src):
            skipped.append(rel_path)
            continue

        dst = os.path.join(backup_dir, rel_path)
        if not dry_run:
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            shutil.copy2(src, dst)

        copied.append(rel_path)

    # Write manifest atomically
    manifest = {
        "schema_version": "1.0",
        "timestamp": timestamp,
        "backup_dir": backup_dir,
        "source": base_dir,
        "files_copied": copied,
        "files_skipped": skipped,
        "dry_run": dry_run,
    }

    if not dry_run:
        manifest_path = os.path.join(backup_dir, "manifest.json")
        _atomic_write_json(manifest, manifest_path)

    if dry_run:
        print(f"[DRY-RUN] Would backup {len(copied)} files to {backup_dir}")
        for f in copied:
            print(f"  + {f}")
        if skipped:
            print(f"  (skip {len(skipped)} missing files)")
    else:
        print(f"Backed up {len(copied)} files to {backup_dir}")
        if skipped:
            print(f"  Skipped {len(skipped)} missing: {skipped}")

    return backup_dir


def _atomic_write_json(data: dict, path: str) -> None:
    """Write *data* as JSON to *path* atomically (tmp + os.replace)."""
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


def list_backups(backup_root: str = DEFAULT_BACKUP_ROOT) -> List[dict]:
    """Return a list of backup metadata dicts sorted newest-first."""
    if not os.path.isdir(backup_root):
        return []

    results = []
    for entry in sorted(os.listdir(backup_root), reverse=True):
        bdir = os.path.join(backup_root, entry)
        if not os.path.isdir(bdir) or not entry.startswith("backup_"):
            continue
        manifest_path = os.path.join(bdir, "manifest.json")
        if os.path.exists(manifest_path):
            try:
                with open(manifest_path, encoding="utf-8") as f:
                    m = json.load(f)
            except Exception:
                m = {"backup_dir": bdir, "timestamp": entry}
        else:
            m = {"backup_dir": bdir, "timestamp": entry}
        results.append(m)

    return results


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(description="SPA data backup tool")
    parser.add_argument(
        "--dest",
        default=DEFAULT_BACKUP_ROOT,
        help=f"Backup root directory (default: {DEFAULT_BACKUP_ROOT})",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be backed up, without copying",
    )
    parser.add_argument(
        "--list-backups",
        action="store_true",
        help="List existing backups in --dest",
    )
    parser.add_argument(
        "--source",
        default=_REPO_ROOT,
        help="Source directory (default: repo root)",
    )
    args = parser.parse_args()

    if args.list_backups:
        backups = list_backups(args.dest)
        if not backups:
            print(f"No backups found in {args.dest}")
            return 0
        print(f"Backups in {args.dest}:")
        for b in backups:
            ts = b.get("timestamp", "?")
            n = len(b.get("files_copied", []))
            print(f"  {ts} — {n} files")
        return 0

    backup(base_dir=args.source, backup_root=args.dest, dry_run=args.dry_run)
    return 0


if __name__ == "__main__":
    sys.exit(main())
