"""
SPA CEO Agent (M4)

Модель: Claude Sonnet 4.6 (в реальном деплое)
Роль:   Координатор. Потребляет STRATEGY_SIGNAL и HEALTH_ALERT,
        принимает финальное решение, публикует TRADE_DECISION.

Логика:
  1. Проверяет HEALTH_ALERT — если CRITICAL, блокирует новые позиции
  2. Читает STRATEGY_SIGNAL — оценивает рекомендации стратегии Strategy Agent
  3. Публикует TRADE_DECISION для каждой одобренной рекомендации
  4. Решение финализируется в  PaperTrader.open_position() через Risk Policy
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from agents.base import BaseAgent
from message_bus.bus import MessageBus
from message_bus.topics import Priority, Topic, trade_decision_payload


class CEOAgent(BaseAgent):
    """
    CEO Agent — решение и финальный decision maker.
    Не обходит Risk Policy — финальная проверка в PaperTrader.
    """

    AGENT_ID = "ceo_agent"

    def run(self) -> list[str]:
        """
        1. Проверить HEALTH_ALERT
        2. Прочитать STRATEGY_SIGNAL
        3. Опубликовать TRADE_DECISION для каждой одобренной рекомендации
        """
        self._run_count += 1
        self.log.info("Run #%d — CEO decision cycle", self._run_count)

        # ── 1. Health Check ──────────────────────────────────────────────────
        health_msgs  = self.consume(Topic.HEALTH_ALERT, limit=5)
        is_blocked   = False
        block_reason = None

        for hm in health_msgs:
            self.ack(hm.id)
            status = hm.payload.get("overall_status", "OK")
            if status == "CRITICAL":
                is_blocked   = True
                block_reason = f"Health CRITICAL: {hm.payload.get('critical_count', 0)} alerts"
                self.log.warning("BLOCKED by health alert: %s", block_reason)
                break

        # ── 2. Strategy Signal ───────────────────────────────────────────────
        signal_msgs = self.consume(Topic.STRATEGY_SIGNAL, limit=5)
        if not signal_msgs:
            self.log.info("No STRATEGY_SIGNAL in queue — idle")
            return []

        latest_signal = signal_msgs[-1]
        for sm in signal_msgs:
            self.ack(sm.id)

        recommendations = latest_signal.payload.get("recommendations", [])
        reasoning_base  = latest_signal.payload.get("reasoning", "")
        confidence      = latest_signal.payload.get("confidence", 0.8)

        self.log.info(
            "Processing %d recommendations (blocked=%s, confidence=%.2f)",
            len(recommendations), is_blocked, confidence,
        )

        # ── 3. Decision ──────────────────────────────────────────────────────
        published = []

        if is_blocked:
            # Публикуем HOLD decision для каждой рекомендации
            for rec in recommendations:
                payload = trade_decision_payload(
                    protocol_key     = rec["protocol_key"],
                    action           = "HOLD",
                    amount_usd       = rec.get("amount_usd", 0),
                    reasoning        = f"CEO HOLD: {block_reason}",
                    approved         = False,
                    rejection_reason = block_reason,
                )
                msg_id = self.publish(
                    Topic.TRADE_DECISION, payload, priority=Priority.HIGH
                )
                published.append(msg_id)
        else:
            # Одобряем рекомендации с confidence > 0.6
            min_confidence = 0.60
            for rec in recommendations:
                if confidence < min_confidence:
                    self.log.info(
                        "Skipping %s — confidence %.2f < %.2f",
                        rec["protocol_key"], confidence, min_confidence,
                    )
                    continue

                # CEO может скорректировать сумму (±20%)
                amount = rec.get("amount_usd", 1000)

                reasoning = (
                    f"CEO approved: {reasoning_base} "
                    f"| confidence={confidence:.2f} "
                    f"| APY={rec.get('apy', 0):.2f}%"
                )

                payload = trade_decision_payload(
                    protocol_key = rec["protocol_key"],
                    action       = rec.get("action", "OPEN"),
                    amount_usd   = amount,
                    reasoning    = reasoning,
                    approved     = True,
                )
                msg_id = self.publish(
                    Topic.TRADE_DECISION, payload, priority=Priority.NORMAL
                )
                published.append(msg_id)

        self.log.info("CEO published %d TRADE_DECISION messages", len(published))
        return published
