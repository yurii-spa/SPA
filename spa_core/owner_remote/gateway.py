"""Owner gateway — turns a text/voice message into a safe PLAN, and executes confirmed writes.

One classifier (spa_core.owner_remote.intent) gates every decision. RED never executes. YELLOW returns a
confirm plan; the canonical write happens only in confirm_task(), keyed by an idempotency token so a
Telegram retry / double-tap creates NO duplicate. GREEN answers come from deterministic read models.
Telegram is NOT a second memory authority — the only persistence is the existing canonical task intake
and the accepted docs/ideas home, plus a small pending/idempotency ledger (not canonical truth).
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path

from spa_core.owner_remote import answers
from spa_core.owner_remote.intent import classify

REPO = Path(__file__).resolve().parents[2]
PENDING = REPO / "data" / "tg_owner_pending.json"
IDEAS = REPO / "docs" / "ideas"
_SLUG = re.compile(r"[^a-z0-9а-яё]+", re.I)


def is_owner(chat_id, owner_chat_id) -> bool:
    """Fail-closed allow-list: serve only the configured owner (mirrors Router.is_owner)."""
    if not owner_chat_id:
        return False
    return str(chat_id) == str(owner_chat_id)


def _now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _load_pending() -> dict:
    try:
        return json.loads(PENDING.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _save_pending(d: dict) -> None:
    try:
        from spa_core.utils.atomic import atomic_save   # atomic_save(data, path): serialises itself
        atomic_save(d, str(PENDING))
    except Exception:
        tmp = PENDING.with_suffix(".tmp")
        tmp.write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")
        tmp.replace(PENDING)


def token_for(source: str, message_id) -> str:
    """Idempotency key: same source+message_id → same token → at most one canonical task."""
    return f"{source}:{message_id}"


def plan(text: str, *, source: str, message_id=None) -> dict:
    """Classify a message into a safe action plan. No side effects."""
    c = classify(text)
    zone, intent = c["zone"], c["intent"]
    base = {"zone": zone, "intent": intent, "transcript": text, "normalized": c.get("normalized", text),
            "source": source, "ts": _now()}
    if zone == "NONE":
        return {**base, "action": "noop", "text": "Пустое сообщение."}
    if zone == "RED":
        return {**base, "action": "block", "offer_idea": True,
                "text": ("⛔ ЗАБЛОКИРОВАНО — RED. Голос/чат НИКОГДА не двигает капитал, не подписывает, "
                         "не включает live, не меняет риск/лимиты. Ничего не создано и не исполнено.\n"
                         "Могу оформить это как ИДЕЮ-предложение (не исполнение).")}
    if zone == "YELLOW" and intent == "create_task":
        token = token_for(source, message_id if message_id is not None else "manual")
        title = c["normalized"][:120]
        return {**base, "action": "confirm_task", "token": token, "title": title,
                "text": (f"🟡 ЗАДАЧА (черновик) — подтвердить?\n«{title}»\n"
                         f"После подтверждения создам каноническую inbox-карточку (source={source}, "
                         f"status=new). Без подтверждения ничего не создаётся.")}
    if zone == "YELLOW" and intent == "record_decision":
        return {**base, "action": "decision_draft",
                "text": ("🟡 РЕШЕНИЕ → черновик PROPOSED (ADR-495). Запишу как предложение решения; "
                         "перевод в ACCEPTED (нумерованный ADR) — только по твоему подтверждению. "
                         "Каноническая запись решения теперь доступна как ЧЕРНОВИК.")}
    if zone == "GREEN" and intent == "capture_idea":
        return {**base, "action": "idea", "text": text}
    # GREEN navigate / query / why → deterministic read-model answer
    return {**base, "action": "answer", "text": answers.route_green(text, c.get("view"))}


#: What a confirmed draft becomes. "unclassified" = the Owner picks task/idea at confirm time.
KINDS = ("task", "idea", "decision", "unclassified")


def register_pending(token: str, *, title: str, body: str, source: str, kind: str = "task") -> None:
    if kind not in KINDS:
        raise ValueError(f"unknown draft kind {kind!r}")
    d = _load_pending()
    if token not in d:                       # never overwrite a decided token (idempotency)
        d[token] = {"title": title, "body": body, "source": source, "status": "pending", "ts": _now(),
                    "kind": kind}
        _save_pending(d)


def confirm(token: str, *, as_kind: str | None = None) -> dict:
    """Owner-confirmed write for ANY draft kind — exactly once per token (retry / double-tap safe).

    `as_kind` lets the Owner decide an "unclassified" draft (only task / idea). RED is re-checked on
    the stored text here as defence-in-depth: a draft can never become a write if its words ask to
    move money, sign, go live or change risk — whatever the plan said earlier.
    """
    d = _load_pending()
    rec = d.get(token)
    if not rec:
        return {"ok": False, "error": "no such pending draft"}
    if rec.get("status") == "done":
        return {"ok": True, "id": rec.get("card_id"), "kind": rec.get("kind", "task"), "idempotent": True}
    if rec.get("status") == "cancelled":
        return {"ok": False, "error": "cancelled"}
    from spa_core.owner_remote.intent import is_red
    if is_red(rec.get("body") or rec.get("title") or ""):
        return {"ok": False, "error": "red_blocked"}
    kind = rec.get("kind", "task")
    if as_kind is not None:
        if as_kind not in ("task", "idea") or kind not in ("unclassified", as_kind):
            return {"ok": False, "error": f"cannot confirm a {kind} draft as {as_kind}"}
        kind = as_kind
    if kind == "unclassified":
        return {"ok": False, "error": "choose task or idea"}
    if kind == "task":
        rec["kind"] = "task"; d[token] = rec; _save_pending(d)
        res = confirm_task(token)
        res["kind"] = "task"
        return res
    if kind == "idea":
        res = capture_idea(rec.get("body") or rec["title"], source=rec.get("source", "telegram"))
    else:
        res = record_decision_draft(rec.get("body") or rec["title"], source=rec.get("source", "telegram"))
    if not res.get("ok"):
        return {**res, "kind": kind}
    rec.update({"status": "done", "kind": kind, "done_ts": _now(),
                "card_id": res.get("id") or res.get("draft_id") or res.get("path")})
    d[token] = rec; _save_pending(d)
    return {**res, "ok": True, "kind": kind, "idempotent": False, "id": rec["card_id"]}


def confirm_task(token: str) -> dict:
    """Create the canonical task exactly once for a token. Idempotent on retry/double-tap."""
    d = _load_pending()
    rec = d.get(token)
    if not rec:
        return {"ok": False, "error": "no such pending draft"}
    if rec.get("status") == "done":
        return {"ok": True, "id": rec.get("card_id"), "idempotent": True}
    if rec.get("status") == "cancelled":
        return {"ok": False, "error": "cancelled"}
    from spa_core.telegram.inbox_intake import save_inbox_task
    path, title = save_inbox_task(rec["body"] or rec["title"], source=rec.get("source", "telegram"))
    rec["status"] = "done"; rec["card_id"] = str(path); rec["done_ts"] = _now()
    d[token] = rec; _save_pending(d)
    # Persist the relationship overlay at CREATION time (ADR-497): project + source are EXPLICIT here
    # (the gateway knows them for certain). Failure is SURFACED (LINKAGE_WRITE_FAILED), never swallowed;
    # the canonical task still succeeds.
    linkage = {"ok": True}
    try:
        from spa_core.studio_os.links import record_link
        linkage = record_link(Path(str(path)).stem, origin="EXPLICIT",
                              provenance="Owner Remote gateway at task creation",
                              project_id="earn-defi-product", source=rec.get("source", "telegram"),
                              created_at=_now())
    except Exception as exc:  # module import itself failed — still surfaced, task still ok
        linkage = {"ok": False, "error": "LINKAGE_WRITE_FAILED", "detail": str(exc)}
    result = {"ok": True, "id": str(path), "title": title, "idempotent": False,
              "canonical": "orchestrator_queue/inbox"}
    if not linkage.get("ok"):
        result["linkage"] = "LINKAGE_WRITE_FAILED"      # recoverable; task creation unaffected
        rec["linkage_error"] = linkage.get("error"); d[token] = rec; _save_pending(d)
    return result


def cancel(token: str) -> dict:
    d = _load_pending()
    rec = d.get(token) or {"status": "pending"}
    if rec.get("status") == "done":
        return {"ok": False, "error": "already created", "id": rec.get("card_id")}
    rec["status"] = "cancelled"; rec["ts"] = _now()
    d[token] = rec; _save_pending(d)
    return {"ok": True, "status": "cancelled"}


def record_decision_draft(text: str, *, project_id: str = "earn-defi-product",
                          source: str = "telegram", now_iso: str = "") -> dict:
    """Write a PROPOSED decision draft (ADR-495). Safe/non-accepted; ACCEPTED needs Owner accept_decision."""
    try:
        from spa_core.studio_os.decisions import propose_decision
        return propose_decision(project_id=project_id, problem=text[:120], decision=text,
                                rationale="captured via Owner Remote", source=source, now_iso=now_iso)
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": str(e)}


def capture_idea(text: str, *, source: str = "telegram") -> dict:
    """Write to the accepted owner idea home docs/ideas (agents don't act until #promote)."""
    if not IDEAS.exists():
        return {"ok": False, "error": "docs/ideas not present"}
    date = _now()[:10]
    slug = _SLUG.sub("-", (text or "").lower()).strip("-")[:48] or "idea"
    p = IDEAS / f"{date}-{slug}.md"
    n = 2
    while p.exists():
        p = IDEAS / f"{date}-{slug}-{n}.md"; n += 1
    p.write_text(f"# {text.strip()[:80]}\n\n> Захвачено через Owner Remote ({source}) {date}. "
                 f"Идея ≠ инструкция — агенты не действуют до `#promote`.\n\n{text.strip()}\n",
                 encoding="utf-8")
    return {"ok": True, "id": str(p.relative_to(REPO)), "canonical": "docs/ideas"}
