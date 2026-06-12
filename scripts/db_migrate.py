#!/usr/bin/env python3
"""One-time migration of existing JSON data into SQLite (MP-109).

Run once (or multiple times — the operation is idempotent):

    python3 scripts/db_migrate.py

What it does
============
* Initialises ``data/spa.db`` (creates tables if absent).
* Imports ``data/equity_curve_daily.json``  → ``equity_curve`` table.
* Imports ``data/daily_report_YYYY-MM-DD.json`` files → ``daily_reports`` table.
* Imports ``data/analytics_summary.json`` → ``analytics`` table.

All imports use upsert semantics so re-running never creates duplicates.
"""
from spa_core.persistence.db import init_db, migrate_json_to_db

if __name__ == "__main__":
    print("Initialising spa.db …")
    init_db()
    print("Running JSON → SQLite migration …")
    result = migrate_json_to_db()
    print(f"Migration complete: {result}")
