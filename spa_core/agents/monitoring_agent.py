"""
SPA Monitoring Agent (M4)

Модель: Claude Haiku (в реальном деплое)
Роль:   Проверяет здоровье портфеля и данных, публикует HEALTH_ALERT.

Логика:
  1. Запускает HealthCheck.run()
  2. Если есть alerts — публикует HEALTH_ALERT с priority=CRITICAL|HIGH
  3. Если всё ок — публикует INFO HEALTH_ALERT с overall_status=OK
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from agents.base import BaseAgent
from message_bus.bus import MessageBus
from message_bus.topics import Priority, Topic, health_alert_payload
from monitor.health_check import HealthCheck


class MonitoringAgent(BaseAgent):
    """
    Агент мониторинга — обёртка над HealthCheck (M3).
    Публикует HEALTH_ALERT в шину после каждой проверки.
    """

    AGENT_ID = "monitoring_agent"

    def __init__(self, bus: MessageBus, db_path: Path | None = None):
        super().__init__(bus, db_path)
        self._checker = HealthCheck(db_path=db_path)

    def run(self) -> list[str]:
        """Выполнить health check и опубликовать результат."""
        self._run_count += 1
        self.log.info("Run #%d — starting health check", self._run_count)

        result  = self._checker.run()
        summary = result["summary"]
        alerts  = result["alerts"]
        portfolio = result.get("portfolio", {})

        overall = summary["overall_status"]  # OK | WARNING | CRITICAL

        priority = {
            "OK":       Priority.LOW,
            "WARNING":  Priority.HIGH,
            "CRITICAL": Priority.CRITICAL,
        }.get(overall, Priority.NORMAL)

        payload = health_alert_payload(
            alerts    = alerts,
            overall_status = overall,
            portfolio = portfolio,
        )

        msg_id = self.publish(Topic.HEALTH_ALERT, payload, priority=priority)

        self.log.info(
            "Health check done: %s | %d critical, %d warnings | published %s",
            overall, summary["critical"], summary["warnings"], msg_id[:8],
        )
        return [msg_id]
