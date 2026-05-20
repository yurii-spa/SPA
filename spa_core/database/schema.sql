-- SPA Database Schema v1.0
-- SQLite — основное хранилище для Фаз 1-5
-- Миграция на PostgreSQL — только при Go-Live (Фаза 6)

PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;

-- ─── protocols ────────────────────────────────────────────────────────────────
-- Справочник протоколов whitelist
CREATE TABLE IF NOT EXISTS protocols (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    key             TEXT NOT NULL UNIQUE,       -- e.g. "aave-v3-usdc-ethereum"
    protocol        TEXT NOT NULL,              -- e.g. "Aave V3"
    asset           TEXT NOT NULL,              -- e.g. "USDC"
    chain           TEXT NOT NULL,              -- e.g. "Ethereum"
    tier            TEXT NOT NULL,              -- "T1" | "T2"
    pool_id         TEXT,                       -- DeFiLlama pool UUID
    is_active       INTEGER NOT NULL DEFAULT 1, -- 0 = исключён из торговли
    added_at        TEXT NOT NULL DEFAULT (datetime('now', 'utc')),
    notes           TEXT
);

-- ─── apy_snapshots ────────────────────────────────────────────────────────────
-- Снимки данных APY/TVL (каждые 4 часа)
CREATE TABLE IF NOT EXISTS apy_snapshots (
    id                    INTEGER PRIMARY KEY AUTOINCREMENT,
    snapshot_id           TEXT NOT NULL DEFAULT (
                              strftime('%Y%m%d_%H%M%S', datetime('now', 'utc'))
                          ),
    timestamp             TEXT NOT NULL,         -- ISO 8601 UTC
    protocol_key          TEXT NOT NULL,
    protocol              TEXT NOT NULL,
    asset                 TEXT NOT NULL,
    chain                 TEXT NOT NULL,
    tier                  TEXT NOT NULL,
    pool_id               TEXT,
    apy_total             REAL NOT NULL,         -- % годовых
    apy_base              REAL NOT NULL DEFAULT 0.0,
    apy_reward            REAL NOT NULL DEFAULT 0.0,
    tvl_usd               REAL NOT NULL,         -- USD
    utilization_rate      REAL,                  -- 0-1, может быть NULL
    is_valid              INTEGER NOT NULL DEFAULT 1,  -- прошёл валидацию?
    validation_warnings   TEXT,                  -- JSON array of warning strings
    raw_json              TEXT,                  -- полный ответ DeFiLlama

    FOREIGN KEY (protocol_key) REFERENCES protocols(key)
);

CREATE INDEX IF NOT EXISTS idx_snapshots_protocol_time
    ON apy_snapshots (protocol_key, timestamp DESC);

CREATE INDEX IF NOT EXISTS idx_snapshots_timestamp
    ON apy_snapshots (timestamp DESC);

-- ─── paper_trades ─────────────────────────────────────────────────────────────
-- Виртуальные сделки (paper trading)
CREATE TABLE IF NOT EXISTS paper_trades (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    trade_id        TEXT NOT NULL UNIQUE DEFAULT (
                        'PT-' || strftime('%Y%m%d%H%M%S', datetime('now', 'utc'))
                    ),
    strategy_id     TEXT NOT NULL,              -- e.g. "v1_passive"
    timestamp_open  TEXT NOT NULL,              -- ISO 8601 UTC
    timestamp_close TEXT,                       -- NULL = позиция открыта
    protocol_key    TEXT NOT NULL,
    asset           TEXT NOT NULL,
    action          TEXT NOT NULL,              -- "OPEN" | "CLOSE" | "REBALANCE"
    amount_usd      REAL NOT NULL,              -- виртуальный размер позиции
    apy_at_open     REAL,                       -- APY в момент открытия
    apy_at_close    REAL,                       -- APY в момент закрытия
    pnl_usd         REAL,                       -- реализованный PnL (при закрытии)
    pnl_pct         REAL,                       -- PnL %
    net_apy_annualized REAL,                    -- annualized return
    sharpe_contribution REAL,                   -- вклад в Sharpe
    reason          TEXT,                       -- причина сделки
    risk_check_passed INTEGER NOT NULL DEFAULT 1,
    notes           TEXT,

    FOREIGN KEY (protocol_key) REFERENCES protocols(key)
);

CREATE INDEX IF NOT EXISTS idx_trades_strategy
    ON paper_trades (strategy_id, timestamp_open DESC);

CREATE INDEX IF NOT EXISTS idx_trades_protocol
    ON paper_trades (protocol_key, timestamp_open DESC);

-- ─── risk_events ──────────────────────────────────────────────────────────────
-- Лог событий риска (аномалии, circuit breakers, ошибки pipeline)
CREATE TABLE IF NOT EXISTS risk_events (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp       TEXT NOT NULL,              -- ISO 8601 UTC
    event_type      TEXT NOT NULL,              -- "data_anomaly" | "circuit_breaker" |
                                                -- "concentration_limit" | "data_pipeline_error" |
                                                -- "missing_data" | "stale_data"
    severity        TEXT NOT NULL,              -- "LOW" | "MEDIUM" | "HIGH" | "CRITICAL"
    protocol_key    TEXT,                       -- NULL = системное событие
    message         TEXT NOT NULL,
    details_json    TEXT,                       -- произвольный JSON с деталями
    resolved        INTEGER NOT NULL DEFAULT 0, -- 0 = активное, 1 = разрешено
    resolved_at     TEXT,
    resolved_by     TEXT                        -- "manual" | "auto" | agent name
);

CREATE INDEX IF NOT EXISTS idx_risk_events_time
    ON risk_events (timestamp DESC);

CREATE INDEX IF NOT EXISTS idx_risk_events_severity
    ON risk_events (severity, resolved);

-- ─── strategy_state ───────────────────────────────────────────────────────────
-- Текущее состояние стратегий (портфель, метрики)
CREATE TABLE IF NOT EXISTS strategy_state (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    strategy_id     TEXT NOT NULL,
    timestamp       TEXT NOT NULL DEFAULT (datetime('now', 'utc')),
    total_capital_usd    REAL NOT NULL DEFAULT 10000.0,
    deployed_capital_usd REAL NOT NULL DEFAULT 0.0,
    cash_usd             REAL NOT NULL DEFAULT 10000.0,
    total_pnl_usd        REAL NOT NULL DEFAULT 0.0,
    total_pnl_pct        REAL NOT NULL DEFAULT 0.0,
    current_apy          REAL,                  -- текущая эффективная APY портфеля
    sharpe_to_date       REAL,
    max_drawdown_pct     REAL,
    trade_count          INTEGER NOT NULL DEFAULT 0,
    state_json           TEXT                   -- полный snapshot состояния
);

CREATE INDEX IF NOT EXISTS idx_strategy_state
    ON strategy_state (strategy_id, timestamp DESC);

-- ─── message_bus ──────────────────────────────────────────────────────────────
-- Шина сообщений между агентами (M4)
CREATE TABLE IF NOT EXISTS message_bus (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    message_id      TEXT NOT NULL UNIQUE,
    topic           TEXT NOT NULL,              -- MARKET_DATA | HEALTH_ALERT | STRATEGY_SIGNAL | TRADE_DECISION | EXECUTION_RESULT
    sender          TEXT NOT NULL,              -- agent_id публикующего агента
    consumer        TEXT,                       -- agent_id получателя (NULL = не получено)
    payload_json    TEXT NOT NULL,              -- JSON-payload
    priority        INTEGER NOT NULL DEFAULT 5, -- 1=наивысший, 10=наинизший
    status          TEXT NOT NULL DEFAULT 'pending', -- pending|consumed|acked|dead
    timestamp       TEXT NOT NULL DEFAULT (datetime('now', 'utc')),
    consumed_at     TEXT,                       -- когда consumed
    acked_at        TEXT                        -- когда acked/завершено
);

CREATE INDEX IF NOT EXISTS idx_bus_topic_status
    ON message_bus (topic, status, priority, timestamp);

CREATE INDEX IF NOT EXISTS idx_bus_message_id
    ON message_bus (message_id);
