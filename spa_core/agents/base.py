"""
SPA BaseAgent — абстрактный базовый класс агента (M4)

Каждый агент:
  - имеет agent_id и bus
  - реализует метод run() → list[str]  (message_ids опубликованных сообщений)
  - может publish() и consume() через шину
  - логирует свои действия
"""
from __future__ import annotations

import logging
import sys
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from pathlib import Path
from typing import Sequence

sys.path.insert(0, str(Path(__file__).parent.parent))

from message_bus.bus import MessageBus
from message_bus.topics import Message, Priority, Topic

log = logging.getLogger(__name__)


class BaseAgent(ABC):
    """
    Абстрактный базовый класс для всех SPA-агентов.

    Агенты НЕ содержат Risk Policy логику.
    Risk Policy проверяется в PaperTrader.open_position() — всегда и безоговорочно.
    """

    #: Переопределить в подклассе
    AGENT_ID: str = "base_agent"

    def __init__(self, bus: MessageBus, db_path: Path | None = None):
        self.bus     = bus
        self.db_path = db_path
        self.log     = logging.getLogger(f"spa.agent.{self.AGENT_ID}")
        self._run_count = 0

    @abstractmethod
    def run(self) -> list[str]:
        """
        Выполнить одну итерацию агента.
        Возвращает список message_id опубликованных сообщений.
        """

    # ── Helpers ───────────────────────────────────────────────────────────────

    def publish(
        self,
        topic: str,
        payload: dict,
        priority: int = Priority.NORMAL,
    ) -> str:
        """Опубликовать сообщение от имени этого агента."""
        msg_id = self.bus.publish(topic, self.AGENT_ID, payload, priority)
        self.log.debug("Published %s (id=%s)", topic, msg_id[:8])
        return msg_id

    def consume(
        self,
        topics: str | Sequence[str],
        limit: int = 10,
    ) -> list[Message]:
        """Получить сообщения из шины для этого агента."""
        msgs = self.bus.consume(topics, self.AGENT_ID, limit)
        if msgs:
            self.log.debug("Consumed %d messages from %s", len(msgs), topics)
        return msgs

    def ack(self, message_id: str) -> bool:
        return self.bus.ack(message_id, self.AGENT_ID)

    def nack(self, message_id: str) -> bool:
        return self.bus.nack(message_id, self.AGENT_ID)

    def _ts(self) -> str:
        return datetime.now(timezone.utc).isoformat()

    def __repr__(self) -> str:
        return f"<{self.__class__.__name__} id={self.AGENT_ID}>"
