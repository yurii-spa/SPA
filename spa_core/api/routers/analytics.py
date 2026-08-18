"""spa_core/api/routers/analytics.py — dead-simple, privacy-friendly site analytics (MVP).

Owner decision (2026-07-09): own counter, SIMPLE MVP only — we're still paper-testing, ~1-2 months
of polish before launch, so no heavy analytics stack. This records ONLY a page path + an event type
+ a coarse timestamp. NO IP, NO cookies, NO PII, NO fingerprinting — consistent with the brand.
Append-only JSONL (like audit_trail.jsonl); the /admin Operator Console reads the summary.
stdlib + FastAPI only. Not a gate, not in any risk/exec path.

HONESTY — `ok` never outruns the write (card `agent-checkup-waitlist-fail-open-ok-true`):
  This sink is the twin of `interest.py` and carried the SAME fail-OPEN the card measured on the
  DeFi Checkup waitlist: a bare ``except: pass`` around the append followed by an unconditional
  ``{"ok": True}``. Measured 2026-08-18 with the sink path pointed at a directory — the endpoint
  answered ``{"ok": true}`` while NOTHING reached disk, so "the counter is broken" was
  indistinguishable from "everything works". That matters here specifically because this is the
  sink that carries the Checkup funnel attribution (``utm_source=defi-checkup``): a silently dead
  write turns a broken funnel into a funnel that merely "has no traffic".
  Swallowing the exception stays right (analytics must never 500 a page); publishing ``ok: true``
  about it does not. The write outcome is now RETURNED: ``stored`` = ``"ok" | "error"`` and
  ``ok`` = the write actually happened.
  The read side keeps the same three outcomes distinct instead of collapsing two of them to zero:
    * ``sink: "ok"``       — the log was read; counts are measured;
    * ``sink: "absent"``   — no log yet ⇒ genuinely zero events (a measured zero);
    * ``sink: "unreadable"`` — the log exists but could not be read ⇒ NOT measured. Counts are
      withheld (``None``) with ``measured: false`` + ``flag_reason``, never rendered as a zero,
      and the admin surface still does not 500 (an unreadable sink used to raise ``OSError``
      straight through — only ``FileNotFoundError`` was caught).
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


def _append_jsonl(path: Path, rec: dict) -> bool:
    """Append one record to the append-only sink. Returns True ONLY if it is on disk.

    Never raises — analytics must not 500 a public page — but the outcome is RETURNED instead of
    swallowed, so the endpoint can never report success for a write that did not happen."""
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
        return True
    except Exception:  # noqa: BLE001 — reported, not hidden
        return False


@router.post("/api/analytics/event")
def record_event(ev: Event) -> dict:
    """Record one page-view or click. Privacy-friendly: page + event + day-timestamp only (+ optional
    utm_source/utm_campaign for funnel attribution — strings, never PII).

    ``ok`` tracks the WRITE: a sink that could not be appended to answers ``ok:false`` /
    ``stored:"error"`` rather than a cosmetic success (see the module docstring)."""
    rec = {"t": int(time.time()), "page": (ev.page or "/")[:200], "event": (ev.event or "view")[:48]}
    if ev.utm_source or ev.utm_campaign:
        rec["utm_source"] = (ev.utm_source or "")[:48]
        rec["utm_campaign"] = (ev.utm_campaign or "")[:48]
    stored = _append_jsonl(_LOG, rec)
    return {"ok": stored, "stored": "ok" if stored else "error"}


@router.get("/api/analytics/summary")
def summary() -> dict:
    """Coarse counts for the Operator Console: views today/7d, events by type, top pages."""
    now = int(time.time())
    views_today = views_7d = total_views = 0
    events: dict = {}
    pages: dict = {}
    campaigns: dict = {}
    sink = "ok"
    _reason = ""
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
        sink = "absent"          # no log yet ⇒ genuinely zero events — a MEASURED zero
    except OSError as exc:       # noqa: BLE001
        # The log exists but could not be read (permissions, a directory in its place, I/O error).
        # This is NOT a zero — it is "not measured". Withhold the counts instead of publishing a
        # fabricated zero, and do not let a broken sink 500 the admin surface (it used to).
        sink = "unreadable"
        _reason = f"{type(exc).__name__}: {exc}"
    measured = sink != "unreadable"
    top_pages = sorted(pages.items(), key=lambda kv: -kv[1])[:8]
    top_campaigns = sorted(campaigns.items(), key=lambda kv: -kv[1])[:8]
    out = {
        "views_today": views_today if measured else None,
        "views_7d": views_7d if measured else None,
        "total_views": total_views if measured else None,
        "events": events if measured else {},
        "top_pages": [{"page": p, "views": c} for p, c in top_pages] if measured else [],
        "top_campaigns": ([{"campaign": k, "hits": c} for k, c in top_campaigns]
                          if measured else []),
        "sink": sink,
        "measured": measured,
        "note": "privacy-friendly MVP — page + event + coarse time only, no IP/cookies/PII",
    }
    if not measured:
        out["flag_reason"] = f"analytics sink unreadable — counts withheld, not zero ({_reason})"
    return out
