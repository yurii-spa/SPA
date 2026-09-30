"""Owner Remote CLI — the narrow process seam other surfaces (the Studio Bridge Telegram bot) call.

Why a CLI and not an import: the Bridge is a separate repository with its own release discipline.
It must not vendor or import SPA code, and SPA must stay the ONE owner of canonical intake
(`owner_queue.create_card` via `gateway.confirm_task`), of the accepted idea home (`docs/ideas`) and of
the GREEN/YELLOW/RED classifier. So the Bridge speaks JSON over a subprocess and renders the answer;
it never writes a card, an idea or a decision itself (ADR-493 lineage: Telegram is an interface, not a
second memory authority).

    plan       --text T --source S --message-id N   classify; register a pending draft; NO write
    confirm    --token K [--as task|idea]            the ONLY write — exactly once per token
    cancel     --token K
    transcribe --file F                              local offline whisper (same STT the SPA bot uses)

Every command prints ONE JSON object and exits 0 when it could answer (a refusal is an answer:
``{"ok": false, "error": ...}``) and 2 on bad usage. LLM FORBIDDEN; stdlib only.
"""
from __future__ import annotations

import argparse
import json
import sys

from spa_core.owner_remote import gateway



SENSITIVE_EXPLAIN = (
    "ℹ️ Это вопрос о чувствительном действии — отвечаю, ничего не меняя.\n"
    "Деньги, ставки, лимиты риска, стоп-кран и включение live из Telegram не меняются НИКОГДА. "
    "Пороги RiskPolicy v1.0 меняются только новым ADR с твоим решением; сейчас идёт бумажный трек, "
    "реальный капитал не задействован. Если хочешь это обсудить — скажи «запиши решение …» (черновик)."
)
ACTION_REFUSED = ("Действия из свободного текста я не выполняю. Если это поручение — скажи "
                  "«создай задачу …», и я предложу записать его после твоей кнопки.")
CLARIFY = "Не уверен, что ты имеешь в виду. Это вопрос или это нужно записать?"
_KIND = {"TASK_CAPTURE": "task", "IDEA_CAPTURE": "idea", "DECISION_CAPTURE": "decision"}


def cmd_plan(text: str, source: str, message_id) -> dict:
    """ONE router for text and Whisper transcripts (intent.route). Only a real capture intent (or the
    Owner's own choice after a clarification) registers a draft; a question is answered, never recorded."""
    from spa_core.owner_remote.intent import route
    r = route(text)
    out = {"ok": True, "intent": r["intent"], "zone": r["zone"], "confidence": r.get("confidence")}
    intent = r["intent"]
    if r["zone"] == "NONE":
        return {**out, "action": "noop", "text": "Пустое сообщение."}
    if intent == "ACTION_COMMAND":
        if r["zone"] == "RED":
            return {**out, "action": "block",
                    "text": gateway.plan(text, source=source, message_id=message_id)["text"]}
        return {**out, "action": "refuse_action", "text": ACTION_REFUSED}
    if r.get("topic") == "sensitive":
        return {**out, "action": "explain", "text": SENSITIVE_EXPLAIN}
    if r.get("section"):
        return {**out, "action": "report", "section": r["section"]}
    token = gateway.token_for(source, message_id if message_id is not None else "manual")
    title = " ".join(text.split())[:120]
    if intent in _KIND:
        gateway.register_pending(token, title=title, body=text.strip(), source=source, kind=_KIND[intent])
        return {**out, "action": "confirm", "kind": _KIND[intent], "token": token, "title": title}
    # AMBIGUOUS: one clarification; the Owner's button decides (question → report, or task / idea)
    gateway.register_pending(token, title=title, body=text.strip(), source=source, kind="unclassified")
    return {**out, "action": "clarify", "kind": "unclassified", "token": token, "title": title,
            "text": CLARIFY}


def cmd_transcribe(path: str) -> dict:
    from spa_core.telegram.inbox_intake import transcribe_voice
    text = transcribe_voice(path, timeout=240)
    if not text:
        return {"ok": False, "error": "stt_failed"}
    return {"ok": True, "text": text}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Owner Remote seam (JSON over stdout)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("plan")
    p.add_argument("--text", required=True)
    p.add_argument("--source", required=True)
    p.add_argument("--message-id")
    c = sub.add_parser("confirm")
    c.add_argument("--token", required=True)
    c.add_argument("--as", dest="as_kind", choices=("task", "idea"))
    x = sub.add_parser("cancel")
    x.add_argument("--token", required=True)
    t = sub.add_parser("transcribe")
    t.add_argument("--file", required=True)
    a = ap.parse_args(argv)
    try:
        if a.cmd == "plan":
            res = cmd_plan(a.text, a.source, a.message_id)
        elif a.cmd == "confirm":
            res = gateway.confirm(a.token, as_kind=a.as_kind)
        elif a.cmd == "cancel":
            res = gateway.cancel(a.token)
        else:
            res = cmd_transcribe(a.file)
    except Exception as exc:  # noqa: BLE001 — surfaced to the caller, never swallowed
        res = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
    print(json.dumps(res, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
