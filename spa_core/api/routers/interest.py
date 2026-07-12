"""spa_core/api/routers/interest.py — Q2-5 interest-capture sink (PII-MINIMAL, append-only).

The /pilot funnel needs a durable place to record that someone expressed interest — WITHOUT collecting a
person's identity. This mirrors analytics.py: an append-only JSONL sink (data/interest.jsonl) that stores
ONLY a coarse intent signal — an optional opaque tier bucket, a topic, and campaign attribution — plus a
day-granularity timestamp. NO email, NO name, NO contact, NO IP, NO cookies. The brand is zero-PII.

**Owner-gated policy (flagged, NOT built):** whether to ever capture CONTACT details (an email to follow
up) is an owner decision requiring a consent flow + legal review (E-18). This endpoint deliberately has
NO contact field — it records anonymous intent the owner reads in /admin, and refuses PII-shaped input
fail-closed. stdlib + FastAPI only; not a gate, not in any risk/exec path.
"""
from __future__ import annotations

import json
import re
import time
from pathlib import Path

from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter(tags=["interest"])

_LOG = Path(__file__).resolve().parents[3] / "data" / "interest.jsonl"
_DAY = 86400
# reject any free-form / PII-shaped token (emails, long free text) — opaque buckets only.
_TOKEN_RE = re.compile(r"^[A-Za-z0-9 _.\-]{0,48}$")


class InterestSignal(BaseModel):
    # all optional, all opaque — an interest signal, never an identity
    tier: str = ""          # opaque bucket, e.g. "conservative" | "balanced" | "aggressive"
    topic: str = ""         # e.g. "pilot" | "fundability" | "refusals"
    utm_source: str = ""
    utm_campaign: str = ""


def _clean(s: str) -> str:
    s = (s or "").strip()[:48]
    return s if _TOKEN_RE.match(s) else ""   # PII-shaped / illegal → dropped (fail-closed, never stored)


@router.post("/api/interest")
def record_interest(sig: InterestSignal) -> dict:
    """Record one anonymous interest signal. NO PII: opaque tier/topic/utm + a coarse timestamp only.
    An '@' or over-long / free-form value is dropped, never persisted."""
    rec = {"t": int(time.time()), "tier": _clean(sig.tier), "topic": _clean(sig.topic)}
    src, camp = _clean(sig.utm_source), _clean(sig.utm_campaign)
    if src:
        rec["utm_source"] = src
    if camp:
        rec["utm_campaign"] = camp
    try:
        _LOG.parent.mkdir(parents=True, exist_ok=True)
        with open(_LOG, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except Exception:  # noqa: BLE001 — capture must never break a page
        pass
    return {"ok": True, "pii_minimal": True}


@router.get("/api/interest/summary")
def summary() -> dict:
    """Coarse interest counts for the Operator Console: total, today/7d, by tier, by topic, by campaign."""
    now = int(time.time())
    total = today = last_7d = 0
    by_tier: dict = {}
    by_topic: dict = {}
    campaigns: dict = {}
    try:
        with open(_LOG, encoding="utf-8") as fh:
            for line in fh:
                try:
                    r = json.loads(line)
                except Exception:  # noqa: BLE001
                    continue
                total += 1
                age = now - int(r.get("t", 0))
                if age <= _DAY:
                    today += 1
                if age <= 7 * _DAY:
                    last_7d += 1
                t = str(r.get("tier") or "")
                if t:
                    by_tier[t] = by_tier.get(t, 0) + 1
                tp = str(r.get("topic") or "")
                if tp:
                    by_topic[tp] = by_topic.get(tp, 0) + 1
                camp = str(r.get("utm_campaign") or "")
                if camp:
                    key = (str(r.get("utm_source") or "?") + ":" + camp)[:64]
                    campaigns[key] = campaigns.get(key, 0) + 1
    except FileNotFoundError:
        pass
    return {
        "total_interest": total,
        "interest_today": today,
        "interest_7d": last_7d,
        "by_tier": by_tier,
        "by_topic": by_topic,
        "top_campaigns": [{"campaign": k, "hits": c}
                          for k, c in sorted(campaigns.items(), key=lambda kv: -kv[1])[:8]],
        "pii_minimal": True,
        "note": ("anonymous intent only — opaque tier/topic/utm + coarse time, no email/name/IP/cookies. "
                 "Contact-capture is an owner policy decision (consent + legal), deliberately not built."),
    }


@router.get("/api/pilot/summary")
def pilot_summary() -> dict:
    """Q2-8: the design-partner pilot pipeline funnel rollup for the Operator Console (PII-minimal —
    opaque labels only). Read-only; graceful (missing store → empty funnel). Never a gate."""
    try:
        from spa_core.pilot import pipeline as pp
        return pp.summary()
    except Exception as exc:  # noqa: BLE001 — admin surface must never 500
        return {"model": "pilot_pipeline", "is_advisory": True, "n_prospects": 0,
                "by_stage": {}, "flag_reason": f"unavailable: {exc}"}


# ── Pilot contact request (OWNER-APPROVED opt-in contact capture, 2026-07-12) ──────────────────────
# The owner enabled contact capture for the /pilot funnel: a warm visitor may LEAVE A CONTACT to request
# a conversation. Unlike the anonymous /api/interest beacon (zero-PII), this is an explicit opt-in — the
# person types their own email to be contacted. The full request is delivered to the owner over Telegram
# (private) + appended to data/pilot_requests.jsonl. It is DELIBERATELY NOT exposed in /admin (which has
# no auth yet — Q-OWN-03); /admin shows only a COUNT so no email leaks on an unauthenticated surface.
_REQ_LOG = Path(__file__).resolve().parents[3] / "data" / "pilot_requests.jsonl"
_EMAIL_RE = re.compile(r"^[^@\s]{1,64}@[^@\s]{1,190}\.[A-Za-z]{2,24}$")


class PilotRequest(BaseModel):
    email: str = ""
    message: str = ""      # optional free note from the requester
    tier: str = ""         # opaque interest bucket
    source: str = ""       # M7: e.g. "early_access" — routes framing + returns a real position number
    utm_source: str = ""
    utm_campaign: str = ""


def _notify_owner_telegram(email: str, message: str, tier: str, utm: str, source: str = "") -> bool:
    """Best-effort Telegram ping to the owner. Never raises (a page must not break on notify failure)."""
    try:
        import html as _html
        from spa_core.alerts.telegram_client import send_message
        header = ("🎟 <b>Early-access заявка</b>\n" if source == "early_access"
                  else "🔔 <b>Новая заявка с /pilot</b>\n")
        body = (
            header
            + f"✉️ <b>Email:</b> {_html.escape(email)}\n"
            + (f"🏷 <b>Тир:</b> {_html.escape(tier)}\n" if tier else "")
            + (f"📈 <b>UTM:</b> {_html.escape(utm)}\n" if utm else "")
            + (f"💬 <b>Сообщение:</b> {_html.escape(message)}\n" if message else "")
            + "\n<i>Некастодиально · это запрос на разговор, не сделка.</i>"
        )
        return bool(send_message(body, parse_mode="HTML"))
    except Exception:  # noqa: BLE001 — notify is best-effort
        return False


@router.post("/api/pilot/request")
def pilot_request(req: PilotRequest) -> dict:
    """Record a pilot CONTACT request (opt-in). Validates a plausible email fail-closed, appends to
    data/pilot_requests.jsonl, and pings the owner on Telegram. No email is ever surfaced on /admin."""
    email = (req.email or "").strip()[:256]
    if not _EMAIL_RE.match(email):
        return {"ok": False, "error": "a valid email is required to request a conversation"}
    message = (req.message or "").strip()[:1000]
    tier = _clean(req.tier)
    source = _clean(req.source)
    src, camp = _clean(req.utm_source), _clean(req.utm_campaign)
    utm = (f"{src}:{camp}" if (src or camp) else "")
    # M7: early-access position = count of prior early_access signups + 1 (REAL, never fabricated).
    position = None
    if source == "early_access":
        try:
            with open(_REQ_LOG, encoding="utf-8") as fh:
                position = sum(1 for l in fh if '"source": "early_access"' in l) + 1
        except FileNotFoundError:
            position = 1
    rec = {"t": int(time.time()), "email": email, "message": message, "tier": tier,
           "source": source, "utm": utm}
    try:
        _REQ_LOG.parent.mkdir(parents=True, exist_ok=True)
        with open(_REQ_LOG, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except Exception:  # noqa: BLE001 — capture must never break the page
        pass
    notified = _notify_owner_telegram(email, message, tier, utm, source)
    out = {"ok": True, "notified": notified}
    if position is not None:
        out["position"] = position
    return out


@router.get("/api/pilot/requests/count")
def pilot_requests_count() -> dict:
    """COUNT-ONLY rollup of contact requests for the Operator Console — NO email/message is returned
    (that would leak PII on the currently-unauthenticated /admin). Total + today + 7d only."""
    now = int(time.time())
    total = today = last_7d = 0
    try:
        with open(_REQ_LOG, encoding="utf-8") as fh:
            for line in fh:
                try:
                    r = json.loads(line)
                except Exception:  # noqa: BLE001
                    continue
                total += 1
                age = now - int(r.get("t", 0))
                if age <= _DAY:
                    today += 1
                if age <= 7 * _DAY:
                    last_7d += 1
    except FileNotFoundError:
        pass
    return {"total_requests": total, "requests_today": today, "requests_7d": last_7d,
            "note": "count only — full contact requests are delivered to the owner via Telegram + "
                    "data/pilot_requests.jsonl; never exposed on the unauthenticated admin surface."}
