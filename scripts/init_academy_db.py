#!/usr/bin/env python3
"""
scripts/init_academy_db.py

Production wrapper for initialising / migrating the Academy SQLite DB.

Safety-first: by default this refuses to CREATE a new database file. You must
pass --create for an explicit prod deploy that intends to create the file.
Without --create, the target must already exist (so a typo'd path can never
silently spawn a stray empty DB).

Usage:
  # Migrate an existing DB:
  python3 scripts/init_academy_db.py --db ~/Documents/SPA_Claude/data/academy.db

  # First-time prod create (explicit):
  python3 scripts/init_academy_db.py --db ~/Documents/SPA_Claude/data/academy.db --create

Academy stage 1.
"""

from __future__ import annotations

import argparse
import os
import sys

# Ensure the repo root is importable when run as a bare script.
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from spa_core.academy.db import AcademyDB  # noqa: E402


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Initialise / migrate the Academy SQLite database."
    )
    parser.add_argument("--db", required=True, help="path to the academy.db file")
    parser.add_argument(
        "--create",
        action="store_true",
        help="allow creating the DB file if it does not exist (explicit prod deploy)",
    )
    args = parser.parse_args(argv)

    db_path = os.path.abspath(os.path.expanduser(args.db))

    if not os.path.exists(db_path):
        if not args.create:
            print(
                f"error: database file does not exist: {db_path}\n"
                f"       Refusing to create it implicitly. If this is an intentional\n"
                f"       first-time deploy, re-run with --create.",
                file=sys.stderr,
            )
            return 1
        parent = os.path.dirname(db_path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        print(f"creating new database: {db_path}")

    db = AcademyDB(db_path=db_path)
    applied = db.run_migrations()
    if applied:
        print(f"applied migrations: {applied}")
    else:
        print("no new migrations (already current)")
    print(f"schema_version = {db.schema_version()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
