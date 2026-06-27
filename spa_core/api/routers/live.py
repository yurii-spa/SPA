"""Live-API router — low-latency dashboard polling (/api/live/*).

Behavior-preserving extraction from server.py. Contract for ALL handlers: read-only,
never raise (always return a JSON dict, never a 5xx), stamp _fetched_at so the client
can show data age; a missing/corrupt file degrades to a status field, not an error.
Async non-blocking reads via _shared.aio_* keep the event loop free under concurrency.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import time as _time
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse

from spa_core.api._shared import (
    NO_CACHE_HEADERS,
    aio_exists,
    aio_read_json,
    data_dir,
)

log = logging.getLogger("spa.api")

router = APIRouter(tags=["live"])


@router.get("/api/live/ping")
async def live_ping():
    """Health check — if this answers, the Mac mini is online and reachable."""
    return JSONResponse(
        {"ok": True, "ts": _time.time(), "version": "live-api-v1"},
        headers=NO_CACHE_HEADERS,
    )


@router.get("/api/live/agents")
async def live_agents():
    """Live agent heartbeat — reads data/agent_health.json directly."""
    path = data_dir() / "agent_health.json"
    if not await aio_exists(path):
        return JSONResponse({"status": "no_data", "ts": _time.time()}, headers=NO_CACHE_HEADERS)
    try:
        data = await aio_read_json(path)
        if isinstance(data, dict):
            data["_fetched_at"] = _time.time()
            return JSONResponse(data, headers=NO_CACHE_HEADERS)
        return JSONResponse({"data": data, "_fetched_at": _time.time()}, headers=NO_CACHE_HEADERS)
    except asyncio.TimeoutError:
        return JSONResponse(
            {"ok": False, "error": "data_unavailable", "reason": "read_timeout", "ts": _time.time()},
            status_code=503, headers=NO_CACHE_HEADERS,
        )
    except Exception as e:
        return JSONResponse({"status": "error", "error": str(e), "ts": _time.time()}, headers=NO_CACHE_HEADERS)


# Snapshot is considered STALE if older than this many minutes. agent_health
# runs ~hourly but writes a fresh snapshot every run; >35min means the writer
# (com.spa.agent_health) itself is lagging → the counts must be shown as stale,
# never silently as if live (the T1 lesson: a stale briefing must look stale).
FLEET_STALE_MIN: float = 35.0


def _snapshot_age_min(ts: Any) -> float | None:
    """Minutes since the snapshot ISO `timestamp`; None if unparseable (→ stale)."""
    if not isinstance(ts, str) or not ts:
        return None
    try:
        dt = datetime.fromisoformat(ts)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        age = (datetime.now(timezone.utc) - dt).total_seconds() / 60.0
        return round(age, 1)
    except (ValueError, TypeError):
        return None


@router.get("/api/live/fleet")
async def live_fleet():
    """Fleet-health summary from data/agent_health.json — the trustworthy single
    source (T1). Serves a compact, honesty-first verdict for the dashboard:

        {overall_status, healthy, warning, critical, total,
         snapshot_age_min, stale (bool, >35min OR unparseable),
         agents: [{name, status, reason}]  # warn/crit agents only}

    Fail-CLOSED: a missing/corrupt/unparseable-timestamp snapshot is reported as
    ``available: false`` (honest unavailable) or ``stale: true`` — NEVER as a
    fabricated fresh count. Always 200 (consumers must not break)."""
    path = data_dir() / "agent_health.json"
    if not await aio_exists(path):
        return JSONResponse(
            {"available": False, "stale": True, "reason": "agent_health.json missing",
             "ts": _time.time()},
            headers=NO_CACHE_HEADERS,
        )
    try:
        data = await aio_read_json(path)
    except asyncio.TimeoutError:
        return JSONResponse(
            {"available": False, "stale": True, "reason": "read_timeout",
             "ts": _time.time()},
            status_code=503, headers=NO_CACHE_HEADERS,
        )
    except Exception as e:  # noqa: BLE001 — corrupt JSON / any read error → unavailable
        return JSONResponse(
            {"available": False, "stale": True, "reason": f"unreadable: {e}",
             "ts": _time.time()},
            headers=NO_CACHE_HEADERS,
        )

    if not isinstance(data, dict):
        return JSONResponse(
            {"available": False, "stale": True, "reason": "unexpected snapshot shape",
             "ts": _time.time()},
            headers=NO_CACHE_HEADERS,
        )

    age = _snapshot_age_min(data.get("timestamp"))
    # Unparseable/missing timestamp → fail-CLOSED to stale.
    stale = (age is None) or (age > FLEET_STALE_MIN)

    # Surface only the warn/crit agents + their reasons (the actionable ones).
    problem_agents: list[dict[str, Any]] = []
    for a in data.get("agents", []) or []:
        if not isinstance(a, dict):
            continue
        status = str(a.get("status", "")).upper()
        if status in ("WARNING", "WARN", "CRITICAL", "CRIT", "ERROR"):
            problem_agents.append({
                "name": a.get("label") or a.get("name") or "unknown",
                "status": a.get("status"),
                "reason": a.get("issue") or a.get("reason") or "",
            })

    return JSONResponse(
        {
            "available": True,
            "overall_status": data.get("overall_status"),
            "healthy": data.get("healthy_count"),
            "warning": data.get("warning_count"),
            "critical": data.get("critical_count"),
            "total": data.get("total_agents"),
            "snapshot_age_min": age,
            "stale": stale,
            "stale_threshold_min": FLEET_STALE_MIN,
            "timestamp": data.get("timestamp"),
            "agents": problem_agents,
            "_fetched_at": _time.time(),
        },
        headers=NO_CACHE_HEADERS,
    )


# A de-risk snapshot is considered STALE if older than this many minutes. The
# cycle (which writes derisk_status.json) runs daily; >26h means the writer is
# lagging → a possibly-outdated safety claim must be flagged, never shown as if
# freshly confirmed (the T1 lesson: a stale snapshot must look stale).
SAFETY_STALE_MIN: float = 26.0 * 60.0


@router.get("/api/live/safety")
async def live_safety():
    """Two-tier safety state (D3-T3, ADR-034) — owner-visible kill/de-risk surface.

    Makes the NEW safety states visible to the dashboard/owner:

        {state, label, derisk_active, kill_active, tier, reason,
         snapshot_age_min, stale, ...}

      • ``state == "HARD_KILL"``  → book is all-cash (CRITICAL). Set when
        ``kill_switch_active.json`` is present (and not ``active=False``) OR
        ``kill_switch_status.json`` reports ``triggered``.
      • ``state == "SOFT_DERISK"`` → ``derisk_status.json`` ``active=true``:
        new allocations / increases halted, held book retained (WARNING).
      • ``state == "CLEAR"``      → neither active.
      • ``state == "UNKNOWN"``    → a status file is present but unreadable /
        malformed (fail-CLOSED: an unverifiable state is never reported CLEAR).

    Read-only, verbatim, fail-CLOSED, always 200. A SOFT de-risk snapshot older
    than ~26h is flagged ``stale: true`` (the writer is lagging), with the
    last-known state still echoed so the owner sees it — just flagged."""
    dd = data_dir()

    # ── HARD kill / all-cash (highest severity) ───────────────────────────────
    kill_active = False
    kill_reason = ""
    kill_unreadable = False
    p_active = dd / "kill_switch_active.json"
    if await aio_exists(p_active):
        try:
            doc = await aio_read_json(p_active)
            if isinstance(doc, dict) and doc.get("active") is False:
                kill_active = False  # explicit deactivation marker
            else:
                kill_active = True
                if isinstance(doc, dict):
                    kill_reason = str(doc.get("reason") or "")
        except Exception:  # noqa: BLE001 — corrupt marker → cannot verify, fail-CLOSED
            kill_unreadable = True

    # Corroborate with the cycle-written verdict.
    status_triggered = False
    p_status = dd / "kill_switch_status.json"
    if await aio_exists(p_status):
        try:
            sdoc = await aio_read_json(p_status)
            if isinstance(sdoc, dict) and sdoc.get("triggered") is True:
                status_triggered = True
                if not kill_reason:
                    kill_reason = str(sdoc.get("reason") or "")
        except Exception:  # noqa: BLE001
            kill_unreadable = True

    if kill_active or status_triggered:
        return JSONResponse(
            {"available": True, "state": "HARD_KILL",
             "label": "HARD kill — all cash",
             "kill_active": True, "derisk_active": False,
             "tier": "HARD_KILL", "reason": kill_reason,
             "stale": False, "_fetched_at": _time.time()},
            headers=NO_CACHE_HEADERS,
        )

    # ── SOFT de-risk ──────────────────────────────────────────────────────────
    p_derisk = dd / "derisk_status.json"
    if not await aio_exists(p_derisk):
        # De-risk never fired and no kill → clean (unless a kill marker was
        # unreadable, in which case we cannot confirm CLEAR).
        if kill_unreadable:
            return JSONResponse(
                {"available": True, "state": "UNKNOWN",
                 "label": "safety state unverifiable (kill marker unreadable)",
                 "kill_active": False, "derisk_active": False,
                 "reason": "kill_switch_active/status unreadable",
                 "stale": True, "_fetched_at": _time.time()},
                headers=NO_CACHE_HEADERS,
            )
        return JSONResponse(
            {"available": True, "state": "CLEAR",
             "label": "no safety state active",
             "kill_active": False, "derisk_active": False,
             "tier": "NONE", "reason": "no de-risk, no kill",
             "stale": False, "_fetched_at": _time.time()},
            headers=NO_CACHE_HEADERS,
        )

    try:
        ddoc = await aio_read_json(p_derisk)
    except Exception as e:  # noqa: BLE001 — corrupt → UNKNOWN, never silently CLEAR
        return JSONResponse(
            {"available": True, "state": "UNKNOWN",
             "label": "de-risk state unverifiable (file unreadable)",
             "kill_active": False, "derisk_active": False,
             "reason": f"derisk_status.json unreadable: {e}",
             "stale": True, "_fetched_at": _time.time()},
            headers=NO_CACHE_HEADERS,
        )

    if not isinstance(ddoc, dict):
        return JSONResponse(
            {"available": True, "state": "UNKNOWN",
             "label": "de-risk state unverifiable (malformed)",
             "kill_active": False, "derisk_active": False,
             "reason": "derisk_status.json malformed", "stale": True,
             "_fetched_at": _time.time()},
            headers=NO_CACHE_HEADERS,
        )

    derisk_active = bool(ddoc.get("active"))
    age = _snapshot_age_min(ddoc.get("generated_at"))
    stale = (age is None) or (age > SAFETY_STALE_MIN)
    tier = ddoc.get("tier")
    reason = str(ddoc.get("reason") or "")

    if derisk_active:
        return JSONResponse(
            {"available": True, "state": "SOFT_DERISK",
             "label": "SOFT de-risk active" + (f" — {reason}" if reason else ""),
             "kill_active": False, "derisk_active": True,
             "tier": tier, "reason": reason, "policy": ddoc.get("policy"),
             "snapshot_age_min": age, "stale": stale,
             "stale_threshold_min": SAFETY_STALE_MIN,
             "_fetched_at": _time.time()},
            headers=NO_CACHE_HEADERS,
        )

    return JSONResponse(
        {"available": True, "state": "CLEAR",
         "label": "no safety state active",
         "kill_active": False, "derisk_active": False,
         "tier": tier, "reason": reason,
         "snapshot_age_min": age, "stale": stale,
         "stale_threshold_min": SAFETY_STALE_MIN,
         "_fetched_at": _time.time()},
        headers=NO_CACHE_HEADERS,
    )


@router.get("/api/live/portfolio")
async def live_portfolio():
    """Live portfolio bundle — merges available portfolio/pnl/equity files."""
    result: dict[str, Any] = {}
    for fname in ["portfolio_state.json", "pnl_history.json",
                  "equity_curve_daily.json", "current_positions.json",
                  "paper_trading_status.json"]:
        p = data_dir() / fname
        if not await aio_exists(p):
            continue
        try:
            result[fname[:-5]] = await aio_read_json(p)
        except asyncio.TimeoutError:
            result[fname[:-5]] = {"_error": "read_timeout"}
        except Exception as e:
            result[fname[:-5]] = {"_error": str(e)}
    result["_fetched_at"] = _time.time()
    return JSONResponse(result, headers=NO_CACHE_HEADERS)


@router.get("/api/live/system")
async def live_system():
    """Live system-health bundle — merges available health/watcher/log files."""
    result: dict[str, Any] = {}
    for fname in ["system_health.json", "telegram_watcher_status.json",
                  "auto_fixer_log.json", "golive_status.json"]:
        p = data_dir() / fname
        if not await aio_exists(p):
            continue
        try:
            result[fname[:-5]] = await aio_read_json(p)
        except asyncio.TimeoutError:
            result[fname[:-5]] = {"_error": "read_timeout"}
        except Exception as e:
            result[fname[:-5]] = {"_error": str(e)}
    result["_fetched_at"] = _time.time()
    return JSONResponse(result, headers=NO_CACHE_HEADERS)


@router.get("/api/live/status")
async def live_status():
    """Live aggregate status — paper_trading_status + golive_status + current_positions.
    Never raises: missing/corrupt file → {"_error": ...}."""
    result: dict[str, Any] = {"_fetched_at": _time.time()}
    for fname in ["paper_trading_status.json", "golive_status.json",
                  "current_positions.json"]:
        p = data_dir() / fname
        if not await aio_exists(p):
            continue
        try:
            result[fname[:-5]] = await aio_read_json(p)
        except asyncio.TimeoutError:
            result[fname[:-5]] = {"_error": "read_timeout"}
        except Exception as e:
            result[fname[:-5]] = {"_error": str(e)}
    return JSONResponse(result, headers=NO_CACHE_HEADERS)


@router.get("/api/live/health")
async def live_health():
    """Deep health check — server alive + data dir reachable + TRACK FRESH.

    Always 200 (consumers must not break), but the BODY honestly reports
    ``status: degraded`` when the one thing that matters — the honest go-live
    track accruing a fresh evidenced bar — is stale (newest evidenced bar / last
    cycle older than the SLA window) or unreadable. Fail-CLOSED: an unreadable
    track degrades, it is never silently reported ``ok``.
    """
    _dd = data_dir()
    try:
        data_dir_ok: bool = await asyncio.wait_for(
            asyncio.to_thread(lambda: _dd.exists() and _dd.is_dir()),
            timeout=2.0,
        )
    except asyncio.TimeoutError:
        data_dir_ok = False

    try:
        json_count: int = await asyncio.wait_for(
            asyncio.to_thread(
                lambda: sum(1 for f in _dd.glob("*.json") if f.is_file())
            ),
            timeout=2.0,
        )
    except asyncio.TimeoutError:
        json_count = -1

    # Track-accrual freshness — fail-CLOSED to degraded on any read/parse trouble.
    try:
        from spa_core.paper_trading.track_freshness import check_track_freshness

        track = await asyncio.wait_for(
            asyncio.to_thread(check_track_freshness, _dd), timeout=2.0,
        )
    except Exception:  # noqa: BLE001 — timeout/import/any error → fail-CLOSED
        track = {
            "track_fresh": False,
            "status": "degraded",
            "age_hours": None,
            "last_evidenced_date": None,
            "last_cycle_ts": None,
            "reason": "track freshness check failed (unreadable)",
        }

    track_fresh = bool(track.get("track_fresh"))
    # Overall body status: degraded if data dir is unreachable OR track is stale.
    status = "ok" if (data_dir_ok and track_fresh) else "degraded"

    return JSONResponse(
        {
            "ok": data_dir_ok,
            "status": status,
            "ts": _time.time(),
            "version": "live-api-v1",
            "data_dir_ok": data_dir_ok,
            "json_files": json_count,
            "track_fresh": track_fresh,
            "track": track,
        },
        headers=NO_CACHE_HEADERS,
    )


# Generic read-only passthrough — hardened against traversal: only flat *.json
# basenames that resolve inside the data dir are served.
_LIVE_FILE_RE = re.compile(r"^[A-Za-z0-9_.-]+\.json$")


@router.get("/api/live/data/{filename}")
async def live_data_file(filename: str):
    """Serve a single data/*.json file verbatim (read-only, traversal-safe)."""
    if not _LIVE_FILE_RE.match(filename):
        raise HTTPException(status_code=400, detail={"error": "invalid filename"})
    _dd = data_dir()
    path = (_dd / filename).resolve()
    try:
        path.relative_to(_dd.resolve())
    except ValueError:
        raise HTTPException(status_code=400, detail={"error": "path escapes data dir"})
    if not await aio_exists(path):
        raise HTTPException(status_code=404, detail={"error": "not found"})
    try:
        data = await aio_read_json(path)
        return JSONResponse(data, headers=NO_CACHE_HEADERS)
    except asyncio.TimeoutError:
        return JSONResponse(
            {"ok": False, "error": "data_unavailable", "reason": "read_timeout"},
            status_code=503,
            headers=NO_CACHE_HEADERS,
        )
    except json.JSONDecodeError as e:
        raise HTTPException(status_code=502, detail={"error": f"corrupt json: {e}"})
