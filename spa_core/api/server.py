"""
SPA FastAPI server — real-time data API (v0.17).
Run: uvicorn spa_core.api.server:app --reload --port 8765

This module is the APP FACTORY: it builds the FastAPI `app`, configures CORS +
lifespan, and INCLUDES the tagged routers (P3-7 split). The 58 handlers now live
in spa_core/api/routers/*.py (tier1 / live / strategy_lab / rates_desk / v1 /
tournament / misc), and the cross-cutting state + helpers live in
spa_core/api/_shared.py. The route table + every response is byte-identical to the
former monolith — verified by spa_core/tests/test_api_surface_snapshot.py.

The launch target is UNCHANGED: `uvicorn spa_core.api.server:app` (com.spa.apiserver),
because `app` is still defined here.

IMPORTANT: This server is READ-ONLY. No write operations allowed.
All write operations go through normal file/CLI interface.

Backward-compat re-exports (the test suite + dashboards depend on these names on
this module): `app`, `event_queue`, `broadcaster`, `_DATA_DIR`, `_PROJECT_ROOT`,
`_load_json`, `_now`, `_get_live_portfolio`, and the handler callables that some
tests invoke directly (e.g. `get_health_public`). `_DATA_DIR` is the canonical
data-dir attribute; the API test suite redirects it via
`monkeypatch.setattr(server, "_DATA_DIR", tmp_path)` and the routers resolve it at
call time, so that hermetic redirection keeps working unchanged.
"""

from __future__ import annotations

import logging
import os
import sys
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path

# ─── Path setup ──────────────────────────────────────────────────────────────
# Allows running as: uvicorn spa_core.api.server:app from project root
_HERE = Path(__file__).resolve().parent
_SPA_CORE = _HERE.parent
_PROJECT_ROOT = _SPA_CORE.parent
for _p in [str(_SPA_CORE), str(_PROJECT_ROOT)]:
    if _p not in sys.path:
        sys.path.insert(0, _p)

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from spa_core.api.agent_broadcaster import broadcaster

# Shared state + helpers (single copy, deduped from the per-handler boilerplate).
from spa_core.api import _shared
from spa_core.api._shared import event_queue as event_queue  # re-export (tests import this name)  # noqa: F401

log = logging.getLogger("spa.api")

# ─── Data directory ──────────────────────────────────────────────────────────
# Canonical data-dir attribute. Resolved fresh from SPA_DATA_DIR so that
# importlib.reload(server) (used by tests setting SPA_DATA_DIR) rebinds it. All
# router handlers read THIS attribute at call time via _shared.data_dir(), so the
# test monkeypatch on server._DATA_DIR reaches every handler.
_DATA_DIR = Path(os.environ.get("SPA_DATA_DIR", _PROJECT_ROOT / "data"))


# ─── Backward-compatible helper re-exports ────────────────────────────────────
# Some tests / callers reference these names on the server module directly.
_load_json = _shared.read_state
_get_live_portfolio = _shared.get_live_portfolio


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _error(msg: str, status: int = 500):
    raise HTTPException(status_code=status, detail={"error": msg})


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
        # (legacy github.io dashboard origin removed 2026-06-28 — github.io dashboard deleted)
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


# ─── Routers ─────────────────────────────────────────────────────────────────
# Order preserved from the monolith's definition order so OpenAPI listing is stable.
from spa_core.api.routers import (  # noqa: E402
    live,
    misc,
    rates_desk,
    strategy_lab,
    tier1,
    tournament,
    v1,
)

app.include_router(misc.router)
app.include_router(tier1.router)
app.include_router(strategy_lab.router)
app.include_router(rates_desk.router)
app.include_router(v1.router)
app.include_router(live.router)
app.include_router(tournament.router)


# ─── Backward-compatible handler re-exports ───────────────────────────────────
# A few tests call handler functions directly on the server module (e.g.
# get_health_public). Re-bind the public ones here so those imports keep working.
health = misc.health
get_portfolio = misc.get_portfolio
get_positions = misc.get_positions
get_pools = misc.get_pools
get_risk = misc.get_risk
get_trades = misc.get_trades
get_backtest = misc.get_backtest
get_health_public = misc.get_health_public
get_ssot_facts = misc.get_ssot_facts
get_governance = misc.get_governance
get_execution_readiness = misc.get_execution_readiness
get_optimization = misc.get_optimization
get_status = misc.get_status
post_chat = misc.post_chat
post_agent_thought = misc.post_agent_thought
get_events_history = misc.get_events_history
sse_stream = misc.sse_stream
ws_agents = misc.ws_agents
get_apy_trends = misc.get_apy_trends
get_protocol_history = misc.get_protocol_history

get_strategy_lab = strategy_lab.get_strategy_lab
get_strategy_lab_promotion = strategy_lab.get_strategy_lab_promotion
get_refusal = strategy_lab.get_refusal
get_rwa_safety_board = strategy_lab.get_rwa_safety_board
get_rwa_nav_curve = strategy_lab.get_rwa_nav_curve

get_rates_desk_surface = rates_desk.get_rates_desk_surface
get_rates_desk_opportunities = rates_desk.get_rates_desk_opportunities
get_rates_desk_decisions = rates_desk.get_rates_desk_decisions
get_rates_desk_proof = rates_desk.get_rates_desk_proof
get_rates_desk_track = rates_desk.get_rates_desk_track

v1_status = v1.v1_status
v1_golive = v1.v1_golive
v1_adapters = v1.v1_adapters
v1_evidence = v1.v1_evidence

get_tournament = tournament.get_tournament
get_tournament_status = tournament.get_tournament_status


# ─── Dev entrypoint ──────────────────────────────────────────────────────────
# Public re-exports (the launch target + names the test suite/dashboards import).
__all__ = ["app", "event_queue", "broadcaster", "_DATA_DIR", "_PROJECT_ROOT"]


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
