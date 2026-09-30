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
    r"|(измени|поменяй|подними|подня|снизь|сниз|поставь|увелич|уменьш|повыс|пониз|increase|raise|lower|decrease)[а-яёa-z]*\s*(the\s*)?(риск|ставк|порог|лимит|политик|risk|rate|limit|policy)"
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


# ── Intent routing (2026-09-30) ────────────────────────────────────────────────────────────────
# `classify()` answers ONE question: how DANGEROUS is this text (zone). It never answered «what does
# the Owner WANT» — so every question with no known topic fell to GREEN/query, and the Telegram seam
# turned it into «Как задачу / Как идею» (live defect 30.09: «Скажи, пожалуйста, что сейчас нужно от
# меня?» offered to be RECORDED). `route()` answers the second question on top of the first, and keeps
# them apart: a QUESTION about a risky action is explained; an ORDER to do it stays RED.
INTENTS = ("READ_QUESTION", "OWNER_NEEDS", "SYSTEM_STATUS", "PRODUCT_QUERY", "TASK_CAPTURE",
           "IDEA_CAPTURE", "DECISION_CAPTURE", "ACTION_COMMAND", "AMBIGUOUS")

_POLITE = re.compile(r"^(?:(?:скажи(?:те)?|подскажи(?:те)?|расскажи(?:те)?|пожалуйста|слушай|"
                     r"а|ну|так|привет|бридж|bridge|please|tell me|hey)[\s,!.:—-]+)+", re.I)
_QWORD = re.compile(r"^(что|как|какие|какой|какая|каков|сколько|почему|зачем|когда|где|кто|есть ли|"
                    r"можно ли|нужно ли|будет ли|что будет|что если|what|how|why|when|where|which|is|are|can|do|does)\b", re.I)
_SHOW = re.compile(r"^(покажи|показать|дай|выведи\s+(отч|спис|статус)|открой|отчёт|отчет|сводк|статус|report|show)", re.I)
_TOPIC_NEEDS = re.compile(r"(нужно\s+от\s+меня|от\s+меня\s+нужно|нужн[оа]?\s+мне|мне\s+(нужно\s+)?(решить|сделать|ответить)|"
                          r"жд[её]т\s+меня|жду[тт]?\s+меня|на\s+мне|мои\s+решени|решени[яй]\s+(владельца|от\s+меня)|"
                          r"моего\s+решения|нужно\s+от\s+юрия|needs?\s+(from\s+)?me|waiting\s+for\s+me)", re.I)
_TOPIC_BROKEN = re.compile(r"(слома|не\s+работа|проблем|трево|упал|авари|ошибк|broken|failing|alert)", re.I)
_TOPIC_DONE = re.compile(r"(сделан|сделали|сделал|готово|завершен|закрыт|выполнен|done|completed)", re.I)
_TOPIC_SYSTEM = re.compile(r"(работает|систем|агент|флот|служб|здоров|статус|релиз|worker|работник|system|fleet|health)", re.I)
_TOPIC_PRODUCT = re.compile(r"(капитал|портфел|позици|стратег|доходн|apy|трек|go.?live|пул|протокол|aave|morpho|"
                            r"pendle|sky|euler|earn\s*defi|spa\b|nav|просадк|portfolio|strateg|yield)", re.I)
_IDEA = re.compile(r"(у\s+меня\s+(есть\s+)?иде|иде[яю]\s*[:—-]|запиши\s+иде|добавь\s+иде|новая\s+иде|есть\s+иде|"
                   r"заметк|\bidea\b)", re.I)
_TASK = re.compile(r"(созда(й|ть)\s*задач|добавь\s*задач|нов(ая|ую)\s*задач|поставь\s*задач|задача\s*[:—-]|"
                   r"напомни|поручи|create\s*(a\s*)?task|add\s*(a\s*)?task|new\s*task|\btodo\b|remind)", re.I)
_DECISION = re.compile(r"(запиши\s*решени|зафиксируй\s*решени|прими\s*решени|решение\s*[:—-]|record\s*(a\s*)?decision|"
                       r"log\s*decision|decision:)", re.I)
_IMPERATIVE = re.compile(r"^(запусти|останови|перезапусти|выключи|включи|удали|сотри|отмени|откати|задеплой|"
                         r"опубликуй|отправь|сделай|почини|исправь|обнови|restart|stop|start|delete|deploy|publish|run)", re.I)


_INFINITIVE = re.compile(r"[а-яё]{2,}(ть|ться|чь)(?![а-яё])", re.I)


def normalize_for_intent(text: str) -> str:
    t = " ".join((text or "").strip().split())
    return _POLITE.sub("", t).strip()


def is_question(text: str) -> bool:
    t = normalize_for_intent(text)
    return t.endswith("?") or bool(_QWORD.match(t))


def route(text: str) -> dict:
    """{intent, zone, section?, confidence} — ONE router for typed text and Whisper transcripts alike.

    `zone` is `classify()`'s risk verdict and is never softened; `intent` is what the Owner wants.
    Capture intents are ONLY returned for explicit capture wording; a question is never a capture."""
    zone = classify(text)["zone"]
    t = normalize_for_intent(text)
    if not t:
        return {"intent": "AMBIGUOUS", "zone": "NONE", "confidence": "low"}
    q = is_question(text)
    if zone == "RED":
        if q:   # asking ABOUT a sensitive action: explain, never act
            return {"intent": "READ_QUESTION", "zone": "RED", "topic": "sensitive", "confidence": "high"}
        return {"intent": "ACTION_COMMAND", "zone": "RED", "confidence": "high"}
    if not q:
        if _DECISION.search(t):
            return {"intent": "DECISION_CAPTURE", "zone": zone, "confidence": "high"}
        if _TASK.search(t):
            return {"intent": "TASK_CAPTURE", "zone": zone, "confidence": "high"}
        if _IDEA.search(t):
            return {"intent": "IDEA_CAPTURE", "zone": zone, "confidence": "high"}
    readish = q or bool(_SHOW.match(t))
    # A short STATEMENT naming only a topic («портфель», «статус системы») is a read; one carrying a
    # verb («проверить Morpho», «потом посмотреть») is an unclear instruction — ask, don't guess.
    verbish = bool(_INFINITIVE.search(t)) or bool(_IMPERATIVE.match(t))
    if readish or (len(t.split()) <= 6 and not verbish):
        if _TOPIC_NEEDS.search(t):
            return {"intent": "OWNER_NEEDS", "zone": zone, "section": "owner", "confidence": "high"}
        if _TOPIC_BROKEN.search(t):
            return {"intent": "SYSTEM_STATUS", "zone": zone, "section": "alerts", "confidence": "high"}
        if _TOPIC_DONE.search(t):
            return {"intent": "READ_QUESTION", "zone": zone, "section": "work", "confidence": "high"}
        if _TOPIC_PRODUCT.search(t):
            return {"intent": "PRODUCT_QUERY", "zone": zone, "section": "product", "confidence": "high"}
        if _TOPIC_SYSTEM.search(t):
            return {"intent": "SYSTEM_STATUS", "zone": zone, "section": "system", "confidence": "high"}
    if readish:
        return {"intent": "READ_QUESTION", "zone": zone, "section": "summary", "confidence": "medium"}
    if _IMPERATIVE.match(t):
        return {"intent": "ACTION_COMMAND", "zone": zone, "confidence": "high"}
    return {"intent": "AMBIGUOUS", "zone": zone, "confidence": "low"}
