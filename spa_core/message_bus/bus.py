"""
SPA Message Bus — SQLite-backed pub/sub (M4)

MessageBus:
    publish(topic, sender, payload, priority) → message_id
    consume(topics, consumer_id, limit)       → list[Message]
    ack(message_id, consumer_id)              → bool
    nack(message_id, consumer_id)             → bool  (requeue)
    requeue_stale(timeout_minutes)            → int   (dead-letter recovery)
    stats()                                   → dict
"""
from __future__ import annotations

import json
import logging
import sys
import uuid
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Sequence

sys.path.insert(0, str(Path(__file__).parent.parent))

from database.init_db import get_connection, get_db_path
from message_bus.topics import Message, Priority, Topic
from spa_core.utils.errors import RegistryError

log = logging.getLogger(__name__)


class MessageBus:
    """
    SQLite-backed message bus.
    Thread-safe благодаря WAL mode в SQLite.
    Одна строка в БД = одно сообщение.
    """

    # Через сколько минут consumed-но-не-acked сообщение уходит в dead-letter
    STALE_TIMEOUT_MINUTES = 5

    def __init__(self, db_path: Path | None = None):
        self.db_path = db_path or get_db_path()
        self._ensure_table()

    # ── Public API ────────────────────────────────────────────────────────────

    def publish(
        self,
        topic: str,
        sender: str,
        payload: dict,
        priority: int = Priority.NORMAL,
    ) -> str:
        """Опубликовать сообщение. Возвращает message_id."""
        if topic not in Topic.ALL:
            raise RegistryError(f"Unknown topic: {topic!r}. Valid: {Topic.ALL}", code="UNKNOWN_TOPIC")

        msg_id = str(uuid.uuid4())
        ts     = datetime.now(timezone.utc).isoformat()

        with get_connection(self.db_path) as conn:
            conn.execute(
                """
                INSERT INTO message_bus
                    (message_id, topic, sender, payload_json, priority, status, timestamp)
                VALUES (?, ?, ?, ?, ?, 'pending', ?)
                """,
                (msg_id, topic, sender, json.dumps(payload, ensure_ascii=False),
                 priority, ts),
            )
            conn.commit()

        log.debug("Published %s from %s (id=%s)", topic, sender, msg_id[:8])
        return msg_id

    def consume(
        self,
        topics: str | Sequence[str],
        consumer_id: str,
        limit: int = 10,
    ) -> list[Message]:
        """
        Получить до `limit` pending-сообщений по топикам.
        Атомарно помечает их как 'consumed'.
        """
        if isinstance(topics, str):
            topics = (topics,)

        placeholders = ",".join("?" * len(topics))
        ts_now = datetime.now(timezone.utc).isoformat()

        with get_connection(self.db_path) as conn:
            rows = conn.execute(
                f"""
                SELECT message_id, topic, sender, payload_json, priority, timestamp
                FROM message_bus
                WHERE topic IN ({placeholders}) AND status = 'pending'
                ORDER BY priority ASC, timestamp ASC
                LIMIT ?
                """,
                (*topics, limit),
            ).fetchall()

            if not rows:
                return []

            ids = [r["message_id"] for r in rows]
            id_placeholders = ",".join("?" * len(ids))
            conn.execute(
                f"""
                UPDATE message_bus
                SET status = 'consumed', consumer = ?, consumed_at = ?
                WHERE message_id IN ({id_placeholders})
                """,
                (consumer_id, ts_now, *ids),
            )
            conn.commit()

        messages = []
        for r in rows:
            try:
                payload = json.loads(r["payload_json"])
            except json.JSONDecodeError:
                payload = {"raw": r["payload_json"]}
            messages.append(
                Message(
                    id        = r["message_id"],
                    topic     = r["topic"],
                    sender    = r["sender"],
                    payload   = payload,
                    priority  = r["priority"],
                    timestamp = r["timestamp"],
                    status    = "consumed",
                    consumer  = consumer_id,
                )
            )
        log.debug("%s consumed %d messages from %s", consumer_id, len(messages), topics)
        return messages

    def ack(self, message_id: str, consumer_id: str) -> bool:
        """Подтвердить обработку сообщения → статус 'acked'."""
        ts_now = datetime.now(timezone.utc).isoformat()
        with get_connection(self.db_path) as conn:
            rows = conn.execute(
                """
                UPDATE message_bus
                SET status = 'acked', acked_at = ?
                WHERE message_id = ? AND consumer = ? AND status = 'consumed'
                """,
                (ts_now, message_id, consumer_id),
            ).rowcount
            conn.commit()
        return rows > 0

    def nack(self, message_id: str, consumer_id: str) -> bool:
        """Вернуть сообщение в очередь (requeue)."""
        with get_connection(self.db_path) as conn:
            rows = conn.execute(
                """
                UPDATE message_bus
                SET status = 'pending', consumer = NULL, consumed_at = NULL
                WHERE message_id = ? AND consumer = ? AND status = 'consumed'
                """,
                (message_id, consumer_id),
            ).rowcount
            conn.commit()
        return rows > 0

    def requeue_stale(self, timeout_minutes: int | None = None) -> int:
        """
        Найти consumed-но-не-acked сообщения старше timeout_minutes
        и вернуть их в очередь (или пометить как dead).
        Возвращает количество requeueed сообщений.
        """
        timeout = timeout_minutes or self.STALE_TIMEOUT_MINUTES
        cutoff  = (datetime.now(timezone.utc) - timedelta(minutes=timeout)).isoformat()

        with get_connection(self.db_path) as conn:
            rows = conn.execute(
                """
                UPDATE message_bus
                SET status = 'pending', consumer = NULL, consumed_at = NULL
                WHERE status = 'consumed' AND consumed_at < ?
                """,
                (cutoff,),
            ).rowcount
            conn.commit()

        if rows:
            log.warning("Requeued %d stale messages (timeout=%dm)", rows, timeout)
        return rows

    def stats(self) -> dict:
        """Статистика шины по топикам и статусам."""
        with get_connection(self.db_path) as conn:
            rows = conn.execute(
                """
                SELECT topic, status, COUNT(*) as cnt
                FROM message_bus
                GROUP BY topic, status
                ORDER BY topic, status
                """
            ).fetchall()

        result: dict = {t: {"pending": 0, "consumed": 0, "acked": 0, "dead": 0}
                        for t in Topic.ALL}
        for r in rows:
            topic  = r["topic"]
            status = r["status"]
            count  = r["cnt"]
            if topic in result:
                result[topic][status] = count
        return result

    def purge(self, topic: str | None = None, status: str = "acked") -> int:
        """Удалить обработанные сообщения (maintenance). Только acked по умолчанию."""
        with get_connection(self.db_path) as conn:
            if topic:
                rows = conn.execute(
                    "DELETE FROM message_bus WHERE topic = ? AND status = ?",
                    (topic, status),
                ).rowcount
            else:
                rows = conn.execute(
                    "DELETE FROM message_bus WHERE status = ?",
                    (status,),
                ).rowcount
            conn.commit()
        return rows

    # ── Private ───────────────────────────────────────────────────────────────

    def _ensure_table(self) -> None:
        """Создать таблицу message_bus если её нет (идемпотентно)."""
        with get_connection(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS message_bus (
                    id           INTEGER PRIMARY KEY AUTOINCREMENT,
                    message_id   TEXT NOT NULL UNIQUE,
                    topic        TEXT NOT NULL,
                    sender       TEXT NOT NULL,
                    consumer     TEXT,
                    payload_json TEXT NOT NULL,
                    priority     INTEGER NOT NULL DEFAULT 5,
                    status       TEXT NOT NULL DEFAULT 'pending',
                    timestamp    TEXT NOT NULL,
                    consumed_at  TEXT,
                    acked_at     TEXT
                )
            """)
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_bus_topic_status "
                "ON message_bus (topic, status, priority, timestamp)"
            )
            conn.commit()
