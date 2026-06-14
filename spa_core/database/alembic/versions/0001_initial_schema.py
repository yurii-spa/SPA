"""initial schema — BL-008 Phase 3 baseline

Captures the entire SPA v1.6 schema (7 tables + indexes + FKs) as a
single Alembic revision. Idempotent against existing SQLite databases
created by `init_db.init_database()` because every CREATE uses
IF NOT EXISTS — applying this revision to a populated dev box is a
no-op that just stamps `alembic_version`.

For a fresh PostgreSQL instance, `alembic upgrade head` builds the
schema from zero. Seeding the protocols whitelist is OUT of scope for
the migration — that is done by `init_db._seed_protocols()` or the
operator runbook.

Revision ID: 0001_initial_schema
Revises: None
Create Date: 2026-05-27
"""
from __future__ import annotations

from alembic import op

# revision identifiers, used by Alembic.
revision = "0001_initial_schema"
down_revision = None
branch_labels = None
depends_on = None


# ---------------------------------------------------------------------------
# Dialect-specific DDL fragments.
#
# Keeping the two flavours side-by-side mirrors the structure of
# schema.sql / schema_postgres.sql so the baseline is the byte-identical
# union of both. Each table is emitted via `op.execute(...)` so we don't
# rely on SQLAlchemy ORM or table reflection.
# ---------------------------------------------------------------------------

_SQLITE_TABLES = [
    # protocols
    """
    CREATE TABLE IF NOT EXISTS protocols (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        key             TEXT NOT NULL UNIQUE,
        protocol        TEXT NOT NULL,
        asset           TEXT NOT NULL,
        chain           TEXT NOT NULL,
        tier            TEXT NOT NULL,
        pool_id         TEXT,
        is_active       INTEGER NOT NULL DEFAULT 1,
        added_at        TEXT NOT NULL DEFAULT (datetime('now', 'utc')),
        notes           TEXT
    )
    """,
    # apy_snapshots
    """
    CREATE TABLE IF NOT EXISTS apy_snapshots (
        id                    INTEGER PRIMARY KEY AUTOINCREMENT,
        snapshot_id           TEXT NOT NULL DEFAULT (
                                  strftime('%Y%m%d_%H%M%S', datetime('now', 'utc'))
                              ),
        timestamp             TEXT NOT NULL,
        protocol_key          TEXT NOT NULL,
        protocol              TEXT NOT NULL,
        asset                 TEXT NOT NULL,
        chain                 TEXT NOT NULL,
        tier                  TEXT NOT NULL,
        pool_id               TEXT,
        apy_total             REAL NOT NULL,
        apy_base              REAL NOT NULL DEFAULT 0.0,
        apy_reward            REAL NOT NULL DEFAULT 0.0,
        tvl_usd               REAL NOT NULL,
        utilization_rate      REAL,
        is_valid              INTEGER NOT NULL DEFAULT 1,
        validation_warnings   TEXT,
        raw_json              TEXT,
        FOREIGN KEY (protocol_key) REFERENCES protocols(key)
    )
    """,
    # paper_trades
    """
    CREATE TABLE IF NOT EXISTS paper_trades (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        trade_id        TEXT NOT NULL UNIQUE DEFAULT (
                            'PT-' || strftime('%Y%m%d%H%M%S', datetime('now', 'utc'))
                        ),
        strategy_id     TEXT NOT NULL,
        timestamp_open  TEXT NOT NULL,
        timestamp_close TEXT,
        protocol_key    TEXT NOT NULL,
        asset           TEXT NOT NULL,
        action          TEXT NOT NULL,
        amount_usd      REAL NOT NULL,
        apy_at_open     REAL,
        apy_at_close    REAL,
        pnl_usd         REAL,
        pnl_pct         REAL,
        net_apy_annualized REAL,
        sharpe_contribution REAL,
        reason          TEXT,
        risk_check_passed INTEGER NOT NULL DEFAULT 1,
        notes           TEXT,
        FOREIGN KEY (protocol_key) REFERENCES protocols(key)
    )
    """,
    # risk_events
    """
    CREATE TABLE IF NOT EXISTS risk_events (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        timestamp       TEXT NOT NULL,
        event_type      TEXT NOT NULL,
        severity        TEXT NOT NULL,
        protocol_key    TEXT,
        message         TEXT NOT NULL,
        details_json    TEXT,
        resolved        INTEGER NOT NULL DEFAULT 0,
        resolved_at     TEXT,
        resolved_by     TEXT
    )
    """,
    # strategy_state
    """
    CREATE TABLE IF NOT EXISTS strategy_state (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        strategy_id     TEXT NOT NULL,
        timestamp       TEXT NOT NULL DEFAULT (datetime('now', 'utc')),
        total_capital_usd    REAL NOT NULL DEFAULT 10000.0,
        deployed_capital_usd REAL NOT NULL DEFAULT 0.0,
        cash_usd             REAL NOT NULL DEFAULT 10000.0,
        total_pnl_usd        REAL NOT NULL DEFAULT 0.0,
        total_pnl_pct        REAL NOT NULL DEFAULT 0.0,
        current_apy          REAL,
        sharpe_to_date       REAL,
        max_drawdown_pct     REAL,
        trade_count          INTEGER NOT NULL DEFAULT 0,
        state_json           TEXT
    )
    """,
    # message_bus
    """
    CREATE TABLE IF NOT EXISTS message_bus (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        message_id      TEXT NOT NULL UNIQUE,
        topic           TEXT NOT NULL,
        sender          TEXT NOT NULL,
        consumer        TEXT,
        payload_json    TEXT NOT NULL,
        priority        INTEGER NOT NULL DEFAULT 5,
        status          TEXT NOT NULL DEFAULT 'pending',
        timestamp       TEXT NOT NULL DEFAULT (datetime('now', 'utc')),
        consumed_at     TEXT,
        acked_at        TEXT
    )
    """,
    # agent_decisions
    """
    CREATE TABLE IF NOT EXISTS agent_decisions (
        id                  INTEGER PRIMARY KEY AUTOINCREMENT,
        timestamp           TEXT NOT NULL,
        agent_name          TEXT NOT NULL,
        decision_type       TEXT NOT NULL,
        protocol_key        TEXT,
        amount_usd          REAL,
        reasoning           TEXT NOT NULL,
        data_snapshot       TEXT,
        policy_version      TEXT DEFAULT 'v1.0',
        strategy_id         TEXT DEFAULT 'paper-v1',
        risk_check_result   TEXT,
        outcome             TEXT
    )
    """,
]

_POSTGRES_TABLES = [
    # protocols
    """
    CREATE TABLE IF NOT EXISTS protocols (
        id              SERIAL PRIMARY KEY,
        key             TEXT NOT NULL UNIQUE,
        protocol        TEXT NOT NULL,
        asset           TEXT NOT NULL,
        chain           TEXT NOT NULL,
        tier            TEXT NOT NULL,
        pool_id         TEXT,
        is_active       INTEGER NOT NULL DEFAULT 1,
        added_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        notes           TEXT
    )
    """,
    # apy_snapshots
    """
    CREATE TABLE IF NOT EXISTS apy_snapshots (
        id                    SERIAL PRIMARY KEY,
        snapshot_id           TEXT NOT NULL,
        timestamp             TEXT NOT NULL,
        protocol_key          TEXT NOT NULL,
        protocol              TEXT NOT NULL,
        asset                 TEXT NOT NULL,
        chain                 TEXT NOT NULL,
        tier                  TEXT NOT NULL,
        pool_id               TEXT,
        apy_total             DOUBLE PRECISION NOT NULL,
        apy_base              DOUBLE PRECISION NOT NULL DEFAULT 0.0,
        apy_reward            DOUBLE PRECISION NOT NULL DEFAULT 0.0,
        tvl_usd               DOUBLE PRECISION NOT NULL,
        utilization_rate      DOUBLE PRECISION,
        is_valid              INTEGER NOT NULL DEFAULT 1,
        validation_warnings   TEXT,
        raw_json              TEXT,
        FOREIGN KEY (protocol_key) REFERENCES protocols(key)
    )
    """,
    # paper_trades
    """
    CREATE TABLE IF NOT EXISTS paper_trades (
        id              SERIAL PRIMARY KEY,
        trade_id        TEXT NOT NULL UNIQUE,
        strategy_id     TEXT NOT NULL,
        timestamp_open  TEXT NOT NULL,
        timestamp_close TEXT,
        protocol_key    TEXT NOT NULL,
        asset           TEXT NOT NULL,
        action          TEXT NOT NULL,
        amount_usd      DOUBLE PRECISION NOT NULL,
        apy_at_open     DOUBLE PRECISION,
        apy_at_close    DOUBLE PRECISION,
        pnl_usd         DOUBLE PRECISION,
        pnl_pct         DOUBLE PRECISION,
        net_apy_annualized  DOUBLE PRECISION,
        sharpe_contribution DOUBLE PRECISION,
        reason          TEXT,
        risk_check_passed INTEGER NOT NULL DEFAULT 1,
        notes           TEXT,
        FOREIGN KEY (protocol_key) REFERENCES protocols(key)
    )
    """,
    # risk_events
    """
    CREATE TABLE IF NOT EXISTS risk_events (
        id              SERIAL PRIMARY KEY,
        timestamp       TEXT NOT NULL,
        event_type      TEXT NOT NULL,
        severity        TEXT NOT NULL,
        protocol_key    TEXT,
        message         TEXT NOT NULL,
        details_json    TEXT,
        resolved        INTEGER NOT NULL DEFAULT 0,
        resolved_at     TEXT,
        resolved_by     TEXT
    )
    """,
    # strategy_state
    """
    CREATE TABLE IF NOT EXISTS strategy_state (
        id              SERIAL PRIMARY KEY,
        strategy_id     TEXT NOT NULL,
        timestamp       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        total_capital_usd    DOUBLE PRECISION NOT NULL DEFAULT 10000.0,
        deployed_capital_usd DOUBLE PRECISION NOT NULL DEFAULT 0.0,
        cash_usd             DOUBLE PRECISION NOT NULL DEFAULT 10000.0,
        total_pnl_usd        DOUBLE PRECISION NOT NULL DEFAULT 0.0,
        total_pnl_pct        DOUBLE PRECISION NOT NULL DEFAULT 0.0,
        current_apy          DOUBLE PRECISION,
        sharpe_to_date       DOUBLE PRECISION,
        max_drawdown_pct     DOUBLE PRECISION,
        trade_count          INTEGER NOT NULL DEFAULT 0,
        state_json           TEXT
    )
    """,
    # message_bus
    """
    CREATE TABLE IF NOT EXISTS message_bus (
        id              SERIAL PRIMARY KEY,
        message_id      TEXT NOT NULL UNIQUE,
        topic           TEXT NOT NULL,
        sender          TEXT NOT NULL,
        consumer        TEXT,
        payload_json    TEXT NOT NULL,
        priority        INTEGER NOT NULL DEFAULT 5,
        status          TEXT NOT NULL DEFAULT 'pending',
        timestamp       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        consumed_at     TEXT,
        acked_at        TEXT
    )
    """,
    # agent_decisions
    """
    CREATE TABLE IF NOT EXISTS agent_decisions (
        id                  SERIAL PRIMARY KEY,
        timestamp           TEXT NOT NULL,
        agent_name          TEXT NOT NULL,
        decision_type       TEXT NOT NULL,
        protocol_key        TEXT,
        amount_usd          DOUBLE PRECISION,
        reasoning           TEXT NOT NULL,
        data_snapshot       TEXT,
        policy_version      TEXT DEFAULT 'v1.0',
        strategy_id         TEXT DEFAULT 'paper-v1',
        risk_check_result   TEXT,
        outcome             TEXT
    )
    """,
]

# Indexes are dialect-agnostic in our schema — identical CREATE INDEX
# IF NOT EXISTS statements work on both SQLite and Postgres.
_COMMON_INDEXES = [
    "CREATE INDEX IF NOT EXISTS idx_snapshots_protocol_time "
    "ON apy_snapshots (protocol_key, timestamp DESC)",
    "CREATE INDEX IF NOT EXISTS idx_snapshots_timestamp "
    "ON apy_snapshots (timestamp DESC)",
    "CREATE INDEX IF NOT EXISTS idx_trades_strategy "
    "ON paper_trades (strategy_id, timestamp_open DESC)",
    "CREATE INDEX IF NOT EXISTS idx_trades_protocol "
    "ON paper_trades (protocol_key, timestamp_open DESC)",
    "CREATE INDEX IF NOT EXISTS idx_risk_events_time "
    "ON risk_events (timestamp DESC)",
    "CREATE INDEX IF NOT EXISTS idx_risk_events_severity "
    "ON risk_events (severity, resolved)",
    "CREATE INDEX IF NOT EXISTS idx_strategy_state "
    "ON strategy_state (strategy_id, timestamp DESC)",
    "CREATE INDEX IF NOT EXISTS idx_bus_topic_status "
    "ON message_bus (topic, status, priority, timestamp)",
    "CREATE INDEX IF NOT EXISTS idx_bus_message_id "
    "ON message_bus (message_id)",
    "CREATE INDEX IF NOT EXISTS idx_agent_decisions_agent "
    "ON agent_decisions(agent_name)",
    "CREATE INDEX IF NOT EXISTS idx_agent_decisions_time "
    "ON agent_decisions(timestamp)",
    "CREATE INDEX IF NOT EXISTS idx_agent_decisions_type "
    "ON agent_decisions(decision_type, protocol_key)",
]


def _bind_dialect() -> str:
    """Return the active migration dialect name (e.g. 'sqlite', 'postgresql')."""
    bind = op.get_bind()
    return bind.dialect.name


def upgrade() -> None:
    dialect = _bind_dialect()
    tables = _POSTGRES_TABLES if dialect == "postgresql" else _SQLITE_TABLES
    for ddl in tables:
        op.execute(ddl)
    for idx in _COMMON_INDEXES:
        op.execute(idx)


def downgrade() -> None:
    """
    Drop every table created in upgrade().

    Order matters because of foreign keys: drop the children first, then
    the parent `protocols` table last.
    """
    for table in (
        "agent_decisions",
        "message_bus",
        "strategy_state",
        "risk_events",
        "paper_trades",
        "apy_snapshots",
        "protocols",
    ):
        op.execute(f"DROP TABLE IF EXISTS {table}")
