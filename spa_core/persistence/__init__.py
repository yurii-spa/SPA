"""
SPA persistence package — SPA-V331.

Houses database migration / persistence tooling that sits one level above the
driver seam in `spa_core.database`. The first inhabitant is `pg_migration`,
which prepares (but does NOT execute) a SQLite → PostgreSQL migration.
"""
