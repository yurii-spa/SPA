-- SPA Message Bus Schema
-- Добавляется к основной spa.db (уже в WAL mode)
-- Применяется автоматически при первом создании MessageBus()

CREATE TABLE IF NOT EXISTS message_bus (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    message_id   TEXT    NOT NULL UNIQUE,       -- UUID v4
    topic        TEXT    NOT NULL,              -- Topic.*
    sender       TEXT    NOT NULL,              -- имя агента-отправителя
    consumer     TEXT,                          -- имя агента-потребителя (после consume)
    payload_json TEXT    NOT NULL,              -- JSON payload
    priority     INTEGER NOT NULL DEFAULT 5,   -- 1=CRITICAL … 10=BATCH
    status       TEXT    NOT NULL DEFAULT 'pending',  -- pending|consumed|acked|dead
    timestamp    TEXT    NOT NULL,              -- ISO 8601 UTC (время публикации)
    consumed_at  TEXT,                          -- когда взято на обработку
    acked_at     TEXT                           -- когда подтверждено
);

-- Главный индекс для consume(): по топику и статусу, с приоритетом
CREATE INDEX IF NOT EXISTS idx_bus_topic_status
    ON message_bus (topic, status, priority ASC, timestamp ASC);

-- Индекс для dead-letter recovery: ищем consumed без ack по времени
CREATE INDEX IF NOT EXISTS idx_bus_status_consumed
    ON message_bus (status, consumed_at);

-- Для быстрого поиска по message_id (ack/nack)
CREATE INDEX IF NOT EXISTS idx_bus_message_id
    ON message_bus (message_id);
