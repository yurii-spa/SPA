"""v1 versioned read-only API router (MP-1527): status / golive / adapters / evidence.

Behavior-preserving extraction from server.py. The adapter roster TTL cache (module-level)
moves here verbatim so /api/v1/adapters keeps its non-blocking-after-first-fetch behavior.
"""

from __future__ import annotations

import json
import logging
import time as _time
from typing import Any

from fastapi import APIRouter

from spa_core.api._shared import now, read_state

log = logging.getLogger("spa.api")

router = APIRouter(tags=["v1"])


def _project_root():
    """Resolve project root AT CALL TIME from server._PROJECT_ROOT so tests that
    patch('spa_core.api.server._PROJECT_ROOT', ...) keep working unchanged."""
    from spa_core.api import server as _srv
    return _srv._PROJECT_ROOT


@router.get("/api/v1/status")
def v1_status():
    """Sprint / KANBAN summary — done_count + sprint_completed from KANBAN.json."""
    try:
        kanban_path = _project_root() / "KANBAN.json"
        k = json.loads(kanban_path.read_text(encoding="utf-8"))
        return {
            "done_count": k.get("done_count"),
            "sprint": k.get("sprint_completed"),
            "version": k.get("version", "unknown"),
            "timestamp": now(),
        }
    except Exception as e:
        log.warning(f"/api/v1/status error: {e}")
        return {"error": str(e), "timestamp": now()}


@router.get("/api/v1/golive")
def v1_golive():
    """GoLive readiness report — data/golive_status.json, with inline-report fallback."""
    golive_data = read_state("golive_status.json", None)
    if golive_data is not None:
        golive_data["timestamp"] = now()
        golive_data["source"] = "file"
        return golive_data

    try:
        from spa_core.analytics.golive_readiness_report import GoLiveReadinessReport
        report = GoLiveReadinessReport(base_dir=str(_project_root()))
        result = report.generate_report()
        result["timestamp"] = now()
        result["source"] = "inline"
        return result
    except Exception as e:
        log.warning(f"/api/v1/golive inline report error: {e}")
        return {"error": str(e), "timestamp": now()}


# ─── Adapters endpoint cache ──────────────────────────────────────────────────
# Building the roster makes a live blocking fetch per adapter (~13s for 33). Cache
# the computed roster with a TTL so only the first call after expiry pays the cost.
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
            result.append({"name": name, "tier": tier, "apy": None,
                           "research_only": False})
    return result


@router.get("/api/v1/adapters")
def v1_adapters():
    """All registered adapters with tier and live APY (served from a TTL cache)."""
    now_t = _time.time()
    cached = _ADAPTERS_CACHE.get("data")
    fresh = cached is not None and (now_t - _ADAPTERS_CACHE.get("ts", 0.0)) < _ADAPTERS_TTL
    if fresh:
        return {"adapters": cached, "count": len(cached),
                "cached": True, "timestamp": now()}
    try:
        result = _build_adapters_roster()
        _ADAPTERS_CACHE["data"] = result
        _ADAPTERS_CACHE["ts"] = now_t
        return {"adapters": result, "count": len(result),
                "cached": False, "timestamp": now()}
    except Exception as e:
        log.warning(f"/api/v1/adapters error: {e}")
        if cached is not None:
            return {"adapters": cached, "count": len(cached),
                    "cached": True, "stale": True, "timestamp": now()}
        fallback = read_state("adapter_status.json", None)
        if fallback is not None:
            return {"adapters": fallback, "count": len(fallback) if isinstance(fallback, list) else 0,
                    "source": "file_fallback", "timestamp": now()}
        return {"error": str(e), "adapters": [], "count": 0, "timestamp": now()}


@router.get("/api/v1/evidence")
def v1_evidence():
    """Paper trading evidence history — data/paper_evidence_history.json (equity-curve fallback)."""
    evidence = read_state("paper_evidence_history.json", None)
    if evidence is not None:
        return {"data": evidence, "timestamp": now(), "source": "file"}
    equity = read_state("equity_curve_daily.json", None)
    if equity is not None:
        return {"data": equity, "timestamp": now(), "source": "equity_curve"}
    return {"error": "evidence file not found", "data": [], "timestamp": now()}
