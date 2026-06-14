# PostgreSQL Cutover Procedure (BL-008 Phase 3)

Status: **Production-ready** — Phase 1 + Phase 2 + Phase 3 of BL-008 complete.
Last updated: 2026-05-27

This document is the operator runbook for moving SPA from its development
SQLite file (`spa_core/database/spa.db`) to a managed PostgreSQL instance,
once paper trading has graduated and go-live has been approved.

The cutover is built on three orthogonal pieces that already exist:

1. **`SPA_DATABASE_URL`** — single environment variable that selects the
   backend. See `spa_core/database/db_url.py` (Phase 1).
2. **`spa_core.database.connection.get_connection`** — dual-driver
   context manager that every call-site flows through (Phase 2).
3. **Alembic** at `spa_core/database/alembic/` with baseline migration
   `0001_initial_schema` (Phase 3, this doc).

## Pre-flight checklist

- [ ] Managed Postgres provisioned (Supabase, Neon, RDS, etc.) with a
      dedicated database `spa` and a least-privilege role.
- [ ] Connection string saved to GitHub Actions secrets as
      `SPA_DATABASE_URL` (format: `postgresql://user:pw@host:5432/spa`).
- [ ] `psycopg2-binary` installed on the runner (it already is — see
      `spa_core/requirements.txt`).
- [ ] Backup of the live SQLite file: `cp spa_core/database/spa.db
      spa_core/database/spa.db.cutover-$(date -u +%F).bak`.
- [ ] Architect proposal + go-live ADR refer to this doc.

## Step 1 — Bootstrap the empty Postgres database

From a workstation with Postgres connectivity:

```bash
export SPA_DATABASE_URL='postgresql://user:pw@host:5432/spa'
cd spa_core/database
alembic upgrade head
```

Expected output ends with:

```
INFO  [alembic.runtime.migration] Running upgrade  -> 0001_initial_schema, initial schema
```

Verify:

```bash
alembic current        # 0001_initial_schema (head)
```

If you need to seed the 15-protocol whitelist:

```bash
cd <repo-root>
python -m spa_core.database.init_db
```

`init_database()` is a no-op for schema in Postgres mode after Alembic
has already created the tables (every CREATE is `IF NOT EXISTS`); it
will only seed the `protocols` rows via `INSERT ... ON CONFLICT DO NOTHING`.

## Step 2 — Copy live data (one-shot)

For the v1.6 paper-trading cutover we only need to move rows from a small
number of high-volume tables: `protocols`, `apy_snapshots`,
`paper_trades`, `strategy_state`, `agent_decisions`. The `message_bus`
and `risk_events` tables are operational and OK to start fresh.

Use the included helper (`spa_core/tools/migrate_sqlite_to_pg.py` — TODO if
not present yet; otherwise hand-write the dump):

```bash
# Dump from SQLite to CSV
python - <<'PY'
import csv, sqlite3, pathlib
src = sqlite3.connect("spa_core/database/spa.db")
src.row_factory = sqlite3.Row
out = pathlib.Path("data/cutover_csv"); out.mkdir(parents=True, exist_ok=True)
for table in ["protocols", "apy_snapshots", "paper_trades",
              "strategy_state", "agent_decisions"]:
    rows = src.execute(f"SELECT * FROM {table}").fetchall()
    if not rows: continue
    fp = out / f"{table}.csv"
    with fp.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(rows[0].keys())
        w.writerows([list(r) for r in rows])
    print(table, len(rows), "->", fp)
PY

# Load into Postgres
for t in protocols apy_snapshots paper_trades strategy_state agent_decisions; do
  psql "$SPA_DATABASE_URL" -c "\\copy $t FROM 'data/cutover_csv/$t.csv' WITH CSV HEADER"
done
```

Verify row counts match.

## Step 3 — Flip the switch

In GitHub Actions (`.github/workflows/spa-run.yml`), add the env var to
the job:

```yaml
env:
  SPA_DATABASE_URL: ${{ secrets.SPA_DATABASE_URL }}
```

For local boxes (Mac Mini, dev laptops): export the same var in the
shell rc file or the launchd plist.

The next cron tick reads/writes Postgres. SQLite is now read-only legacy.

## Step 4 — Validate

After the first post-cutover cycle:

```bash
# Counts should match what the SQLite file held at cutover + new rows.
psql "$SPA_DATABASE_URL" -c "SELECT count(*) FROM apy_snapshots;"
psql "$SPA_DATABASE_URL" -c "SELECT count(*) FROM paper_trades;"

# Alembic version is recorded.
psql "$SPA_DATABASE_URL" -c "SELECT * FROM alembic_version;"

# Application self-check (uses get_connection internally):
python -m spa_core.database.init_db --check
```

The CLI dumps a JSON stats blob:

```json
{ "status": "ok", "backend": "postgres",
  "protocols": 15, "snapshots": N, "trades": N, ... }
```

## Rollback

Two layers of rollback are available.

1. **Soft rollback (preferred during the first week).** Unset
   `SPA_DATABASE_URL` in CI + on operator boxes. The application falls
   back to the SQLite file. Postgres data is retained for diagnosis.
2. **Hard rollback.** `cp spa.db.cutover-YYYY-MM-DD.bak spa.db` and
   restart workflows. Loses any rows written to Postgres after cutover.

## Future migrations

Add a new revision:

```bash
cd spa_core/database
alembic revision -m "describe-change"
# edits versions/<rev>_describe_change.py
alembic upgrade head    # applies locally
git commit ...
```

The CI workflow should run `alembic upgrade head` before the data
pipeline step on every run; this is idempotent on already-migrated
databases.

## Open items for v2.0

* `JSONB` migration of `raw_json` / `state_json` columns (currently `TEXT`).
* Read replica routing for the dashboard.
* Add the `migrate_sqlite_to_pg.py` helper script to the repo so Step 2
  doesn't require ad-hoc heredocs.
