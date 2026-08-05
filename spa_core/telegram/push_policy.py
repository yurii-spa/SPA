"""spa_core/telegram/push_policy.py — THE single push authority (Tier-1 gate).

Phase 1 of the Telegram rebuild (docs/TELEGRAM_BOT_ARCHITECTURE.md). This is the
*only* code path allowed to push an unsolicited (Tier-1) message to the owner's
ops chat. Every former ad-hoc ``send_message`` call site in the noisy monitors
becomes a single ``push_critical(...)`` call here.

The gate, in order (ALL must pass to push):

1. **Closed whitelist.** ``event_key`` must be on ``TIER1_WHITELIST``. Anything
   else is demoted to the digest queue (``data/telegram/digest_queue.json``) and
   returns ``False`` — it is *physically* not allowed to interrupt the owner.

2. **Edge-trigger (not level-trigger).** Durable state in
   ``data/telegram/push_state.json`` records each event's last state. We push
   only on the ``ok → bad`` transition; while the bad state *persists* we are
   silent (this kills the agent-health 17×/day re-fire); on the ``bad → ok``
   transition we emit exactly one "✅ RESOLVED".

   Two refinements (2026-08-05, the "alerts_undelivered [self_heal,
   threat_reactor] refused_by_push_policy" fix — both close FALSE suppression
   without weakening genuine dedup):

   * **Per-incident fingerprint (``dedup_key``).** The edge state is keyed by
     ``event_key`` — a CLASS of events shared by several senders (self_heal,
     watchdog and uptime_monitor all push ``core_agent_down``). Without a
     fingerprint, agent X down yesterday left the class ``bad`` and agent Y
     down today was silenced as "still bad" — a DIFFERENT incident eaten by
     class-level dedup (measured in prod: ``core_agent_down`` stuck ``bad``,
     no sender ever resolves it). Callers may pass ``dedup_key`` describing
     the concrete incident; persistence is silent ONLY while the fingerprint
     is unchanged. A changed fingerprint = a new distinct incident = a push.
     Callers that pass no ``dedup_key`` keep the old class-level behaviour.

   * **Retry-until-delivered-once.** The entry push used to mark the state
     ``bad`` even when the transport FAILED or the daily ceiling demoted it
     (``entry_pushed: false``) — the alert was then permanently swallowed:
     never delivered, never retried (measured in prod: ``kill_switch`` stuck
     ``bad`` with ``entry_pushed: false`` since 2026-07-04). Now a persisting
     bad state whose entry was never actually delivered re-attempts the entry
     (still subject to the daily ceiling). Once delivered, persistence is
     silent exactly as before.

3. **Held-protocol scoping.** Peg / red-flag events only push when they hit a
   protocol we actually hold (``held_protocol=True``). Advisory protocols are
   demoted to the digest.

4. **Hard daily ceiling.** At most ``DEFAULT_DAILY_CEILING`` (10) Tier-1 pushes
   per UTC day; the ceiling+1th is coalesced into a single "N more critical
   events — open /alerts" notice (sent once), and further events that day are
   dropped to the digest. Defends against a flapping detector.

5. **Transport.** Sends via ``telegram_client._post_message`` so the shared
   flood-guard and ``alert_history.json`` audit trail still apply (belt &
   suspenders under the policy layer).

Invariants (RULES.md / CLAUDE.md):
  * stdlib only.
  * deterministic — no LLM anywhere.
  * fail-CLOSED on a bad event (an unwhitelisted key never pushes), fail-SAFE on
    infra errors (a state-file error never crashes the caller; ``push_critical``
    never raises).
  * atomic state writes via ``spa_core.utils.atomic.atomic_save``.
  * secrets only from Keychain (inherited from ``telegram_client``).

Public API
----------
``push_critical(event_key, severity, title, body, *, held_protocol=False,
                resolved=False, ...) -> bool``
    Emit a Tier-1 push IFF it passes the gate. Returns whether a message was
    actually sent.

``resolve(event_key, ...) -> bool``
    Convenience wrapper for the ``bad → ok`` transition (one "RESOLVED" push).

``TIER1_WHITELIST`` / ``HELD_SCOPED_KEYS``
    The closed policy tables (also consumed by the CI single-authority guard's
    docstring and the tests).
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from spa_core.utils.atomic import atomic_load, atomic_save

log = logging.getLogger("spa.telegram.push_policy")

_REPO_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_TG_DIR = _REPO_ROOT / "data" / "telegram"
PUSH_STATE_FILENAME = "push_state.json"
DIGEST_QUEUE_FILENAME = "digest_queue.json"

# ── Closed Tier-1 whitelist (docs/TELEGRAM_BOT_ARCHITECTURE.md §2) ───────────
# An event_key NOT in this set can never push — it is demoted to the digest.
# kill_switch      — kill-switch FIRED (drawdown / threat / manual)
# cycle_failed     — daily cycle FAILED / did not run (track integrity)
# cycle_gap        — missed daily cycle (cycle_gap_monitor; ≤1/day via edge)
# system_critical  — CRITICAL system health (corruption / all-feeds-down / NAV)
# agent_health_critical — agent-health overall CRITICAL (e.g. core agent down)
# core_agent_down  — a cycle-critical launchd agent is down (uptime_monitor)
# peg_break        — stablecoin peg break on a HELD protocol
# red_flag         — red-flag CRITICAL (hack/exploit) on a HELD protocol
# rules_critical   — CRITICAL rule breach (rules_watchdog)
# golive_ready     — go-live state change NOT-READY → READY (one-shot)
# pilot_request    — a MATERIAL /pilot lead (B2B/institutional/early-access) — instant per-lead
#                    ping (owner decision Q-OWN-16 / ADR-OWN-2026-07-lead-pings). Non-material
#                    leads stay demoted to the digest at the call site (interest.py).
# architecture_conformance_critical — the fleet has diverged from the architecture manifest
#                    (ADR-066 контур B): an agent runs undeclared, an `active` agent is gone,
#                    a `designed` architecture activated itself, a required product has no
#                    reader. Edge-triggered with a set-of-findings fingerprint, so a persistent
#                    divergence pings ONCE, and a DIFFERENT set is a new incident.
TIER1_WHITELIST: frozenset[str] = frozenset(
    {
        "kill_switch",
        "cycle_failed",
        "cycle_gap",
        "system_critical",
        "agent_health_critical",
        "core_agent_down",
        "peg_break",
        "red_flag",
        "rules_critical",
        "golive_ready",
        "pilot_request",
        "architecture_conformance_critical",
    }
)

# Keys whose push is gated on hitting a HELD protocol (live capital at risk).
HELD_SCOPED_KEYS: frozenset[str] = frozenset({"peg_break", "red_flag"})

# One-shot keys: each occurrence is a DISTINCT real event (a new lead), NOT a persistent
# condition. They bypass the edge-trigger (which would silence the 2nd+ occurrence as
# "still bad") and instead always push — subject only to the daily ceiling — never recording
# a persistent bad-state. A material lead today and another tomorrow both ping.
ONESHOT_KEYS: frozenset[str] = frozenset({"pilot_request"})

DEFAULT_DAILY_CEILING = 10

# Edge-trigger state constants.
_STATE_BAD = "bad"
_STATE_OK = "ok"


# ── IO helpers (atomic, fail-safe) ───────────────────────────────────────────
def _tg_dir(data_dir: Optional[Path] = None) -> Path:
    return Path(data_dir) / "telegram" if data_dir is not None else _DEFAULT_TG_DIR


def _load_state(tg_dir: Path) -> dict:
    """Load push_state.json → {"events": {...}, "ceiling": {...}}. Never raises."""
    try:
        doc = atomic_load(str(tg_dir / PUSH_STATE_FILENAME), default={})
    except Exception:  # noqa: BLE001 — a corrupt state file must not blind the policy
        doc = {}
    if not isinstance(doc, dict):
        doc = {}
    events = doc.get("events")
    if not isinstance(events, dict):
        events = {}
    ceiling = doc.get("ceiling")
    if not isinstance(ceiling, dict):
        ceiling = {}
    return {"events": events, "ceiling": ceiling}


def _save_state(tg_dir: Path, state: dict) -> None:
    """Atomic write of push_state.json. Never raises (logs on failure)."""
    try:
        payload = {
            "schema_version": 1,
            "source": "push_policy",
            "updated_at": _now_iso(),
            "events": state.get("events", {}),
            "ceiling": state.get("ceiling", {}),
        }
        atomic_save(payload, str(tg_dir / PUSH_STATE_FILENAME))
    except Exception:  # noqa: BLE001
        log.warning("push_policy: push_state write failed", exc_info=True)


def _enqueue_digest(tg_dir: Path, item: dict, *, cap: int = 500) -> None:
    """Append a demoted (non-Tier-1) event to the digest queue. Never raises."""
    try:
        doc = atomic_load(str(tg_dir / DIGEST_QUEUE_FILENAME), default={})
        if not isinstance(doc, dict):
            doc = {}
        items = doc.get("items")
        if not isinstance(items, list):
            items = []
        items.append(item)
        if len(items) > cap:
            items = items[-cap:]
        atomic_save(
            {
                "schema_version": 1,
                "source": "push_policy",
                "updated_at": _now_iso(),
                "count": len(items),
                "items": items,
            },
            str(tg_dir / DIGEST_QUEUE_FILENAME),
        )
    except Exception:  # noqa: BLE001 — a queue error must never crash a monitor
        log.warning("push_policy: digest enqueue failed", exc_info=True)


def enqueue_digest(
    event_key: str,
    title: str,
    body: str = "",
    *,
    severity: str = "INFO",
    reason: str = "demoted",
    data_dir: Optional[str | Path] = None,
) -> None:
    """Public convenience for a RETIRED/informational sender to demote its text
    to the digest queue (folded into the one daily digest) instead of pushing.

    Never raises. This is the canonical "I am not a Tier-1 push" call site for
    the monitors/agents that used to push unsolicited Telegram directly.
    """
    _enqueue_digest(
        _tg_dir(Path(data_dir) if data_dir is not None else None),
        {
            "ts": _now_iso(),
            "event_key": event_key,
            "severity": severity,
            "title": title,
            "body": (body or "")[:500],
            "reason": reason,
        },
    )


def _now_iso(now: Optional[datetime] = None) -> str:
    return (now or datetime.now(timezone.utc)).isoformat()


def _today(now: Optional[datetime] = None) -> str:
    return (now or datetime.now(timezone.utc)).strftime("%Y-%m-%d")


# ── Transport (the ONLY allowed Tier-1 send) ─────────────────────────────────
def _send(text: str) -> bool:
    """Send via the shared telegram_client transport (HTML). Never raises."""
    try:
        from spa_core.alerts.telegram_client import _post_message
        return bool(_post_message({"text": text, "parse_mode": "HTML"}))
    except Exception as exc:  # noqa: BLE001 — alerts must never crash callers
        log.warning("push_policy: telegram send failed: %s", exc)
        return False


def _humanize(title: str, body: str) -> tuple[str, str]:
    """Перевести заголовок/тело алерта на простой русский (owner-задание 2026-07-20/27).

    Чистый текстовый слой (``spa_core.telegram.humanize``): нераспознанное проходит
    вербатим, ничего не выдумывается, ошибок не бросает. Гейт (whitelist /
    edge-trigger / ceiling / held-scoping) НЕ затрагивается — это только рендер.
    """
    try:
        from spa_core.telegram.humanize import humanize
        return humanize(title, body)
    except Exception as exc:  # noqa: BLE001 — алерт обязан дойти даже «сырым»
        log.warning("push_policy: humanize failed (%s) — sending raw text", exc)
        return title, body


def _format_message(severity: str, title: str, body: str,
                    *, resolved: bool = False) -> str:
    icon = "✅" if resolved else ("🚨" if str(severity).upper() == "CRITICAL" else "⚠️")
    title, body = _humanize(title, body)
    head = f"{icon} <b>{title}</b>"
    parts = [head]
    if body:
        parts.append("")
        parts.append(body)
    parts.append("")
    parts.append(f"<i>{_now_iso()}</i>")
    return "\n".join(parts)


# ── Ceiling bookkeeping ──────────────────────────────────────────────────────
def _ceiling_for_today(state: dict, today: str) -> dict:
    """Return the (mutable) ceiling record for ``today``, resetting on date roll."""
    c = state.get("ceiling") or {}
    if c.get("date") != today:
        c = {"date": today, "pushed": 0, "coalesced_sent": False}
        state["ceiling"] = c
    c.setdefault("pushed", 0)
    c.setdefault("coalesced_sent", False)
    return c


# ── Public API ───────────────────────────────────────────────────────────────
def push_critical(
    event_key: str,
    severity: str,
    title: str,
    body: str = "",
    *,
    held_protocol: bool = False,
    resolved: bool = False,
    data_dir: Optional[str | Path] = None,
    now: Optional[datetime] = None,
    daily_ceiling: int = DEFAULT_DAILY_CEILING,
    send: bool = True,
    dedup_key: Optional[str] = None,
) -> bool:
    """Emit a Tier-1 push IFF it passes the policy gate. Returns ``sent?``.

    Parameters
    ----------
    event_key : closed whitelist key (see ``TIER1_WHITELIST``). Off-list ⇒ demote
        to the digest queue, never push.
    severity  : "CRITICAL"/"WARNING"/… — display only (icon selection).
    title, body : message content (already HTML-safe; callers escape dynamic data).
    held_protocol : for peg/red-flag keys, whether the protocol is in
        current_positions. Off-held ⇒ demote to digest.
    resolved : push the ``bad → ok`` "RESOLVED" transition instead of the entry.
    data_dir : override the data dir (tests). Default <repo>/data.
    now      : injectable UTC time (determinism / tests).
    daily_ceiling : hard cap on Tier-1 pushes per UTC day.
    send     : when False, run the full gate but do not hit the transport (tests).
    dedup_key : optional STABLE fingerprint of the concrete incident (e.g. the
        sorted labels of the agents that are down). While the bad state persists
        with the SAME fingerprint the event is silent (dedup); a DIFFERENT
        fingerprint is a new distinct incident and pushes. ``None`` keeps the
        legacy class-level edge-trigger.

    Never raises. Fail-closed: an unwhitelisted / off-held event is demoted.
    """
    try:
        return _push_critical_impl(
            event_key,
            severity,
            title,
            body,
            held_protocol=held_protocol,
            resolved=resolved,
            data_dir=Path(data_dir) if data_dir is not None else None,
            now=now,
            daily_ceiling=daily_ceiling,
            send=send,
            dedup_key=dedup_key,
        )
    except Exception as exc:  # noqa: BLE001 — the push authority must never crash a monitor
        log.warning("push_policy: push_critical failed for %r: %s", event_key, exc)
        return False


def _push_critical_impl(
    event_key: str,
    severity: str,
    title: str,
    body: str,
    *,
    held_protocol: bool,
    resolved: bool,
    data_dir: Optional[Path],
    now: Optional[datetime],
    daily_ceiling: int,
    send: bool,
    dedup_key: Optional[str] = None,
) -> bool:
    tg_dir = _tg_dir(data_dir)
    today = _today(now)
    ts = _now_iso(now)

    # ── Gate 1: closed whitelist ─────────────────────────────────────────────
    if event_key not in TIER1_WHITELIST:
        _enqueue_digest(
            tg_dir,
            {
                "ts": ts,
                "event_key": event_key,
                "severity": severity,
                "title": title,
                "body": body,
                "reason": "not_whitelisted",
            },
        )
        log.info("push_policy: %r not whitelisted → digest", event_key)
        return False

    # ── Gate 3 (early): held-protocol scoping ────────────────────────────────
    # Demote BEFORE mutating edge-state so an advisory flap never primes the
    # edge-trigger (it must never suppress a future genuine held-protocol push).
    if event_key in HELD_SCOPED_KEYS and not held_protocol and not resolved:
        _enqueue_digest(
            tg_dir,
            {
                "ts": ts,
                "event_key": event_key,
                "severity": severity,
                "title": title,
                "body": body,
                "reason": "not_held_protocol",
            },
        )
        log.info("push_policy: %r not on held protocol → digest", event_key)
        return False

    state = _load_state(tg_dir)
    events = state["events"]
    prev = events.get(event_key) or {}
    prev_state = prev.get("state")

    # ── One-shot path (leads etc.) — bypass edge-trigger, keep the ceiling ────
    # Each occurrence is a distinct real event; we must NOT silence the 2nd one.
    # Push immediately if under the daily ceiling; never write a persistent bad-state.
    if event_key in ONESHOT_KEYS and not resolved:
        ceil = _ceiling_for_today(state, today)
        if int(ceil["pushed"]) >= daily_ceiling:
            # Over the ceiling: coalesce once, then demote further ones to the digest.
            if not ceil["coalesced_sent"]:
                coalesced = (
                    f"⚠️ <b>Ещё события — их пока не показываю</b>\n\n"
                    f"Достигнут дневной лимит уведомлений ({daily_ceiling}). Остальные "
                    f"события копятся в очереди — открой /alerts, чтобы посмотреть."
                    f"\n\n<i>{ts}</i>"
                )
                if send:
                    _send(coalesced)
                ceil["coalesced_sent"] = True
            else:
                _enqueue_digest(
                    tg_dir,
                    {"ts": ts, "event_key": event_key, "severity": severity,
                     "title": title, "body": body, "reason": "ceiling_exceeded"},
                )
            _save_state(tg_dir, state)
            log.info("push_policy: one-shot %r over ceiling → coalesced/demoted", event_key)
            return False
        sent = _send(_format_message(severity, title, body)) if send else True
        if sent:
            ceil["pushed"] = int(ceil["pushed"]) + 1
        # record last_ts only — NO persistent bad-state (so the next lead pushes too)
        events[event_key] = {"state": _STATE_OK, "last_ts": ts, "oneshot": True}
        _save_state(tg_dir, state)
        log.info("push_policy: one-shot %r pushed (sent=%s, ceiling=%d/%d)",
                 event_key, sent, ceil["pushed"], daily_ceiling)
        return bool(sent)

    # ── Gate 2: edge-trigger ─────────────────────────────────────────────────
    if resolved:
        # bad → ok: emit ONE "RESOLVED", only if we were actually in a bad state.
        if prev_state != _STATE_BAD:
            log.info("push_policy: %r resolve with no prior bad state → silent", event_key)
            # Normalize to ok without sending.
            events[event_key] = {"state": _STATE_OK, "last_ts": ts}
            _save_state(tg_dir, state)
            return False
        sent = _send(_format_message(severity, title, body, resolved=True)) if send else True
        events[event_key] = {"state": _STATE_OK, "last_ts": ts, "resolved_sent": bool(sent)}
        _save_state(tg_dir, state)
        log.info("push_policy: %r RESOLVED (sent=%s)", event_key, sent)
        return bool(sent)

    # Entry / persistence path.
    if prev_state == _STATE_BAD:
        # Silence ONLY the genuine persistence case: the SAME incident
        # (unchanged fingerprint) whose entry the owner has actually received.
        #   * A different fingerprint = a NEW distinct incident hiding behind a
        #     shared event_key (e.g. a different agent down) → falls through to
        #     the entry path and pushes.
        #   * entry_pushed False = the recorded entry was never delivered
        #     (transport failure / ceiling demote) → falls through and retries
        #     until delivered ONCE (still ceiling-capped). Booking "bad" without
        #     delivery used to swallow the alert permanently.
        same_incident = prev.get("fingerprint") == dedup_key
        entry_delivered = bool(prev.get("entry_pushed", True))
        if same_incident and entry_delivered:
            # Condition persists → SILENT (the re-fire fix). Refresh last_ts only.
            prev["last_ts"] = ts
            events[event_key] = prev
            _save_state(tg_dir, state)
            log.info("push_policy: %r still bad → silent (edge-trigger)", event_key)
            return False
        log.info(
            "push_policy: %r bad but %s → entry path",
            event_key,
            "new incident (fingerprint changed)" if not same_incident
            else "entry never delivered (retry)",
        )

    # ── Gate 4: daily ceiling ────────────────────────────────────────────────
    ceil = _ceiling_for_today(state, today)
    if ceil["pushed"] >= daily_ceiling:
        # Mark the new bad state so the eventual RESOLVED still fires, but do not
        # push it individually — coalesce / demote. entry_pushed=False means the
        # persistence path will RETRY delivery once the ceiling frees up.
        events[event_key] = {"state": _STATE_BAD, "last_ts": ts,
                             "entry_pushed": False, "fingerprint": dedup_key}
        if not ceil["coalesced_sent"]:
            coalesced = (
                f"⚠️ <b>Ещё критические события — их пока не показываю</b>\n\n"
                f"Достигнут дневной лимит уведомлений ({daily_ceiling}). Остальные "
                f"критические события копятся в очереди — открой /alerts, чтобы "
                f"посмотреть.\n\n<i>{ts}</i>"
            )
            if send:
                _send(coalesced)
            ceil["coalesced_sent"] = True
        else:
            _enqueue_digest(
                tg_dir,
                {
                    "ts": ts,
                    "event_key": event_key,
                    "severity": severity,
                    "title": title,
                    "body": body,
                    "reason": "ceiling_exceeded",
                },
            )
        _save_state(tg_dir, state)
        log.info("push_policy: %r over ceiling → coalesced/demoted", event_key)
        return False

    # ── Push the entry transition ────────────────────────────────────────────
    sent = _send(_format_message(severity, title, body)) if send else True
    events[event_key] = {"state": _STATE_BAD, "last_ts": ts,
                         "entry_pushed": bool(sent), "fingerprint": dedup_key}
    if sent:
        ceil["pushed"] = int(ceil["pushed"]) + 1
    _save_state(tg_dir, state)
    log.info("push_policy: %r ENTRY pushed (sent=%s, ceiling=%d/%d)",
             event_key, sent, ceil["pushed"], daily_ceiling)
    return bool(sent)


def resolve(
    event_key: str,
    title: str,
    body: str = "",
    *,
    data_dir: Optional[str | Path] = None,
    now: Optional[datetime] = None,
    send: bool = True,
) -> bool:
    """Convenience: emit the one ``bad → ok`` RESOLVED push for ``event_key``."""
    return push_critical(
        event_key,
        "OK",
        title,
        body,
        resolved=True,
        data_dir=data_dir,
        now=now,
        send=send,
    )


def current_state(
    event_key: str,
    *,
    data_dir: Optional[str | Path] = None,
) -> Optional[str]:
    """Return the recorded edge-state for ``event_key`` ("bad"/"ok"/None)."""
    tg_dir = _tg_dir(Path(data_dir) if data_dir is not None else None)
    state = _load_state(tg_dir)
    rec = state["events"].get(event_key) or {}
    return rec.get("state")


def current_record(
    event_key: str,
    *,
    data_dir: Optional[str | Path] = None,
) -> dict:
    """Return a COPY of the recorded edge-record for ``event_key`` ({} if none).

    Read-only companion to ``current_state`` for a caller that needs the
    incident details — e.g. self_heal (owner decision own-28) reading the
    ``fingerprint`` of the pending ``core_agent_down`` incident so its
    "✅ восстановлено" push can NAME what was down. Never raises; the copy
    means a caller mutating the result cannot corrupt the edge state.
    """
    tg_dir = _tg_dir(Path(data_dir) if data_dir is not None else None)
    state = _load_state(tg_dir)
    rec = state["events"].get(event_key)
    return dict(rec) if isinstance(rec, dict) else {}


def drain_digest_queue(
    *,
    data_dir: Optional[str | Path] = None,
    clear: bool = True,
) -> list[dict]:
    """Return (and optionally clear) all digest-queued items.

    The daily digest builder calls this to fold demoted events into the one
    daily message. Atomic clear so a concurrent enqueue is not lost on the next
    cycle (worst case: re-queued, never silently dropped). Never raises.
    """
    tg_dir = _tg_dir(Path(data_dir) if data_dir is not None else None)
    try:
        doc = atomic_load(str(tg_dir / DIGEST_QUEUE_FILENAME), default={})
        if not isinstance(doc, dict):
            doc = {}
        items = doc.get("items")
        if not isinstance(items, list):
            items = []
        if clear and items:
            atomic_save(
                {
                    "schema_version": 1,
                    "source": "push_policy",
                    "updated_at": _now_iso(),
                    "count": 0,
                    "items": [],
                },
                str(tg_dir / DIGEST_QUEUE_FILENAME),
            )
        return list(items)
    except Exception:  # noqa: BLE001
        log.warning("push_policy: drain_digest_queue failed", exc_info=True)
        return []
