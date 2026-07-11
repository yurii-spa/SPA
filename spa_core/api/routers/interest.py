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
