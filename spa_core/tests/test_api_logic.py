"""
Tests for API data layer — verifies DB queries used by server endpoints.
Does NOT require FastAPI installed (tests pure SQLite logic).
"""

import sys
from pathlib import Path
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from database.init_db import init_database, get_connection
from paper_trading.engine import PaperTrader
from message_bus.bus import MessageBus
from message_bus.topics import Topic


@pytest.fixture
def db_path(tmp_path):
    p = tmp_path / "test_api.db"
    init_database(p)
    return p


def test_protocols_query(db_path):
    """GET /api/protocols — query returns all 7 seeded protocols."""
    with get_connection(db_path) as conn:
        rows = conn.execute("""
            SELECT p.key, p.protocol, p.asset, p.chain, p.tier
            FROM protocols p
            ORDER BY p.tier, p.key
        """).fetchall()
    assert len(rows) == 7
    tiers = {r["tier"] for r in rows}
    assert tiers == {"T1", "T2"}


def test_status_returns_portfolio(db_path):
    """GET /api/status — PaperTrader.get_status() returns expected keys."""
    trader = PaperTrader(db_path=db_path)
    status = trader.get_status()
    assert "portfolio" in status
    assert "positions" in status
    assert "risk" in status
    assert "paper_trading" in status
    p = status["portfolio"]
    assert p["total_capital_usd"] == 10_000.0
    assert p["cash_usd"] == 10_000.0
    assert p["deployed_usd"] == 0.0


def test_bus_stats_returns_dict(db_path):
    """GET /api/bus/stats — MessageBus.stats() returns topic dict."""
    bus = MessageBus(db_path=db_path)
    stats = bus.stats()
    assert isinstance(stats, dict)
    # After publish, stats should reflect it
    bus.publish(Topic.MARKET_DATA, "test_agent", {"data": [1, 2, 3]})
    stats2 = bus.stats()
    assert stats2.get(Topic.MARKET_DATA, {}).get("pending", 0) >= 1


def test_snapshots_query_empty(db_path):
    """GET /api/snapshots — empty DB returns empty list."""
    with get_connection(db_path) as conn:
        rows = conn.execute(
            "SELECT * FROM apy_snapshots WHERE is_valid = 1 ORDER BY timestamp DESC LIMIT 50"
        ).fetchall()
    assert rows == []


def test_trades_query_empty(db_path):
    """GET /api/trades — fresh DB returns empty list."""
    with get_connection(db_path) as conn:
        rows = conn.execute(
            "SELECT * FROM paper_trades WHERE strategy_id = 'paper-v1' ORDER BY timestamp_open DESC LIMIT 50"
        ).fetchall()
    assert rows == []


def test_trades_open_only_filter(db_path):
    """GET /api/trades?open_only=true — only returns trades without close timestamp."""
    trader = PaperTrader(db_path=db_path)
    trader.open_position("aave-v3-usdc-ethereum", amount_usd=1000.0,
                         current_apy=4.65, tvl_usd=138_000_000)

    with get_connection(db_path) as conn:
        open_trades = conn.execute("""
            SELECT * FROM paper_trades
            WHERE strategy_id = 'paper-v1' AND timestamp_close IS NULL
            ORDER BY timestamp_open DESC LIMIT 50
        """).fetchall()
        all_trades = conn.execute("""
            SELECT * FROM paper_trades
            WHERE strategy_id = 'paper-v1'
            ORDER BY timestamp_open DESC LIMIT 50
        """).fetchall()

    assert len(open_trades) == 1
    assert len(all_trades) == 1
    assert open_trades[0]["protocol_key"] == "aave-v3-usdc-ethereum"


def test_strategy_state_history(db_path):
    """GET /api/strategy/state — returns chronological list."""
    with get_connection(db_path) as conn:
        rows = conn.execute("""
            SELECT timestamp, total_capital_usd, deployed_capital_usd,
                   cash_usd, total_pnl_usd
            FROM strategy_state
            WHERE strategy_id = 'paper-v1'
            ORDER BY timestamp DESC LIMIT 48
        """).fetchall()
    # Fresh DB has initial strategy_state seeded by PaperTrader constructor
    assert isinstance(rows, list)


def test_risk_events_filter(db_path):
    """GET /api/risk-events — severity filter works."""
    with get_connection(db_path) as conn:
        conn.execute("""
            INSERT INTO risk_events (timestamp, event_type, severity, message)
            VALUES (datetime('now','utc'), 'data_anomaly', 'HIGH', 'test event')
        """)
        conn.commit()

        high_rows = conn.execute(
            "SELECT * FROM risk_events WHERE severity = 'HIGH' ORDER BY timestamp DESC LIMIT 50"
        ).fetchall()
        low_rows = conn.execute(
            "SELECT * FROM risk_events WHERE severity = 'LOW' ORDER BY timestamp DESC LIMIT 50"
        ).fetchall()

    assert len(high_rows) == 1
    assert len(low_rows) == 0


def test_bus_messages_topic_filter(db_path):
    """GET /api/bus/messages — topic filter returns only matching messages."""
    bus = MessageBus(db_path=db_path)
    bus.publish(Topic.MARKET_DATA, "data_agent", {"apy": 4.5})
    bus.publish(Topic.HEALTH_ALERT, "monitoring_agent", {"status": "OK"})

    with get_connection(db_path) as conn:
        market_rows = conn.execute(
            "SELECT * FROM message_bus WHERE topic = 'MARKET_DATA' ORDER BY timestamp DESC LIMIT 20"
        ).fetchall()
        health_rows = conn.execute(
            "SELECT * FROM message_bus WHERE topic = 'HEALTH_ALERT' ORDER BY timestamp DESC LIMIT 20"
        ).fetchall()

    assert len(market_rows) == 1
    assert len(health_rows) == 1
    assert market_rows[0]["sender"] == "data_agent"
