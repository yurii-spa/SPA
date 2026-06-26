"""Misc router — health/meta, core data endpoints, ssot/governance/execution,
chat, events (SSE + WebSocket), and APY trends.

Behavior-preserving extraction from server.py. The handlers keep their original
tags (meta/data/public/ssot/governance/execution/chat/events/apy) set per-route
so the OpenAPI tag grouping is identical to the monolith. The /health route also
reports app.version via the running FastAPI app (resolved through server.app).
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel

from spa_core.api._shared import (
    aio_read_json,
    data_dir,
    event_queue,
    now,
    read_state,
)
from spa_core.api.agent_broadcaster import broadcaster

log = logging.getLogger("spa.api")

router = APIRouter()


def _error(msg: str, status: int = 500):
    raise HTTPException(status_code=status, detail={"error": msg})


def get_live_portfolio():
    """Resolve the live-portfolio reader AT CALL TIME via server._get_live_portfolio.

    Several tests stub the live path with
    `monkeypatch.setattr(server, "_get_live_portfolio", lambda: None)` to force the
    JSON-fallback branch deterministically; routing through the server attribute
    here keeps that stubbing working exactly as it did in the monolith."""
    from spa_core.api import server as _srv
    return _srv._get_live_portfolio()


# ─── Health / meta ────────────────────────────────────────────────────────────

@router.get("/health", tags=["meta"])
def health():
    """Liveness check — 200 + version info when running."""
    from spa_core.api import server as _srv
    return {
        "status": "ok",
        "version": _srv.app.version,
        "timestamp": now(),
    }


# ─── Core data endpoints ──────────────────────────────────────────────────────

@router.get("/api/portfolio", tags=["data"])
def get_portfolio():
    """Current portfolio state — live from PaperTrader, falling back to paper_trading_status.json."""
    live = get_live_portfolio()
    if live is not None:
        port = live.get("portfolio", {})
        if isinstance(port, dict):
            port.setdefault("apy_today_pct_note", "annualized, not a daily figure")
        return port

    pts = read_state("paper_trading_status.json", None)
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
            "apy_today_pct_annualized": round(pts.get("apy_today_pct", 0.0), 2),
            "apy_today_pct_note": "annualized, not a daily figure",
            "days_running": pts.get("days_running", 0),
            "source": "paper_trading_status",
        }

    status = read_state("status.json", {})
    return status.get("portfolio", {
        "total_capital_usd": 100_000.0,
        "deployed_usd": 0,
        "cash_usd": 100_000.0,
        "cash_pct": 1.0,
        "total_pnl_usd": 0.0,
        "total_drawdown_pct": 0.0,
    })


@router.get("/api/positions", tags=["data"])
def get_positions():
    """Current open positions — live from PaperTrader, falling back to data/status.json."""
    live = get_live_portfolio()
    if live is not None:
        return live.get("positions", [])

    status = read_state("status.json", {})
    return status.get("positions", [])


@router.get("/api/pools", tags=["data"])
def get_pools():
    """Latest DeFiLlama APY pool data (falls back to data/protocols.json)."""
    pools = read_state("pools.json", None)
    if pools is not None:
        return pools

    protocols = read_state("protocols.json", [])
    return protocols


@router.get("/api/risk", tags=["data"])
def get_risk():
    """Risk alerts and portfolio health. Schema matches data/risk_alerts.json."""
    live = get_live_portfolio()
    if live is not None:
        risk_data = live.get("risk", {})
        return {
            "generated_at": now(),
            "status": "ok" if risk_data.get("health_approved", True) else "alert",
            "count": len(risk_data.get("violations", [])),
            "alerts": risk_data.get("violations", []),
            "warnings": risk_data.get("warnings", []),
            "var_usd": risk_data.get("var_usd", 0.0),
            "var_pct": risk_data.get("var_pct", 0.0),
            "var_breach": risk_data.get("var_breach", False),
        }

    return read_state("risk_alerts.json", {
        "generated_at": now(),
        "count": 0,
        "status": "ok",
        "alerts": [],
    })


@router.get("/api/trades", tags=["data"])
def get_trades(limit: int = Query(default=20, ge=1, le=500)):
    """Recent paper trades. Reads from data/trades.json. ?limit=N (default 20, max 500)."""
    trades = read_state("trades.json", [])
    if isinstance(trades, list):
        return trades[:limit]
    if isinstance(trades, dict):
        inner = trades.get("trades", trades.get("data", []))
        return inner[:limit] if isinstance(inner, list) else []
    return []


@router.get("/api/backtest", tags=["data"])
def get_backtest():
    """Backtest results. Schema matches data/backtest_results.json."""
    return read_state("backtest_results.json", {
        "generated_at": now(),
        "data_source": "unavailable",
        "metrics": {},
        "equity_curve": [],
    })


@router.get("/api/health-public", tags=["public"])
def get_health_public():
    """Flat public health snapshot for the landing LiveStatsWidget."""
    ps = read_state("paper_trading_status.json", {})
    gl = read_state("golive_status.json", {})
    ts = read_state("tear_sheet.json", {})
    passed = gl.get("passed", gl.get("passed_count"))
    total = gl.get("total", gl.get("total_count", gl.get("criteria_total")))
    real_track_days = gl.get("real_track_days")
    return {
        "generated_at": now(),
        "source": "live",
        "real_track_days": real_track_days,
        "evidenced_anchor": gl.get("evidenced_anchor"),
        "go_live_target": gl.get("target_date"),
        "track_days": real_track_days,
        "days_running_raw": ps.get("days_running"),
        "ytd_apy_pct": ps.get("apy_today_pct"),
        "ytd_apy_pct_note": "annualized, not a daily figure",
        "apy_today_pct_annualized": ps.get("apy_today_pct"),
        "current_equity": ps.get("current_equity"),
        "total_return_pct": ps.get("total_return_pct"),
        "sharpe_30d": ts.get("sharpe_ratio", ts.get("sharpe")),
        "max_drawdown_pct": ts.get("max_drawdown_pct", ts.get("max_dd_pct")),
        "risk_gates_passed": passed,
        "risk_gates_total": total,
        "status": ps.get("last_cycle_status", "ok"),
        "last_cycle_at": ps.get("last_cycle_ts"),
        "active_protocols": ps.get("num_adapters_live", ps.get("active_protocols")),
        "is_demo": ps.get("is_demo", False),
    }


@router.get("/api/ssot/facts", tags=["ssot"])
def get_ssot_facts():
    """Canonical headline facts straight from SSOT (Law 3)."""
    try:
        from spa_core.governance.ssot import key_facts
        return key_facts()
    except Exception as exc:  # noqa: BLE001
        return {"generated_at": now(), "error": str(exc), "facts": {}}


@router.get("/api/governance", tags=["governance"])
def get_governance():
    """Governance-as-code: auto-vs-human action policy + dual-control posture."""
    return read_state("governance_policy.json", {
        "generated_at": now(), "policy": {}, "dual_control_posture": {"enforced": False},
    })


@router.get("/api/execution/readiness", tags=["execution"])
def get_execution_readiness():
    """Execution go/no-go posture (PAPER_SAFE) + honest live-blockers."""
    return read_state("execution_readiness.json", {
        "generated_at": now(), "posture": "unknown", "ready_for_live": False,
    })


# ─── Backtest replay / summary / compare ──────────────────────────────────────

@router.get("/api/backtest/replay", tags=["backtesting"])
def get_backtest_replay(days: int = Query(default=90, ge=1, le=365)):
    """Full historical replay data — one frame per day."""
    try:
        from spa_core.backtesting.replay import ReplayEngine
        engine = ReplayEngine(data_dir=data_dir(), synthetic_days=days)
        frames = engine.full_replay()
        return {
            "generated_at": now(),
            "source": engine.source,
            "total_days": engine.total_days,
            "frames": frames,
        }
    except Exception as e:
        log.warning(f"/api/backtest/replay error: {e}")
        raise HTTPException(status_code=500, detail={"error": str(e)})


@router.get("/api/backtest/summary", tags=["backtesting"])
def get_backtest_summary():
    """Replay summary metrics computed from the full pnl_history equity curve."""
    try:
        from spa_core.backtesting.replay import ReplayEngine
        engine = ReplayEngine(data_dir=data_dir())
        summary = engine.replay_summary()
        summary["generated_at"] = now()
        return summary
    except Exception as e:
        log.warning(f"/api/backtest/summary error: {e}")
        raise HTTPException(status_code=500, detail={"error": str(e)})


@router.get("/api/backtest/compare", tags=["backtesting"])
def get_backtest_compare(
    days: int = Query(default=90, ge=1, le=365),
    seed: int = Query(default=42, ge=0),
):
    """Side-by-side strategy comparison: v1_passive vs v2_aggressive."""
    try:
        from spa_core.backtesting.scenario_runner import compare_scenarios
        result = compare_scenarios(days=days, seed=seed)
        for key in ("v1_passive", "v2_aggressive"):
            result[key].pop("equity_curve", None)
        result["generated_at"] = now()
        return result
    except Exception as e:
        log.warning(f"/api/backtest/compare error: {e}")
        raise HTTPException(status_code=500, detail={"error": str(e)})


@router.get("/api/optimization", tags=["data"])
def get_optimization():
    """Optimisation recommendations from the last strategy scan."""
    v2 = read_state("strategy_v2.json", None)
    if v2 is not None:
        return v2

    comparison = read_state("strategy_comparison.json", None)
    if comparison is not None:
        return comparison

    return {
        "generated_at": now(),
        "recommendations": [],
        "status": "no_data",
    }


@router.get("/api/status", tags=["data"])
def get_status():
    """Aggregated status — all sections in one response (single-fetch dashboard mode)."""
    live = get_live_portfolio()

    if live is not None:
        backtest = read_state("backtest_results.json", {})
        live["backtest_summary"] = backtest.get("metrics", {})
        live["pools_count"] = len(read_state("protocols.json", []))
        live["server_timestamp"] = now()
        live["data_source"] = "live"
        return live

    status = read_state("status.json", {})
    backtest = read_state("backtest_results.json", {})
    risk_alerts = read_state("risk_alerts.json", {})
    trades = read_state("trades.json", [])

    return {
        "timestamp": now(),
        "data_source": "json",
        "portfolio": status.get("portfolio", {}),
        "positions": status.get("positions", []),
        "risk": status.get("risk", {}),
        "risk_alerts": risk_alerts.get("alerts", []),
        "paper_trading": status.get("paper_trading", {}),
        "strategy": status.get("strategy", {}),
        "backtest_summary": backtest.get("metrics", {}),
        "recent_trades": trades[:5] if isinstance(trades, list) else [],
        "server_timestamp": now(),
    }


# ─── Chat (LLM agent reasoning) ───────────────────────────────────────────────

class _ChatRequest(BaseModel):
    question: str


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
                data_dir=str(data_dir()),
            )
            log.info("ChatHandler initialised (LLM agent chat active)")
        except Exception as e:
            log.warning(f"ChatHandler init failed — chat will use canned responses: {e}")
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


@router.post("/api/chat", tags=["chat"])
def post_chat(body: _ChatRequest):
    """Ask an LLM agent a question about the portfolio (canned fallback w/o API key)."""
    question = (body.question or "").strip()
    if not question:
        raise HTTPException(status_code=400, detail={"error": "question must not be empty"})

    handler = _get_chat_handler()
    result = handler.handle(question)
    result["timestamp"] = now()
    return result


# ─── WebSocket ────────────────────────────────────────────────────────────────

@router.websocket("/ws/agents")
async def ws_agents(websocket: WebSocket):
    """Real-time agent activity stream."""
    await broadcaster.connect(websocket)
    try:
        live = get_live_portfolio()
        snapshot = {
            "agent": "PortfolioAgent",
            "message": "Connected to SPA agent stream — sending portfolio snapshot",
            "timestamp": now(),
            "type": "snapshot",
            "data": {
                "portfolio": live.get("portfolio", {}) if live else {},
                "positions": live.get("positions", []) if live else [],
                "risk": live.get("risk", {}) if live else {},
            },
        }
        await broadcaster.send_to(websocket, snapshot)

        while True:
            try:
                data = await websocket.receive_text()
                if data.strip().lower() in ("ping", ""):
                    await broadcaster.send_to(websocket, {
                        "type": "pong",
                        "timestamp": now(),
                    })
            except WebSocketDisconnect:
                break

    except WebSocketDisconnect:
        pass
    except Exception as e:
        log.warning(f"WebSocket error: {e}")
    finally:
        broadcaster.disconnect(websocket)


# ─── SSE + Agent Thought Events ───────────────────────────────────────────────

class _ThoughtRequest(BaseModel):
    """Payload for POST /api/agent/thought."""
    agent:   str
    message: str
    type:    str = "agent_thought"
    data:    dict | None = None


@router.post("/api/agent/thought", tags=["events"])
async def post_agent_thought(body: _ThoughtRequest):
    """Push a structured agent event into the SSE stream and ring buffer."""
    if not body.message.strip():
        raise HTTPException(status_code=400, detail={"error": "message must not be empty"})

    event: dict[str, Any] = {
        "agent":     body.agent,
        "message":   body.message.strip(),
        "type":      body.type,
        "timestamp": now(),
        "data":      body.data or {},
    }
    await event_queue.push(event)
    await broadcaster.broadcast(event)
    log.info(f"[{body.type}] {body.agent}: {body.message[:80]}")
    return {"ok": True, "event_count": len(event_queue.history())}


@router.get("/api/events/history", tags=["events"])
def get_events_history():
    """Return the last 50 agent events as JSON."""
    history = event_queue.history()
    return {"events": history, "count": len(history)}


@router.get("/api/events", tags=["events"])
async def sse_stream(request: Request):
    """Server-Sent Events stream for real-time agent activity."""
    queue = event_queue.subscribe()

    async def generator():
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
                    yield ": keepalive\n\n"
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


# ─── APY Trend Endpoints ──────────────────────────────────────────────────────

@router.get("/api/apy/trends", tags=["apy"])
async def get_apy_trends():
    """Return 7-day APY trends for all tracked protocols."""
    try:
        return await aio_read_json(data_dir() / "apy_trends.json")
    except asyncio.TimeoutError:
        return JSONResponse(
            {"ok": False, "error": "data_unavailable", "reason": "read_timeout"},
            status_code=503,
        )
    except Exception:
        return {"trends": {}, "protocols_tracked": 0}


@router.get("/api/apy/history/{protocol_key}", tags=["apy"])
async def get_protocol_history(protocol_key: str):
    """Return 30-day APY trend for a single protocol. Use '__' instead of ':'."""
    from spa_core.analytics.apy_tracker import APYTracker
    tracker = APYTracker(history_file=str(data_dir() / "apy_history.json"))
    return tracker.get_trend(protocol_key.replace("__", ":"), days=30)
