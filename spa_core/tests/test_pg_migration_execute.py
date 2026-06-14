"""
SPA-V341 — tests for the gated PostgreSQL migration *execution* path.

These tests are fully offline: PostgreSQL is replaced by a fake DB-API
connection/cursor that records every statement and parameter set, and the
SQLite source is an in-memory database. No psycopg2, no network, no real DB.

Coverage:
  * execution is BLOCKED unless both the env flag and the opt-in are set;
  * dry_run (default) reports the ordered DDL + copy plan WITHOUT connecting;
  * a real run (dry_run=False) applies DDL then copies rows table-by-table in
    FK-safe order, commits, and returns accurate per-table counts;
  * dry_run=False without a sqlite_source raises MigrationPlanError;
  * generated schema DDL is idempotent (CREATE ... IF NOT EXISTS);
  * an error mid-copy triggers rollback and propagates;
  * batching splits large copies into multiple executemany calls;
  * split_sql_statements drops comments/blank fragments.
"""
import sqlite3

import pytest

from spa_core.persistence import pg_migration as pg


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


class FakeCursor:
    def __init__(self, conn, fail_on=None):
        self._conn = conn
        self._fail_on = fail_on  # substring that makes execute/executemany raise

    def execute(self, sql, params=None):
        if self._fail_on and self._fail_on in sql:
            raise RuntimeError(f"boom on: {sql[:40]}")
        self._conn.executed.append((sql, params))

    def executemany(self, sql, seq_of_params):
        seq = list(seq_of_params)
        if self._fail_on and self._fail_on in sql:
            raise RuntimeError(f"boom on many: {sql[:40]}")
        self._conn.executemany_calls.append((sql, seq))
        for p in seq:
            self._conn.inserted.setdefault(sql, []).append(p)

    def close(self):
        pass


class FakeConnection:
    def __init__(self, fail_on=None):
        self.executed = []          # list of (sql, params) from execute()
        self.executemany_calls = [] # list of (sql, rows) from executemany()
        self.inserted = {}          # sql -> [rows]
        self.committed = False
        self.rolled_back = False
        self.closed = False
        self._fail_on = fail_on

    def cursor(self):
        return FakeCursor(self, fail_on=self._fail_on)

    def commit(self):
        self.committed = True

    def rollback(self):
        self.rolled_back = True

    def close(self):
        self.closed = True


def make_factory(conn):
    created = {"count": 0, "url": None}

    def factory(pg_url):
        created["count"] += 1
        created["url"] = pg_url
        return conn

    factory.created = created
    return factory


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def sqlite_conn():
    """In-memory SQLite with a parent/child FK relationship + sample rows."""
    conn = sqlite3.connect(":memory:")
    conn.executescript(
        """
        CREATE TABLE authors (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL
        );
        CREATE TABLE books (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            author_id INTEGER NOT NULL,
            title TEXT NOT NULL,
            FOREIGN KEY (author_id) REFERENCES authors(id)
        );
        CREATE INDEX idx_books_author ON books(author_id);
        INSERT INTO authors (id, name) VALUES (1, 'Ada'), (2, 'Bob');
        INSERT INTO books (id, author_id, title) VALUES
            (1, 1, 'Notes'), (2, 1, 'Essays'), (3, 2, 'Poems');
        """
    )
    conn.commit()
    yield conn
    conn.close()


@pytest.fixture
def plan(sqlite_conn):
    return pg.build_migration_plan(sqlite_conn, count_rows=True)


@pytest.fixture
def enable_execute(monkeypatch):
    monkeypatch.setenv("SPA_PG_MIGRATION_EXECUTE", "1")


# ---------------------------------------------------------------------------
# Gating
# ---------------------------------------------------------------------------


def test_blocked_without_env_or_optin(plan, monkeypatch):
    monkeypatch.delenv("SPA_PG_MIGRATION_EXECUTE", raising=False)
    with pytest.raises(pg.MigrationExecutionBlocked):
        pg.execute_migration(plan, "postgres://x", i_understand_this_writes_data=True)


def test_blocked_with_env_but_no_optin(plan, enable_execute):
    with pytest.raises(pg.MigrationExecutionBlocked):
        pg.execute_migration(plan, "postgres://x", i_understand_this_writes_data=False)


def test_blocked_with_optin_but_no_env(plan, monkeypatch):
    monkeypatch.delenv("SPA_PG_MIGRATION_EXECUTE", raising=False)
    with pytest.raises(pg.MigrationExecutionBlocked):
        pg.execute_migration(plan, "postgres://x", i_understand_this_writes_data=True)


# ---------------------------------------------------------------------------
# Dry run
# ---------------------------------------------------------------------------


def test_dry_run_reports_without_connecting(plan, enable_execute):
    conn = FakeConnection()
    factory = make_factory(conn)
    res = pg.execute_migration(
        plan, "postgres://x",
        i_understand_this_writes_data=True,
        connection_factory=factory,
        dry_run=True,
    )
    assert res["dry_run"] is True
    assert res["committed"] is False
    # The factory must never be invoked on a dry run.
    assert factory.created["count"] == 0
    assert conn.committed is False
    # FK-safe order: authors before books.
    assert res["copy_order"].index("authors") < res["copy_order"].index("books")
    # DDL statements are reported.
    assert any("CREATE TABLE IF NOT EXISTS authors" in s for s in res["ddl_statements"])


def test_dry_run_is_the_default(plan, enable_execute):
    conn = FakeConnection()
    factory = make_factory(conn)
    res = pg.execute_migration(
        plan, "postgres://x",
        i_understand_this_writes_data=True,
        connection_factory=factory,
    )
    assert res["dry_run"] is True
    assert factory.created["count"] == 0


# ---------------------------------------------------------------------------
# Real run
# ---------------------------------------------------------------------------


def test_real_run_applies_ddl_and_copies_rows(plan, sqlite_conn, enable_execute):
    conn = FakeConnection()
    factory = make_factory(conn)
    res = pg.execute_migration(
        plan, "postgres://x",
        i_understand_this_writes_data=True,
        sqlite_source=sqlite_conn,
        connection_factory=factory,
        dry_run=False,
    )
    assert res["dry_run"] is False
    assert res["committed"] is True
    assert conn.committed is True
    assert conn.closed is True
    assert factory.created["count"] == 1
    assert factory.created["url"] == "postgres://x"

    # Row counts copied correctly.
    assert res["rows_copied"]["authors"] == 2
    assert res["rows_copied"]["books"] == 3

    # DDL was applied via execute() (CREATE statements recorded).
    create_sql = [s for s, _ in conn.executed if s.startswith("CREATE TABLE")]
    assert any("authors" in s for s in create_sql)
    assert any("books" in s for s in create_sql)

    # INSERTs are parameterized with %s placeholders (Postgres style).
    insert_sqls = list(conn.inserted.keys())
    assert all("%s" in s for s in insert_sqls)
    assert any("INSERT INTO authors" in s for s in insert_sqls)


def test_real_run_copies_fk_safe_order(plan, sqlite_conn, enable_execute):
    conn = FakeConnection()
    res = pg.execute_migration(
        plan, "postgres://x",
        i_understand_this_writes_data=True,
        sqlite_source=sqlite_conn,
        connection_factory=make_factory(conn),
        dry_run=False,
    )
    # Order of executemany INSERTs: authors must precede books.
    insert_order = [sql for sql, _ in conn.executemany_calls]
    a_idx = next(i for i, s in enumerate(insert_order) if "INSERT INTO authors" in s)
    b_idx = next(i for i, s in enumerate(insert_order) if "INSERT INTO books" in s)
    assert a_idx < b_idx
    assert res["committed"] is True


def test_real_run_requires_sqlite_source(plan, enable_execute):
    conn = FakeConnection()
    with pytest.raises(pg.MigrationPlanError):
        pg.execute_migration(
            plan, "postgres://x",
            i_understand_this_writes_data=True,
            connection_factory=make_factory(conn),
            dry_run=False,
        )


def test_error_mid_copy_rolls_back(plan, sqlite_conn, enable_execute):
    # Fail when inserting into books -> rollback, no commit, error propagates.
    conn = FakeConnection(fail_on="INSERT INTO books")
    with pytest.raises(RuntimeError):
        pg.execute_migration(
            plan, "postgres://x",
            i_understand_this_writes_data=True,
            sqlite_source=sqlite_conn,
            connection_factory=make_factory(conn),
            dry_run=False,
        )
    assert conn.rolled_back is True
    assert conn.committed is False
    assert conn.closed is True


def test_batching_splits_large_copies(enable_execute):
    # Build a source with more rows than the batch size.
    sconn = sqlite3.connect(":memory:")
    sconn.executescript(
        "CREATE TABLE nums (id INTEGER PRIMARY KEY AUTOINCREMENT, v INTEGER NOT NULL);"
    )
    sconn.executemany(
        "INSERT INTO nums (v) VALUES (?)", [(i,) for i in range(250)]
    )
    sconn.commit()
    plan = pg.build_migration_plan(sconn, count_rows=True)

    conn = FakeConnection()
    res = pg.execute_migration(
        plan, "postgres://x",
        i_understand_this_writes_data=True,
        sqlite_source=sconn,
        connection_factory=make_factory(conn),
        dry_run=False,
        batch_size=100,
    )
    assert res["rows_copied"]["nums"] == 250
    # 250 rows / batch 100 -> 3 executemany calls (100, 100, 50).
    nums_calls = [rows for sql, rows in conn.executemany_calls if "nums" in sql]
    assert [len(r) for r in nums_calls] == [100, 100, 50]
    sconn.close()


# ---------------------------------------------------------------------------
# Statement splitting
# ---------------------------------------------------------------------------


def test_split_sql_statements_drops_comments_and_blanks():
    ddl = (
        "-- header comment\n"
        "CREATE TABLE IF NOT EXISTS a (\n    id INTEGER PRIMARY KEY\n);\n"
        "\n"
        "-- Indexes\n"
        "CREATE INDEX IF NOT EXISTS ix ON a (id);\n"
    )
    stmts = pg.split_sql_statements(ddl)
    assert len(stmts) == 2
    assert stmts[0].startswith("CREATE TABLE IF NOT EXISTS a")
    assert stmts[1].startswith("CREATE INDEX IF NOT EXISTS ix")
    assert all(s.endswith(";") for s in stmts)
    assert not any("--" in s for s in stmts)


def test_generated_ddl_is_idempotent(plan):
    # Every CREATE in the plan must use IF NOT EXISTS so re-runs are safe.
    for stmt in pg.split_sql_statements(plan.ddl):
        if stmt.upper().startswith("CREATE TABLE"):
            assert "IF NOT EXISTS" in stmt.upper()
        if stmt.upper().startswith("CREATE") and "INDEX" in stmt.upper():
            assert "IF NOT EXISTS" in stmt.upper()
