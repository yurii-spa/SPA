"""Shared intent classifier — the ONE safety authority for Owner Remote (web server-side + Telegram).

Zones: GREEN (execute now: navigate/query/why/draft-idea), YELLOW (needs Owner confirm: task/decision),
RED (NEVER execute: money/sign/live/risk/custody). RED is checked FIRST so it wins over any other match.

Mirrors studio_shell/surfaces.js::classifyIntent verbatim in behaviour; a parity test locks them.
NOTE: no ASCII `\b` around Cyrillic (Python \b is unicode-aware but JS \b is ASCII-only — to keep the two
runtimes identical we avoid word-boundaries next to Cyrillic and match substrings; for RED that also means
over-matching toward BLOCK, which is the safe direction).
"""
from __future__ import annotations

import re

ZONES = ("GREEN", "YELLOW", "RED", "NONE")

_RED = re.compile(
    r"(перевед|переведи|перевес|перевод|перечисл|продай|продать|продаж|купи|купить|покуп|выведи|вывести|вывод"
    r"|сними|снять|подпиш|подпис|включи\s*(live|исполнен|реальн|торг)|перейти\s*на\s*live|запусти\s*исполнен"
    r"|(измени|поменяй|подними|снизь|поставь)\s*(риск|ставк|порог|лимит|политик|risk|rate|limit|policy)"
    r"|kill.?switch|стоп-?кран|отключи\s*(стоп|кран|защит)|move\s*(capital|funds|money)|transfer|sell|buy\b"
    r"|withdraw|deposit|\bsign\b|enable\s*(live|execution|real|trading)|go\s*live"
    r"|change\s*(the\s*)?(rate|risk|policy|limit)|disable\s*(stop|kill)|custody|private\s*key)", re.I)
_YELLOW_TASK = re.compile(
    r"(созда(й|ть)\s*задач|нов(ая|ую)\s*задач|поставь\s*задач|задача\b|задачу\b|напомни|поручи"
    r"|create\s*(a\s*)?task|new\s*task|\btodo\b|remind|dispatch|отправь\s*на\s*выполнен)", re.I)
_YELLOW_DEC = re.compile(
    r"(запиши\s*решени|зафиксируй\s*решени|прими\s*решени|record\s*(a\s*)?decision|log\s*decision|decision:)", re.I)
_GREEN_IDEA = re.compile(r"(иде(я|ю|и)|запиши\s*иде|заметк|запиши\s*заметк|note|\bidea\b|черновик|capture)", re.I)
_GREEN_WHY = re.compile(r"(почему|\bwhy\b)", re.I)
_QUERY = re.compile(r"(сколько|какой|каков|что|какая|какие|status|how\s*much|what|show|state)", re.I)
_NAV = [
    (re.compile(r"(обзор|главн|overview|home|dashboard)", re.I), "home"),
    (re.compile(r"(капитал|портфел|деньг|баланс|позици|capital|holdings|portfolio|\bmoney\b|balance)", re.I), "capital"),
    (re.compile(r"(стратег|strateg)", re.I), "strategies"),
    (re.compile(r"(систем|флот|агент|system|fleet|agents|health)", re.I), "system"),
    (re.compile(r"(вселенн|граф|карт|universe|graph|\bmap\b)", re.I), "universe"),
    (re.compile(r"(решени|decision)", re.I), "decisions"),
    (re.compile(r"(почему|\bwhy\b|трасс|trace)", re.I), "why"),
]


def classify(text: str) -> dict:
    """Return {zone, intent, normalized, view?}. RED first (safety), then YELLOW, then GREEN."""
    t = (text or "").strip()
    if not t:
        return {"zone": "NONE", "intent": "empty", "normalized": ""}
    if _RED.search(t):
        return {"zone": "RED", "intent": "financial/execution", "normalized": t}
    if _YELLOW_TASK.search(t):
        return {"zone": "YELLOW", "intent": "create_task", "normalized": t}
    if _YELLOW_DEC.search(t):
        return {"zone": "YELLOW", "intent": "record_decision", "normalized": t}
    if _GREEN_WHY.search(t):
        return {"zone": "GREEN", "intent": "why", "normalized": t, "view": "why"}
    nav = next((v for rx, v in _NAV if rx.search(t)), None)
    if nav:
        q = bool(_QUERY.search(t))
        return {"zone": "GREEN", "intent": "query" if q else "navigate", "normalized": t, "view": nav}
    if _GREEN_IDEA.search(t):
        return {"zone": "GREEN", "intent": "capture_idea", "normalized": t}
    return {"zone": "GREEN", "intent": "query", "normalized": t, "view": None}


def is_red(text: str) -> bool:
    """Fast RED check for defence-in-depth on write paths."""
    return bool(_RED.search(text or ""))
