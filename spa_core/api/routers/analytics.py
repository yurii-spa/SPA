"""spa_core/api/routers/analytics.py — dead-simple, privacy-friendly site analytics (MVP).

Owner decision (2026-07-09): own counter, SIMPLE MVP only — we're still paper-testing, ~1-2 months
of polish before launch, so no heavy analytics stack. This records ONLY a page path + an event type
+ a coarse timestamp. NO IP, NO cookies, NO PII, NO fingerprinting — consistent with the brand.
Append-only JSONL (like audit_trail.jsonl); the /admin Operator Console reads the summary.
stdlib + FastAPI only. Not a gate, not in any risk/exec path.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter(tags=["analytics"])

_LOG = Path(__file__).resolve().parents[3] / "data" / "site_analytics.jsonl"
_DAY = 86400


class Event(BaseModel):
    page: str = "/"
    event: str = "view"
    # Q2-9: optional campaign attribution (e.g. utm_source=defi-checkup, utm_campaign=depeg from the
    # Checkup deep-link funnel). Strings only, no PII — lets the reverse funnel be measured end-to-end.
    utm_source: str = ""
    utm_campaign: str = ""


@router.post("/api/analytics/event")
def record_event(ev: Event) -> dict:
    """Record one page-view or click. Privacy-friendly: page + event + day-timestamp only (+ optional
    utm_source/utm_campaign for funnel attribution — strings, never PII)."""
    rec = {"t": int(time.time()), "page": (ev.page or "/")[:200], "event": (ev.event or "view")[:48]}
    if ev.utm_source or ev.utm_campaign:
        rec["utm_source"] = (ev.utm_source or "")[:48]
        rec["utm_campaign"] = (ev.utm_campaign or "")[:48]
    try:
        _LOG.parent.mkdir(parents=True, exist_ok=True)
        with open(_LOG, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except Exception:  # noqa: BLE001 — analytics must never break a page
        pass
    return {"ok": True}


@router.get("/api/analytics/summary")
def summary() -> dict:
    """Coarse counts for the Operator Console: views today/7d, events by type, top pages."""
    now = int(time.time())
    views_today = views_7d = total_views = 0
    events: dict = {}
    pages: dict = {}
    campaigns: dict = {}
    try:
        with open(_LOG, encoding="utf-8") as fh:
            for line in fh:
                try:
                    r = json.loads(line)
                except Exception:  # noqa: BLE001
                    continue
                age = now - int(r.get("t", 0))
                ev = str(r.get("event", "view"))
                events[ev] = events.get(ev, 0) + 1
                if ev == "view":
                    total_views += 1
                    if age <= _DAY:
                        views_today += 1
                    if age <= 7 * _DAY:
                        views_7d += 1
                    p = str(r.get("page", "/"))
                    pages[p] = pages.get(p, 0) + 1
                camp = str(r.get("utm_campaign") or "")
                if camp:
                    key = (str(r.get("utm_source") or "?") + ":" + camp)[:64]
                    campaigns[key] = campaigns.get(key, 0) + 1
    except FileNotFoundError:
        pass
    top_pages = sorted(pages.items(), key=lambda kv: -kv[1])[:8]
    top_campaigns = sorted(campaigns.items(), key=lambda kv: -kv[1])[:8]
    return {
        "views_today": views_today,
        "views_7d": views_7d,
        "total_views": total_views,
        "events": events,
        "top_pages": [{"page": p, "views": c} for p, c in top_pages],
        "top_campaigns": [{"campaign": k, "hits": c} for k, c in top_campaigns],
        "note": "privacy-friendly MVP — page + event + coarse time only, no IP/cookies/PII",
    }
