#!/usr/bin/env python3
"""
scripts/migrate_json_to_sqlite.py

Migrates existing SPA JSON data files to the SQLite database managed by
spa_core.database.sqlite_manager.SQLiteManager.

Supported migrations:
  • data/paper_evidence_history.json → evidence_records table
  • data/equity_curve_daily.json     → paper_trading_records table
  • data/adapter_status.json         → adapter_apy_history table (advisory only)

Modes:
  --dry-run  (default) Print what would be migrated without writing to DB.
  --apply    Execute the migration and write to SQLite.
  --verify   After migration, print row counts from SQLite for validation.

Usage:
  python3 scripts/migrate_json_to_sqlite.py --dry-run
  python3 scripts/migrate_json_to_sqlite.py --apply
  python3 scripts/migrate_json_to_sqlite.py --apply --verify
  python3 scripts/migrate_json_to_sqlite.py --apply --db data/spa.db

stdlib only, no external dependencies.
LLM FORBIDDEN in this module (data integrity).
MP-1540 (v11.56)
"""

from __future__ import annotations

import argparse
import json
import os
import sys

# Allow running as a script from repo root
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from spa_core.database.sqlite_manager import SQLiteManager


# ─── Individual migration functions ─────────────────────────────────────────


def migrate_paper_evidence(
    db: SQLiteManager,
    data_dir: str = "data",
    dry_run: bool = True,
) -> int:
    """
    Migrate data/paper_evidence_history.json → evidence_records table.

    Supports both list format and dict-with-'days' format.

    Returns:
        Number of records migrated (or that would be migrated in dry-run).
    """
    evidence_path = os.path.join(data_dir, "paper_evidence_history.json")
    if not os.path.exists(evidence_path):
        print(f"  SKIP: {evidence_path} not found")
        return 0

    with open(evidence_path, encoding="utf-8") as fh:
        data = json.load(fh)

    # Normalise to list of day dicts
    if isinstance(data, list):
        records = data
    elif isinstance(data, dict):
        records = data.get("days", data.get("records", []))
    else:
        print(f"  SKIP: {evidence_path} — unexpected format {type(data)}")
        return 0

    migrated = 0
    for record in records:
        if not isinstance(record, dict):
            continue

        date = record.get("date", "")
        if not date:
            continue

        # Evidence pts mapping (legacy vs new key names)
        daily_cycle_pts = float(
            record.get("daily_cycle_pts", 1.0 if record.get("cycle_completed") else 0.0)
        )
        apy_tracking_pts = float(
            record.get("apy_tracking_pts", 1.0 if record.get("apy_verified") else 0.0)
        )
        risk_policy_pts = float(
            record.get("risk_policy_pts", 1.0 if record.get("risk_policy_passed") else 0.0)
        )
        total_pts = float(
            record.get("total_pts", daily_cycle_pts + apy_tracking_pts + risk_policy_pts)
        )
        is_seed = bool(record.get("is_seed", False))

        if dry_run:
            print(
                f"  DRY-RUN: evidence {date} "
                f"pts={total_pts:.1f} seed={is_seed}"
            )
        else:
            db.insert_evidence_record(
                date=date,
                daily_cycle_pts=daily_cycle_pts,
                apy_tracking_pts=apy_tracking_pts,
                risk_policy_pts=risk_policy_pts,
                total_pts=total_pts,
                is_seed=is_seed,
            )
        migrated += 1

    return migrated


def migrate_equity_curve(
    db: SQLiteManager,
    data_dir: str = "data",
    dry_run: bool = True,
) -> int:
    """
    Migrate data/equity_curve_daily.json → paper_trading_records table.

    Each daily entry is recorded with strategy_id='S_COMPOSITE' and
    cycle_number derived from position in the array.

    Returns:
        Number of records migrated (or would-be in dry-run).
    """
    curve_path = os.path.join(data_dir, "equity_curve_daily.json")
    if not os.path.exists(curve_path):
        print(f"  SKIP: {curve_path} not found")
        return 0

    with open(curve_path, encoding="utf-8") as fh:
        data = json.load(fh)

    if isinstance(data, list):
        daily = data
    elif isinstance(data, dict):
        daily = data.get("daily", [])
    else:
        print(f"  SKIP: {curve_path} — unexpected format {type(data)}")
        return 0

    migrated = 0
    for idx, entry in enumerate(daily):
        if not isinstance(entry, dict):
            continue

        date = entry.get("date", "")
        if not date:
            continue

        portfolio_nav = float(entry.get("nav", entry.get("equity", entry.get("close_equity", 0.0))))
        daily_pnl = float(entry.get("daily_yield_usd", 0.0))
        daily_apy = float(entry.get("apy_today", entry.get("apy_today_pct", 0.0)))
        allocation = entry.get("positions")

        if dry_run:
            print(
                f"  DRY-RUN: equity_curve {date} "
                f"nav={portfolio_nav:.2f} apy={daily_apy:.2f}%"
            )
        else:
            db.insert_paper_record(
                date=date,
                cycle_number=idx + 1,
                strategy_id="S_COMPOSITE",
                portfolio_nav=portfolio_nav,
                daily_pnl=daily_pnl,
                daily_apy=daily_apy,
                allocation=allocation,
            )
        migrated += 1

    return migrated


def migrate_adapter_apys(
    db: SQLiteManager,
    data_dir: str = "data",
    dry_run: bool = True,
) -> int:
    """
    Migrate adapter APY snapshots from data/adapter_orchestrator_status.json
    → adapter_apy_history table.

    Only migrates adapters that have an explicit 'apy' field.

    Returns:
        Number of records migrated (or would-be in dry-run).
    """
    status_path = os.path.join(data_dir, "adapter_orchestrator_status.json")
    if not os.path.exists(status_path):
        print(f"  SKIP: {status_path} not found")
        return 0

    with open(status_path, encoding="utf-8") as fh:
        data = json.load(fh)

    # Normalise: top-level 'adapters' dict or the whole object
    adapters = data.get("adapters", data) if isinstance(data, dict) else {}
    timestamp = data.get("timestamp", data.get("generated_at", ""))
    date = str(timestamp)[:10] if timestamp else ""

    if not date:
        print(f"  SKIP: {status_path} — no timestamp to derive date")
        return 0

    migrated = 0
    for adapter_name, info in adapters.items():
        if not isinstance(info, dict):
            continue
        apy = info.get("apy")
        if apy is None:
            continue

        if dry_run:
            print(
                f"  DRY-RUN: adapter_apy {date} "
                f"{adapter_name}={float(apy):.2f}%"
            )
        else:
            db.insert_adapter_apy(
                date=date,
                adapter_name=adapter_name,
                apy=float(apy),
                source="migration",
            )
        migrated += 1

    return migrated


def verify(db: SQLiteManager) -> None:
    """Print SQLite row counts for all managed tables."""
    counts = db.table_counts()
    print("\n[VERIFY] SQLite row counts:")
    for table, count in counts.items():
        print(f"  {table}: {count} rows")


# ─── CLI entry point ─────────────────────────────────────────────────────────


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Migrate SPA JSON data files to SQLite."
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        default=True,
        help="Print what would be migrated without writing (default).",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Execute migration and write to SQLite.",
    )
    parser.add_argument(
        "--verify",
        action="store_true",
        help="Print row counts from SQLite after migration.",
    )
    parser.add_argument(
        "--db",
        default="data/spa.db",
        help="Path to SQLite database (default: data/spa.db).",
    )
    parser.add_argument(
        "--data-dir",
        default="data",
        help="Directory containing JSON data files (default: data/).",
    )
    args = parser.parse_args(argv)

    dry_run = not args.apply

    db = SQLiteManager(db_path=args.db)

    mode = "DRY-RUN" if dry_run else "APPLY"
    print(f"[{mode}] Migrating JSON → SQLite ({args.db})")
    print()

    total = 0

    print("── paper_evidence_history.json → evidence_records ──")
    total += migrate_paper_evidence(db, data_dir=args.data_dir, dry_run=dry_run)

    print()
    print("── equity_curve_daily.json → paper_trading_records ──")
    total += migrate_equity_curve(db, data_dir=args.data_dir, dry_run=dry_run)

    print()
    print("── adapter_orchestrator_status.json → adapter_apy_history ──")
    total += migrate_adapter_apys(db, data_dir=args.data_dir, dry_run=dry_run)

    print()
    print(f"[{mode}] Total: {total} records")

    if args.verify:
        verify(db)

    return 0


if __name__ == "__main__":
    sys.exit(main())
