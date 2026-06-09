"""
Tests for the Alembic migration scaffold — BL-008 Phase 3.

Scope:
  * `alembic upgrade head` builds the full v1.6 schema on a fresh SQLite
    file from zero.
  * Running it twice is a no-op (idempotent CREATE IF NOT EXISTS).
  * `alembic downgrade base` drops everything we created.
  * The migration honours `SPA_DATABASE_URL` via env.py and writes the
    alembic_version row.

These tests deliberately use SQLite + a temp file so they are hermetic
and require no PostgreSQL server. The Postgres branch of the migration
is exercised by ADR-005 review + the manual cutover procedure.
"""
from __future__ import annotations

import os
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest


_ROOT = Path(__file__).resolve().parents[2]
_ALEMBIC_DIR = _ROOT / "spa_core" / "database"
_EXPECTED_TABLES = {
    "protocols",
    "apy_snapshots",
    "paper_trades",
    "risk_events",
    "strategy_state",
    "message_bus",
    "agent_decisions",
}
_EXPECTED_INDEXES = {
    "idx_snapshots_protocol_time",
    "idx_snapshots_timestamp",
    "idx_trades_strategy",
    "idx_trades_protocol",
    "idx_risk_events_time",
    "idx_risk_events_severity",
    "idx_strategy_state",
    "idx_bus_topic_status",
    "idx_bus_message_id",
    "idx_agent_decisions_agent",
    "idx_agent_decisions_time",
    "idx_agent_decisions_type",
}


def _have_alembic() -> bool:
    try:
        import alembic  # noqa: F401
    except Exception:
        return False
    return True


pytestmark = pytest.mark.skipif(
    not _have_alembic(),
    reason="alembic not installed in this test environment",
)


def _run_alembic(args: list[str], db_path: Path) -> subprocess.CompletedProcess:
    """Invoke alembic CLI as a subprocess with SPA_DATABASE_URL set."""
    env = os.environ.copy()
    env["SPA_DATABASE_URL"] = f"sqlite:///{db_path}"
    # PYTHONPATH ensures `import spa_core...` works in env.py.
    env["PYTHONPATH"] = f"{_ROOT}{os.pathsep}{env.get('PYTHONPATH', '')}"
    return subprocess.run(
        [sys.executable, "-m", "alembic", *args],
        cwd=_ALEMBIC_DIR,
        capture_output=True,
        text=True,
        env=env,
        timeout=60,
        check=False,
    )


def _tables(db_path: Path) -> set[str]:
    conn = sqlite3.connect(db_path)
    try:
        rows = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
        return {r[0] for r in rows}
    finally:
        conn.close()


def _indexes(db_path: Path) -> set[str]:
    conn = sqlite3.connect(db_path)
    try:
        rows = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='index' "
            "AND name NOT LIKE 'sqlite_%'"
        ).fetchall()
        return {r[0] for r in rows}
    finally:
        conn.close()


def _version(db_path: Path) -> str | None:
    conn = sqlite3.connect(db_path)
    try:
        rows = conn.execute("SELECT version_num FROM alembic_version").fetchall()
        if not rows:
            return None
        return rows[0][0]
    finally:
        conn.close()


def test_upgrade_head_creates_full_schema(tmp_path):
    db = tmp_path / "spa_upgrade.db"
    result = _run_alembic(["upgrade", "head"], db)
    assert result.returncode == 0, f"alembic failed: {result.stderr}"

    tables = _tables(db)
    assert _EXPECTED_TABLES.issubset(tables), (
        f"missing tables: {_EXPECTED_TABLES - tables}"
    )
    assert "alembic_version" in tables, "alembic_version row missing"

    indexes = _indexes(db)
    assert _EXPECTED_INDEXES.issubset(indexes), (
        f"missing indexes: {_EXPECTED_INDEXES - indexes}"
    )

    assert _version(db) == "0001_initial_schema"


def test_upgrade_head_is_idempotent(tmp_path):
    db = tmp_path / "spa_idem.db"
    first = _run_alembic(["upgrade", "head"], db)
    assert first.returncode == 0, first.stderr

    second = _run_alembic(["upgrade", "head"], db)
    assert second.returncode == 0, second.stderr

    # State is unchanged.
    assert _EXPECTED_TABLES.issubset(_tables(db))
    assert _version(db) == "0001_initial_schema"


def test_downgrade_base_removes_all_tables(tmp_path):
    db = tmp_path / "spa_down.db"
    up = _run_alembic(["upgrade", "head"], db)
    assert up.returncode == 0, up.stderr
    assert _EXPECTED_TABLES.issubset(_tables(db))

    down = _run_alembic(["downgrade", "base"], db)
    assert down.returncode == 0, down.stderr

    remaining = _tables(db)
    # All SPA tables gone. alembic_version stays empty (or table itself
    # remains but with no rows), which is the expected Alembic behaviour.
    overlap = remaining & _EXPECTED_TABLES
    assert overlap == set(), f"tables not dropped on downgrade: {overlap}"


def test_current_reports_head_after_upgrade(tmp_path):
    db = tmp_path / "spa_current.db"
    up = _run_alembic(["upgrade", "head"], db)
    assert up.returncode == 0, up.stderr

    cur = _run_alembic(["current"], db)
    assert cur.returncode == 0, cur.stderr
    # `alembic current` prints the revision id; check it appears.
    assert "0001_initial_schema" in (cur.stdout + cur.stderr)


def test_init_db_get_connection_compatible_after_upgrade(tmp_path):
    """
    Smoke: after `alembic upgrade head`, the existing init_db.get_connection()
    code path can still open the file and see all tables. This is the
    contract that lets us swap CI to alembic-driven schema management
    without breaking the rest of the codebase.
    """
    db = tmp_path / "spa_smoke.db"
    up = _run_alembic(["upgrade", "head"], db)
    assert up.returncode == 0, up.stderr

    sys.path.insert(0, str(_ROOT))
    try:
        from spa_core.database.init_db import get_connection
    finally:
        sys.path.pop(0)

    with get_connection(db) as conn:
        rows = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
        names = {r[0] for r in rows}
    assert _EXPECTED_TABLES.issubset(names)
