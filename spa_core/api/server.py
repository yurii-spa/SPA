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


# ─── Honesty meta (additive labeling) ─────────────────────────────────────────
# Honesty-audit requirement: no consumer (direct API / third party / cached page)
# may see a bare backtest/assumed/annualized number as if it were a realized
# track record. These helpers attach an ADDITIVE `meta` envelope (and per-field
# labels) alongside existing payloads — existing fields are never removed or
# renamed, so the site's renderers keep working unchanged.

_BACKTEST_DISCLAIMER = (
    "Backtest/paper research — advisory, not realized capital, not a track record"
)


def _backtest_meta(basis: str, period: str, *, is_realized: bool = False) -> dict:
    """Standard additive meta block for endpoints serving backtest/simulated numbers."""
    return {
        "is_backtest": True,
        "is_realized": bool(is_realized),
        "basis": basis,
        "period": period,
        "disclaimer": _BACKTEST_DISCLAIMER,
    }


# Per-sleeve yield-basis labels for /api/strategy-lab. engine_b (~8.33%) and
# engine_c (~8.87%) are ASSUMED sleeve yields (HY band-median proxy; LP fee-only,
# IL not modeled) — NOT realized. rwa_floor is a live tokenized-T-bill feed.
_SLEEVE_YIELD_BASIS = {
    "engine_b": "assumed",
    "engine_c": "assumed",
    "rwa_floor": "live_feed",
    "rwa_sleeve": "live_feed",
}
_SLEEVE_YIELD_BASIS_NOTE = {
    "engine_b": "ASSUMED: HY band-median proxy, not realized",
    "engine_c": "ASSUMED: LP fee-only, impermanent loss NOT modeled, not realized",
    "rwa_floor": "live tokenized-T-bill feed",
    "rwa_sleeve": "live tokenized-T-bill feed",
}


def _sleeve_yield_basis(sid: str) -> str:
    """assumed | live_feed | realized — default 'realized' for live paper sleeves."""
    return _SLEEVE_YIELD_BASIS.get(sid, "realized")


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
        "version": app.version,
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
        port = live.get("portfolio", {})
        if isinstance(port, dict):
            # Honesty label: any APY in the portfolio is ANNUALIZED, not a daily figure.
            port.setdefault("apy_today_pct_note", "annualized, not a daily figure")
        return port

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
            # Honesty label: apy_today_pct is an ANNUALIZED figure, not a daily return.
            "apy_today_pct_annualized": round(pts.get("apy_today_pct", 0.0), 2),
            "apy_today_pct_note": "annualized, not a daily figure",
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


@app.get("/api/health-public", tags=["public"])
def get_health_public():
    """Flat public health snapshot for the landing LiveStatsWidget. Assembled from
    paper_trading_status.json + golive_status.json so the widget shows LIVE numbers
    (it was 404ing → frozen on hardcoded fallback)."""
    ps = _load_json("paper_trading_status.json", {})
    gl = _load_json("golive_status.json", {})
    ts = _load_json("tear_sheet.json", {})
    passed = gl.get("passed", gl.get("passed_count"))
    total = gl.get("total", gl.get("total_count", gl.get("criteria_total")))
    # Canonical track-days = EVIDENCED count from golive_checker (real_track_days),
    # NOT paper_trading_status.days_running (the padded raw-bar count). This is the
    # single honest number every surface must read. Fail-CLOSED: if golive_status
    # has no real_track_days, expose None rather than silently falling back to the
    # inflated days_running.
    real_track_days = gl.get("real_track_days")
    return {
        "generated_at": _now(),
        "source": "live",
        # Honest, evidenced track-day count (single source of truth = golive_checker).
        "real_track_days": real_track_days,
        # Honest go-live anchor + target — the ONE derived value (golive_checker
        # surfaces these top-level; fail-closed None until first evidenced day).
        "evidenced_anchor": gl.get("evidenced_anchor"),
        "go_live_target": gl.get("target_date"),
        # track_days is the DISPLAYED field — now the honest evidenced count, not
        # the padded days_running. Kept for backward-compat with existing consumers.
        "track_days": real_track_days,
        # Raw equity-bar count, retained for transparency / debugging only.
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


@app.get("/api/ssot/facts", tags=["ssot"])
def get_ssot_facts():
    """Canonical headline facts straight from SSOT (Law 3) — the presentation layer should
    render THESE verbatim so the site can't show a number that isn't in canon."""
    try:
        from spa_core.governance.ssot import key_facts
        return key_facts()
    except Exception as exc:  # noqa: BLE001
        return {"generated_at": _now(), "error": str(exc), "facts": {}}


@app.get("/api/governance", tags=["governance"])
def get_governance():
    """Governance-as-code: auto-vs-human action policy + dual-control posture."""
    return _load_json("governance_policy.json", {
        "generated_at": _now(), "policy": {}, "dual_control_posture": {"enforced": False},
    })


@app.get("/api/execution/readiness", tags=["execution"])
def get_execution_readiness():
    """Execution go/no-go posture (PAPER_SAFE) + honest live-blockers."""
    return _load_json("execution_readiness.json", {
        "generated_at": _now(), "posture": "unknown", "ready_for_live": False,
    })


@app.get("/api/tier1/nav", tags=["tier1"])
def get_tier1_nav():
    """Verifiable NAV / proof-of-reserves snapshot — anyone can recompute from components."""
    nav = _load_json("tier1_nav_proof.json", {
        "generated_at": _now(), "computed_nav_usd": None, "reconciliation_ok": None,
    })
    if isinstance(nav, dict):
        # Honest pointer — does NOT change any day count (operator-pending decision).
        nav.setdefault("meta", {
            "track_basis": "paper, advisory",
            "is_realized": False,
            "evidence_note": "see /track-record for which days are live-cycle-evidenced "
                             "vs backfill",
        })
    return nav


@app.get("/api/tier1/packages", tags=["tier1"])
def get_tier1_packages():
    """Tier-1 risk-tier packages (Conservative/Balanced/Aggressive) — data/tier1_packages.json.
    Validated (real-data backtest + net-of-cost + OOS + capacity) ∩ diversified core."""
    _pkg_meta = _backtest_meta(
        basis="real-data backtest, net-of-cost, out-of-sample + capacity-validated; "
              "risk-tier packages, NOT realized capital",
        period="tier-1 backtest validation window",
    )
    pkgs = _load_json("tier1_packages.json", {
        "generated_at": _now(), "model": "tier1_packages", "packages": {},
        "note": "Tier-1 packages not yet generated (run the backtest pipeline).",
    })
    if isinstance(pkgs, dict):
        pkgs.setdefault("meta", _pkg_meta)
    return pkgs


@app.get("/api/tier1/verdict", tags=["tier1"])
def get_tier1_verdict():
    """Full Tier-1 verdict over the tournament — data/tier1_verdict.json."""
    return _load_json("tier1_verdict.json", {
        "generated_at": _now(), "model": "tier1_parallel", "leaderboard_tier1": [],
    })


@app.get("/api/tier1/gate", tags=["tier1"])
def get_tier1_gate():
    """Backtest→paper eligibility gate + live-vs-backtest divergence — data/tier1_gate.json."""
    return _load_json("tier1_gate.json", {
        "generated_at": _now(), "gate": "tier1_backtest_to_paper",
        "eligible_for_paper": [], "blocked": {},
    })


@app.get("/api/tier1/status", tags=["tier1"])
def get_tier1_status():
    """One-glance Tier-1 rollup (regime, eligible, packages, integrity, divergence)."""
    return _load_json("tier1_status.json", {
        "generated_at": _now(), "model": "tier1_status", "health": "unknown", "packages": {},
    })


@app.get("/api/tier1/reverse-stress", tags=["tier1"])
def get_tier1_reverse_stress():
    """Inverse stress test — minimal shock that breaches loss tolerance — data/tier1_reverse_stress.json."""
    return _load_json("tier1_reverse_stress.json", {
        "generated_at": _now(), "model": "tier1_reverse_stress", "strategies": {},
    })


@app.get("/api/tier1/walk-forward", tags=["tier1"])
def get_tier1_walk_forward():
    """Walk-forward out-of-sample validation (consistency, robustness, capacity) — data/tier1_walk_forward.json."""
    return _load_json("tier1_walk_forward.json", {
        "generated_at": _now(), "model": "tier1_walk_forward", "strategies": {},
    })


@app.get("/api/tier1/correlation", tags=["tier1"])
def get_tier1_correlation():
    """Cross-strategy / package correlation matrix — data/tier1_correlation.json."""
    return _load_json("tier1_correlation.json", {
        "generated_at": _now(), "model": "tier1_correlation", "packages": {},
    })


@app.get("/api/tier1/monte-carlo", tags=["tier1"])
def get_tier1_monte_carlo():
    """Block-bootstrap Monte-Carlo path simulation — data/tier1_monte_carlo.json."""
    return _load_json("tier1_monte_carlo.json", {
        "generated_at": _now(), "model": "tier1_monte_carlo", "strategies": {},
    })


@app.get("/api/tier1/var", tags=["tier1"])
def get_tier1_var():
    """Value-at-Risk / CVaR (yield + principal) per validated strategy — data/tier1_var.json."""
    return _load_json("tier1_var.json", {
        "generated_at": _now(), "model": "tier1_var", "strategies": [],
    })


@app.get("/api/tier1/limits", tags=["tier1"])
def get_tier1_limits():
    """Risk-limit gate (HHI, concentration, tier aggregates, cash floor) — data/tier1_limits.json."""
    return _load_json("tier1_limits.json", {
        "generated_at": _now(), "model": "tier1_limits", "limits": {}, "current_portfolio": {},
    })


@app.get("/api/tier1/attribution", tags=["tier1"])
def get_tier1_attribution():
    """In-sample vs out-of-sample return attribution — data/tier1_attribution.json."""
    return _load_json("tier1_attribution.json", {
        "generated_at": _now(), "model": "tier1_attribution", "strategies": {},
    })


@app.get("/api/tier1/benchmark", tags=["tier1"])
def get_tier1_benchmark():
    """Strategy returns vs Aave / risk-free benchmark — data/tier1_benchmark.json."""
    return _load_json("tier1_benchmark.json", {
        "generated_at": _now(), "model": "tier1_benchmark", "results": {},
    })


@app.get("/api/tier1/regime", tags=["tier1"])
def get_tier1_regime():
    """Market regime classification + per-regime yield — data/tier1_regime.json."""
    return _load_json("tier1_regime.json", {
        "generated_at": _now(), "model": "tier1_regime", "current": None, "labels": [],
    })


@app.get("/api/strategy-lab", tags=["strategy_lab"])
def get_strategy_lab():
    """Strategy-Lab comparative backtest — data/strategy_lab_backtest.json.

    Projects the lab backtest result into the flat shape the site /strategies page consumes:
    {strategies:[{id,name,mandate,net_apy_pct,max_drawdown_pct,sharpe,beta_to_eth,
    funding_drag_pct,beats_rwa_floor,killed,kill_reason}], rwa_floor_pct, window_start,
    window_end, generated_at}.

    Read-only, graceful: returns an empty {} payload (not an error) when the backtest JSON is
    missing/corrupt, mirroring the tier1 handlers. Values are passed through VERBATIM from the
    file — no recomputation here. (TTL is the file's own generated_at; the lab refreshes it.)
    """
    raw = _load_json("strategy_lab_backtest.json", {})
    if not raw or not isinstance(raw, dict):
        return {
            "strategies": [], "rwa_floor_pct": None,
            "window_start": None, "window_end": None, "generated_at": None,
            "meta": _backtest_meta(
                basis="comparative backtest, equal-capital, net-of-cost",
                period="strategy_lab backtest window (see window_start/window_end)",
            ),
        }
    manifest = raw.get("manifest", {}) or {}
    kills = raw.get("kills", {}) or {}
    strategies = []
    for sid, blk in (raw.get("strategies", {}) or {}).items():
        m = blk.get("metrics", {}) or {}
        extra = m.get("extra", {}) or {}
        kill = blk.get("kill") or kills.get(sid)
        sid_key = blk.get("id", sid)
        strategies.append({
            "id": sid_key,
            "name": blk.get("name", sid),
            "mandate": blk.get("mandate", ""),
            "net_apy_pct": m.get("net_apy_pct"),
            "max_drawdown_pct": m.get("max_drawdown_pct"),
            "sharpe": m.get("sharpe"),
            "beta_to_eth": m.get("beta_to_eth"),
            "funding_drag_pct": m.get("funding_drag_pct"),
            "beats_rwa_floor": m.get("beats_rwa_floor"),
            "killed": bool(kill) or bool(extra.get("killed")),
            "kill_reason": (kill or {}).get("reason") if isinstance(kill, dict) else None,
            # Honesty label: assumed (engine_b/c) vs live_feed (rwa) vs realized.
            "yield_basis": _sleeve_yield_basis(sid_key),
            "yield_basis_note": _SLEEVE_YIELD_BASIS_NOTE.get(sid_key),
        })
    win_start = manifest.get("window_start")
    win_end = manifest.get("window_end")
    return {
        "strategies": strategies,
        "rwa_floor_pct": manifest.get("rwa_floor_apy_pct"),
        "window_start": win_start,
        "window_end": win_end,
        "generated_at": manifest.get("generated_at"),
        "meta": _backtest_meta(
            basis="comparative backtest, equal-capital, net-of-cost; per-sleeve "
                  "yield_basis distinguishes assumed/live_feed/realized",
            period=f"{win_start or '?'} → {win_end or '?'}",
        ),
    }


# ── Rates-Desk promotion section (REPORTING ONLY — NEVER a live-allocation path) ───────────────
# Architect decision T5: the four rates-desk sleeves are surfaced in the promotion REPORTING view,
# but they are IS_ADVISORY=True and MUST NOT feed the live tournament/allocator pre-go-live. We
# therefore emit them in a CLEARLY-SEPARATED `rates_desk` section (NOT merged into the lab `sleeves`
# list the live pipeline reads). Every sleeve carries explicit advisory/live-blocked flags so no
# consumer can mistake a research stage for a live allocation.
_RATES_DESK_SHAPE_LABEL = {
    "fixed_carry": "FixedCarry",
    "levered_carry": "LeveredCarry",
    "basis_hedge": "BasisHedge",
    "rate_matrix": "RateMatrix",
}
_RATES_DESK_ORDER = ("fixed_carry", "levered_carry", "rate_matrix", "basis_hedge")


def _rates_desk_promotion_section() -> dict:
    """Build the clearly-separated `rates_desk` reporting section for /api/strategy-lab/promotion.

    Read VERBATIM from data/rates_desk/rates_desk_promotion.json (the rates-desk promotion mapping
    that reuses promotion.score_sleeve), then enrich the BasisHedge sleeve with its BACKTEST-ONLY
    funding proxy (~4.99% net APY) pulled from data/rates_desk/rates_backtest.json — surfaced as a
    RESEARCH-ONLY sub-field, explicitly live-blocked (no keyless Boros forward-funding venue).

    HARD SEPARATION (reporting only, never live allocation):
      • every sleeve is force-flagged is_advisory=True + live_eligible=False here, regardless of
        its on-disk stage, so the reporting surface can never imply a live allocation;
      • the section is returned UNDER its own `rates_desk` key — it is NOT appended to the lab
        `sleeves` list that the live tournament/allocator pipeline consumes.

    Fail-CLOSED + graceful: a missing/corrupt file → an empty section (n_sleeves=0, never a
    fabricated promotion), mirroring the other handlers. Imported nothing — pure file read."""
    raw = _load_json("rates_desk/rates_desk_promotion.json", {})
    if not raw or not isinstance(raw, dict):
        return {
            "generated_at": None,
            "model": "rates_desk_promotion",
            "advisory": True,
            "live_eligible": False,
            "rwa_floor_pct": None,
            "n_sleeves": 0,
            "stage_counts": {},
            "sleeves": [],
            "note": ("RATES DESK — reporting only. These sleeves are IS_ADVISORY=True and are "
                     "NEVER routed to the live tournament/allocator before go-live."),
        }

    # the BasisHedge backtest-only funding proxy (~4.99% net APY), surfaced research-only.
    bt = _load_json("rates_desk/rates_backtest.json", {})
    bh_proxy = None
    if isinstance(bt, dict):
        bh_blk = (bt.get("sleeves") or {}).get("basis_hedge")
        if isinstance(bh_blk, dict):
            proxy = bh_blk.get("backtest_proxy")
            if isinstance(proxy, dict):
                bh_proxy = {
                    "net_apy_pct": proxy.get("net_apy_pct"),
                    "mean_apy_pct": proxy.get("mean_apy_pct"),
                    "beats_floor": bool(proxy.get("beats_floor")),
                    "deflated_sharpe": proxy.get("deflated_sharpe"),
                    "carry_days": proxy.get("carry_days"),
                    "hedge_rate_source": proxy.get("hedge_rate_source"),
                    "live_eligible": False,
                    "research_only": True,
                    "label": proxy.get(
                        "label",
                        "BACKTEST-ONLY (funding proxy) · live-BLOCKED until Boros permissionless"),
                }

    in_sleeves = raw.get("sleeves") if isinstance(raw.get("sleeves"), list) else []
    by_shape = {}
    for s in in_sleeves:
        if isinstance(s, dict):
            by_shape[s.get("shape")] = s

    out_sleeves = []
    for shape in _RATES_DESK_ORDER:
        s = by_shape.get(shape)
        if not isinstance(s, dict):
            continue
        sleeve = dict(s)
        sleeve["shape_label"] = _RATES_DESK_SHAPE_LABEL.get(shape, shape)
        # HARD SEPARATION: force advisory + live-blocked on the reporting surface regardless of
        # the on-disk stage — a PAPER_CANDIDATE here is a RESEARCH stage, NOT a live allocation.
        sleeve["is_advisory"] = True
        sleeve["live_eligible"] = False
        if shape == "basis_hedge" and bh_proxy is not None:
            sleeve["backtest_proxy"] = bh_proxy
        out_sleeves.append(sleeve)

    stage_counts = {}
    for s in out_sleeves:
        stage_counts[s.get("stage")] = stage_counts.get(s.get("stage"), 0) + 1

    return {
        "generated_at": raw.get("generated_at"),
        "model": raw.get("model", "rates_desk_promotion"),
        "advisory": True,
        "live_eligible": False,
        "rwa_floor_pct": raw.get("rwa_floor_pct"),
        "pipeline": raw.get("pipeline"),
        "n_sleeves": len(out_sleeves),
        "stage_counts": stage_counts,
        "sleeves": out_sleeves,
        "note": ("RATES DESK — reporting only. These four sleeves are IS_ADVISORY=True and are "
                 "NEVER routed to the live tournament/allocator before go-live. BasisHedge is "
                 "live-BLOCKED (no keyless forward-funding venue); its ~4.99% figure is a "
                 "BACKTEST-ONLY funding proxy under backtest_proxy, research-only."),
    }


@app.get("/api/strategy-lab/promotion", tags=["strategy_lab"])
def get_strategy_lab_promotion():
    """Strategy-Lab promotion engine verdicts — data/strategy_lab_promotion.json.

    The deterministic decision layer: each lab sleeve scored on the multi-criterion rubric and
    assigned a pipeline STAGE (REJECT / BACKTEST_PASS / PAPER_CANDIDATE) along
    RESEARCH -> BACKTEST -> WALK-FORWARD -> PAPER -> CANARY -> FULL.

    Additionally carries a clearly-separated `rates_desk` section (the four rates-desk sleeves,
    REPORTING ONLY — IS_ADVISORY, never a live-allocation path; see _rates_desk_promotion_section).

    Read-only, graceful: served VERBATIM from the file; returns an empty payload (not an error)
    when the JSON is missing/corrupt, mirroring /api/strategy-lab and the tier1 handlers.
    """
    raw = _load_json("strategy_lab_promotion.json", {})
    _promo_meta = _backtest_meta(
        basis="deterministic promotion rubric over strategy_lab backtest/walk-forward metrics",
        period="strategy_lab backtest window",
    )
    rates_desk = _rates_desk_promotion_section()
    if not raw or not isinstance(raw, dict):
        return {
            "generated_at": None,
            "model": "strategy_lab_promotion",
            "rwa_floor_pct": None,
            "n_sleeves": 0,
            "stage_counts": {},
            "sleeves": [],
            "rates_desk": rates_desk,
            "meta": _promo_meta,
        }
    raw.setdefault("meta", _promo_meta)
    # ALWAYS expose the rates-desk section under its OWN key — never merged into raw["sleeves"]
    # (the live-pipeline list). Overwrite any stale on-disk key so the separation is authoritative.
    raw["rates_desk"] = rates_desk
    return raw


@app.get("/api/refusal", tags=["strategy_lab"])
def get_refusal():
    """Rates-Desk advisory refusal engine — data/refusal_status.json.

    Per-underlying daily tail-risk verdict (SAFE / WATCH / REFUSE / UNKNOWN) from the §8-validated
    scorer run on live data. ADVISORY only — never trades / never touches the go-live track.

    Read-only, graceful: served VERBATIM from the file; returns an empty payload (not an error)
    when the JSON is missing/corrupt, mirroring /api/strategy-lab and the tier1 handlers.
    """
    raw = _load_json("refusal_status.json", {})
    if not raw or not isinstance(raw, dict):
        return {
            "generated_at": None,
            "model": "rates_desk_refusal_engine",
            "advisory": True,
            "latest_date": None,
            "thresholds": {},
            "verdict_counts": {},
            "underlyings": [],
        }
    return raw


@app.get("/api/rwa-safety-board", tags=["strategy_lab"])
def get_rwa_safety_board():
    """RWA Collateral Safety Board — data/rwa_safety_board.json.

    Per-asset daily verdict (LIQUID / THIN / REDEMPTION_ONLY / UNSAFE) on whether tokenized-RWA
    collateral has a REAL executable on-chain exit, plus the quantified marketing-vs-Liquidation-NAV
    gap %. Produced by the §SPA-RRB-validated LiquidationNAVEngine run on live DeFiLlama data.
    ADVISORY / RESEARCH only — never lends / trades / touches the go-live track.

    Read-only, graceful: served VERBATIM from the file; returns an empty payload (not an error)
    when the JSON is missing/corrupt, mirroring /api/refusal and the other strategy_lab handlers.
    """
    raw = _load_json("rwa_safety_board.json", {})
    if not raw or not isinstance(raw, dict):
        return {
            "generated_at": None,
            "model": "rwa_backstop_liquidation_nav",
            "advisory": True,
            "research_only": True,
            "verdict_counts": {},
            "n_assets": 0,
            # transparent on-chain-NAV coverage (T6): how many assets have a REAL ERC-4626 intrinsic
            # NAV read on-chain vs how many are permissioned/non-4626 → off-chain estimate.
            "onchain_nav_coverage": {
                "enabled": False, "onchain_4626": 0, "off_chain_estimate": 0, "total": 0,
                "assets_onchain": [],
                "note": "board not yet generated → coverage unavailable.",
            },
            "assets": [],
        }
    return raw


@app.get("/api/rates-desk/surface", tags=["strategy_lab"])
def get_rates_desk_surface():
    """Rates-Desk current RateSurface — data/rates_desk/rate_surface.json.

    The assembled fixed/implied-rate surface (PT / lending / boros RateQuotes + per-underlying risk +
    the honest per-underlying hedge_available map) from feeds.build_surface. Read-only, graceful: served
    VERBATIM from the file; returns an empty payload (not an error) when the JSON is missing/corrupt,
    mirroring /api/strategy-lab and the tier1 handlers.
    """
    _surface_meta = _backtest_meta(
        basis="implied/fixed-rate surface from live PT/lending feeds + deep Pendle PT "
              "history 2024-01→2026-06; quoted rates are research, not realized P&L",
        period="current surface (see as_of); history 2024-01→2026-06",
    )
    raw = _load_json("rates_desk/rate_surface.json", {})
    if not raw or not isinstance(raw, dict):
        return {
            "generated_at": None, "as_of": None, "mode": None,
            "hedge_available": {}, "quotes": [], "underlying_risk": {},
            "meta": _surface_meta,
        }
    raw.setdefault("meta", _surface_meta)
    return raw


@app.get("/api/rates-desk/opportunities", tags=["strategy_lab"])
def get_rates_desk_opportunities():
    """Rates-Desk current opportunity scan — the four trade shapes ranked by net_edge.

    Built from the cached RateSurface (data/rates_desk/rate_surface.json) via the pure OpportunityEngine
    (NO risk veto — that is the gate's job). Read-only, graceful: returns an empty payload (not an error)
    when the surface is missing/corrupt or the scan cannot be built, mirroring the other handlers.
    """
    _opp_meta = _backtest_meta(
        basis="ranked trade shapes scanned from the cached rate surface (deep Pendle PT "
              "history 2024-01→2026-06, total-capital basis, capacity-constrained); "
              "net_edge is research, not realized P&L",
        period="current scan (see as_of); history 2024-01→2026-06",
    )
    raw = _load_json("rates_desk/rate_surface.json", {})
    empty = {"generated_at": None, "as_of": None, "n_opportunities": 0,
             "opportunities": [], "meta": _opp_meta}
    if not raw or not isinstance(raw, dict) or not raw.get("quotes"):
        return empty
    try:
        from spa_core.strategy_lab.rates_desk.surface_io import scan_cached_surface
        scan = scan_cached_surface(raw)
        if isinstance(scan, dict):
            scan.setdefault("meta", _opp_meta)
        return scan
    except Exception as e:  # noqa: BLE001 — graceful, never 500 the dashboard
        log.warning(f"rates-desk opportunities scan failed: {e}")
        return empty


@app.get("/api/rates-desk/decisions", tags=["strategy_lab"])
def get_rates_desk_decisions(limit: int = Query(default=50, ge=1, le=500)):
    """Rates-Desk recent decision log — data/rates_desk/decision_log.jsonl (incl. REFUSALS).

    The public "what we traded AND what we refused + why" record: each entry is a hashed gate verdict
    (ENTRY or REFUSAL) with its proof_hash + the yield decomposition. Read-only, graceful: returns an
    empty list when the log is absent. Most recent last.
    """
    path = (_DATA_DIR / "rates_desk" / "decision_log.jsonl")
    rows = []
    if path.exists():
        try:
            for ln in path.read_text(encoding="utf-8").splitlines():
                ln = ln.strip()
                if not ln:
                    continue
                try:
                    rows.append(json.loads(ln))
                except json.JSONDecodeError:
                    continue
        except OSError as e:
            log.warning(f"rates-desk decision log read failed: {e}")
    rows = rows[-limit:]
    counts = {"ENTRY": 0, "REFUSAL": 0}
    for r in rows:
        k = r.get("kind")
        if k in counts:
            counts[k] += 1
    return {
        "generated_at": _now(),
        "model": "rates_desk_decision_log",
        "n_decisions": len(rows),
        "counts": counts,
        "decisions": rows,
    }


# Payload keys carried by every decision_log mirror row that are NOT part of the
# hash-covered decision payload (they are the chain-linkage envelope). Everything
# else in the row IS the verbatim decision_payload that the entry_hash covers.
_PROOF_ENVELOPE_KEYS = ("seq", "ts", "entry_hash", "prev_hash")
_PROOF_EVENT_TYPE = "rates_desk_decision"


def _verify_decision_log(rows: list) -> dict:
    """Re-derive the hash over every public decision_log mirror row, fail-CLOSED — tamper-evidence.

    Each mirror row is ``{seq, ts, entry_hash, prev_hash, **decision_payload}`` — an excerpt of the
    authoritative spa_core.audit.hash_chain. The mirror is a ring-buffered WINDOW of that append-only
    chain (LOG_CAP rows, possibly batched/out of seq order), so it is NOT a contiguous genesis-rooted
    slice — we therefore verify each row's INTRINSIC authenticity rather than cross-row genesis linkage:

      • Every entry_hash MUST recompute to its stored value via hash_chain.compute_entry_hash over the
        row's own payload + its own seq/ts/prev_hash. Because prev_hash is part of that hash preimage,
        flipping ANY field of a past decision (the verdict, the haircut, the reason, even the back-link)
        changes the recomputed hash and no longer matches → tamper detected at that seq. This is the
        full "did anyone rewrite a published decision" guarantee.

    Returns {"valid", "length", "broken_at", "head_hash"} where head_hash is the entry_hash of the
    highest-seq (newest) row — the current chain head that fingerprints the history. broken_at is the
    row index of the first decision that fails the recompute, else None. An empty log is valid.
    """
    try:
        from spa_core.audit import hash_chain
    except Exception as e:  # noqa: BLE001 — fail-CLOSED if the integrity module is unavailable
        log.warning(f"rates-desk proof: hash_chain import failed: {e}")
        return {"valid": False, "length": len(rows), "broken_at": None, "head_hash": None}

    head_seq = None
    head_hash = None
    for idx, row in enumerate(rows):
        if not isinstance(row, dict):
            return {"valid": False, "length": len(rows), "broken_at": idx, "head_hash": head_hash}
        seq = row.get("seq")
        ts = row.get("ts")
        prev_hash = row.get("prev_hash")
        entry_hash = row.get("entry_hash")
        # The hash-covered payload is the row minus the chain-linkage envelope.
        payload = {k: v for k, v in row.items() if k not in _PROOF_ENVELOPE_KEYS}
        # entry_hash must match a fresh recompute over the covered fields (intrinsic tamper-evidence).
        try:
            recomputed = hash_chain.compute_entry_hash(seq, ts, _PROOF_EVENT_TYPE, payload, prev_hash)
        except Exception:  # noqa: BLE001 — malformed row → fail-CLOSED at this row
            return {"valid": False, "length": len(rows), "broken_at": idx, "head_hash": head_hash}
        if recomputed != entry_hash:
            return {"valid": False, "length": len(rows), "broken_at": idx, "head_hash": head_hash}
        # Track the newest row (highest seq) as the chain head.
        if isinstance(seq, int) and (head_seq is None or seq > head_seq):
            head_seq = seq
            head_hash = entry_hash
    return {"valid": True, "length": len(rows), "broken_at": None, "head_hash": head_hash}


@app.get("/api/rates-desk/proof", tags=["strategy_lab"])
def get_rates_desk_proof(last_n: int = Query(default=12, ge=1, le=200)):
    """Rates-Desk PROOF surface — publicly verifiable, tamper-evident decision chain.

    The credibility moat made legible: the decision log (data/rates_desk/decision_log.jsonl) is an
    append-only hash chain — every gate verdict (ENTRY and REFUSAL) is hashed, and each entry carries
    the hash of the prior head. This endpoint actually RUNS the chain verification on the log and
    reports whether it is intact: flipping any past decision breaks the linkage and is detectable here.

    Returns:
        chain_length, head_hash, verified (bool — the chain self-verifies), broken_at (seq of the
        first tampered entry, else None), counts, last_n_decisions[], generated_at.

    Read-only, graceful, fail-CLOSED: an absent/corrupt log yields verified=true over a length-0 chain
    (vacuously intact), never a 500.
    """
    path = (_DATA_DIR / "rates_desk" / "decision_log.jsonl")
    rows: list = []
    if path.exists():
        try:
            for ln in path.read_text(encoding="utf-8").splitlines():
                ln = ln.strip()
                if not ln:
                    continue
                try:
                    rows.append(json.loads(ln))
                except json.JSONDecodeError:
                    # A corrupt line is itself tamper evidence — keep a sentinel so verify fails-CLOSED.
                    rows.append({"__corrupt__": True})
        except OSError as e:
            log.warning(f"rates-desk proof: decision log read failed: {e}")

    result = _verify_decision_log(rows)

    counts = {"ENTRY": 0, "REFUSAL": 0}
    for r in rows:
        if isinstance(r, dict):
            k = r.get("kind")
            if k in counts:
                counts[k] += 1

    last = []
    for r in rows[-last_n:]:
        if not isinstance(r, dict):
            continue
        dec = r.get("decomposition") or {}
        last.append({
            "seq": r.get("seq"),
            "ts": r.get("ts"),
            "as_of": r.get("as_of"),
            "underlying": r.get("underlying") or dec.get("underlying"),
            "kind": r.get("kind"),
            "allowed": bool(r.get("approved")),
            "reason": (r.get("detail", {}) or {}).get("note") or r.get("reason"),
            "haircut_total": dec.get("total_haircut"),
            "net_edge": r.get("net_edge"),
            "payload_hash": r.get("proof_hash"),
            "entry_hash": r.get("entry_hash"),
        })

    return {
        "generated_at": _now(),
        "model": "rates_desk_proof_chain",
        "chain_length": result["length"],
        "head_hash": result["head_hash"],
        "verified": result["valid"],
        "broken_at": result["broken_at"],
        "counts": counts,
        "last_n_decisions": last,
    }


@app.get("/api/rates-desk/track", tags=["strategy_lab"])
def get_rates_desk_track():
    """Rates-Desk LIVE paper forward-track — the validated FixedCarry sleeve, accruing.

    The credibility/distribution artifact: the validated FixedCarry sleeve runs live in paper (NO
    capital) via com.spa.rates_desk_paper, recording a verifiable FORWARD track. This serves that
    growing record from data/rates_desk/paper/ (status.json + the {sleeve}_series.json time-series):
    the days accumulated so far, cumulative return, and the equity series.

    Read-only, graceful, fail-CLOSED: returns an empty track (not an error) when no track exists yet
    (the service has not ticked), mirroring /api/rates-desk/decisions. is_advisory is ALWAYS true — this
    is advisory research, the same engine that will run live, recorded transparently. NOT the go-live
    track, NOT real capital.
    """
    status = _load_json("rates_desk/paper/status.json", {})
    series_doc = _load_json("rates_desk/paper/rates_desk_fixed_carry_series.json", {})

    sleeve = status.get("sleeve", {}) if isinstance(status, dict) else {}
    sleeve_id = sleeve.get("id") or (series_doc.get("id") if isinstance(series_doc, dict) else None) \
        or "rates_desk_fixed_carry"

    raw_series = series_doc.get("series", []) if isinstance(series_doc, dict) else []
    daily_series = []
    for pt in raw_series:
        if not isinstance(pt, dict):
            continue
        eq = pt.get("equity_usd")
        daily_series.append({
            "date": pt.get("date"),
            "equity": eq,
            "nav": eq,
            "net_apy_pct": pt.get("net_apy_pct"),
        })

    started_at = daily_series[0]["date"] if daily_series else None
    days = len(daily_series)

    current_equity = None
    cumulative_return_pct = None
    if daily_series:
        first_eq = daily_series[0].get("equity")
        last_eq = daily_series[-1].get("equity")
        current_equity = last_eq if last_eq is not None else sleeve.get("equity_usd")
        if isinstance(first_eq, (int, float)) and first_eq and isinstance(last_eq, (int, float)):
            cumulative_return_pct = round((last_eq / first_eq - 1.0) * 100.0, 6)
    else:
        current_equity = sleeve.get("equity_usd")

    return {
        "generated_at": _now(),
        "model": "rates_desk_paper_track",
        "sleeve_id": sleeve_id,
        "name": sleeve.get("name"),
        "started_at": started_at,
        "days": days,
        "current_equity": current_equity,
        "cumulative_return_pct": cumulative_return_pct,
        "net_apy_pct": sleeve.get("net_apy_pct"),
        "open_books": sleeve.get("open_books"),
        "closed_books": sleeve.get("closed_books"),
        "last_tick": sleeve.get("last_tick"),
        "gap": status.get("gap") if isinstance(status, dict) else None,
        "daily_series": daily_series,
        "is_advisory": True,
        "meta": _backtest_meta(
            basis="deep Pendle PT history 2024-01→2026-06, total-capital basis, "
                  "capacity-constrained; advisory paper forward-track, NOT real capital",
            period="rates-desk paper forward-track (see started_at/days)",
        ),
    }


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
    GoLive readiness report — full criteria set (currently 29, v6.0).
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


# ─── Adapters endpoint cache ──────────────────────────────────────────────────
# Building the adapter roster makes a live blocking DeFiLlama/CoinGecko fetch per
# adapter (~13s for 33 adapters). Without caching, every request blocks for the
# full sweep and clients with a normal timeout (5–10s) see an empty/failed
# response (HTTP 000). Cache the computed roster with a TTL so only the first
# call after expiry pays the network cost; all others are served instantly.
_ADAPTERS_CACHE: dict[str, Any] = {"data": None, "ts": 0.0}
_ADAPTERS_TTL = 300.0  # seconds — matches DeFiLlama feed TTL


def _build_adapters_roster() -> list:
    """Build the full adapter roster (live APY per adapter). Blocking/slow."""
    from spa_core.adapters import ADAPTER_REGISTRY
    result = []
    for entry in ADAPTER_REGISTRY:
        try:
            name, tier, cls = entry
        except (ValueError, TypeError):
            continue
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
            result.append({
                "name": name,
                "tier": getattr(instance, "TIER", tier),
                "apy": apy,
                "research_only": getattr(
                    instance, "RESEARCH_ONLY",
                    getattr(instance, "IS_ADVISORY", False),
                ),
            })
        except Exception as adapter_err:
            log.debug(f"Adapter entry error for {name!r}: {adapter_err}")
            # Still surface the adapter (from registry tuple) even if it
            # can't be instantiated / priced, so the site shows the roster.
            result.append({"name": name, "tier": tier, "apy": None,
                           "research_only": False})
    return result


@app.get("/api/v1/adapters", tags=["v1"])
def v1_adapters():
    """
    All registered adapters with tier and live APY.
    Uses ADAPTER_REGISTRY (the populated registry) from spa_core/adapters/__init__.py.

    Served from a TTL cache so requests don't block on the full live-APY sweep.
    """
    now = _time.time()
    cached = _ADAPTERS_CACHE.get("data")
    fresh = cached is not None and (now - _ADAPTERS_CACHE.get("ts", 0.0)) < _ADAPTERS_TTL
    if fresh:
        return {"adapters": cached, "count": len(cached),
                "cached": True, "timestamp": _now()}
    try:
        result = _build_adapters_roster()
        _ADAPTERS_CACHE["data"] = result
        _ADAPTERS_CACHE["ts"] = now
        return {"adapters": result, "count": len(result),
                "cached": False, "timestamp": _now()}
    except Exception as e:
        log.warning(f"/api/v1/adapters error: {e}")
        # Serve a stale cache if we have one — better than empty.
        if cached is not None:
            return {"adapters": cached, "count": len(cached),
                    "cached": True, "stale": True, "timestamp": _now()}
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


# ─── Tournament Endpoints ────────────────────────────────────────────────────
# Read-only; never raises; always stamps server_time + live=True.
# Sources: data/mass_tournament_results.json  (leaderboard, 60 strategies)
#          data/strategy_tournament.json       (top-5 shadow traders)
#          data/shadow_paper_trading.json      (paper tracking)

@app.get("/api/tournament", tags=["tournament"])
async def get_tournament():
    """
    Tournament leaderboard — top strategies ranked by Sharpe.
    Merges mass_tournament_results.json + strategy_tournament.json + shadow_paper_trading.json.
    """
    result: dict[str, Any] = {}

    _defaults: dict[str, Any] = {
        "mass_results":  {"leaderboard": [], "strategies_tested": 0},
        "tournament":    {"active_strategies": []},
        "shadow_paper":  {},
    }

    for fname, key in [
        ("mass_tournament_results.json", "mass_results"),
        ("strategy_tournament.json",     "tournament"),
        ("shadow_paper_trading.json",    "shadow_paper"),
    ]:
        p = _DATA_DIR / fname
        if not await _aio_exists(p):
            result[key] = _defaults[key]
            continue
        try:
            result[key] = await _aio_read_json(p)
        except asyncio.TimeoutError:
            result[key] = {"_error": "read_timeout"}
        except Exception as exc:
            result[key] = {"_error": str(exc)}

    # Honesty label: tournament `paper_apy` is BACKTEST-DERIVED, not live paper.
    # Tag each strategy row in-place so a direct consumer can't read paper_apy as live.
    tour = result.get("tournament")
    if isinstance(tour, dict):
        for _list_key in ("shadow_active_strategies", "active_strategies",
                          "ranked_strategies", "top_5", "bottom_5"):
            rows = tour.get(_list_key)
            if isinstance(rows, list):
                for row in rows:
                    if isinstance(row, dict) and "paper_apy" in row:
                        row.setdefault("apy_source", "backtest_derived")

    result["server_time"] = _now()
    result["live"] = True
    _meta = _backtest_meta(
        basis="deterministic backtest 2022-2025; leaderboard ranked by Sharpe; "
              "paper_apy is backtest_derived, NOT live paper",
        period="deterministic backtest 2022-2025",
    )
    # Surface the honest mass-tournament meta (degenerate-Sharpe caveat + real
    # per-protocol provenance + owner-gated rank-metric note) alongside the
    # standard backtest meta, without overwriting it.
    _mass = result.get("mass_results")
    if isinstance(_mass, dict) and isinstance(_mass.get("meta"), dict):
        _mm = _mass["meta"]
        for _k in (
            "sharpe_note", "data_source", "protocol_data_sources",
            "rank_metric", "rank_metric_owner_gated", "alt_rank_metric",
        ):
            if _k in _mm:
                _meta.setdefault(_k, _mm[_k])
    result["meta"] = _meta
    return JSONResponse(result, headers=_NO_CACHE_HEADERS)


@app.get("/api/tournament/status", tags=["tournament"])
async def get_tournament_status():
    """Quick status — phase counts and top-3 for the live indicator."""
    mass: dict[str, Any] = {}
    tournament: dict[str, Any] = {}

    p = _DATA_DIR / "mass_tournament_results.json"
    if await _aio_exists(p):
        try:
            mass = await _aio_read_json(p)
        except Exception:
            pass

    p2 = _DATA_DIR / "strategy_tournament.json"
    if await _aio_exists(p2):
        try:
            tournament = await _aio_read_json(p2)
        except Exception:
            pass

    leaderboard = mass.get("leaderboard", [])
    top3 = leaderboard[:3]
    # Honesty label: any paper_apy in the top-3 rows is backtest-derived, not live.
    for row in top3:
        if isinstance(row, dict) and "paper_apy" in row:
            row.setdefault("apy_source", "backtest_derived")

    # strategy_tournament.json uses "shadow_active_strategies"; older/other
    # producers used "active_strategies". Accept both so the count isn't always 0.
    active = (tournament.get("shadow_active_strategies")
              or tournament.get("active_strategies")
              or [])

    return JSONResponse(
        {
            "total_backtested":  mass.get("strategies_tested", 0),
            "total_skipped":     mass.get("strategies_skipped", 0),
            "paper_phase_count": len(active),
            "top3":              top3,
            "server_time":       _now(),
            "live":              True,
            "meta": _backtest_meta(
                basis="deterministic backtest 2022-2025; phase counts + Sharpe-ranked top-3; "
                      "paper_apy is backtest_derived, NOT live paper",
                period="deterministic backtest 2022-2025",
            ),
        },
        headers=_NO_CACHE_HEADERS,
    )


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
