# ADR-005: PostgreSQL Migration Plan (BL-008)

Date: 2026-05-27
Status: ACCEPTED (Phase 1 implemented)
Supersedes: nothing
Related: BL-008 (Architect proposal, 16h)

## Context

SPA currently persists all state — protocols whitelist, APY snapshots,
paper trades, risk events, strategy state, the inter-agent message bus and
the agent-decision audit trail — in a single SQLite file at
`spa_core/database/spa.db`. SQLite has been excellent for the paper-trading
development loop (zero-ops, file-copyable, embeddable in pytest), but the
go-live target requires:

* **Concurrent writers** — multiple agents and a REST API hitting the DB
  simultaneously, which SQLite handles only with global write locks.
* **Operational tooling** — backups, replicas, point-in-time recovery,
  managed hosting, metrics. All standard for Postgres, all DIY for SQLite.
* **Stronger typing** — `TIMESTAMPTZ`, `JSONB`, real `BOOLEAN`.

We need a path from "SQLite everywhere" to "Postgres in production" that
does not freeze feature work for the duration of the migration.

## Decision

Adopt an **environment-driven dual-driver** approach. A new module
`spa_core.database.connection` exposes a single `get_connection()` context
manager that picks the backend based on `SPA_DATABASE_URL`:

* unset → existing SQLite file (default; preserves dev loop)
* `sqlite:///path.db` → SQLite at that path
* `postgresql://...` / `postgres://...` → Postgres via psycopg2

The PG schema lives alongside the SQLite schema as
`spa_core/database/schema_postgres.sql`, hand-translated for SERIAL primary
keys, `DOUBLE PRECISION`, `TIMESTAMPTZ DEFAULT NOW()`, and removal of
SQLite-specific `strftime`/`PRAGMA` constructs.

### Phasing

* **Phase 1 — Scaffold (this sprint).** Add `db_url.py`, `connection.py`,
  `schema_postgres.sql`, unit tests, and this ADR. **No call-sites are
  modified**: every existing `sqlite3.connect(...)` keeps working
  unchanged. psycopg2-binary is listed in `requirements.txt` but the code
  imports it lazily so a SQLite-only install still works if pip skips
  optional deps.
* **Phase 2 — Migrate call-sites (next sprint, ~6h).** Replace
  `sqlite3.connect(...)` in `defillama_fetcher`, `init_db`, `data_agent`
  and the ~12 indirect consumers with `connection.get_connection(...)`.
  Run the existing pytest suite against both backends in CI.
* **Phase 3 — Production cutover (~4h).** Introduce Alembic migrations,
  seed a managed Postgres instance, dual-write briefly, then flip
  `SPA_DATABASE_URL` and decommission the SQLite file.

## Alternatives considered

* **SQLAlchemy ORM.** Cleanest long-term, but requires rewriting every
  query as ORM models — too much refactor for the value at this stage,
  and we lose the very readable raw SQL.
* **Hard replace (Postgres only, no fallback).** Would break the local
  dev loop and pytest's `:memory:` patterns. Rejected.
* **Sqlitedict / DuckDB.** Don't solve the concurrency / managed-hosting
  problem.

## Risk mitigation

* **Binary feature flag.** The whole switch is one env var. `unset` →
  pre-BL-008 behaviour, byte-identical. Rollback is `unset SPA_DATABASE_URL`
  plus a restart.
* **Lazy driver import.** A box without psycopg2 still boots in SQLite
  mode; the Postgres branch only fails when actually selected.
* **Schema files diverge intentionally.** No clever cross-dialect SQL —
  each backend gets its own file, reviewed independently.

## Out of scope (for now)

JSONB migration of `raw_json` / `state_json`, full-text search,
read-replica routing. Revisit after Phase 3.

---

## Phase 2 — Done (MP-210, 2026-06-11)

All `sqlite3.connect(...)` call-sites outside the abstraction layer and the
intentionally-raw files have been migrated to `get_connection()`.

### Migrated files

| File | Change |
|---|---|
| `spa_core/database/init_db.py` | Removed `import sqlite3`; replaced `with sqlite3.connect(str(path)) as conn:` in `init_database()` with `with _abstract_get_connection(f"sqlite:///{path}") as conn:` |
| `spa_core/persistence/db.py` | Converted local `get_connection(db_path)` factory function to a `@contextmanager` delegating to `spa_core.database.connection.get_connection`; migrated all 9 public functions (`init_db`, `upsert_equity_point`, `get_equity_curve`, `upsert_daily_report`, `get_daily_report`, `upsert_analytics`, `get_analytics`, `upsert_allocation`, `get_allocation_history`) from `conn = …; try/finally conn.close()` to `with get_connection(…) as conn:` |

### New files

| File | Purpose |
|---|---|
| `spa_core/database/migrate_callsites.py` | Verification utility — `find_raw_sqlite_connects()` + `run_verification()` + CLI; test 35 (live codebase scan) confirms 0 raw connects remain |
| `spa_core/tests/test_postgres_migration.py` | 45 tests covering db_url, connection, init_db, migrate_callsites, and db.py regression |

### Intentionally excluded (raw sqlite3 kept)

- `spa_core/database/connection.py` — the abstraction itself
- `spa_core/persistence/pg_migration.py` — migration utility, supports both backends
- `spa_core/persistence/track_store.py` — scratch DBs, intentionally raw

### Verification

```
python3 -m spa_core.database.migrate_callsites
# → "✓ Phase 2 complete — no raw sqlite3.connect() found"
```

Phase 3 (Alembic + production cutover) remains out of scope until the paper
track record qualifies for go-live (ADR-002).
