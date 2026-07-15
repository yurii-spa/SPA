"""Telegram Q&A router — бот ОТВЕЧАЕТ на вопросы, а не только принимает задачи.

Классифицирует свободный текст/голос владельца:
  - ВОПРОС о состоянии проекта → короткий человеческий ответ по-русски из
    docs/STATE.md + карточек + журнала;
  - ПОРУЧЕНИЕ/задача → маркер task (bot создаёт inbox-карточку, как раньше);
  - НЕПОНЯТНО → уточняющий вопрос.

Классификация/ответ делает локальный headless `claude -p` (LLM нужен для NL-ответа;
это НЕ risk/execution/monitoring, поэтому LLM тут допустим). Весь контекст передаётся
в промпте (модель отвечает из него). Fail-safe: любая ошибка → ("unclear", <просьба переформулировать>).
"""

from __future__ import annotations

import logging
import os
import subprocess
from pathlib import Path

log = logging.getLogger(__name__)

_REPO = Path(__file__).resolve().parents[2]
_CLAUDE = os.environ.get("SPA_CLAUDE_BIN") or "/Users/yuriikulieshov/.local/bin/claude"


def _build_context(max_chars: int = 6000) -> str:
    parts: list[str] = []
    try:
        parts.append("=== docs/STATE.md ===\n" + (_REPO / "docs" / "STATE.md").read_text(encoding="utf-8"))
    except Exception:
        pass
    try:
        from spa_core.owner_queue.queue import list_cards

        lines = [f"{c.id} [{c.status}] ({c.tracker_type}): {c.title}" for c in list_cards()]
        if lines:
            parts.append("=== Карточки (очередь) ===\n" + "\n".join(lines))
    except Exception:
        pass
    try:
        jdir = _REPO / "docs" / "journal"
        jfiles = sorted(jdir.glob("*.md")) if jdir.exists() else []
        if jfiles:
            txt = jfiles[-1].read_text(encoding="utf-8")
            parts.append("=== Журнал (последняя неделя, хвост) ===\n" + txt[-2500:])
    except Exception:
        pass
    ctx = "\n\n".join(parts)
    return ctx[:max_chars]


_PROMPT = """Ты — ассистент проекта SPA (DeFi yield-система). Владелец прислал сообщение через \
Telegram. Определи ТИП сообщения и ответь СТРОГО в одном из трёх форматов:

1) Если это ВОПРОС о состоянии проекта (что в работе, что меня ждёт, что нового, что решили по \
теме, статус, агенты и т.п.) → ПЕРВАЯ строка ровно `QUESTION`, дальше короткий человеческий ответ \
по-русски (2–6 строк) СТРОГО на основе КОНТЕКСТА ниже. Не выдумывай: если в контексте ответа нет — \
честно напиши, что в записях этого нет.

2) Если это ПОРУЧЕНИЕ или ЗАДАЧА (просьба что-то сделать/построить/починить) → верни РОВНО одну \
строку `TASK` (больше ничего).

3) Если НЕПОНЯТНО — вопрос это или задача, или неясен смысл → ПЕРВАЯ строка ровно `UNCLEAR`, \
вторая строка — короткий уточняющий вопрос по-русски.

=== СООБЩЕНИЕ ВЛАДЕЛЬЦА ===
{msg}

=== КОНТЕКСТ ПРОЕКТА ===
{ctx}
"""


def classify_and_answer(text: str, *, timeout: int = 120) -> tuple[str, str]:
    """Return (kind, response): kind ∈ {'question','task','unclear'}.

    'question' → response is the answer; 'unclear' → response is the clarifying
    question; 'task' → response is ''.
    """
    prompt = _PROMPT.format(msg=text.strip(), ctx=_build_context())
    env = dict(os.environ)
    env["PATH"] = "/Users/yuriikulieshov/.local/bin:/opt/homebrew/bin:/usr/local/bin:" + env.get("PATH", "")
    try:
        proc = subprocess.run(
            [_CLAUDE, "-p", prompt, "--dangerously-skip-permissions"],
            capture_output=True, text=True, timeout=timeout, env=env,
        )
    except Exception as exc:  # noqa: BLE001
        log.warning("ask_router: claude call failed: %s", exc)
        return ("unclear", "Не смог обработать сообщение. Переформулируй или пришли как /task <текст>.")
    if proc.returncode != 0:
        log.warning("ask_router: claude exit %s: %s", proc.returncode, proc.stderr[-200:])
        return ("unclear", "Не смог обработать сообщение. Переформулируй или пришли как /task <текст>.")
    out = (proc.stdout or "").strip()
    if not out:
        return ("unclear", "Пустой ответ. Переформулируй или пришли как /task <текст>.")

    first, _, rest = out.partition("\n")
    head = first.strip().upper()
    if head == "TASK":
        return ("task", "")
    if head == "UNCLEAR":
        q = rest.strip() or "Уточни, пожалуйста: это вопрос или задача?"
        return ("unclear", q)
    if head == "QUESTION":
        return ("question", rest.strip() or "(пустой ответ)")
    # модель не соблюла формат → отдаём весь текст как ответ на вопрос (лучше, чем потерять)
    return ("question", out)
