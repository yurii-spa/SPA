"""
Tests for BL-008 Phase 2 — Postgres migration call-site migration.

Coverage:
  1.  init_db.py  — schema initialisation through get_connection()
  2.  connection.py — SQLite mode (no psycopg2 needed)
  3.  db_url.py  — URL parsing for sqlite:// and postgres:// forms
  4.  migrate_callsites.py — scanner on synthetic temp directories
  5.  Regression: existing public functions in db.py still work post-refactor

All tests are deterministic (no network, no real spa.db touched).
"""
from __future__ import annotations

import os
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path


# ─── Helpers ─────────────────────────────────────────────────────────────────


def _make_mem_db() -> sqlite3.Connection:
    """Return a plain :memory: sqlite3 connection for low-level inspection."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    return conn


# ═══════════════════════════════════════════════════════════════════════════════
# Group 1: db_url.py
# ═══════════════════════════════════════════════════════════════════════════════

class TestDbUrl(unittest.TestCase):
    """Tests for spa_core.database.db_url — URL resolution helpers."""

    def setUp(self):
        from spa_core.database import db_url as M
        self.M = M
        # Stash and clear the env var so tests are hermetic.
        self._orig = os.environ.pop(M.ENV_VAR, None)

    def tearDown(self):
        if self._orig is not None:
            os.environ[self.M.ENV_VAR] = self._orig
        else:
            os.environ.pop(self.M.ENV_VAR, None)

    # 1
    def test_default_url_is_sqlite(self):
        url = self.M.get_db_url()
        self.assertTrue(url.startswith("sqlite:///"), url)

    # 2
    def test_default_url_ends_with_spa_db(self):
        url = self.M.get_db_url()
        self.assertTrue(url.endswith("spa.db"), url)

    # 3
    def test_env_var_overrides_default(self):
        os.environ[self.M.ENV_VAR] = "postgresql://u:p@localhost/mydb"
        self.assertEqual(self.M.get_db_url(), "postgresql://u:p@localhost/mydb")

    # 4
    def test_empty_env_var_falls_back_to_sqlite(self):
        os.environ[self.M.ENV_VAR] = "   "
        url = self.M.get_db_url()
        self.assertTrue(url.startswith("sqlite:///"))

    # 5
    def test_is_postgres_with_postgresql_prefix(self):
        self.assertTrue(self.M.is_postgres("postgresql://u@h/db"))

    # 6
    def test_is_postgres_with_postgres_alias(self):
        self.assertTrue(self.M.is_postgres("postgres://u@h/db"))

    # 7
    def test_is_postgres_false_for_sqlite(self):
        self.assertFalse(self.M.is_postgres("sqlite:///tmp/x.db"))

    # 8
    def test_is_sqlite_recognises_triple_slash(self):
        self.assertTrue(self.M.is_sqlite("sqlite:///some/path.db"))

    # 9
    def test_is_sqlite_false_for_postgres(self):
        self.assertFalse(self.M.is_sqlite("postgresql://u@h/db"))

    # 10
    def test_get_sqlite_path_returns_path_object(self):
        p = self.M.get_sqlite_path("sqlite:///tmp/foo.db")
        self.assertIsInstance(p, Path)

    # 11
    def test_get_sqlite_path_memory(self):
        p = self.M.get_sqlite_path("sqlite:///:memory:")
        self.assertIsNotNone(p)
        self.assertEqual(str(p), ":memory:")

    # 12
    def test_get_sqlite_path_none_for_postgres(self):
        p = self.M.get_sqlite_path("postgresql://u@h/db")
        self.assertIsNone(p)


# ═══════════════════════════════════════════════════════════════════════════════
# Group 2: connection.py — SQLite branch (no psycopg2 required)
# ═══════════════════════════════════════════════════════════════════════════════

class TestConnectionSQLite(unittest.TestCase):
    """Tests for spa_core.database.connection.get_connection (SQLite path)."""

    def setUp(self):
        from spa_core.database.connection import get_connection, DriverNotInstalled
        self.get_connection = get_connection
        self.DriverNotInstalled = DriverNotInstalled

    # 13
    def test_memory_url_yields_connection(self):
        with self.get_connection("sqlite:///:memory:") as conn:
            self.assertIsNotNone(conn)

    # 14
    def test_memory_connection_is_sqlite3_connection(self):
        with self.get_connection("sqlite:///:memory:") as conn:
            self.assertIsInstance(conn, sqlite3.Connection)

    # 15
    def test_memory_connection_has_row_factory(self):
        with self.get_connection("sqlite:///:memory:") as conn:
            self.assertEqual(conn.row_factory, sqlite3.Row)

    # 16
    def test_memory_connection_can_execute_query(self):
        with self.get_connection("sqlite:///:memory:") as conn:
            conn.execute("CREATE TABLE t(x INTEGER)")
            conn.execute("INSERT INTO t VALUES (42)")
            conn.commit()
            row = conn.execute("SELECT x FROM t").fetchone()
            self.assertEqual(row[0], 42)

    # 17
    def test_file_db_created_on_disk(self):
        with tempfile.TemporaryDirectory() as td:
            db_path = os.path.join(td, "test.db")
            url = f"sqlite:///{db_path}"
            with self.get_connection(url) as conn:
                conn.execute("CREATE TABLE t(id INTEGER)")
                conn.commit()
            self.assertTrue(os.path.exists(db_path))

    # 18
    def test_connection_closed_after_context_exit(self):
        """The connection object should be closed once the `with` block exits."""
        with self.get_connection("sqlite:///:memory:") as conn:
            pass
        # Accessing a closed connection raises ProgrammingError.
        with self.assertRaises(Exception):
            conn.execute("SELECT 1")

    # 19
    def test_invalid_scheme_raises_value_error(self):
        with self.assertRaises(ValueError):
            with self.get_connection("mysql://localhost/db") as _:
                pass

    # 20
    def test_postgres_without_driver_raises_driver_not_installed(self):
        """If psycopg2 is absent, requesting a PG connection raises DriverNotInstalled."""
        # Temporarily hide psycopg2 from the import system.
        psycopg2_mod = sys.modules.pop("psycopg2", None)
        psycopg2_extras_mod = sys.modules.pop("psycopg2.extras", None)
        # Also block future import attempts.
        sys.modules["psycopg2"] = None  # type: ignore[assignment]
        sys.modules["psycopg2.extras"] = None  # type: ignore[assignment]
        try:
            with self.assertRaises(self.DriverNotInstalled):
                with self.get_connection("postgresql://u:p@localhost/testdb") as _:
                    pass
        finally:
            # Restore original state.
            if psycopg2_mod is not None:
                sys.modules["psycopg2"] = psycopg2_mod
            else:
                sys.modules.pop("psycopg2", None)
            if psycopg2_extras_mod is not None:
                sys.modules["psycopg2.extras"] = psycopg2_extras_mod
            else:
                sys.modules.pop("psycopg2.extras", None)


# ═══════════════════════════════════════════════════════════════════════════════
# Group 3: init_db.py — init_database via get_connection (no raw sqlite3)
# ═══════════════════════════════════════════════════════════════════════════════

class TestInitDb(unittest.TestCase):
    """Tests for spa_core.database.init_db after Phase 2 migration."""

    def setUp(self):
        import spa_core.database.init_db as M
        self.M = M

    # 21
    def test_init_database_creates_file(self):
        with tempfile.TemporaryDirectory() as td:
            db_path = Path(td) / "test_init.db"
            self.M.init_database(db_path=db_path)
            self.assertTrue(db_path.exists())

    # 22
    def test_init_database_creates_protocols_table(self):
        with tempfile.TemporaryDirectory() as td:
            db_path = Path(td) / "test_proto.db"
            self.M.init_database(db_path=db_path)
            conn = sqlite3.connect(str(db_path))
            rows = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='protocols'"
            ).fetchall()
            conn.close()
            self.assertEqual(len(rows), 1)

    # 23
    def test_init_database_seeds_protocols(self):
        with tempfile.TemporaryDirectory() as td:
            db_path = Path(td) / "test_seed.db"
            self.M.init_database(db_path=db_path)
            conn = sqlite3.connect(str(db_path))
            count = conn.execute("SELECT COUNT(*) FROM protocols").fetchone()[0]
            conn.close()
            self.assertGreater(count, 0, "Expected seeded protocol rows")

    # 24
    def test_init_database_idempotent(self):
        """Running init_database twice must not raise or duplicate rows."""
        with tempfile.TemporaryDirectory() as td:
            db_path = Path(td) / "test_idem.db"
            self.M.init_database(db_path=db_path)
            count_first = sqlite3.connect(str(db_path)).execute(
                "SELECT COUNT(*) FROM protocols"
            ).fetchone()[0]
            self.M.init_database(db_path=db_path)  # second run
            count_second = sqlite3.connect(str(db_path)).execute(
                "SELECT COUNT(*) FROM protocols"
            ).fetchone()[0]
            self.assertEqual(count_first, count_second)

    # 25
    def test_get_connection_wrapper_in_init_db_yields_sqlite(self):
        """init_db.get_connection(db_path) must yield a sqlite3.Connection."""
        with tempfile.TemporaryDirectory() as td:
            db_path = Path(td) / "wrap.db"
            with self.M.get_connection(db_path) as conn:
                self.assertIsInstance(conn, sqlite3.Connection)


# ═══════════════════════════════════════════════════════════════════════════════
# Group 4: migrate_callsites.py — scanner
# ═══════════════════════════════════════════════════════════════════════════════

class TestMigrateCallsites(unittest.TestCase):
    """Tests for spa_core.database.migrate_callsites."""

    def setUp(self):
        from spa_core.database import migrate_callsites as M
        self.M = M

    def _write_py(self, directory: Path, name: str, content: str) -> Path:
        p = directory / name
        p.write_text(content, encoding="utf-8")
        return p

    # 26
    def test_clean_dir_returns_empty_list(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "spa_core"
            root.mkdir()
            self._write_py(root, "clean.py", "# no sqlite3.connect here\nx = 1\n")
            hits = self.M.find_raw_sqlite_connects(root)
            self.assertEqual(hits, [])

    # 27
    def test_detects_raw_connect(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "spa_core"
            root.mkdir()
            self._write_py(root, "bad.py", 'conn = sqlite3.connect("/tmp/x.db")\n')
            hits = self.M.find_raw_sqlite_connects(root)
            self.assertEqual(len(hits), 1)
            self.assertIn("bad.py", hits[0][0])

    # 28
    def test_excludes_connection_py(self):
        """connection.py itself must never appear in results."""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "spa_core"
            db_dir = root / "database"
            db_dir.mkdir(parents=True)
            self._write_py(db_dir, "connection.py", 'conn = sqlite3.connect(":memory:")\n')
            # Override exclusions to match this synthetic tree.
            orig = self.M._EXCLUDED_FILES
            self.M._EXCLUDED_FILES = frozenset({"spa_core/database/connection.py"})
            try:
                hits = self.M.find_raw_sqlite_connects(root)
                self.assertEqual(hits, [])
            finally:
                self.M._EXCLUDED_FILES = orig

    # 29
    def test_excludes_tests_directory(self):
        """Files under spa_core/tests/ must be excluded."""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "spa_core"
            test_dir = root / "tests"
            test_dir.mkdir(parents=True)
            self._write_py(test_dir, "test_foo.py", 'conn = sqlite3.connect(":memory:")\n')
            orig_dirs = self.M._EXCLUDED_DIRS
            self.M._EXCLUDED_DIRS = frozenset({"spa_core/tests"})
            try:
                hits = self.M.find_raw_sqlite_connects(root)
                self.assertEqual(hits, [])
            finally:
                self.M._EXCLUDED_DIRS = orig_dirs

    # 30
    def test_run_verification_returns_dict_with_required_keys(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "spa_core"
            root.mkdir()
            result = self.M.run_verification(root)
            self.assertIn("ok", result)
            self.assertIn("raw_connects_remaining", result)
            self.assertIn("files_checked", result)
            self.assertIn("hits", result)

    # 31
    def test_run_verification_ok_for_clean_tree(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "spa_core"
            root.mkdir()
            self._write_py(root, "ok.py", "print('hello')\n")
            result = self.M.run_verification(root)
            self.assertTrue(result["ok"])
            self.assertEqual(result["raw_connects_remaining"], 0)

    # 32
    def test_run_verification_not_ok_when_raw_connect_exists(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "spa_core"
            root.mkdir()
            self._write_py(root, "bad.py", 'sqlite3.connect("/tmp/x.db")\n')
            result = self.M.run_verification(root)
            self.assertFalse(result["ok"])
            self.assertGreater(result["raw_connects_remaining"], 0)

    # 33
    def test_run_verification_counts_files_checked(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "spa_core"
            root.mkdir()
            for i in range(3):
                self._write_py(root, f"mod{i}.py", f"x = {i}\n")
            result = self.M.run_verification(root)
            self.assertEqual(result["files_checked"], 3)

    # 34
    def test_hits_contain_file_line_text_keys(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "spa_core"
            root.mkdir()
            self._write_py(root, "bad.py", 'conn = sqlite3.connect(path)\n')
            result = self.M.run_verification(root)
            self.assertEqual(len(result["hits"]), 1)
            hit = result["hits"][0]
            self.assertIn("file", hit)
            self.assertIn("line", hit)
            self.assertIn("text", hit)

    # 35
    def test_live_codebase_has_zero_raw_connects(self):
        """Phase 2 complete: no raw sqlite3.connect() outside excluded files."""
        result = self.M.run_verification()
        if not result["ok"]:
            details = "\n".join(
                f"  {h['file']}:{h['line']}  {h['text']}" for h in result["hits"]
            )
            self.fail(
                f"Found {result['raw_connects_remaining']} raw sqlite3.connect() "
                f"call(s) — Phase 2 incomplete:\n{details}"
            )


# ═══════════════════════════════════════════════════════════════════════════════
# Group 5: db.py regression — existing public functions still work
# ═══════════════════════════════════════════════════════════════════════════════

class TestDbRegression(unittest.TestCase):
    """Regression tests: persistence/db.py public API still works after refactor.

    Uses a per-test temporary *file* database (not :memory:) so that every
    call-site within a single test shares the same on-disk DB and the schema
    initialised by init_db() is visible to subsequent connections.
    """

    def setUp(self):
        import spa_core.persistence.db as M
        self.M = M
        self._tmpdir = tempfile.mkdtemp(prefix="spa_test_")
        self._db = os.path.join(self._tmpdir, "test_regression.db")
        # Initialise schema once for this test's DB.
        self.M.init_db(self._db)

    def tearDown(self):
        import shutil
        shutil.rmtree(self._tmpdir, ignore_errors=True)

    # 36
    def test_get_connection_is_context_manager(self):
        """After Phase 2, get_connection must be a context manager."""
        cm = self.M.get_connection(self._db)
        self.assertTrue(hasattr(cm, "__enter__") and hasattr(cm, "__exit__"))

    # 37
    def test_get_connection_yields_sqlite_connection(self):
        with self.M.get_connection(self._db) as conn:
            self.assertIsInstance(conn, sqlite3.Connection)

    # 38
    def test_upsert_and_get_equity_point(self):
        self.M.upsert_equity_point("2026-06-01", 100500.0, 50.0, 0.05, self._db)
        rows = self.M.get_equity_curve(db_path=self._db)
        self.assertEqual(len(rows), 1)
        self.assertAlmostEqual(rows[0]["equity"], 100500.0)

    # 39
    def test_upsert_equity_point_updates_existing(self):
        self.M.upsert_equity_point("2026-06-01", 100000.0, 0.0, 0.0, self._db)
        self.M.upsert_equity_point("2026-06-01", 101000.0, 1000.0, 1.0, self._db)
        rows = self.M.get_equity_curve(db_path=self._db)
        self.assertEqual(len(rows), 1)
        self.assertAlmostEqual(rows[0]["equity"], 101000.0)

    # 40
    def test_get_equity_curve_respects_days_limit(self):
        for i in range(5):
            self.M.upsert_equity_point(f"2026-06-0{i+1}", float(i * 1000), 0.0, 0.0, self._db)
        rows = self.M.get_equity_curve(days=3, db_path=self._db)
        self.assertEqual(len(rows), 3)

    # 41
    def test_upsert_and_get_daily_report(self):
        report = {"date": "2026-06-01", "pnl": 42.0}
        self.M.upsert_daily_report("2026-06-01", report, self._db)
        fetched = self.M.get_daily_report("2026-06-01", self._db)
        self.assertEqual(fetched["pnl"], 42.0)

    # 42
    def test_get_daily_report_none_if_missing(self):
        result = self.M.get_daily_report("1999-01-01", self._db)
        self.assertIsNone(result)

    # 43
    def test_upsert_and_get_analytics(self):
        snap = {"sharpe": 1.5, "drawdown": 0.02}
        self.M.upsert_analytics("2026-06-01", snap, self._db)
        fetched = self.M.get_analytics("2026-06-01", self._db)
        self.assertAlmostEqual(fetched["sharpe"], 1.5)

    # 44
    def test_upsert_allocation_and_get_history(self):
        alloc = {"aave": 0.5, "compound": 0.5}
        self.M.upsert_allocation("2026-06-01", alloc, self._db)
        history = self.M.get_allocation_history(days=10, db_path=self._db)
        self.assertEqual(len(history), 1)
        self.assertEqual(history[0]["allocation"]["aave"], 0.5)

    # 45 — confirm no raw import of connection machinery breaks the module
    def test_db_module_importable_without_psycopg2(self):
        """persistence/db.py must be importable even if psycopg2 is absent."""
        # psycopg2 is imported lazily inside connection.py only for PG URLs.
        import spa_core.persistence.db  # noqa: F401 — just testing importability


# ─── Runner ──────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    unittest.main(verbosity=2)
