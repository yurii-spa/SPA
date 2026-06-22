"""
SPA FastAPI server — real-time data API (v0.17).
Run: uvicorn spa_core.api.server:app --reload --port 8765

Dashboard auto-detects: if http://localhost:8765/health returns 200,
switches from JSON polling to live API.

Endpoints:
    GET  /health              → server liveness + version
    GET  /api/portfolio       → current portfolio state
    GET  /api/positions       → current open positions
    GET  /api/pools           → latest DeFiLlama APY pool data
    GET  /api/risk            → risk alerts
    GET  /api/trades          → recent trades (optional ?limit=N)
    GET  /api/backtest        → backtest results
    GET  /api/optimization    → optimisation recommendations
    GET  /api/status          → all of the above merged (single-fetch mode)
    POST /api/chat            → LLM agent chat (falls back to canned if no API key)
    WS   /ws/agents           → real-time agent activity stream

    --- v1 versioned read-only API (MP-1527) ---
    GET  /api/v1/status       → KANBAN sprint/done_count summary
    GET  /api/v1/golive       → GoLive readiness report (26 criteria)
    GET  /api/v1/adapters     → Adapter registry with live APY
    GET  /api/v1/evidence     → Paper trading evidence history

IMPORTANT: This server is READ-ONLY. No write operations allowed.
All write operations go through normal file/CLI interface.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import sys
import time as _time
from collections import deque
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# ─── Path setup ──────────────────────────────────────────────────────────────
# Allows running as: uvicorn spa_core.api.server:app from project root
_HERE = Path(__file__).resolve().parent
_SPA_CORE = _HERE.parent
_PROJECT_ROOT = _SPA_CORE.parent
for _p in [str(_SPA_CORE), str(_PROJECT_ROOT)]:
    if _p not in sys.path:
        sys.path.insert(0, _p)

from fastapi import FastAPI, HTTPException, Query, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel

from spa_core.api.agent_broadcaster import broadcaster

log = logging.getLogger("spa.api")

# ─── Data directory ──────────────────────────────────────────────────────────
_DATA_DIR = Path(os.environ.get("SPA_DATA_DIR", _PROJECT_ROOT / "data"))


def _load_json(filename: str, default: Any = None) -> Any:
    """Load a JSON file from data_dir; return default if missing or corrupt."""
    path = _DATA_DIR / filename
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        log.debug(f"Data file not found: {path} — returning default")
        return default if default is not None else {}
    except json.JSONDecodeError as e:
        log.warning(f"JSON decode error in {path}: {e}")
        return default if default is not None else {}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ─── PaperTrader (optional — graceful fallback) ───────────────────────────────
def _get_live_portfolio() -> dict | None:
    """
    Try to read live portfolio directly from PaperTrader.
    Returns None if the DB / engine is unavailable (e.g. first run, no DB yet).
    """
    try:
        from paper_trading.engine import PaperTrader
        from database.init_db import get_db_path, init_database
        db_path = get_db_path()
        init_database(db_path)
        trader = PaperTrader(db_path=db_path)
        return trader.get_status()
    except Exception as e:
        log.debug(f"PaperTrader unavailable: {e}")
        return None


# ─── Event Queue (SSE ring buffer) ───────────────────────────────────────────

class _EventQueue:
    """
    In-memory ring buffer (last 50 events) + async fan-out to SSE subscribers.

    push(event)    — add event, fan-out to all active SSE listeners
    subscribe()    — returns an asyncio.Queue for one SSE client
    unsubscribe()  — remove a client queue on disconnect
    history()      — snapshot of the ring buffer as a plain list
    """

    def __init__(self, maxsize: int = 50) -> None:
        self._history: deque = deque(maxlen=maxsize)
        self._subscribers: list[asyncio.Queue] = []

    async def push(self, event: dict[str, Any]) -> None:
        self._history.append(event)
        for q in list(self._subscribers):
            try:
                q.put_nowait(event)
            except asyncio.QueueFull:
                pass  # slow consumer — drop rather than block

    def subscribe(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=200)
        self._subscribers.append(q)
        return q

    def unsubscribe(self, q: asyncio.Queue) -> None:
        try:
            self._subscribers.remove(q)
        except ValueError:
            pass

    def history(self) -> list[dict]:
        return list(self._history)

    def clear(self) -> None:
        """Clear history and subscribers (used in tests)."""
        self._history.clear()
        self._subscribers.clear()


event_queue = _EventQueue(maxsize=50)


# ─── Lifespan ────────────────────────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    )
    log.info(f"SPA API v0.17 starting — data dir: {_DATA_DIR}")
    broadcaster.start()
    yield
    broadcaster.stop()
    log.info("SPA API shutting down.")


# ─── App ─────────────────────────────────────────────────────────────────────
app = FastAPI(
    title="SPA — Smart Passive Aggregator",
    version="v0.17",
    description=(
        "Real-time DeFi yield aggregation API. "
        "Dashboard auto-detects this server and switches from static JSON to live data."
    ),
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost",
        "http://localhost:8765",
        "http://localhost:3000",
        "http://localhost:5173",
        "http://127.0.0.1:8765",
        "https://yurii-spa.github.io",
        # Public dashboard origins (live API via api.earn-defi.com tunnel)
        "https://earn-defi.com",
        "https://www.earn-defi.com",
        "https://app.earn-defi.com",
        # Wildcard for any localhost port (development)
        "http://localhost:*",
    ],
    # Allow localhost (any port) and *.earn-defi.com / *.pages.dev preview deploys
    allow_origin_regex=r"https?://localhost(:\d+)?|https://([a-z0-9-]+\.)?earn-defi\.com|https://[a-z0-9-]+\.pages\.dev",
    allow_credentials=False,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)


# ─── Helpers ─────────────────────────────────────────────────────────────────

def _error(msg: str, status: int = 500):
    raise HTTPException(status_code=status, detail={"error": msg})


# ─── Routes ──────────────────────────────────────────────────────────────────

@app.get("/health", tags=["meta"])
def health():
    """
    Liveness check. Dashboard polls this to decide between live API vs JSON fallback.
    Returns 200 with version info when server is running.
    """
    return {
        "status": "ok",
        "version": "v0.16",
        "timestamp": _now(),
    }


@app.get("/api/portfolio", tags=["data"])
def get_portfolio():
    """
    Current portfolio state — live from PaperTrader, falling back to paper_trading_status.json.
    Schema: total_capital_usd, deployed_usd, cash_usd, cash_pct, total_pnl_usd, apy_pct.
    """
    live = _get_live_portfolio()
    if live is not None:
        return live.get("portfolio", {})

    # Primary fallback: paper_trading_status.json (written by cycle_runner every cycle)
    pts = _load_json("paper_trading_status.json", None)
    if pts:
        positions = pts.get("current_positions", {})
        deployed = sum(float(v) for v in positions.values()) if isinstance(positions, dict) else 0.0
        equity = float(pts.get("current_equity", 100_000.0))
        cash = max(0.0, equity - deployed)
        capital = 100_000.0
        return {
            "total_capital_usd": capital,
            "deployed_usd": round(deployed, 2),
            "cash_usd": round(cash, 2),
            "cash_pct": round(cash / capital, 4) if capital else 0.0,
            "total_pnl_usd": round(equity - capital, 2),
            "total_return_pct": round(pts.get("total_return_pct", 0.0), 4),
            "apy_pct": round(pts.get("apy_today_pct", 0.0), 2),
            "days_running": pts.get("days_running", 0),
            "source": "paper_trading_status",
        }

    # Last-resort: status.json (legacy)
    status = _load_json("status.json", {})
    return status.get("portfolio", {
        "total_capital_usd": 100_000.0,
        "deployed_usd": 0,
        "cash_usd": 100_000.0,
        "cash_pct": 1.0,
        "total_pnl_usd": 0.0,
        "total_drawdown_pct": 0.0,
    })


@app.get("/api/positions", tags=["data"])
def get_positions():
    """
    Current open positions — live from PaperTrader, falling back to data/status.json.
    Schema matches data/positions.json.
    """
    live = _get_live_portfolio()
    if live is not None:
        return live.get("positions", [])

    status = _load_json("status.json", {})
    return status.get("positions", [])


@app.get("/api/pools", tags=["data"])
def get_pools():
    """
    Latest DeFiLlama APY pool data.
    Schema matches data/pools.json (falls back to data/protocols.json).
    """
    pools = _load_json("pools.json", None)
    if pools is not None:
        return pools

    # Fallback: protocols.json is the nearest equivalent
    protocols = _load_json("protocols.json", [])
    return protocols


@app.get("/api/risk", tags=["data"])
def get_risk():
    """
    Risk alerts and portfolio health. Schema matches data/risk_alerts.json.
    """
    live = _get_live_portfolio()
    if live is not None:
        risk_data = live.get("risk", {})
        return {
            "generated_at": _now(),
            "status": "ok" if risk_data.get("health_approved", True) else "alert",
            "count": len(risk_data.get("violations", [])),
            "alerts": risk_data.get("violations", []),
            "warnings": risk_data.get("warnings", []),
            "var_usd": risk_data.get("var_usd", 0.0),
            "var_pct": risk_data.get("var_pct", 0.0),
            "var_breach": risk_data.get("var_breach", False),
        }

    return _load_json("risk_alerts.json", {
        "generated_at": _now(),
        "count": 0,
        "status": "ok",
        "alerts": [],
    })


@app.get("/api/trades", tags=["data"])
def get_trades(limit: int = Query(default=20, ge=1, le=500)):
    """
    Recent paper trades. Reads from data/trades.json.
    ?limit=N — number of most recent trades to return (default 20, max 500).
    """
    trades = _load_json("trades.json", [])
    if isinstance(trades, list):
        return trades[:limit]
    # trades.json might be wrapped in an object
    if isinstance(trades, dict):
        inner = trades.get("trades", trades.get("data", []))
        return inner[:limit] if isinstance(inner, list) else []
    return []


@app.get("/api/backtest", tags=["data"])
def get_backtest():
    """
    Backtest results. Schema matches data/backtest_results.json.
    """
    return _load_json("backtest_results.json", {
        "generated_at": _now(),
        "data_source": "unavailable",
        "metrics": {},
        "equity_curve": [],
    })


@app.get("/api/backtest/replay", tags=["backtesting"])
def get_backtest_replay(days: int = Query(default=90, ge=1, le=365)):
    """
    Full historical replay data — one frame per day.

    Reads from data/pnl_history.json (real paper-trading history) or falls
    back to a synthetic OU simulation of the requested length.

    Query params:
        days: number of synthetic days if real history is unavailable (default 90)

    Response: {source, total_days, frames: [{day, date, portfolio_value, ...}]}
    """
    try:
        from spa_core.backtesting.replay import ReplayEngine
        engine = ReplayEngine(data_dir=_DATA_DIR, synthetic_days=days)
        frames = engine.full_replay()
        return {
            "generated_at": _now(),
            "source": engine.source,
            "total_days": engine.total_days,
            "frames": frames,
        }
    except Exception as e:
        log.warning(f"/api/backtest/replay error: {e}")
        raise HTTPException(status_code=500, detail={"error": str(e)})


@app.get("/api/backtest/summary", tags=["backtesting"])
def get_backtest_summary():
    """
    Replay summary metrics computed from the full pnl_history equity curve.

    Response: {total_days, total_return_pct, annualized_return, sharpe_ratio,
               max_drawdown, win_rate, best_day, worst_day, data_source}
    """
    try:
        from spa_core.backtesting.replay import ReplayEngine
        engine = ReplayEngine(data_dir=_DATA_DIR)
        summary = engine.replay_summary()
        summary["generated_at"] = _now()
        return summary
    except Exception as e:
        log.warning(f"/api/backtest/summary error: {e}")
        raise HTTPException(status_code=500, detail={"error": str(e)})


@app.get("/api/backtest/compare", tags=["backtesting"])
def get_backtest_compare(
    days: int = Query(default=90, ge=1, le=365),
    seed: int = Query(default=42, ge=0),
):
    """
    Side-by-side strategy comparison: v1_passive vs v2_aggressive.

    Both strategies run on the same synthetic dataset (same seed) so any
    performance difference is purely due to strategy parameters.

    Query params:
        days: backtest window length (default 90)
        seed: random seed for reproducibility (default 42)

    Response: {winner, delta, strategies: {v1_passive, v2_aggressive}}
    """
    try:
        from spa_core.backtesting.scenario_runner import compare_scenarios
        result = compare_scenarios(days=days, seed=seed)
        # Strip bulky equity_curves from nested strategy dicts for the API response
        for key in ("v1_passive", "v2_aggressive"):
            result[key].pop("equity_curve", None)
        result["generated_at"] = _now()
        return result
    except Exception as e:
        log.warning(f"/api/backtest/compare error: {e}")
        raise HTTPException(status_code=500, detail={"error": str(e)})


@app.get("/api/optimization", tags=["data"])
def get_optimization():
    """
    Optimisation recommendations from the last strategy scan.
    Reads from data/strategy_v2.json or data/strategy_comparison.json.
    """
    # Try strategy_v2 first (most up to date optimisation output)
    v2 = _load_json("strategy_v2.json", None)
    if v2 is not None:
        return v2

    comparison = _load_json("strategy_comparison.json", None)
    if comparison is not None:
        return comparison

    return {
        "generated_at": _now(),
        "recommendations": [],
        "status": "no_data",
    }


@app.get("/api/status", tags=["data"])
def get_status():
    """
    Aggregated status — all sections in one response (single-fetch dashboard mode).
    Merges portfolio, positions, risk, paper_trading clock, strategy, and backtest summary.
    """
    live = _get_live_portfolio()

    if live is not None:
        # Augment live data with backtest summary
        backtest = _load_json("backtest_results.json", {})
        live["backtest_summary"] = backtest.get("metrics", {})
        live["pools_count"] = len(_load_json("protocols.json", []))
        live["server_timestamp"] = _now()
        live["data_source"] = "live"
        return live

    # Fallback: assemble from JSON files
    status = _load_json("status.json", {})
    backtest = _load_json("backtest_results.json", {})
    risk_alerts = _load_json("risk_alerts.json", {})
    trades = _load_json("trades.json", [])

    return {
        "timestamp": _now(),
        "data_source": "json",
        "portfolio": status.get("portfolio", {}),
        "positions": status.get("positions", []),
        "risk": status.get("risk", {}),
        "risk_alerts": risk_alerts.get("alerts", []),
        "paper_trading": status.get("paper_trading", {}),
        "strategy": status.get("strategy", {}),
        "backtest_summary": backtest.get("metrics", {}),
        "recent_trades": trades[:5] if isinstance(trades, list) else [],
        "server_timestamp": _now(),
    }


# ─── Chat (LLM agent reasoning) ──────────────────────────────────────────────

class _ChatRequest(BaseModel):
    question: str


# Lazy-initialised singleton — created on first request, never at import time.
_chat_handler_instance = None


def _get_chat_handler():
    """Return (or create) the ChatHandler singleton."""
    global _chat_handler_instance
    if _chat_handler_instance is None:
        try:
            from spa_core.agents.chat_handler import ChatHandler
            from database.init_db import get_db_path
            _chat_handler_instance = ChatHandler(
                db_path=str(get_db_path()),
                data_dir=str(_DATA_DIR),
            )
            log.info("ChatHandler initialised (LLM agent chat active)")
        except Exception as e:
            log.warning(f"ChatHandler init failed — chat will use canned responses: {e}")
            # Return a minimal fallback so the endpoint still works
            _chat_handler_instance = _FallbackChatHandler()
    return _chat_handler_instance


class _FallbackChatHandler:
    """Minimal fallback used when ChatHandler cannot be initialised."""

    def handle(self, question: str) -> dict:
        return {
            "agent":    "TraderAgent",
            "response": "Agent system offline. Check server logs for details.",
            "used_llm": False,
        }


@app.post("/api/chat", tags=["chat"])
def post_chat(body: _ChatRequest):
    """
    Ask an LLM agent a question about the portfolio.

    - Routes to TraderAgent / DataAgent / RiskAgent / ReportAgent by keyword.
    - Enriches the prompt with live portfolio context.
    - Falls back to canned responses when ANTHROPIC_API_KEY is not set.

    Request body:  {"question": "why did you buy maple?"}
    Response body: {"agent": "TraderAgent", "response": "...", "used_llm": true, "timestamp": "..."}
    """
    question = (body.question or "").strip()
    if not question:
        raise HTTPException(status_code=400, detail={"error": "question must not be empty"})

    handler = _get_chat_handler()
    result = handler.handle(question)
    result["timestamp"] = _now()
    return result


# ─── WebSocket ────────────────────────────────────────────────────────────────

@app.websocket("/ws/agents")
async def ws_agents(websocket: WebSocket):
    """
    Real-time agent activity stream.

    On connect:   sends current portfolio snapshot
    Every 5s:     emits rotating agent activity events
    On alert:     emits immediately with type="alert"

    Message schema:
        {"agent": "DataAgent", "message": "...", "timestamp": "...", "type": "activity"}
        {"agent": "RiskAgent", "message": "...", "timestamp": "...", "type": "alert", "data": {...}}
    """
    await broadcaster.connect(websocket)
    try:
        # Send initial portfolio snapshot on connect
        live = _get_live_portfolio()
        snapshot = {
            "agent": "PortfolioAgent",
            "message": "Connected to SPA agent stream — sending portfolio snapshot",
            "timestamp": _now(),
            "type": "snapshot",
            "data": {
                "portfolio": live.get("portfolio", {}) if live else {},
                "positions": live.get("positions", []) if live else [],
                "risk": live.get("risk", {}) if live else {},
            },
        }
        await broadcaster.send_to(websocket, snapshot)

        # Keep connection alive — the broadcaster background loop handles 5s messages.
        # We just wait for the client to disconnect.
        while True:
            # Receive any client pings / messages (ignored, but keeps the loop alive)
            try:
                data = await websocket.receive_text()
                # Echo back any ping
                if data.strip().lower() in ("ping", ""):
                    await broadcaster.send_to(websocket, {
                        "type": "pong",
                        "timestamp": _now(),
                    })
            except WebSocketDisconnect:
                break

    except WebSocketDisconnect:
        pass
    except Exception as e:
        log.warning(f"WebSocket error: {e}")
    finally:
        broadcaster.disconnect(websocket)


# ─── SSE + Agent Thought Events ──────────────────────────────────────────────

class _ThoughtRequest(BaseModel):
    """Payload for POST /api/agent/thought."""
    agent:   str
    message: str
    type:    str = "agent_thought"
    data:    dict | None = None


@app.post("/api/agent/thought", tags=["events"])
async def post_agent_thought(body: _ThoughtRequest):
    """
    Push a structured agent event into the SSE stream and ring buffer.

    Called by export_data.py during its run so the dashboard shows live
    agent activity in real time.

    Supported types: agent_thought, agent_action, portfolio_update, risk_alert
    """
    if not body.message.strip():
        raise HTTPException(status_code=400, detail={"error": "message must not be empty"})

    event: dict[str, Any] = {
        "agent":     body.agent,
        "message":   body.message.strip(),
        "type":      body.type,
        "timestamp": _now(),
        "data":      body.data or {},
    }
    await event_queue.push(event)
    await broadcaster.broadcast(event)   # also fan-out to WebSocket clients
    log.info(f"[{body.type}] {body.agent}: {body.message[:80]}")
    return {"ok": True, "event_count": len(event_queue.history())}


@app.get("/api/events/history", tags=["events"])
def get_events_history():
    """
    Return the last 50 agent events as JSON.
    Useful for catch-up on page load or testing without SSE.
    """
    history = event_queue.history()
    return {"events": history, "count": len(history)}


@app.get("/api/events", tags=["events"])
async def sse_stream(request: Request):
    """
    Server-Sent Events stream for real-time agent activity.

    Connect via: EventSource('http://localhost:8765/api/events')

    Each event is a JSON object with fields:
        agent, message, type, timestamp, data

    Event types:
        agent_thought     — agent reasoning / status during export
        agent_action      — trade / allocation action taken
        portfolio_update  — portfolio value changed
        risk_alert        — risk policy violation
    """
    queue = event_queue.subscribe()

    async def generator():
        # Send last 5 historical events as catch-up on connect
        for evt in event_queue.history()[-5:]:
            yield f"data: {json.dumps(evt)}\n\n"
        try:
            while True:
                if await request.is_disconnected():
                    break
                try:
                    evt = await asyncio.wait_for(queue.get(), timeout=25.0)
                    yield f"data: {json.dumps(evt)}\n\n"
                except asyncio.TimeoutError:
                    yield ": keepalive\n\n"   # SSE comment — keeps proxy connections alive
        except (asyncio.CancelledError, GeneratorExit):
            pass
        finally:
            event_queue.unsubscribe(queue)

    return StreamingResponse(
        generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control":     "no-cache",
            "X-Accel-Buffering": "no",
            "Connection":        "keep-alive",
        },
    )


# ─── APY Trend Endpoints ─────────────────────────────────────────────────────

@app.get("/api/apy/trends", tags=["apy"])
async def get_apy_trends():
    """
    Return 7-day APY trends for all tracked protocols.
    Reads from data/apy_trends.json (written by export_data.py each run).
    """
    try:
        return await _aio_read_json(_DATA_DIR / "apy_trends.json")
    except asyncio.TimeoutError:
        return JSONResponse(
            {"ok": False, "error": "data_unavailable", "reason": "read_timeout"},
            status_code=503,
        )
    except Exception:
        return {"trends": {}, "protocols_tracked": 0}


@app.get("/api/apy/history/{protocol_key}", tags=["apy"])
async def get_protocol_history(protocol_key: str):
    """
    Return 30-day APY trend for a single protocol.
    Use '__' in the path instead of ':' (e.g. 'aave-v3__USDC').
    """
    from spa_core.analytics.apy_tracker import APYTracker
    tracker = APYTracker(history_file=str(_DATA_DIR / "apy_history.json"))
    return tracker.get_trend(protocol_key.replace("__", ":"), days=30)


# ─── v1 Versioned Read-Only API (MP-1527) ────────────────────────────────────

@app.get("/api/v1/status", tags=["v1"])
def v1_status():
    """
    Sprint / KANBAN summary.
    Reads done_count and sprint_completed from KANBAN.json.
    """
    try:
        kanban_path = _PROJECT_ROOT / "KANBAN.json"
        k = json.loads(kanban_path.read_text(encoding="utf-8"))
        return {
            "done_count": k.get("done_count"),
            "sprint": k.get("sprint_completed"),
            "version": k.get("version", "unknown"),
            "timestamp": _now(),
        }
    except Exception as e:
        log.warning(f"/api/v1/status error: {e}")
        return {"error": str(e), "timestamp": _now()}


@app.get("/api/v1/golive", tags=["v1"])
def v1_golive():
    """
    GoLive readiness report — 26 criteria.
    Reads from data/golive_status.json (written by GoLiveChecker each cycle).
    Falls back to running GoLiveReadinessReport inline if file is missing.
    """
    # Fast path: serve from pre-computed file
    golive_data = _load_json("golive_status.json", None)
    if golive_data is not None:
        golive_data["timestamp"] = _now()
        golive_data["source"] = "file"
        return golive_data

    # Slow path: run the report inline
    try:
        from spa_core.analytics.golive_readiness_report import GoLiveReadinessReport
        report = GoLiveReadinessReport(base_dir=str(_PROJECT_ROOT))
        result = report.generate_report()
        result["timestamp"] = _now()
        result["source"] = "inline"
        return result
    except Exception as e:
        log.warning(f"/api/v1/golive inline report error: {e}")
        return {"error": str(e), "timestamp": _now()}


@app.get("/api/v1/adapters", tags=["v1"])
def v1_adapters():
    """
    All registered adapters with tier and live APY.
    Uses ADAPTER_REGISTRY from spa_core/adapters/adapter_registry.py.
    """
    try:
        from spa_core.adapters.adapter_registry import REGISTRY
        result = []
        for name, cls in REGISTRY.items():
            try:
                instance = cls()
                apy = None
                if hasattr(instance, "safe_apy"):
                    try:
                        apy = instance.safe_apy()
                    except Exception:
                        apy = None
                elif hasattr(instance, "get_apy"):
                    try:
                        apy = instance.get_apy()
                    except Exception:
                        apy = None
                tier = getattr(instance, "TIER", getattr(cls, "TIER", "?"))
                result.append({
                    "name": name,
                    "tier": tier,
                    "apy": apy,
                    "research_only": getattr(instance, "RESEARCH_ONLY", False),
                })
            except Exception as adapter_err:
                log.debug(f"Adapter entry error for {name!r}: {adapter_err}")
        return {"adapters": result, "count": len(result), "timestamp": _now()}
    except Exception as e:
        log.warning(f"/api/v1/adapters error: {e}")
        # Fallback: serve adapter_status.json if available
        fallback = _load_json("adapter_status.json", None)
        if fallback is not None:
            return {"adapters": fallback, "count": len(fallback) if isinstance(fallback, list) else 0,
                    "source": "file_fallback", "timestamp": _now()}
        return {"error": str(e), "adapters": [], "count": 0, "timestamp": _now()}


@app.get("/api/v1/evidence", tags=["v1"])
def v1_evidence():
    """
    Paper trading evidence history.
    Reads from data/paper_evidence_history.json (ring-buffer written by cycle_runner).
    """
    evidence = _load_json("paper_evidence_history.json", None)
    if evidence is not None:
        return {"data": evidence, "timestamp": _now(), "source": "file"}
    # Try equity curve as alternative evidence source
    equity = _load_json("equity_curve_daily.json", None)
    if equity is not None:
        return {"data": equity, "timestamp": _now(), "source": "equity_curve"}
    return {"error": "evidence file not found", "data": [], "timestamp": _now()}


# ─── Live API (low-latency dashboard polling, MP-live-api) ───────────────────
# Purpose: the public dashboard (earn-defi.com) polls these endpoints every
# ~15s through the Cloudflare tunnel (api.earn-defi.com) for fresh Mac-mini
# state, instead of waiting ~60 min for the GitHub-pushed JSON snapshot.
#
# Contract for ALL /api/live/* endpoints: read-only, never raise (always return
# a JSON dict, never a 5xx), always stamp _fetched_at so the client can show
# data age. A missing/corrupt file degrades to a status field, not an error.

def _live_read(filename: str) -> Any:
    """Read+parse data/<filename>; raise on missing/corrupt so callers decide."""
    return json.loads((_DATA_DIR / filename).read_text(encoding="utf-8"))


_NO_CACHE_HEADERS = {
    "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
    "Pragma": "no-cache",
}

_LIVE_READ_TIMEOUT: float = 3.0  # seconds; 503 is returned if exceeded


async def _aio_read_json(path: Path, timeout: float = _LIVE_READ_TIMEOUT) -> Any:
    """
    Async non-blocking JSON file read with hard timeout.

    Runs path.read_text() in the thread-pool so the asyncio event loop is
    NEVER blocked by filesystem I/O — critical for high-concurrency /api/live/*
    handlers where a blocking read would freeze every pending request.

    Raises:
        asyncio.TimeoutError   — read+parse took longer than `timeout` seconds
        FileNotFoundError      — file does not exist
        json.JSONDecodeError   — file is corrupt / not valid JSON
        OSError                — other filesystem error
    """
    text: str = await asyncio.wait_for(
        asyncio.to_thread(path.read_text, encoding="utf-8"),
        timeout=timeout,
    )
    return json.loads(text)


async def _aio_exists(path: Path) -> bool:
    """Non-blocking path.exists() — runs in thread pool."""
    return await asyncio.to_thread(path.exists)


@app.get("/api/live/ping", tags=["live"])
async def live_ping():
    """Health check — if this answers, the Mac mini is online and reachable."""
    return JSONResponse(
        {"ok": True, "ts": _time.time(), "version": "live-api-v1"},
        headers=_NO_CACHE_HEADERS,
    )


@app.get("/api/live/agents", tags=["live"])
async def live_agents():
    """Live agent heartbeat — reads data/agent_health.json directly."""
    path = _DATA_DIR / "agent_health.json"
    if not await _aio_exists(path):
        return JSONResponse({"status": "no_data", "ts": _time.time()}, headers=_NO_CACHE_HEADERS)
    try:
        data = await _aio_read_json(path)
        if isinstance(data, dict):
            data["_fetched_at"] = _time.time()
            return JSONResponse(data, headers=_NO_CACHE_HEADERS)
        return JSONResponse({"data": data, "_fetched_at": _time.time()}, headers=_NO_CACHE_HEADERS)
    except asyncio.TimeoutError:
        return JSONResponse(
            {"ok": False, "error": "data_unavailable", "reason": "read_timeout", "ts": _time.time()},
            status_code=503, headers=_NO_CACHE_HEADERS,
        )
    except Exception as e:
        return JSONResponse({"status": "error", "error": str(e), "ts": _time.time()}, headers=_NO_CACHE_HEADERS)


@app.get("/api/live/portfolio", tags=["live"])
async def live_portfolio():
    """Live portfolio bundle — merges available portfolio/pnl/equity files."""
    result: dict[str, Any] = {}
    for fname in ["portfolio_state.json", "pnl_history.json",
                  "equity_curve_daily.json", "current_positions.json",
                  "paper_trading_status.json"]:
        p = _DATA_DIR / fname
        if not await _aio_exists(p):
            continue
        try:
            result[fname[:-5]] = await _aio_read_json(p)
        except asyncio.TimeoutError:
            result[fname[:-5]] = {"_error": "read_timeout"}
        except Exception as e:
            result[fname[:-5]] = {"_error": str(e)}
    result["_fetched_at"] = _time.time()
    return JSONResponse(result, headers=_NO_CACHE_HEADERS)


@app.get("/api/live/system", tags=["live"])
async def live_system():
    """Live system-health bundle — merges available health/watcher/log files."""
    result: dict[str, Any] = {}
    for fname in ["system_health.json", "telegram_watcher_status.json",
                  "auto_fixer_log.json", "golive_status.json"]:
        p = _DATA_DIR / fname
        if not await _aio_exists(p):
            continue
        try:
            result[fname[:-5]] = await _aio_read_json(p)
        except asyncio.TimeoutError:
            result[fname[:-5]] = {"_error": "read_timeout"}
        except Exception as e:
            result[fname[:-5]] = {"_error": str(e)}
    result["_fetched_at"] = _time.time()
    return JSONResponse(result, headers=_NO_CACHE_HEADERS)


@app.get("/api/live/status", tags=["live"])
async def live_status():
    """
    Live aggregate status — ключевые операционные метрики в одном вызове.
    Мёрджит paper_trading_status.json, golive_status.json, current_positions.json.
    Никогда не бросает исключение: отсутствие/повреждение файла → {"_error": ...}.
    """
    result: dict[str, Any] = {"_fetched_at": _time.time()}
    for fname in ["paper_trading_status.json", "golive_status.json",
                  "current_positions.json"]:
        p = _DATA_DIR / fname
        if not await _aio_exists(p):
            continue
        try:
            result[fname[:-5]] = await _aio_read_json(p)
        except asyncio.TimeoutError:
            result[fname[:-5]] = {"_error": "read_timeout"}
        except Exception as e:
            result[fname[:-5]] = {"_error": str(e)}
    return JSONResponse(result, headers=_NO_CACHE_HEADERS)


@app.get("/api/live/health", tags=["live"])
async def live_health():
    """
    Deep health check — подтверждает что сервер жив и data dir доступна.
    Всегда 200. {"ok": true/false} + диагностика.
    """
    try:
        data_dir_ok: bool = await asyncio.wait_for(
            asyncio.to_thread(lambda: _DATA_DIR.exists() and _DATA_DIR.is_dir()),
            timeout=2.0,
        )
    except asyncio.TimeoutError:
        data_dir_ok = False

    try:
        json_count: int = await asyncio.wait_for(
            asyncio.to_thread(
                lambda: sum(1 for f in _DATA_DIR.glob("*.json") if f.is_file())
            ),
            timeout=2.0,
        )
    except asyncio.TimeoutError:
        json_count = -1

    return JSONResponse(
        {
            "ok": data_dir_ok,
            "ts": _time.time(),
            "version": "live-api-v1",
            "data_dir_ok": data_dir_ok,
            "json_files": json_count,
        },
        headers=_NO_CACHE_HEADERS,
    )


# Generic read-only passthrough so the existing dashboard can refresh EVERY
# panel from live data with zero renderer changes: the client simply points its
# `dataBase` at /api/live/data instead of ./data. Hardened against traversal —
# only flat *.json basenames that resolve inside _DATA_DIR are served.
_LIVE_FILE_RE = re.compile(r"^[A-Za-z0-9_.-]+\.json$")


@app.get("/api/live/data/{filename}", tags=["live"])
async def live_data_file(filename: str):
    """Serve a single data/*.json file verbatim (read-only, traversal-safe)."""
    if not _LIVE_FILE_RE.match(filename):
        raise HTTPException(status_code=400, detail={"error": "invalid filename"})
    path = (_DATA_DIR / filename).resolve()
    try:
        path.relative_to(_DATA_DIR.resolve())
    except ValueError:
        raise HTTPException(status_code=400, detail={"error": "path escapes data dir"})
    if not await _aio_exists(path):
        raise HTTPException(status_code=404, detail={"error": "not found"})
    try:
        data = await _aio_read_json(path)
        return JSONResponse(data, headers=_NO_CACHE_HEADERS)
    except asyncio.TimeoutError:
        return JSONResponse(
            {"ok": False, "error": "data_unavailable", "reason": "read_timeout"},
            status_code=503,
            headers=_NO_CACHE_HEADERS,
        )
    except json.JSONDecodeError as e:
        raise HTTPException(status_code=502, detail={"error": f"corrupt json: {e}"})


# ─── Dev entrypoint ──────────────────────────────────────────────────────────
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "spa_core.api.server:app",
        host="0.0.0.0",
        port=8765,
        reload=True,
        log_level="info",
    )
