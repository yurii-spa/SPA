"""История-чек — обязательный шаг перед созданием карточки из задания/идеи.

Owner-directive 2026-07-16 (ORCHESTRATOR_PROTOCOL §6.6 / Шаг 1a): прежде чем плодить
карточку, поискать по ВСЕЙ памяти — карточки во всех статусах, docs/ideas, ADR-решения,
STATE, журнал — не делали ли это уже, не делаем ли сейчас, не отказались ли осознанно.

Кандидаты из памяти собираются ДЕТЕРМИНИРОВАННО (чтение файлов), а семантический вердикт
выносит локальный `claude -p` из ПЕРЕДАННОГО контекста (никаких инструментов → без
skip-permissions; это reporting/классификация, НЕ risk-путь). Fail-safe: любая ошибка →
verdict NEW (не блокируем приём задания; лучше лишняя карточка, чем потерянное задание).

Вердикты:
  DONE        — уже сделано (ответ со ссылкой на результат; дубль НЕ создавать)
  IN_PROGRESS — уже в работе (ответ со ссылкой на карточку; дубль НЕ создавать)
  REJECTED    — осознанно решили не делать (ответ с причиной + «пересмотреть?»; дубль НЕ создавать)
  PARTIAL     — похоже на что-то (карточку создать, но пометить «похоже на …, проверь»)
  NEW         — совпадений нет (обычная классификация)

**Точный повтор ищется ДЕТЕРМИНИРОВАННО и ДО судьи (цикл #446).** Один класс дубля не
требует суждения вовсе — тот же текст, слово в слово, уже становился вопросом владельцу.
Судья его не видел ПО ПОСТРОЕНИЮ: в контекст едут `id [статус] (тип): заголовок`, а
дословный исходный текст лежит в ТЕЛЕ карточки-уточнения, и тела в контексте нет. К этому
добавлялся fail-safe (`claude` недоступен ⇒ `NEW`), указывающий в ту же сторону: повтор
уезжал владельцу как новый вопрос при ЛЮБОМ исходе.

Замер 31.08: из трёх карточек-уточнений, рождённых за вечер, ДВЕ несли байт-в-байт тексты
от 12.08 (`…adr-070-11-chestny` и `…adr-070-13-trevogu`). По одной из них владелец нажал
«Принято — беру в работу» — на работе, доставленной 07.08 (ADR-070 п.11, циклы #153/#156).
Повтор не просто шумел: он потратил решение владельца на законченное.

**Границы намеренно узкие.** Найденный повтор НЕ подавляет карточку — он её ПОМЕЧАЕТ
(`PARTIAL`): владелец может присылать то же осознанно, и «потерянное задание» дороже
лишней карточки. И проверка молчит, если прежний вопрос ВСЁ ЕЩЁ ОТКРЫТ: этот случай уже
закрыт идемпотентностью `create_card._open_twin`, а пометка изменила бы тело карточки и
тем СЛОМАЛА бы сверку тел, на которой та идемпотентность стоит.
"""
from __future__ import annotations

import logging
import os
import subprocess
from pathlib import Path

log = logging.getLogger(__name__)

_REPO = Path(__file__).resolve().parents[2]
_CLAUDE = os.environ.get("SPA_CLAUDE_BIN") or "/Users/yuriikulieshov/.local/bin/claude"

_VALID = {"DONE", "IN_PROGRESS", "REJECTED", "PARTIAL", "NEW"}


#: Маркер, которым интейк записывает ДОСЛОВНЫЙ исходный текст в тело карточки-уточнения.
#: Объявлен ЗДЕСЬ и импортируется интейком (ADR-154: контракт объявляют, а не выводят) —
#: иначе формат жил бы в двух местах и разошёлся бы молча.
SOURCE_TEXT_OPEN = "Текст: «"
SOURCE_TEXT_CLOSE = "»"

#: Строки, которыми интейк начинает СЛЕДУЮЩИЙ раздел тела. До первой из них (и до
#: закрывающей кавычки перед ней) идёт исходный текст — сам он может содержать «»,
#: поэтому границу задаёт раздел, а не первая попавшаяся кавычка.
_SOURCE_TEXT_END_MARKERS = (
    "\n\n> ⚠️ Проверка истории:",
    "\n\n## Что от тебя нужно",
)


def recorded_source_text(body: str) -> str | None:
    """Дословный текст владельца, записанный интейком в тело карточки-уточнения.

    ``None`` — карточка так текст не записывала (не наша форма). Никогда не бросает:
    это читатель истории, и его сбой не имеет права влиять на приём задания.
    """
    try:
        head = (body or "").split(SOURCE_TEXT_OPEN, 1)
        if len(head) != 2:
            return None
        rest = head[1]
        cut = len(rest)
        for marker in _SOURCE_TEXT_END_MARKERS:
            pos = rest.find(marker)
            if pos != -1:
                cut = min(cut, pos)
        text = rest[:cut].rstrip()
        if text.endswith(SOURCE_TEXT_CLOSE):
            text = text[: -len(SOURCE_TEXT_CLOSE)]
        text = text.strip()
        return text or None
    except Exception:  # noqa: BLE001
        return None


def exact_prior_ask(text: str, *, tracker_dir=None) -> dict | None:
    """Этот ТОЧНЫЙ текст уже становился вопросом владельцу — и тот вопрос ЗАКРЫТ?

    Возвращает ``{'card_id', 'status', 'created'}`` либо ``None``. Детерминированно,
    stdlib, без сети и без LLM — поэтому работает и тогда, когда судья недоступен
    (а именно в этом состоянии повтор и уезжал владельцу как новый вопрос).

    **Открытый прежний вопрос сюда НЕ попадает** — намеренно, см. модульный docstring:
    его держит идемпотентность ``create_card``, и трогать её отсюда нельзя.

    Никогда не бросает: в сомнении ``None`` (карточка создаётся как сегодня).
    """
    wanted = (text or "").strip()
    if not wanted:
        return None
    try:
        from spa_core.owner_queue.queue import _OPEN_STATUSES, list_cards

        for card in list_cards(tracker_type="owner-decision", tracker_dir=tracker_dir):
            if (card.fields or {}).get("source") != "intake":
                continue
            if (card.status or "") in _OPEN_STATUSES:
                continue  # живой вопрос — не наш случай (идемпотентность create_card)
            if recorded_source_text(card.body) != wanted:
                continue
            return {
                "card_id": card.id,
                "status": card.status or "",
                "created": str((card.fields or {}).get("created", "")),
            }
    except Exception as exc:  # noqa: BLE001
        log.warning("exact_prior_ask failed: %s — считаю, что повтора нет", exc)
    return None


def _prior_ask_response(hit: dict) -> str:
    """Человеческий ответ владельцу о найденном точном повторе (по-русски, §2.4)."""
    when = f" от {hit['created']}" if hit.get("created") else ""
    return (f"Ровно этот текст уже становился вопросом к тебе — карточка "
            f"`{hit['card_id']}`{when}, статус `{hit['status']}`. "
            f"Проверь: это тот же вопрос (тогда смотри карточку) или ты поднимаешь его заново?")


def _build_history_context(max_chars: int = 11000) -> str:
    """Deterministically gather candidate memory: cards (all statuses), ideas, ADRs,
    recent STATE decisions, journal tail."""
    parts: list[str] = []

    # 1. All tracker cards — id/status/type/title (the primary dedup surface).
    try:
        from spa_core.owner_queue.queue import list_cards

        lines = [f"{c.id} [{c.status}] ({c.tracker_type}): {c.title}" for c in list_cards()]
        if lines:
            parts.append("=== КАРТОЧКИ (все статусы) ===\n" + "\n".join(lines))
    except Exception:
        pass

    # 2. Ideas.
    try:
        idir = _REPO / "docs" / "ideas"
        if idir.is_dir():
            ilines = []
            for f in sorted(idir.glob("*.md")):
                try:
                    head = f.read_text(encoding="utf-8", errors="replace").splitlines()
                    title = next((l.lstrip("# ").strip() for l in head if l.strip()), f.stem)
                    ilines.append(f"{f.name}: {title}")
                except OSError:
                    continue
            if ilines:
                parts.append("=== docs/ideas/ ===\n" + "\n".join(ilines))
    except Exception:
        pass

    # 3. ADR registry (settled + rejected decisions).
    try:
        idx = _REPO / "docs" / "decisions" / "INDEX.md"
        if idx.is_file():
            parts.append("=== ADR-реестр (docs/decisions/INDEX.md) ===\n"
                         + idx.read_text(encoding="utf-8", errors="replace")[:3500])
    except Exception:
        pass

    # 4. STATE recent decisions.
    try:
        st = _REPO / "docs" / "STATE.md"
        if st.is_file():
            parts.append("=== docs/STATE.md ===\n"
                         + st.read_text(encoding="utf-8", errors="replace")[:2500])
    except Exception:
        pass

    # 5. Journal tail (recently done work).
    try:
        jdir = _REPO / "docs" / "journal"
        jfiles = sorted(jdir.glob("*.md")) if jdir.is_dir() else []
        if jfiles:
            parts.append("=== Журнал (хвост) ===\n"
                         + jfiles[-1].read_text(encoding="utf-8", errors="replace")[-2500:])
    except Exception:
        pass

    return "\n\n".join(parts)[:max_chars]


_PROMPT = """Ты — контролёр памяти проекта SPA. Владелец прислал НОВОЕ задание/идею. Твоя работа —
проверить по КОНТЕКСТУ ПАМЯТИ ниже, НЕ дубликат ли это: не сделали ли мы это уже, не делаем ли
сейчас, не отказались ли осознанно. Отвечай СТРОГО так:

Первая строка — РОВНО одно слово-вердикт:
  DONE         — в памяти есть чёткое свидетельство, что это УЖЕ СДЕЛАНО;
  IN_PROGRESS  — есть открытая карточка/работа ровно про это;
  REJECTED     — есть решение (ADR/STATE), что это осознанно НЕ делаем;
  PARTIAL      — похоже на что-то в памяти, но не точно то же (частичное/сомнительное совпадение);
  NEW          — в памяти совпадений нет.

Дальше (со второй строки) — короткий ЧЕЛОВЕЧЕСКИЙ ответ по-русски владельцу (2–4 строки), СТРОГО по
контексту, со ссылкой на конкретное свидетельство (id карточки / ADR / файл / строку журнала):
  - DONE → «Это уже сделано <когда/где>, вот результат: <ссылка>.»
  - IN_PROGRESS → «Уже в работе, вот карточка: <id>.»
  - REJECTED → «Мы решили это не делать (<ADR/решение>), причина: <…>. Хочешь пересмотреть решение?»
  - PARTIAL → «Похоже на <что-то> (<ссылка>), проверь — это то же или другое?»
  - NEW → одна строка «Совпадений в памяти нет.»
НЕ выдумывай ссылок: если точного свидетельства нет — это NEW или PARTIAL, не DONE/REJECTED.

=== НОВОЕ ЗАДАНИЕ/ИДЕЯ ВЛАДЕЛЬЦА ===
{msg}

=== КОНТЕКСТ ПАМЯТИ ===
{ctx}
"""


def history_check(text: str, *, timeout: int = 120) -> dict:
    """Return {'verdict': one of _VALID, 'response': str, 'raw': str}.

    Fail-safe: any error → verdict NEW (accept the item; never lose an owner task)."""
    text = (text or "").strip()
    if not text:
        return {"verdict": "NEW", "response": "", "raw": ""}

    # Точный повтор — ДО судьи и вместо него: доказательство здесь сильнее суждения
    # (тот же текст слово в слово), и оно доступно, когда судьи нет вовсе.
    prior = exact_prior_ask(text)
    if prior is not None:
        return {"verdict": "PARTIAL", "response": _prior_ask_response(prior),
                "raw": "", "prior_ask": prior}

    prompt = _PROMPT.format(msg=text[:4000], ctx=_build_history_context())
    env = dict(os.environ)
    env["PATH"] = "/Users/yuriikulieshov/.local/bin:/opt/homebrew/bin:/usr/local/bin:" + env.get("PATH", "")
    try:
        # No tools needed (judgement from provided context) → NO skip-permissions.
        proc = subprocess.run(
            [_CLAUDE, "-p", prompt],
            capture_output=True, text=True, timeout=timeout, env=env,
        )
    except Exception as exc:  # noqa: BLE001
        log.warning("history_check: claude call failed: %s", exc)
        return {"verdict": "NEW", "response": "", "raw": ""}
    if proc.returncode != 0:
        log.warning("history_check: claude exit %s: %s", proc.returncode, proc.stderr[-200:])
        return {"verdict": "NEW", "response": "", "raw": ""}
    out = (proc.stdout or "").strip()
    if not out:
        return {"verdict": "NEW", "response": "", "raw": ""}
    first, _, rest = out.partition("\n")
    verdict = first.strip().upper().split()[0] if first.strip() else "NEW"
    if verdict not in _VALID:
        # model didn't emit a clean verdict → treat as NEW (safe: accept the item)
        return {"verdict": "NEW", "response": "", "raw": out}
    return {"verdict": verdict, "response": rest.strip(), "raw": out}


def is_duplicate(verdict: str) -> bool:
    """True for verdicts that mean 'don't create a duplicate card'."""
    return verdict in {"DONE", "IN_PROGRESS", "REJECTED"}
