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

#: `answers.route_green`'s fallback when no question was recognised (it is a hint, not an answer).
GENERIC_ANSWER_PREFIX = "Отвечаю по данным read model."


def cmd_plan(text: str, source: str, message_id) -> dict:
    p = gateway.plan(text, source=source, message_id=message_id)
    action = p["action"]
    out = {"ok": True, "action": action, "zone": p["zone"], "intent": p["intent"], "text": p["text"]}
    if action in ("noop", "block"):
        return out
    if action == "answer" and not (p["text"] or "").startswith(GENERIC_ANSWER_PREFIX):
        return out          # a GREEN question with a real answer: no draft, nothing pending
    if action == "answer":
        # no recognised question and no intake verb — the Owner decides task or idea
        out["action"] = "capture"
    kind = {"confirm_task": "task", "idea": "idea", "decision_draft": "decision"}.get(action, "unclassified")
    token = gateway.token_for(source, message_id if message_id is not None else "manual")
    title = (p.get("normalized") or text).strip()[:120]
    gateway.register_pending(token, title=title, body=text.strip(), source=source, kind=kind)
    out.update({"token": token, "kind": kind, "title": title})
    return out


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
