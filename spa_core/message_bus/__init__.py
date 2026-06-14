"""
SPA Message Bus — M4
SQLite-backed pub/sub шина для агентов оркестратора.

Быстрый старт:
    from message_bus import MessageBus, Topic, Priority
    from message_bus.topics import market_data_payload

    bus = MessageBus()
    msg_id = bus.publish(Topic.MARKET_DATA, "data_agent", market_data_payload([...]))
    msgs = bus.consume(Topic.MARKET_DATA, "strategy_agent")
    for m in msgs:
        process(m)
        bus.ack(m.id, "strategy_agent")
"""

from message_bus.bus import MessageBus
from message_bus.topics import (
    Topic,
    Priority,
    Message,
    market_data_payload,
    health_alert_payload,
    strategy_signal_payload,
    trade_decision_payload,
    execution_result_payload,
)

__all__ = [
    "MessageBus",
    "Topic",
    "Priority",
    "Message",
    "market_data_payload",
    "health_alert_payload",
    "strategy_signal_payload",
    "trade_decision_payload",
    "execution_result_payload",
]
