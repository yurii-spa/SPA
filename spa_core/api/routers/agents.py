"""Agent registry API router — read-only surface of the launchd agent fleet (/api/agents/*).

Serves ``data/agent_registry.json`` (the SSOT produced by ``scripts/build_agent_registry.py``):
every ``com.spa.*`` agent with role, schedule, load state, pid, reboot-safety and problems.
Feeds the internal ``/admin/agents`` management dashboard — the actionable "know every agent"
view. Read-only, no money-path, no LLM. Fail-safe: a missing/unreadable registry returns an
honest empty fleet ``{agents:[], problem_count:0, note:...}`` — never a fabricated one.

Freshness: the cached snapshot is served directly while young (< 5 min); once stale (or absent)
the endpoint best-effort rebuilds it live via the SSOT builder (which queries ``launchctl``).
Any rebuild failure falls back to the last cached snapshot, then to the empty fail-safe.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Request

from spa_core.api.routers.live import _is_operator_request

router = APIRouter(tags=["agents"])

_ROOT = Path(__file__).resolve().parents[3]
_REGISTRY = _ROOT / "data" / "agent_registry.json"
_BUILDER = _ROOT / "scripts" / "build_agent_registry.py"
_MAX_AGE_SEC = 300  # serve cached below this age; rebuild live above it

_ROLES = ["infra", "allocation", "monitoring", "reporting", "research", "other"]
_FAILSAFE = {
    "model": "agent_registry",
    "generated_at": None,
    "total_loaded": 0,
    "total_known": 0,
    "by_role": {},
    "problem_count": 0,
    "roles": _ROLES,
    "agents": [],
    "note": "agent_registry.json missing — run scripts/build_agent_registry.py",
}


def _read_cached() -> dict | None:
    try:
        with open(_REGISTRY, encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:  # noqa: BLE001
        return None


def _age_sec(reg: dict | None) -> float | None:
    ts = reg.get("generated_at") if isinstance(reg, dict) else None
    if not ts:
        return None
    try:
        dt = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return (datetime.now(timezone.utc) - dt).total_seconds()
    except Exception:  # noqa: BLE001
        return None


def _regenerate() -> dict | None:
    """Best-effort live rebuild via the SSOT builder (queries ``launchctl``). Never raises."""
    try:
        import importlib.util

        spec = importlib.util.spec_from_file_location("build_agent_registry", _BUILDER)
        if spec is None or spec.loader is None:
            return None
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        reg = mod.build()
        return reg if isinstance(reg, dict) else None
    except Exception:  # noqa: BLE001
        return None


# Public callers (anything that is not an in-host request — see ``live._is_operator_request``)
# get the fleet COUNTS only, and never trigger the live ``launchctl`` rebuild. P1 2026-10-08
# (ADR-661): this route served every ``com.spa.*`` label with pid / last_exit / problems to the
# internet through the tunnel, the same leak class as /api/live/agents.
_PUBLIC_KEYS = ("model", "generated_at", "total_loaded", "total_known", "by_role",
                "problem_count", "roles")


def _public_view(reg: dict) -> dict:
    out = {k: reg[k] for k in _PUBLIC_KEYS if k in reg}
    out["agents"] = []
    out["detail"] = "per-agent detail is internal (operator console only)"
    return out


@router.get("/api/agents/registry")
def agents_registry(request: Request = None) -> dict:
    """The full agent fleet registry: fleet counts, per-role rollup, problem_count, and the
    per-agent list (label/short/role/schedule/loaded/pid/last_exit/retired/reboot_safe/problems).

    In-host callers: cached snapshot while fresh, else a live rebuild; fail-safe to an empty
    fleet. Public callers: counts from the cached snapshot only (no rebuild)."""
    if not _is_operator_request(request):
        cached = _read_cached()
        return _public_view(cached if isinstance(cached, dict) else dict(_FAILSAFE))
    cached = _read_cached()
    age = _age_sec(cached)
    if cached is not None and age is not None and age < _MAX_AGE_SEC:
        return cached
    fresh = _regenerate()
    if fresh is not None:
        return fresh
    if cached is not None:
        return cached
    return dict(_FAILSAFE)
