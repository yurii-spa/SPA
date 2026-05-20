"""
SPA FastAPI Server — M5
REST API поверх оркестратора и paper trading engine.

Запуск:
    cd spa_core
    uvicorn api.server:app --reload --port 8000

Endpoints:
    GET  /health          → статус сервера
    GET  /api/status      → портфель, позиций, risk, paper trading clock
    GET  /api/protocols   → список протоколов whitelist
    GET  /api/snapshots   → последние APY снапшоты
    GET  /api/trades      → история сделок
    GET  /api/risk-events → лог risk событий
    GET  /api/bus/stats   → статистика Message Bus
    POST /api/run         → запустить одну итерацию оркестратора
"""

from __future__ import annotations

import logging
import sys
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# ─── Path setup ─────────────────────────────────────────────────────────────
sys.path.insert(0, str(Path(__file__).parent.parent))

from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from database.init_db import get_connection, get_db_path, init_database
from paper_trading.engine import PaperTrader
from message_bus.bus import MessageBus
from orchestrator.graph import SPAOrchestrator

log = logging.getLogger("spa.api")

# ─── Globals (singleton pattern, safe для single-process uvicorn) ────────────
_trader: PaperTrader | None = None
_bus: MessageBus | None = None
_orchestrator: SPAOrchestrator | None = None
_last_run_state: dict | None = None


def _get_components() -> tuple[PaperTrader, MessageBus, SPAOrchestrator]:
    global _trader, _bus, _orchestrator
    if _trader is None:
        db_path = get_db_path()
        init_database(db_path)           # идемпотентно
        _trader = PaperTrader(db_path=db_path)
        _bus = MessageBus(db_path=db_path)
        _orchestrator = SPAOrchestrator(db_path=db_path)
    return _trader, _bus, _orchestrator


# ─── Lifespan ────────────────────────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    )
    log.info("SPA API starting up…")
    _get_components()          # прогреть синглтоны
    yield
    log.info("SPA API shutting down.")


# ─── App ─────────────────────────────────────────────────────────────────────
app = FastAPI(
    title="SPA — Smart Passive Aggregator",
    version="1.0.0",
    description="DeFi yield aggregation · Paper Trading API",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],      # GitHub Pages + localhost dev
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)


# ─── Models ──────────────────────────────────────────────────────────────────
class RunResponse(BaseModel):
    iteration: int
    timestamp: str
    fetch_ok: bool
    blocked: bool
    signals: int
    decisions: int
    executions: int
    errors: list[str]
    bus_stats: dict[str, Any]


# ─── Routes ──────────────────────────────────────────────────────────────────

@app.get("/health")
def health():
    """Простой healthcheck."""
    return {
        "status": "ok",
        "version": "1.0.0",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


@app.get("/api/status")
def get_status():
    """
    Полный статус портфеля: капитал, позиций, PnL, risk health, paper trading clock.
    """
    trader, _, _ = _get_components()
    try:
        return trader.get_status()
    except Exception as e:
        log.error(f"get_status error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/protocols")
def get_protocols():
    """Список протоколов whitelist с последним APY."""
    db_path = get_db_path()
    with get_connection(db_path) as conn:
        rows = conn.execute("""
            SELECT p.key, p.protocol, p.asset, p.chain, p.tier, p.is_active,
                   s.apy_total, s.apy_base, s.apy_reward,
                   s.tvl_usd, s.timestamp as last_snapshot
            FROM protocols p
            LEFT JOIN (
                SELECT protocol_key,
                       apy_total, apy_base, apy_reward, tvl_usd, timestamp,
                       ROW_NUMBER() OVER (PARTITION BY protocol_key ORDER BY timestamp DESC) as rn
                FROM apy_snapshots
                WHERE is_valid = 1
            ) s ON p.key = s.protocol_key AND s.rn = 1
            ORDER BY p.tier, COALESCE(s.apy_total, 0) DESC
        """).fetchall()
    return [dict(r) for r in rows]


@app.get("/api/snapshots")
def get_snapshots(limit: int = 50, protocol: str | None = None):
    """
    Последние APY снапшоты.

    ?limit=50      — сколько записей
    ?protocol=key  — фильтр по протоколу
    """
    db_path = get_db_path()
    with get_connection(db_path) as conn:
        if protocol:
            rows = conn.execute("""
                SELECT * FROM apy_snapshots
                WHERE protocol_key = ? AND is_valid = 1
                ORDER BY timestamp DESC LIMIT ?
            """, (protocol, limit)).fetchall()
        else:
            rows = conn.execute("""
                SELECT * FROM apy_snapshots
                WHERE is_valid = 1
                ORDER BY timestamp DESC LIMIT ?
            """, (limit,)).fetchall()
    return [dict(r) for r in rows]


@app.get("/api/trades")
def get_trades(limit: int = 50, strategy: str = "paper-v1", open_only: bool = False):
    """
    История сделок.

    ?open_only=true  — только открытые позиции
    """
    db_path = get_db_path()
    with get_connection(db_path) as conn:
        if open_only:
            rows = conn.execute("""
                SELECT * FROM paper_trades
                WHERE strategy_id = ? AND timestamp_close IS NULL
                ORDER BY timestamp_open DESC LIMIT ?
            """, (strategy, limit)).fetchall()
        else:
            rows = conn.execute("""
                SELECT * FROM paper_trades
                WHERE strategy_id = ?
                ORDER BY timestamp_open DESC LIMIT ?
            """, (strategy, limit)).fetchall()
    return [dict(r) for r in rows]


@app.get("/api/risk-events")
def get_risk_events(limit: int = 50, severity: str | None = None, unresolved_only: bool = False):
    """
    Лог risk событий.

    ?severity=HIGH         — фильтр по severity (LOW/MEDIUM/HIGH/CRITICAL)
    ?unresolved_only=true  — только активные
    """
    db_path = get_db_path()
    with get_connection(db_path) as conn:
        conditions = []
        params: list = []
        if severity:
            conditions.append("severity = ?")
            params.append(severity.upper())
        if unresolved_only:
            conditions.append("resolved = 0")
        where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
        params.append(limit)
        rows = conn.execute(f"""
            SELECT * FROM risk_events
            {where}
            ORDER BY timestamp DESC LIMIT ?
        """, params).fetchall()
    return [dict(r) for r in rows]


@app.get("/api/bus/stats")
def get_bus_stats():
    """Статистика Message Bus по топикам и статусам."""
    _, bus, _ = _get_components()
    return bus.stats()


@app.get("/api/bus/messages")
def get_bus_messages(topic: str | None = None, status: str | None = None, limit: int = 20):
    """
    Последние сообщения в шине.

    ?topic=MARKET_DATA  — фильтр по топику
    ?status=pending     — фильтр по статусу
    """
    db_path = get_db_path()
    with get_connection(db_path) as conn:
        conditions = []
        params: list = []
        if topic:
            conditions.append("topic = ?")
            params.append(topic.upper())
        if status:
            conditions.append("status = ?")
            params.append(status.lower())
        where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
  2     params.append(limit)
        rows = conn.execute(f"""
            SELECT id, message_id, topic, sender, consumer, priority,
                   status, timestamp, consumed_at, acked_at,
                   SUBSTR(payload_json, 1, 200) as payload_preview
            FROM message_bus
            {where}
            ORDER BY timestamp DESC LIMIT ?
        """, params).fetchall()
    return [dict(r) for r in rows]


@app.post("/api/run", response_model=RunResponse)
def run_iteration(background_tasks: BackgroundTasks):
    """
    Запустить одну итерацию оркестратора синхронно.
    Возвращает результат итерации.

    ⚠️  Блокирующий вызов (~1-3 секунды при живом DeFiLlama).
    """
    global _last_run_state
    _, _, orchestrator = _get_components()
    try:
        state = orchestrator.run_once()
        _last_run_state = state
        return RunResponse(
            iteration=state.get("iteration", 0),
            timestamp=state.get("timestamp", datetime.now(timezone.utc).isoformat()),
            fetch_ok=state.get("fetch_ok", False),
            blocked=state.get("is_blocked", False),
            signals=len(state.get("signals", [])),
            decisions=len(state.get("decisions", [])),
            executions=len(state.get("execution_results", [])),
            errors=state.get("errors", []),
            bus_stats=orchestrator.bus.stats(),
        )
    except Exception as e:
        log.error(f"run_iteration error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/run/last")
def get_last_run():
    """Результат последнего запуска оркестратора (если был)."""
    if _last_run_state is None:
        return {"status": "no_runs_yet"}
    return _last_run_state


@app.get("/api/strategy/state")
def get_strategy_state(strategy: str = "paper-v1", limit: int = 48):
    """
    История состояния стратегии (для графиков PnL / APY во времени).

    ?limit=48  — последние N записей (48 = 8 дней × 4-часовые снапшоты)
    """
    db_path = get_db_path()
    with get_connection(db_path) as conn:
        rows = conn.execute("""
            SELECT timestamp, total_capital_usd, deployed_capital_usd,
                   cash_usd, total_pnl_usd, total_pnl_pct,
                   current_apy, sharpe_to_date, max_drawdown_pct, trade_count
            FROM strategy_state
            WHERE strategy_id = ?
            ORDER BY timestamp DESC LIMIT ?
        """, (strategy, limit)).fetchall()
    return list(reversed([dict(r) for r in rows]))   # хронологический порядок


# ─── Dev entrypoint ──────────────────────────────────────────────────────────
if __name__ == "__main__":
    import uvicorn
    uvicorn.run("api.server:app", host="0.0.0.0", port=8000, reload=True, log_level="info")
