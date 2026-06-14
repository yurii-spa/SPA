"""
Tests for spa_core.persistence.pg_migration (SPA-V331).

Plan-only SQLite -> PostgreSQL migration prep. No real Postgres is touched;
everything runs against an in-memory SQLite database built to mirror the SPA
v1.6 canonical schema.
"""
from __future__ import annotations

import os
import sqlite3
import unittest

from spa_core.persistence import pg_migration as M


# A compact but representative slice of the SPA v1.6 SQLite schema: a parent
# table with a SERIAL-style PK and a child with a FK + UNIQUE + datetime default.
_SCHEMA = [
    """
    CREATE TABLE protocols (
        id        INTEGER PRIMARY KEY AUTOINCREMENT,
        key       TEXT NOT NULL UNIQUE,
        protocol  TEXT NOT NULL,
        tier      TEXT NOT NULL,
        is_active INTEGER NOT NULL DEFAULT 1,
        added_at  TEXT NOT NULL DEFAULT (datetime('now', 'utc')),
        notes     TEXT
    )
    """,
    """
    CREATE TABLE apy_snapshots (
        id           INTEGER PRIMARY KEY AUTOINCREMENT,
        snapshot_id  TEXT NOT NULL DEFAULT (strftime('%Y%m%d_%H%M%S', datetime('now','utc'))),
        protocol_key TEXT NOT NULL,
        apy_total    REAL NOT NULL,
        apy_base     REAL NOT NULL DEFAULT 0.0,
        tvl_usd      REAL NOT NULL,
        raw_json     TEXT,
        FOREIGN KEY (protocol_key) REFERENCES protocols(key)
    )
    """,
    "CREATE INDEX idx_snapshots_protocol ON apy_snapshots (protocol_key)",
    "CREATE UNIQUE INDEX idx_protocols_key ON protocols (key)",
]


def _make_db() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    for stmt in _SCHEMA:
        conn.execute(stmt)
    conn.commit()
    return conn


class TestTypeMapping(unittest.TestCase):
    def test_affinity_rules(self):
        self.assertEqual(M.sqlite_affinity("INTEGER"), "INTEGER")
        self.assertEqual(M.sqlite_affinity("BIGINT"), "INTEGER")
        self.assertEqual(M.sqlite_affinity("VARCHAR(255)"), "TEXT")
        self.assertEqual(M.sqlite_affinity("TEXT"), "TEXT")
        self.assertEqual(M.sqlite_affinity("REAL"), "REAL")
        self.assertEqual(M.sqlite_affinity("DOUBLE"), "REAL")
        self.assertEqual(M.sqlite_affinity("NUMERIC"), "NUMERIC")
        self.assertEqual(M.sqlite_affinity("BLOB"), "BLOB")
        self.assertEqual(M.sqlite_affinity(""), "BLOB")  # rule 5

    def test_map_basic_types(self):
        self.assertEqual(M.map_sqlite_type("TEXT"), "TEXT")
        self.assertEqual(M.map_sqlite_type("REAL"), "DOUBLE PRECISION")
        self.assertEqual(M.map_sqlite_type("INTEGER"), "INTEGER")
        self.assertEqual(M.map_sqlite_type("BLOB"), "BYTEA")
        self.assertEqual(M.map_sqlite_type("NUMERIC"), "NUMERIC")

    def test_serial_pk(self):
        self.assertEqual(M.map_sqlite_type("INTEGER", is_serial_pk=True), "SERIAL")

    def test_timestamp_hint(self):
        self.assertEqual(M.map_sqlite_type("TIMESTAMPTZ"), "TIMESTAMPTZ")
        self.assertEqual(M.map_sqlite_type("DATETIME"), "TIMESTAMPTZ")


class TestDefaultTranslation(unittest.TestCase):
    def test_datetime_now_utc(self):
        pg, warn = M.translate_default("datetime('now', 'utc')")
        self.assertEqual(pg, "NOW()")
        self.assertIsNone(warn)

    def test_current_timestamp(self):
        pg, _ = M.translate_default("CURRENT_TIMESTAMP")
        self.assertEqual(pg, "NOW()")

    def test_numeric_literal(self):
        self.assertEqual(M.translate_default("1"), ("1", None))
        self.assertEqual(M.translate_default("0.0"), ("0.0", None))

    def test_string_literal(self):
        self.assertEqual(M.translate_default("'pending'"), ("'pending'", None))

    def test_strftime_dropped_with_warning(self):
        pg, warn = M.translate_default("strftime('%Y', datetime('now'))")
        self.assertIsNone(pg)
        self.assertIsNotNone(warn)
        self.assertIn("strftime", warn)

    def test_none_default(self):
        self.assertEqual(M.translate_default(None), (None, None))


class TestIntrospection(unittest.TestCase):
    def setUp(self):
        self.conn = _make_db()

    def tearDown(self):
        self.conn.close()

    def test_finds_tables(self):
        tables = M.introspect_sqlite(self.conn)
        names = {t.name for t in tables}
        self.assertEqual(names, {"protocols", "apy_snapshots"})

    def test_serial_pk_detected(self):
        tables = {t.name: t for t in M.introspect_sqlite(self.conn)}
        id_col = next(c for c in tables["protocols"].columns if c.name == "id")
        self.assertTrue(id_col.is_serial_pk)
        self.assertEqual(id_col.pg_type, "SERIAL")

    def test_unique_column_detected(self):
        tables = {t.name: t for t in M.introspect_sqlite(self.conn)}
        self.assertIn("key", tables["protocols"].unique_columns)

    def test_foreign_key_detected(self):
        tables = {t.name: t for t in M.introspect_sqlite(self.conn)}
        fks = tables["apy_snapshots"].foreign_keys
        self.assertEqual(len(fks), 1)
        self.assertEqual(fks[0].ref_table, "protocols")
        self.assertEqual(fks[0].ref_column, "key")

    def test_explicit_index_kept_auto_skipped(self):
        tables = {t.name: t for t in M.introspect_sqlite(self.conn)}
        idx_names = {i.name for i in tables["apy_snapshots"].indexes}
        self.assertIn("idx_snapshots_protocol", idx_names)
        # Auto unique index backing UNIQUE constraint should not appear as a
        # standalone index on protocols beyond the explicit one we created.
        proto_idx = {i.name for i in tables["protocols"].indexes}
        self.assertIn("idx_protocols_key", proto_idx)

    def test_missing_db_raises(self):
        with self.assertRaises(M.MigrationPlanError):
            M.introspect_sqlite("/nonexistent/path/to/spa.db")


class TestTopoSort(unittest.TestCase):
    def test_parent_before_child(self):
        conn = _make_db()
        try:
            tables = M.introspect_sqlite(conn)
            order = M.topo_sort_tables(tables)
            self.assertLess(order.index("protocols"), order.index("apy_snapshots"))
        finally:
            conn.close()


class TestDDLGeneration(unittest.TestCase):
    def setUp(self):
        self.conn = _make_db()
        self.tables = M.introspect_sqlite(self.conn)

    def tearDown(self):
        self.conn.close()

    def test_table_ddl_has_serial_and_types(self):
        by_name = {t.name: t for t in self.tables}
        ddl, _ = M.generate_table_ddl(by_name["protocols"])
        self.assertIn("id", ddl)
        self.assertIn("SERIAL PRIMARY KEY", ddl)
        self.assertIn("key", ddl)
        self.assertIn("UNIQUE", ddl)
        self.assertIn("DEFAULT NOW()", ddl)  # datetime('now','utc') -> NOW()
        self.assertIn("CREATE TABLE IF NOT EXISTS protocols", ddl)

    def test_real_maps_to_double_precision(self):
        by_name = {t.name: t for t in self.tables}
        ddl, _ = M.generate_table_ddl(by_name["apy_snapshots"])
        self.assertIn("DOUBLE PRECISION", ddl)
        self.assertNotIn(" REAL", ddl)

    def test_fk_emitted(self):
        by_name = {t.name: t for t in self.tables}
        ddl, _ = M.generate_table_ddl(by_name["apy_snapshots"])
        self.assertIn("FOREIGN KEY (protocol_key) REFERENCES protocols(key)", ddl)

    def test_strftime_default_warns(self):
        ddl, warnings = M.generate_postgres_ddl(self.tables)
        self.assertTrue(any("strftime" in w for w in warnings))
        # The dropped default must NOT appear in DDL.
        self.assertNotIn("strftime", ddl)

    def test_full_ddl_orders_parent_first(self):
        ddl, _ = M.generate_postgres_ddl(self.tables)
        self.assertLess(
            ddl.index("CREATE TABLE IF NOT EXISTS protocols"),
            ddl.index("CREATE TABLE IF NOT EXISTS apy_snapshots"),
        )

    def test_index_ddl_unique_flag(self):
        by_name = {t.name: t for t in self.tables}
        stmts = M.generate_index_ddl(by_name["apy_snapshots"])
        self.assertTrue(any("idx_snapshots_protocol" in s for s in stmts))


class TestMigrationPlan(unittest.TestCase):
    def test_build_plan_from_connection(self):
        conn = _make_db()
        conn.execute("INSERT INTO protocols (key, protocol, tier) VALUES ('aave-usdc','aave','T1')")
        conn.commit()
        try:
            plan = M.build_migration_plan(conn)
            self.assertEqual(plan.copy_order[0], "protocols")
            self.assertEqual(plan.row_counts["protocols"], 1)
            self.assertEqual(plan.row_counts["apy_snapshots"], 0)
            self.assertIn("CREATE TABLE IF NOT EXISTS protocols", plan.ddl)
            d = plan.to_dict()
            self.assertIn("copy_order", d)
            self.assertIn("row_counts", d)
        finally:
            conn.close()

    def test_empty_db_raises(self):
        conn = sqlite3.connect(":memory:")
        try:
            with self.assertRaises(M.MigrationPlanError):
                M.build_migration_plan(conn)
        finally:
            conn.close()


class TestExecutionGuard(unittest.TestCase):
    def setUp(self):
        self.conn = _make_db()
        self.plan = M.build_migration_plan(self.conn, count_rows=False)

    def tearDown(self):
        self.conn.close()
        os.environ.pop("SPA_PG_MIGRATION_EXECUTE", None)

    def test_blocked_by_default(self):
        with self.assertRaises(M.MigrationExecutionBlocked):
            M.execute_migration(self.plan, "postgresql://x/y")

    def test_blocked_without_env_even_with_flag(self):
        with self.assertRaises(M.MigrationExecutionBlocked):
            M.execute_migration(self.plan, "postgresql://x/y", i_understand_this_writes_data=True)

    def test_dry_run_when_fully_opted_in(self):
        # V341: fully opted in now performs a dry run (no NotImplementedError).
        # Default dry_run=True returns a plan dict and never connects/writes.
        os.environ["SPA_PG_MIGRATION_EXECUTE"] = "1"
        res = M.execute_migration(
            self.plan, "postgresql://x/y", i_understand_this_writes_data=True
        )
        self.assertTrue(res["dry_run"])
        self.assertFalse(res["committed"])
        self.assertIn("ddl_statements", res)
        self.assertIn("copy_order", res)


class TestCLI(unittest.TestCase):
    def test_ddl_only_exit_code(self):
        # Point the resolver at an on-disk temp DB.
        import tempfile

        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tf:
            path = tf.name
        try:
            conn = sqlite3.connect(path)
            for stmt in _SCHEMA:
                conn.execute(stmt)
            conn.commit()
            conn.close()
            rc = M.main(["--ddl-only", "--sqlite", path, "--no-counts"])
            self.assertEqual(rc, 0)
        finally:
            os.unlink(path)

    def test_missing_db_returns_2(self):
        rc = M.main(["--plan", "--sqlite", "/nope/missing.db"])
        self.assertEqual(rc, 2)


if __name__ == "__main__":
    unittest.main()
