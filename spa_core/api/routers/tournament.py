"""Tournament router — leaderboard + quick status.

Behavior-preserving extraction from server.py. Read-only; never raises; always stamps
server_time + live=True. Honesty labels (paper_apy → apy_source=backtest_derived, plus the
mass-tournament meta passthrough) are byte-identical.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from spa_core.api._shared import (
    NO_CACHE_HEADERS,
    aio_exists,
    aio_read_json,
    backtest_meta,
    data_dir,
    now,
)
import asyncio

router = APIRouter(tags=["tournament"])


@router.get("/api/tournament")
async def get_tournament():
    """Tournament leaderboard — merges mass_tournament_results + strategy_tournament + shadow_paper."""
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
        p = data_dir() / fname
        if not await aio_exists(p):
            result[key] = _defaults[key]
            continue
        try:
            result[key] = await aio_read_json(p)
        except asyncio.TimeoutError:
            result[key] = {"_error": "read_timeout"}
        except Exception as exc:
            result[key] = {"_error": str(exc)}

    # Honesty label: tournament `paper_apy` is BACKTEST-DERIVED, not live paper.
    tour = result.get("tournament")
    if isinstance(tour, dict):
        for _list_key in ("shadow_active_strategies", "active_strategies",
                          "ranked_strategies", "top_5", "bottom_5"):
            rows = tour.get(_list_key)
            if isinstance(rows, list):
                for row in rows:
                    if isinstance(row, dict) and "paper_apy" in row:
                        row.setdefault("apy_source", "backtest_derived")

    result["server_time"] = now()
    result["live"] = True
    _meta = backtest_meta(
        basis="deterministic backtest 2022-2025; leaderboard ranked by Sharpe; "
              "paper_apy is backtest_derived, NOT live paper",
        period="deterministic backtest 2022-2025",
    )
    _mass = result.get("mass_results")
    if isinstance(_mass, dict) and isinstance(_mass.get("meta"), dict):
        _mm = _mass["meta"]
        for _k in (
            "sharpe_note", "data_source", "protocol_data_sources",
            "rank_metric", "rank_metric_owner_gated", "alt_rank_metric",
            # Honesty gate: whether the Sharpe leaderboard is a trustworthy live ranking.
            "trustworthy", "data_source_regime", "trust_reason",
        ):
            if _k in _mm:
                _meta.setdefault(_k, _mm[_k])
    # Surface the honesty verdict at top level + a meta default so the site can gate
    # without digging. Fail-CLOSED: if the result never stamped trustworthy, treat as
    # NOT trustworthy (a missing flag must never render a mock ranking as live).
    if isinstance(_mass, dict):
        _trust = _mass.get("trustworthy")
        if _trust is None and isinstance(_mass.get("meta"), dict):
            _trust = _mass["meta"].get("trustworthy")
        result["trustworthy"] = bool(_trust) if _trust is not None else False
        _meta.setdefault("trustworthy", result["trustworthy"])
    result["meta"] = _meta
    return JSONResponse(result, headers=NO_CACHE_HEADERS)


@router.get("/api/tournament/status")
async def get_tournament_status():
    """Quick status — phase counts and top-3 for the live indicator."""
    mass: dict[str, Any] = {}
    tournament: dict[str, Any] = {}

    p = data_dir() / "mass_tournament_results.json"
    if await aio_exists(p):
        try:
            mass = await aio_read_json(p)
        except Exception:
            pass

    p2 = data_dir() / "strategy_tournament.json"
    if await aio_exists(p2):
        try:
            tournament = await aio_read_json(p2)
        except Exception:
            pass

    leaderboard = mass.get("leaderboard", [])
    top3 = leaderboard[:3]
    for row in top3:
        if isinstance(row, dict) and "paper_apy" in row:
            row.setdefault("apy_source", "backtest_derived")

    active = (tournament.get("shadow_active_strategies")
              or tournament.get("active_strategies")
              or [])

    return JSONResponse(
        {
            "total_backtested":  mass.get("strategies_tested", 0),
            "total_skipped":     mass.get("strategies_skipped", 0),
            "paper_phase_count": len(active),
            "top3":              top3,
            "server_time":       now(),
            "live":              True,
            "meta": backtest_meta(
                basis="deterministic backtest 2022-2025; phase counts + Sharpe-ranked top-3; "
                      "paper_apy is backtest_derived, NOT live paper",
                period="deterministic backtest 2022-2025",
            ),
        },
        headers=NO_CACHE_HEADERS,
    )
