"""
spa_core/tests/test_academy_db.py

Tests for the Academy SQLite data layer (spa_core/academy/db.py).

stdlib + pytest only. Every test uses a throwaway tmp-file DB (never the repo
data/ dir). SPA_ACADEMY_DB is exercised for the raise-on-unset contract.
"""

from __future__ import annotations

import sqlite3

import pytest

from spa_core.academy.db import AcademyDB, MIGRATIONS_DIR


EXPECTED_TABLES = {
    "schema_migrations",
    "users",
    "invite_codes",
    "sessions",
    "progress",
    "wallets",
    "siwe_nonces",
    "quiz_results",
    "notes",
    "events",
    "used_tx_hashes",
}


@pytest.fixture()
def db(tmp_path):
    """A migrated AcademyDB on a tmp-file path."""
    path = tmp_path / "academy_test.db"
    d = AcademyDB(db_path=str(path))
    d.run_migrations()
    return d


# ── Migrations ─────────────────────────────────────────────────────────────


def test_migrations_apply_without_error(tmp_path):
    d = AcademyDB(db_path=str(tmp_path / "a.db"))
    applied = d.run_migrations()
    assert applied == [1]


def test_init_db_is_idempotent(db):
    # Second run applies nothing and does not raise.
    applied_again = db.run_migrations()
    assert applied_again == []
    assert db.schema_version() == 1


def test_schema_migrations_records_version_1(db):
    with db.connect() as conn:
        rows = [r["version"] for r in conn.execute("SELECT version FROM schema_migrations")]
    assert rows == [1]


def test_all_tables_exist(db):
    with db.connect() as conn:
        names = {
            r["name"]
            for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
    assert EXPECTED_TABLES.issubset(names)


# ── Append-only events triggers ────────────────────────────────────────────


def _insert_event(conn):
    conn.execute(
        "INSERT INTO events(action, payload_json) VALUES ('test', '{}')"
    )


def test_events_no_update_trigger(db):
    with db.connect() as conn:
        _insert_event(conn)
    with pytest.raises(sqlite3.IntegrityError):
        with db.connect() as conn:
            conn.execute("UPDATE events SET action='changed' WHERE id=1")


def test_events_no_delete_trigger(db):
    with db.connect() as conn:
        _insert_event(conn)
    with pytest.raises(sqlite3.IntegrityError):
        with db.connect() as conn:
            conn.execute("DELETE FROM events WHERE id=1")


# ── Constraints / indexes ──────────────────────────────────────────────────


def _make_user(conn, email="owner@example.com"):
    cur = conn.execute(
        "INSERT INTO users(email, password_hash, is_owner) VALUES (?, 'x', 1)",
        (email,),
    )
    return cur.lastrowid


def test_wallet_verified_unique_index(db):
    with db.connect() as conn:
        u1 = _make_user(conn, "a@example.com")
        u2 = _make_user(conn, "b@example.com")
        conn.execute(
            "INSERT INTO wallets(user_id, address, chain, verified_at) "
            "VALUES (?, '0xABC', 'base', datetime('now'))",
            (u1,),
        )
    # Same address+chain verified by a different user must collide.
    with pytest.raises(sqlite3.IntegrityError):
        with db.connect() as conn:
            conn.execute(
                "INSERT INTO wallets(user_id, address, chain, verified_at) "
                "VALUES (?, '0xabc', 'base', datetime('now'))",
                (u2,),
            )


def test_wallet_unverified_not_constrained(db):
    """Two unverified rows (verified_at NULL) for the same address+chain are OK
    across different users — the partial unique index only covers verified rows.
    """
    with db.connect() as conn:
        u1 = _make_user(conn, "a@example.com")
        u2 = _make_user(conn, "b@example.com")
        conn.execute(
            "INSERT INTO wallets(user_id, address, chain) VALUES (?, '0xABC', 'base')",
            (u1,),
        )
        conn.execute(
            "INSERT INTO wallets(user_id, address, chain) VALUES (?, '0xABC', 'base')",
            (u2,),
        )


def test_foreign_keys_enforced(db):
    # progress referencing a non-existent user must fail with FK ON.
    with pytest.raises(sqlite3.IntegrityError):
        with db.connect() as conn:
            conn.execute(
                "INSERT INTO progress(user_id, lesson_id) VALUES (99999, 0)"
            )


# ── Connection PRAGMAs ─────────────────────────────────────────────────────


def test_wal_mode_enabled(db):
    with db.connect() as conn:
        mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
    assert mode.lower() == "wal"


def test_foreign_keys_pragma_on(db):
    with db.connect() as conn:
        fk = conn.execute("PRAGMA foreign_keys").fetchone()[0]
    assert fk == 1


def test_row_factory_is_row(db):
    with db.connect() as conn:
        row = conn.execute("SELECT 1 AS one").fetchone()
    assert isinstance(row, sqlite3.Row)
    assert row["one"] == 1


# ── Env-var contract ───────────────────────────────────────────────────────


def test_missing_env_raises(monkeypatch):
    monkeypatch.delenv("SPA_ACADEMY_DB", raising=False)
    with pytest.raises(ValueError):
        AcademyDB()


def test_env_var_used_when_no_path(tmp_path, monkeypatch):
    path = tmp_path / "from_env.db"
    monkeypatch.setenv("SPA_ACADEMY_DB", str(path))
    d = AcademyDB()
    assert d.db_path == str(path)
    d.run_migrations()
    assert d.schema_version() == 1


def test_migrations_dir_bundled_exists():
    assert (MIGRATIONS_DIR / "0001_initial.sql").exists()
