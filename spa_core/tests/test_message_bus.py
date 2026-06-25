"""
Tests для Message Bus (M4) — publish/consume/ack/requeue/stats.
"""
from __future__ import annotations

import sys
import time
import tempfile
from datetime import datetime, timezone, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from database.init_db import init_database
from message_bus.bus import MessageBus
try:
    from spa_core.utils.errors import RegistryError as _RegistryError
except ImportError:
    _RegistryError = None
from message_bus.topics import Priority, Topic

# ─── Runner ───────────────────────────────────────────────────────────────────

PASS = FAIL = 0
_log = []

def run(name, fn):
    global PASS, FAIL
    try:
        fn()
        PASS += 1
        _log.append(f"  ✅  {name}")
    except Exception as e:
        FAIL += 1
        _log.append(f"  ❌  {name}  →  {str(e)[:90]}")

def make_bus() -> MessageBus:
    p = Path(tempfile.mktemp(suffix=".db"))
    init_database(db_path=p)
    return MessageBus(db_path=p)

# ─── Publish ──────────────────────────────────────────────────────────────────

def test_publish_returns_id():
    bus = make_bus()
    msg_id = bus.publish(Topic.MARKET_DATA, "data_agent", {"test": True})
    assert isinstance(msg_id, str) and len(msg_id) == 36
run("Publish::returns_uuid_string", test_publish_returns_id)

def test_publish_invalid_topic():
    bus = make_bus()
    _expected = (ValueError,) + ((_RegistryError,) if _RegistryError else ())
    try:
        bus.publish("UNKNOWN_TOPIC", "agent", {})
        assert False, "Should raise ValueError or RegistryError"
    except _expected:
        pass
run("Publish::raises_on_invalid_topic", test_publish_invalid_topic)

def test_publish_multiple_topics():
    bus = make_bus()
    ids = [
        bus.publish(Topic.MARKET_DATA,     "data_agent",     {"n": 1}),
        bus.publish(Topic.HEALTH_ALERT,    "monitor_agent",  {"n": 2}),
        bus.publish(Topic.STRATEGY_SIGNAL, "strategy_agent", {"n": 3}),
    ]
    assert len(set(ids)) == 3, "Each message_id must be unique"
run("Publish::unique_ids_per_message", test_publish_multiple_topics)

def test_publish_priority():
    bus = make_bus()
    bus.publish(Topic.HEALTH_ALERT, "monitor", {"x": 1}, priority=Priority.LOW)
    bus.publish(Topic.HEALTH_ALERT, "monitor", {"x": 2}, priority=Priority.CRITICAL)
    msgs = bus.consume(Topic.HEALTH_ALERT, "ceo")
    # CRITICAL (priority=1) должно прийти первым
    assert msgs[0].payload["x"] == 2, f"Expected x=2 (CRITICAL), got {msgs[0].payload}"
run("Publish::priority_ordering_high_first", test_publish_priority)

# ─── Consume ─────────────────────────────────────────────────────────────────

def test_consume_empty_returns_empty():
    bus = make_bus()
    msgs = bus.consume(Topic.MARKET_DATA, "consumer_a")
    assert msgs == []
run("Consume::empty_queue_returns_empty_list", test_consume_empty_returns_empty)

def test_consume_marks_as_consumed():
    bus = make_bus()
    bus.publish(Topic.MARKET_DATA, "sender", {"k": "v"})
    msgs1 = bus.consume(Topic.MARKET_DATA, "consumer_a")
    msgs2 = bus.consume(Topic.MARKET_DATA, "consumer_b")
    assert len(msgs1) == 1
    assert len(msgs2) == 0, "Second consumer should get nothing (already consumed)"
run("Consume::message_not_available_after_consume", test_consume_marks_as_consumed)

def test_consume_multiple_topics():
    bus = make_bus()
    bus.publish(Topic.MARKET_DATA,  "a", {"t": "md"})
    bus.publish(Topic.HEALTH_ALERT, "b", {"t": "ha"})
    msgs = bus.consume([Topic.MARKET_DATA, Topic.HEALTH_ALERT], "ceo")
    assert len(msgs) == 2
    topics = {m.topic for m in msgs}
    assert topics == {Topic.MARKET_DATA, Topic.HEALTH_ALERT}
run("Consume::multiple_topics_in_one_call", test_consume_multiple_topics)

def test_consume_respects_limit():
    bus = make_bus()
    for i in range(10):
        bus.publish(Topic.MARKET_DATA, "sender", {"i": i})
    msgs = bus.consume(Topic.MARKET_DATA, "consumer", limit=3)
    assert len(msgs) == 3
run("Consume::respects_limit_parameter", test_consume_respects_limit)

def test_consume_sets_consumer():
    bus = make_bus()
    bus.publish(Topic.MARKET_DATA, "sender", {})
    msgs = bus.consume(Topic.MARKET_DATA, "my_consumer")
    assert msgs[0].consumer == "my_consumer"
    assert msgs[0].status   == "consumed"
run("Consume::sets_consumer_and_status", test_consume_sets_consumer)

# ─── Ack ──────────────────────────────────────────────────────────────────────

def test_ack_returns_true():
    bus = make_bus()
    bus.publish(Topic.MARKET_DATA, "sender", {})
    msgs = bus.consume(Topic.MARKET_DATA, "consumer")
    result = bus.ack(msgs[0].id, "consumer")
    assert result is True
run("Ack::returns_true_on_success", test_ack_returns_true)

def test_ack_wrong_consumer_returns_false():
    bus = make_bus()
    bus.publish(Topic.MARKET_DATA, "sender", {})
    msgs = bus.consume(Topic.MARKET_DATA, "consumer_a")
    result = bus.ack(msgs[0].id, "consumer_b")  # wrong consumer
    assert result is False
run("Ack::wrong_consumer_returns_false", test_ack_wrong_consumer_returns_false)

def test_ack_idempotent():
    bus = make_bus()
    bus.publish(Topic.MARKET_DATA, "sender", {})
    msgs = bus.consume(Topic.MARKET_DATA, "consumer")
    bus.ack(msgs[0].id, "consumer")
    result2 = bus.ack(msgs[0].id, "consumer")  # second ack
    assert result2 is False  # уже acked, не consumed
run("Ack::second_ack_returns_false", test_ack_idempotent)

# ─── Nack / Requeue ───────────────────────────────────────────────────────────

def test_nack_requeues_message():
    bus = make_bus()
    bus.publish(Topic.MARKET_DATA, "sender", {"x": 42})
    msgs = bus.consume(Topic.MARKET_DATA, "consumer_a")
    assert len(msgs) == 1
    # nack — вернуть в очередь
    bus.nack(msgs[0].id, "consumer_a")
    # другой consumer может получить
    msgs2 = bus.consume(Topic.MARKET_DATA, "consumer_b")
    assert len(msgs2) == 1
    assert msgs2[0].payload["x"] == 42
run("Nack::requeues_for_another_consumer", test_nack_requeues_message)

def test_requeue_stale():
    bus = make_bus()
    bus.publish(Topic.MARKET_DATA, "sender", {"stale": True})
    msgs = bus.consume(Topic.MARKET_DATA, "slow_consumer")
    assert len(msgs) == 1

    # Симулируем просроченный consumed_at вручную
    from database.init_db import get_connection
    old_ts = (datetime.now(timezone.utc) - timedelta(minutes=10)).isoformat()
    with get_connection(bus.db_path) as conn:
        conn.execute(
            "UPDATE message_bus SET consumed_at=? WHERE message_id=?",
            (old_ts, msgs[0].id)
        )
        conn.commit()

    requeued = bus.requeue_stale(timeout_minutes=5)
    assert requeued == 1, f"Expected 1 requeued, got {requeued}"

    # Теперь другой consumer может получить
    msgs2 = bus.consume(Topic.MARKET_DATA, "another_consumer")
    assert len(msgs2) == 1
run("Requeue::stale_consumed_message_requeued", test_requeue_stale)

def test_fresh_not_requeued():
    bus = make_bus()
    bus.publish(Topic.MARKET_DATA, "sender", {})
    bus.consume(Topic.MARKET_DATA, "consumer")
    requeued = bus.requeue_stale(timeout_minutes=5)
    assert requeued == 0, "Fresh consumed messages should not be requeued"
run("Requeue::fresh_message_not_requeued", test_fresh_not_requeued)

# ─── Stats ────────────────────────────────────────────────────────────────────

def test_stats_structure():
    bus = make_bus()
    stats = bus.stats()
    assert isinstance(stats, dict)
    for topic in Topic.ALL:
        assert topic in stats
        assert "pending" in stats[topic]
        assert "acked" in stats[topic]
run("Stats::has_all_topics", test_stats_structure)

def test_stats_counts():
    bus = make_bus()
    bus.publish(Topic.MARKET_DATA, "s1", {})
    bus.publish(Topic.MARKET_DATA, "s2", {})
    bus.publish(Topic.HEALTH_ALERT, "s3", {})
    stats = bus.stats()
    assert stats[Topic.MARKET_DATA]["pending"] == 2
    assert stats[Topic.HEALTH_ALERT]["pending"] == 1
run("Stats::counts_pending_messages", test_stats_counts)

# ─── Purge ────────────────────────────────────────────────────────────────────

def test_purge_acked():
    bus = make_bus()
    bus.publish(Topic.MARKET_DATA, "s", {})
    msgs = bus.consume(Topic.MARKET_DATA, "c")
    bus.ack(msgs[0].id, "c")
    purged = bus.purge(status="acked")
    assert purged == 1
run("Purge::removes_acked_messages", test_purge_acked)

# ─── Payload integrity ────────────────────────────────────────────────────────

def test_payload_preserved():
    bus = make_bus()
    payload = {"nested": {"a": 1, "b": [1, 2, 3]}, "unicode": "тест"}
    bus.publish(Topic.STRATEGY_SIGNAL, "strategy", payload)
    msgs = bus.consume(Topic.STRATEGY_SIGNAL, "ceo")
    assert msgs[0].payload == payload
run("Payload::nested_and_unicode_preserved", test_payload_preserved)

# ─── Report ───────────────────────────────────────────────────────────────────

print(f"\n{'═'*62}")
print(f"  SPA Message Bus (M4) — Test Suite")
print(f"{'═'*62}")
for line in _log:
    print(line)
print(f"{'─'*62}")
total = PASS + FAIL
pct = "100%" if FAIL == 0 else f"{int(PASS/total*100)}%"
print(f"  {total} tests  |  {PASS} passed  |  {FAIL} failed  |  {pct} green")
print(f"{'═'*62}\n")
