#!/usr/bin/env python3
"""Track-accrual freshness gate (P4-2) — the ONE thing that matters, self-detected.

The honest go-live track must accrue one *evidenced* equity bar per day (the daily
cycle runs ~06:00 UTC). Nothing previously self-detected a stale cycle: the API's
``/api/live/health`` returns 200 unconditionally, and the apiserver can serve STALE
data while reporting "up". This module is the single, deterministic, stdlib-only,
fail-CLOSED source of truth for "is the track fresh?" — shared by the live health
endpoint (body honesty) and the agent-health monitor (debounced SLA alert).

Definition (deterministic, fail-CLOSED)
=======================================
Freshness is measured as the age of the NEWEST *evidenced* equity bar
(:mod:`spa_core.paper_trading.track_evidence`), falling back to ``last_cycle_ts``
from ``paper_trading_status.json`` only when no evidenced bar timestamp is
available. The track is:

* ``ok``       — newest evidenced bar age ≤ ``SLA_HOURS`` (default 30h).
* ``degraded`` — age > ``SLA_HOURS``, OR the track cannot be read / has no
                 evidenced bar / has no parseable timestamp.

The SLA window is the daily cadence (24h) + a 6h buffer = **30h** — one full
missed daily cycle. This matches the existing ``EQUITY_STALE_H`` / one-missed-day
tolerance used elsewhere in the monitor, so the two surfaces agree.

Fail-CLOSED: any unreadable / unparseable / empty input → ``degraded`` (never
``ok``). A missing input is never silently treated as healthy.

Scope / safety
==============
* Stdlib only. Deterministic. No LLM, no randomness, no network.
* Read-only — never writes state files.
* ``now`` injectable for tests (frozen clock).
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from spa_core.paper_trading.track_evidence import evidenced_bars

# Daily cadence (24h) + 6h buffer = one fully-missed daily cycle before we degrade.
SLA_HOURS: float = 30.0

STATUS_OK = "ok"
STATUS_DEGRADED = "degraded"


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _parse_iso(ts: Any) -> Optional[datetime]:
    """Parse an ISO-8601 string (date or datetime) → tz-aware UTC datetime.

    Bare dates (``YYYY-MM-DD``) are anchored to 00:00 UTC. Returns None on any
    parse failure (fail-CLOSED at the call site)."""
    if not isinstance(ts, str) or not ts.strip():
        return None
    s = ts.strip().replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        # Try a bare date prefix (e.g. "2026-06-26" or a longer non-ISO string).
        try:
            dt = datetime.fromisoformat(s[:10])
        except ValueError:
            return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _newest_evidenced_ts(equity_doc: Any) -> Optional[str]:
    """Newest evidenced bar's timestamp (``date``/``timestamp``/``ts``), or None.

    Filters the daily series through :func:`evidenced_bars` so backfill /
    reconstructed / warmup bars can never make a stale track look fresh."""
    if not isinstance(equity_doc, dict):
        return None
    daily = equity_doc.get("daily")
    if not isinstance(daily, list):
        return None
    bars = evidenced_bars(daily)
    if not bars:
        return None
    last = bars[-1]
    if not isinstance(last, dict):
        return None
    raw = last.get("date") or last.get("timestamp") or last.get("ts")
    return raw if isinstance(raw, str) else None


def assess_track_freshness(
    equity_doc: Any = None,
    status_doc: Any = None,
    *,
    now: Optional[datetime] = None,
    sla_hours: float = SLA_HOURS,
) -> dict:
    """Return the freshness verdict from already-loaded docs (no filesystem I/O).

    Inputs:
      * ``equity_doc``  — parsed ``equity_curve_daily.json`` (preferred source).
      * ``status_doc``  — parsed ``paper_trading_status.json`` (``last_cycle_ts``
                          fallback when no evidenced bar timestamp is available).

    Returns a dict with at least::

        {
          "track_fresh": bool,
          "status": "ok" | "degraded",
          "age_hours": float | None,
          "sla_hours": float,
          "last_evidenced_date": str | None,   # the bar timestamp used
          "last_cycle_ts": str | None,         # status fallback ts (if any)
          "reason": str,                        # why degraded (or "fresh")
        }

    Deterministic + fail-CLOSED: an unreadable / missing / unparseable input that
    yields no usable timestamp → ``degraded``, never ``ok``.
    """
    _now = now or _utcnow()

    last_evidenced = _newest_evidenced_ts(equity_doc)
    last_cycle_ts = None
    if isinstance(status_doc, dict):
        v = status_doc.get("last_cycle_ts") or status_doc.get("last_run")
        last_cycle_ts = v if isinstance(v, str) else None

    # Prefer the evidenced-bar timestamp; fall back to last_cycle_ts.
    used_ts = last_evidenced or last_cycle_ts
    dt = _parse_iso(used_ts)

    if dt is None:
        return {
            "track_fresh": False,
            "status": STATUS_DEGRADED,
            "age_hours": None,
            "sla_hours": round(float(sla_hours), 2),
            "last_evidenced_date": last_evidenced,
            "last_cycle_ts": last_cycle_ts,
            "reason": (
                "no readable evidenced bar or last_cycle_ts (track unreadable)"
            ),
        }

    age_h = max(0.0, (_now - dt).total_seconds() / 3600.0)
    fresh = age_h <= float(sla_hours)
    return {
        "track_fresh": fresh,
        "status": STATUS_OK if fresh else STATUS_DEGRADED,
        "age_hours": round(age_h, 2),
        "sla_hours": round(float(sla_hours), 2),
        "last_evidenced_date": last_evidenced,
        "last_cycle_ts": last_cycle_ts,
        "reason": (
            "fresh"
            if fresh
            else f"newest evidenced bar {age_h:.1f}h old (>{float(sla_hours):.0f}h SLA)"
        ),
    }


def _load_json(path: Path) -> Any:
    """Fail-CLOSED JSON loader — returns None on missing/corrupt/unreadable."""
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def check_track_freshness(
    data_dir: Path | str,
    *,
    now: Optional[datetime] = None,
    sla_hours: float = SLA_HOURS,
) -> dict:
    """Filesystem entry point — read the track files from ``data_dir`` and assess.

    Reads ``equity_curve_daily.json`` + ``paper_trading_status.json`` (both
    fail-CLOSED: a missing/corrupt file is None → no usable timestamp →
    ``degraded``). Pure read; never writes."""
    dd = Path(data_dir)
    equity_doc = _load_json(dd / "equity_curve_daily.json")
    status_doc = _load_json(dd / "paper_trading_status.json")
    return assess_track_freshness(
        equity_doc, status_doc, now=now, sla_hours=sla_hours
    )


__all__ = [
    "SLA_HOURS",
    "STATUS_OK",
    "STATUS_DEGRADED",
    "assess_track_freshness",
    "check_track_freshness",
]
