"""RTMR (ADR-053) API router — read-only surface of the real-time monitoring state (/api/rtmr/*).

Exposes what the sense/emergency service writes (signals, posture, reaction log, heartbeat) so the
dashboard can show the live monitoring organism: what it's watching, the current defensive posture,
and recent de-risk actions. Read-only, no money-path, no LLM. Fail-safe: missing files → empty/ok.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import json
import time
from pathlib import Path

from fastapi import APIRouter

router = APIRouter(tags=["rtmr"])

_MON = Path(__file__).resolve().parents[3] / "data" / "monitoring"


def _read(path: Path, default):
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:  # noqa: BLE001
        return default


@router.get("/api/rtmr/status")
def rtmr_status() -> dict:
    """One-call dashboard summary: liveness, what's watched, worst severity, active posture count."""
    latest = _read(_MON / "signals" / "latest.json", {})
    posture = _read(_MON / "risk_posture.json", {})
    hb = _read(_MON / "sense_heartbeat.json", {})
    now = int(time.time())
    hb_age = (now - int(hb.get("ts", 0))) if hb.get("ts") else None
    entries = posture.get("entries", {}) if isinstance(posture, dict) else {}
    sources: dict = {}
    for s in latest.get("signals", []):
        sources.setdefault(s.get("source"), {"scopes": 0, "worst": "info"})
        sources[s["source"]]["scopes"] += 1
    return {
        "mode": "paper",
        "alive": bool(hb_age is not None and hb_age < 180),
        "heartbeat_age_sec": hb_age,
        "last_tick_ts": latest.get("ts"),
        "max_severity": latest.get("max_severity", "info"),
        "signals_count": latest.get("count", 0),
        "sources": sorted(sources.keys()),
        "portfolio_posture": posture.get("portfolio", "NORMAL") if isinstance(posture, dict) else "NORMAL",
        "active_postures": len(entries),
        "posture_scopes": list(entries.keys()),
    }


@router.get("/api/rtmr/signals")
def rtmr_signals() -> dict:
    """The latest normalised RiskSignal snapshot (what each sensor sees right now)."""
    return _read(_MON / "signals" / "latest.json", {"ts": None, "signals": [], "max_severity": "info"})


@router.get("/api/rtmr/posture")
def rtmr_posture() -> dict:
    """The current defensive posture (what the emergency-path has de-risked)."""
    return _read(_MON / "risk_posture.json", {"portfolio": "NORMAL", "entries": {}})


@router.get("/api/rtmr/reactions")
def rtmr_reactions(limit: int = 20) -> dict:
    """Recent de-risk actions (paper) — the reaction log tail."""
    log = _read(_MON / "reaction_log.json", [])
    log = log if isinstance(log, list) else []
    return {"count": len(log), "recent": log[-int(limit):]}
