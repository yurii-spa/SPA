"""
SPA FastAPI server — real-time data API (v0.16).
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
"""

from __future__ import annotations

import json
import logging
import os
import sys
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

from fastapi import FastAPI, HTTPException, Query, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
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


# ─── Lifespan ────────────────────────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    )
    log.info(f"SPA API v0.15 starting — data dir: {_DATA_DIR}")
    broadcaster.start()
    yield
    broadcaster.stop()
    log.info("SPA API shutting down.")


# ─── App ─────────────────────────────────────────────────────────────────────
app = FastAPI(
    title="SPA — Smart Passive Aggregator",
    version="v0.15",
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
        # Wildcard for any localhost port (development)
        "http://localhost:*",
    ],
    allow_origin_regex=r"https?://localhost(:\d+)?",
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
        "version": "v0.15",
        "timestamp": _now(),
    }


@app.get("/api/portfolio", tags=["data"])
def get_portfolio():
    """
    Current portfolio state — live from PaperTrader, falling back to data/status.json.
    Schema matches data/portfolio.json (portfolio sub-key of status).
    """
    live = _get_live_portfolio()
    if live is not None:
        return live.get("portfolio", {})

    status = _load_json("status.json", {})
    portfolio = status.get("portfolio", {
        "total_capital_usd": 100000.0,
        "deployed_usd": 0,
        "cash_usd": 100000.0,
        "cash_pct": 1.0,
        "total_pnl_usd": 0.0,
        "total_drawdown_pct": 0.0,
    })
    return portfolio


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
