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

# ─── CORS (WS2 — tightened 2026-06-29) ────────────────────────────────────────
# SECURITY FIX: the former policy allowed `https://[a-z0-9-]+\.pages\.dev` — i.e.
# ANY third-party Cloudflare Pages site (incl. a rogue `evil.pages.dev`) could
# call this API cross-origin. Replaced with an explicit allow-list of SPA's OWN
# origins only: earn-defi.com (+ www/app/api), the CANONICAL SPA pages.dev deploy,
# and localhost (dev). A rogue *.pages.dev is now blocked. The canonical SPA
# pages.dev project slug is env-overridable for deploy-name changes.
_SPA_PAGES_PROJECT = os.environ.get("SPA_PAGES_PROJECT", "spa-landing").strip()

_ALLOWED_ORIGINS = [
    # Local development
    "http://localhost",
    "http://localhost:3000",
    "http://localhost:4321",  # Astro dev
    "http://localhost:5173",  # Vite dev
    "http://localhost:8765",
    "http://127.0.0.1:8765",
    # Production (live API via api.earn-defi.com tunnel)
    "https://earn-defi.com",
    "https://www.earn-defi.com",
    "https://app.earn-defi.com",
    "https://api.earn-defi.com",
    # Canonical SPA Cloudflare Pages deploy ONLY (not third-party *.pages.dev)
    f"https://{_SPA_PAGES_PROJECT}.pages.dev",
]

# Regex: localhost any port + *.earn-defi.com + SPA's OWN pages.dev preview
# branches (<branch>.<project>.pages.dev). NO bare *.pages.dev wildcard, so a
# rogue evil.pages.dev cannot match.
_ALLOWED_ORIGIN_REGEX = (
    r"https?://localhost(:\d+)?"
    r"|https?://127\.0\.0\.1(:\d+)?"
    r"|https://([a-z0-9-]+\.)?earn-defi\.com"
    rf"|https://([a-z0-9-]+\.)?{_SPA_PAGES_PROJECT}\.pages\.dev"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=_ALLOWED_ORIGINS,
    allow_origin_regex=_ALLOWED_ORIGIN_REGEX,
    allow_credentials=False,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)

# ─── Rate limiting (WS2 — per-IP token bucket, 2026-06-29) ─────────────────────
# A flood (esp. the LLM POST /api/chat budget-burn vector) → 429. GET proof/data
# /live endpoints + the dashboard's ~15s polling stay well under the default
# bucket. Added AFTER CORS so it sits OUTSIDE it (runs first on each request);
# the strict bucket targets the LLM/write POSTs.
from spa_core.api.rate_limit import RateLimitMiddleware  # noqa: E402

app.add_middleware(RateLimitMiddleware)


# ─── Routers ─────────────────────────────────────────────────────────────────
# Order preserved from the monolith's definition order so OpenAPI listing is stable.
from spa_core.api.routers import (  # noqa: E402
    aggressive_lab,
    analytics,
    cockpit,
    competitive_watch,
    dfb,
    dfb_data_api,
    interest,
    live,
    misc,
    optimizer,
    rates_desk,
    readiness,
    redteam,
    riskwire,
    rtmr,
    strategy_lab,
    swarm,
    tier1,
    tournament,
    underwriting,
    v1,
)

app.include_router(misc.router)
app.include_router(analytics.router)
app.include_router(interest.router)
app.include_router(tier1.router)
app.include_router(strategy_lab.router)
# Aggressive Lab (Lane 3 SURFACE) — advisory/paper-only ranking of the 10-15% strategies the desk
# REFUSES, shown WITH the tail. OUTSIDE_RiskPolicy; never live-allocated, never touches go-live.
app.include_router(aggressive_lab.router)
# SPA Swarm (block-6 SURFACE) — read-only status of the swarm organs (guardians/regime/blend/
# brain/health). Advisory/paper-only; recommends, never allocates. docs/SWARM_ARCHITECTURE.md.
app.include_router(swarm.router)
app.include_router(rates_desk.router)
app.include_router(readiness.router)
app.include_router(optimizer.router)
app.include_router(v1.router)
app.include_router(live.router)
app.include_router(tournament.router)
app.include_router(competitive_watch.router)
app.include_router(redteam.router)
# RTMR (ADR-053) — read-only surface of the real-time monitoring organism (/api/rtmr/*):
# live signals, defensive posture, recent de-risk actions. Feeds the dashboard.
app.include_router(rtmr.router)
# Lane C (Layer-3 moat) — the underwriting report surface is FLAG-GATED OFF by default
# (SPA_UNDERWRITING_PUBLISH); every route 404s until the owner flips the flag.
app.include_router(underwriting.router)
# DFB — DeFi Board (LANE 2): the public risk-first pool-analytics surface (/api/dfb/*).
# Read-only, GET-only, fail-CLOSED; serves Lane 1's risk overlay verbatim (never forks the math).
app.include_router(dfb.router)
# DFB Data API (Month-3 Lane-1) — the risk-graded, KEY-GATED developer surface (/api/dfb/v1/*).
# OWNER-GATED behind SPA_DFB_DATA_API (default OFF): every /v1 route 404s in-handler until the
# owner flips the flag (defense-in-depth + always-mounted so a runtime flag flip takes effect).
# Flag ON + no key configured → 401 (fail-CLOSED, never silently open). NO-FORK: serves /api/dfb/*'s
# overlay byte-identical. Public launch (keys/billing/SLA) is OWNER-GATED — see docs/DFB_DATA_API.md.
app.include_router(dfb_data_api.router)
# RISKWIRE (Layer-3 measurement-as-a-product) — the PROOF / "check us" surface (/api/riskwire/proof*).
# Read-only, GET-only, fail-CLOSED; serves every RISKWIRE deliverable's proof chain VERBATIM (uncapped)
# so a third party re-derives every hash with scripts/verify_riskwire.py (zero spa_core import). NOT
# flag-gated — verifiability is always available; the PUBLIC report/oracle product surfaces are the
# owner-flag-gated ones (in their own routers). NO-FORK: every verdict is the seed's, served verbatim.
app.include_router(riskwire.router)
# Desk Cockpit (Sprint-0 Lane A) — the NORMALIZED read-API the Cockpit screens consume.
# Read-only RESHAPE facade (SPA-001 unified decisions/refusals + regime/strategies folds,
# SPA-002 per-condition kill-gauge headroom). NO-FORK: reuses kill_switch/rate_policy/the
# rates-desk decision_log/market_regime/strategy-lab; never re-derives risk math. Every
# response carries ts+stale, fail-CLOSED honest-unavailable, GET-only/advisory.
app.include_router(cockpit.router)


# Academy onboarding sub-app (D4: own CORS, own credentials)
try:
    from spa_core.academy.api.app import create_academy_app as _create_academy_app
    _academy_app = _create_academy_app()
    app.mount("/academy", _academy_app)
except Exception as _e:  # noqa: BLE001
    import logging as _logging
    _logging.getLogger(__name__).warning("Academy sub-app not mounted: %s", _e)


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

get_aggressive_lab_scorecard = aggressive_lab.get_aggressive_lab_scorecard
get_aggressive_lab_strategy = aggressive_lab.get_aggressive_lab_strategy
get_aggressive_lab_annual_contrast = aggressive_lab.get_aggressive_lab_annual_contrast

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
get_rates_desk_exit_nav = rates_desk.get_rates_desk_exit_nav
get_rates_desk_anchors = rates_desk.get_rates_desk_anchors
list_full_chain_surfaces = rates_desk.list_full_chain_surfaces
get_full_chain = rates_desk.get_full_chain

get_optimizer_ab = optimizer.get_optimizer_ab
get_captured_book = optimizer.get_captured_book

v1_status = v1.v1_status
v1_golive = v1.v1_golive
v1_adapters = v1.v1_adapters
v1_evidence = v1.v1_evidence

get_tournament = tournament.get_tournament
get_tournament_status = tournament.get_tournament_status

# Desk Cockpit (Sprint-0 Lane A) — unified decisions/refusals + regime/strategies + kill-gauge.
get_decisions = cockpit.get_decisions
get_refusals = cockpit.get_refusals
get_regime = cockpit.get_regime
get_strategies = cockpit.get_strategies
get_strategy = cockpit.get_strategy
get_kill_gauge = cockpit.get_kill_gauge

get_dfb_pools = dfb.get_dfb_pools
get_dfb_pool = dfb.get_dfb_pool
get_dfb_pool_history = dfb.get_dfb_pool_history
get_dfb_pool_proof = dfb.get_dfb_pool_proof
get_dfb_summary = dfb.get_dfb_summary

# DFB Data API (Month-3 Lane-1) — key-gated developer surface (flag SPA_DFB_DATA_API).
dfb_v1_pools = dfb_data_api.v1_pools
dfb_v1_pool = dfb_data_api.v1_pool
dfb_v1_pool_history = dfb_data_api.v1_pool_history
dfb_v1_refusals = dfb_data_api.v1_refusals
dfb_v1_screener = dfb_data_api.v1_screener
dfb_v1_index = dfb_data_api.v1_index


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
