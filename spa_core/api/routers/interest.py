"""spa_core/api/routers/interest.py — Q2-5 interest-capture sink (PII-MINIMAL, append-only).

The /pilot funnel needs a durable place to record that someone expressed interest — WITHOUT collecting a
person's identity. This mirrors analytics.py: an append-only JSONL sink (data/interest.jsonl) that stores
ONLY a coarse intent signal — an optional opaque tier bucket, a topic, and campaign attribution — plus a
day-granularity timestamp. NO email, NO name, NO contact, NO IP, NO cookies. The brand is zero-PII.

**Owner-gated policy (flagged, NOT built):** whether to ever capture CONTACT details (an email to follow
up) is an owner decision requiring a consent flow + legal review (E-18). This endpoint deliberately has
NO contact field — it records anonymous intent the owner reads in /admin, and refuses PII-shaped input
fail-closed. stdlib + FastAPI only; not a gate, not in any risk/exec path.

HONESTY — `ok` never outruns the write (card `agent-checkup-waitlist-fail-open-ok-true`):
  Both sinks here are best-effort by design ("a capture must never break a page"), and that was
  implemented as a bare ``except: pass`` followed by an unconditional ``{"ok": True}``. The failure
  mode is the one measured on the sibling DeFi Checkup waitlist between 15.07 and 02.08: the caller
  is told the join succeeded while NOTHING was persisted, so "the sink is broken" is indistinguishable
  from "everything works" — for weeks. Swallowing the exception is still right (a full disk must not
  500 the page); publishing ``ok: true`` about it is not.
  The fix separates the two facts instead of merging them into one optimistic flag:
    * ``stored``: ``"ok" | "error"`` — did the record actually reach the JSONL sink;
    * ``notified``: the owner-notification OUTCOME, not "we called the notifier" —
      ``"sent" | "queued" | "skipped" | "error" | "unknown"`` (2026-08-19). The bool it
      replaced was ``True`` whenever no exception escaped, so a push refused by the policy
      gate, a failed transport, an unconfigured channel and a failed digest write all
      reported a notified owner. ``skipped`` is the local twin of the missing
      ``RESEND_API_KEY``: not attempted, and SAID so, instead of an anonymous failure.
      Only ``sent``/``queued`` count as delivery; ``unknown`` means NOT MEASURED and
      never counts (fail-CLOSED). ``notify_reason`` names the cause when it is not clean.
      The same state is published on ``/api/pilot/requests/count`` as ``notify_channel``,
      so "leads arrive, nobody is notified" is visible before a lead is lost;
    * ``ok`` — true only when the lead survived on AT LEAST ONE durable path. Both paths failing
      means the lead is LOST, and the endpoint says so (the /pilot form already renders ``error``).
  A ``position`` is likewise never returned for a row that was not written: the number would be
  re-issued to the next signup, i.e. fabricated.
"""
from __future__ import annotations

import json
import logging
import re
import time
from pathlib import Path

from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter(tags=["interest"])
log = logging.getLogger(__name__)

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


def _append_jsonl(path: Path, rec: dict) -> bool:
    """Append one record to an append-only JSONL sink. Returns True ONLY if it is on disk.

    Never raises — a capture failure must not 500 a public page — but the outcome is RETURNED
    instead of swallowed, so a caller can never report success for a write that did not happen
    (the waitlist fail-OPEN class; see the module docstring)."""
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
        return True
    except Exception:  # noqa: BLE001 — reported, not hidden
        return False


@router.post("/api/interest")
def record_interest(sig: InterestSignal) -> dict:
    """Record one anonymous interest signal. NO PII: opaque tier/topic/utm + a coarse timestamp only.
    An '@' or over-long / free-form value is dropped, never persisted.

    ``ok`` tracks the WRITE: a sink that could not be appended to reports ``ok:false`` /
    ``stored:"error"`` rather than a cosmetic success."""
    rec = {"t": int(time.time()), "tier": _clean(sig.tier), "topic": _clean(sig.topic)}
    src, camp = _clean(sig.utm_source), _clean(sig.utm_campaign)
    if src:
        rec["utm_source"] = src
    if camp:
        rec["utm_campaign"] = camp
    stored = _append_jsonl(_LOG, rec)
    return {"ok": stored, "stored": "ok" if stored else "error", "pii_minimal": True}


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


# Common free email providers — a lead from one of these is treated as a retail/individual signal.
# A lead from ANY OTHER domain is a B2B/institutional signal (a company/family-office/fund address)
# → "material" → instant per-lead Telegram ping. Owner decision Q-OWN-16: big/B2B → instant, rest → digest.
_FREE_EMAIL_DOMAINS = frozenset({
    "gmail.com", "googlemail.com", "outlook.com", "hotmail.com", "live.com", "msn.com",
    "yahoo.com", "yahoo.co.uk", "ymail.com", "icloud.com", "me.com", "mac.com",
    "proton.me", "protonmail.com", "pm.me", "aol.com", "gmx.com", "gmx.net", "mail.com",
    "zoho.com", "yandex.ru", "yandex.com", "mail.ru", "inbox.ru", "bk.ru", "list.ru",
    "fastmail.com", "hey.com", "web.de", "t-online.de", "qq.com", "163.com", "126.com",
})


def _is_material_lead(email: str, message: str, tier: str, source: str) -> bool:
    """Deterministic materiality classifier for a /pilot lead (owner Q-OWN-16: big/B2B → instant ping,
    rest → digest). No dollar field is captured (zero-PII brand), so materiality is inferred from
    available signals. MATERIAL if ANY of:
      • B2B/institutional — email domain is NOT a common free provider (company/fund/family-office);
      • early-access — the person joined the committed early-access list (source == "early_access");
      • aggressive tier — the largest-ticket interest band.
    Otherwise (free-mail retail signal with no commitment marker) → non-material → digest.
    Pure, side-effect-free; easy to tune via the signals above."""
    domain = email.rsplit("@", 1)[-1].strip().lower() if "@" in email else ""
    if domain and domain not in _FREE_EMAIL_DOMAINS:
        return True                       # B2B / institutional address
    if (source or "").strip().lower() == "early_access":
        return True                       # explicit commitment
    if (tier or "").strip().lower() == "aggressive":
        return True                       # largest-ticket band
    return False


#: Outcome vocabulary of the owner-notification leg. Three DIFFERENT facts, never merged:
#:   "sent"    — a Tier-1 push was accepted by the transport (delivered);
#:   "queued"  — demoted to the owner's daily digest AND the queue write is confirmed on disk;
#:   "skipped" — not attempted, because the channel is not configured (measured absence);
#:   "error"   — attempted and NOT delivered (transport/queue failure) — reason carried alongside;
#:   "unknown" — the channel state could not be measured at all (never counted as delivery).
_DELIVERED_STATES = frozenset({"sent", "queued"})


def _telegram_configured() -> bool | None:
    """Is the owner-notification channel configured? ``True``/``False`` = MEASURED,
    ``None`` = could not be measured (do not guess in either direction).

    This is the local analogue of the missing ``RESEND_API_KEY`` that made the sibling
    DeFi Checkup waitlist look healthy for three weeks: "no credentials" must be a
    DISTINCT, named outcome, not an anonymous delivery failure.
    """
    try:
        from spa_core.alerts import telegram_client as _tc
        try:
            return bool(_tc.get_bot_token() and _tc.get_chat_id())
        except EnvironmentError:
            return False          # measured: credentials are absent
    except Exception:  # noqa: BLE001 — importing/probing the channel itself failed
        return None               # NOT measured — never reported as "configured"


def notify_channel_status() -> dict:
    """Operator-visible state of the owner-notification channel (health surface).

    Exposed so that "leads arrive but nobody is notified" is VISIBLE without waiting for
    a lead to be lost: an unconfigured channel is a loud field on the console, not a
    line in a log nobody reads.
    """
    cfg = _telegram_configured()
    if cfg is True:
        return {"channel": "telegram", "configured": True, "measured": True}
    if cfg is False:
        return {"channel": "telegram", "configured": False, "measured": True,
                "flag_reason": "telegram credentials are not configured — contact requests are "
                               "stored but the owner is NOT notified"}
    return {"channel": "telegram", "configured": None, "measured": False,
            "flag_reason": "notification channel state could not be measured"}


def _notify_owner_telegram(email: str, message: str, tier: str, utm: str,
                           source: str = "") -> tuple[str, str]:
    """Route the owner lead-alert through the SINGLE Telegram authority (push_policy),
    NOT a direct telegram_client.send — a raw send bypasses the one push authority
    (see test_no_rogue_telegram_senders).

    Owner decision Q-OWN-16 (ADR-OWN-2026-07-lead-pings): a MATERIAL lead (B2B / early-access /
    aggressive tier — see ``_is_material_lead``) fires an instant per-lead Tier-1 ping via the
    ``pilot_request`` one-shot whitelist key (still under the policy's daily ceiling). A non-material
    lead is demoted to the owner's daily digest exactly as before. Best-effort, never raises.

    Returns ``(state, reason)`` — see ``_DELIVERED_STATES``. It used to return ``True`` for
    "no exception was raised", which is NOT delivery: ``push_critical`` returns ``False``
    whenever the gate demotes the event or the transport fails, and the digest enqueue
    swallowed its own failure. Both cases reported a notified owner who was never notified.
    """
    cfg = _telegram_configured()
    if cfg is False:
        # The RESEND_API_KEY analogue — loud, not a silent console.log inside the handler.
        log.warning("pilot lead NOT notified: telegram credentials are not configured "
                    "(the request is stored, the owner is not pinged)")
        return ("skipped", "owner-notification channel is not configured")
    if cfg is None:
        log.warning("pilot lead notification state NOT measurable: telegram channel could not be probed")
        return ("unknown", "owner-notification channel could not be probed")
    try:
        import html as _html
        from spa_core.telegram import push_policy
        material = _is_material_lead(email, message, tier, source)
        head = ("🎟 Early-access заявка" if source == "early_access" else "🔔 Новая заявка с /pilot")
        title = f"{head} — крупная/B2B" if material else head
        parts = [f"✉️ Email: {_html.escape(email)}"]
        if tier:
            parts.append(f"🏷 Тир: {_html.escape(tier)}")
        if utm:
            parts.append(f"📈 UTM: {_html.escape(utm)}")
        if message:
            parts.append(f"💬 {_html.escape(message)}")
        parts.append("Некастодиально · запрос на разговор, не сделка.")
        body = " · ".join(parts)
        if material:
            # instant per-lead ping (one-shot Tier-1 key; still capped by the daily ceiling)
            sent = push_policy.push_critical("pilot_request", "INFO", title, body)
            if sent:
                return ("sent", "")
            # The gate demoted it (ceiling/whitelist) or the transport failed — either way the
            # owner has NOT seen it. Fall through to the digest so the lead is not lost silently.
            queued = push_policy.enqueue_digest("pilot_request", title, body,
                                                severity="INFO", reason="pilot_lead_push_failed")
            if queued:
                return ("queued", "instant ping not delivered — folded into the daily digest")
            return ("error", "owner ping not delivered and the digest queue write failed")
        # retail/individual signal → folds into the one daily digest (unchanged behaviour)
        queued = push_policy.enqueue_digest("pilot_request", title, body,
                                            severity="INFO", reason="pilot_lead")
        if queued:
            return ("queued", "")
        return ("error", "digest queue write failed")
    except Exception as exc:  # noqa: BLE001 — notify is best-effort, but never silently "ok"
        log.warning("pilot lead notification failed: %s", exc)
        return ("error", f"owner notification failed: {type(exc).__name__}")


@router.post("/api/pilot/request")
def pilot_request(req: PilotRequest) -> dict:
    """Record a pilot CONTACT request (opt-in). Validates a plausible email fail-closed, appends to
    data/pilot_requests.jsonl, and pings the owner on Telegram. No email is ever surfaced on /admin.

    Response carries the two facts SEPARATELY (see the module docstring): ``stored`` (did the row
    reach the sink) and ``notified`` (did the owner ping report delivery). ``ok`` is true only when
    at least one of them held — a lead lost by BOTH paths is reported as lost, never as ``ok``."""
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
            position = 1          # no sink yet ⇒ this is genuinely the first signup
        except OSError:
            position = None       # sink present but unreadable ⇒ the place in the queue is
            # NOT measurable. Fail-closed: withhold the number (guessing "1" would tell every
            # signup they are first) and do not let a broken sink 500 the public form.
    rec = {"t": int(time.time()), "email": email, "message": message, "tier": tier,
           "source": source, "utm": utm}
    stored = _append_jsonl(_REQ_LOG, rec)
    notified, notify_reason = _notify_owner_telegram(email, message, tier, utm, source)
    delivered = notified in _DELIVERED_STATES
    # ok = the lead survived on at least one durable path (sink OR owner notification that
    # actually landed). "We called the notifier and it did not raise" is NOT a durable path.
    out = {"ok": bool(stored or delivered), "stored": "ok" if stored else "error",
           "notified": notified}
    if notify_reason:
        out["notify_reason"] = notify_reason
    if position is not None and stored:
        # A position for an unwritten row would be handed out again to the next signup.
        out["position"] = position
    if not out["ok"]:
        # Neutral, honest wording — no promise is made that was not kept.
        log.warning("pilot request LOST: stored=%s notified=%s (%s)", out["stored"], notified,
                    notify_reason or "-")
        out["error"] = "could not record the request — please try again"
    elif not delivered:
        # Stored, but nobody was pinged: the lead is safe, the follow-up is not automatic.
        log.warning("pilot request stored but owner NOT notified: notified=%s (%s)",
                    notified, notify_reason or "-")
    return out


@router.get("/api/pilot/requests/count")
def pilot_requests_count() -> dict:
    """COUNT-ONLY rollup of contact requests for the Operator Console — NO email/message is returned
    (that would leak PII on the currently-unauthenticated /admin). Total + today + 7d only."""
    now = int(time.time())
    total = today = last_7d = 0
    by_source: dict = {}   # I1: leads by SOURCE (early_access / snapshot / pilot) — opaque labels, no PII
    by_tier: dict = {}     # I1: leads by opaque interest band/tier — no PII
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
                src = str(r.get("source") or "pilot")
                by_source[src] = by_source.get(src, 0) + 1
                tier = str(r.get("tier") or "")
                if tier:
                    by_tier[tier] = by_tier.get(tier, 0) + 1
    except FileNotFoundError:
        pass
    return {"total_requests": total, "requests_today": today, "requests_7d": last_7d,
            "by_source": by_source, "by_tier": by_tier,
            # An unconfigured notification channel is named HERE, before a lead is lost —
            # not discovered weeks later from an unanswered contact request.
            "notify_channel": notify_channel_status(),
            "note": "count only (incl. by-source/by-tier opaque breakdowns) — full contact requests are "
                    "delivered to the owner via Telegram + data/pilot_requests.jsonl; never exposed on the "
                    "unauthenticated admin surface."}
