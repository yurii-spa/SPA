#!/usr/bin/env python3
"""subject.py — ОДНА общая функция темы ADR-285 для карточек владельца (C5, ADR-580).

До этого модуля тему карточки угадывали ДВАЖДЫ, двумя РАЗНЫМИ эвристиками, и они не
сходились:

* Mission Control (`spa_core.studio_os.mission_control.risk_class`) брал первое
  совпадение по словарю ключевых слов в title+body. Карточка «Закрыть три PR»
  получала «1 · real money», потому что в тексте встречается слово «ключ» (PAT не
  хватает прав — это PR-права, а не деньги).
* Director (`scripts/cartographer/owner_decisions.SUBJECT_HINTS`/`_subject_of`) берёт
  СВОЙ первый совпавший ключ из СВОЕГО словаря и для тех же карточек отвечает иначе:
  10 из 12 он называет дефектами очереди, Mission Control — нет.

Владелец видит «11 / 12 / 6» вопросов в разных окнах, и причина — не три разные
очереди, а два угадывателя, читающие тот же текст по-разному (A5_owner_control.md,
замер 2026-10-05).

Что здесь вместо угадывания
------------------------------------------------------------------------------
Тема — ОБЪЯВЛЕННОЕ поле `subject:` во frontmatter карточки, а не вывод из слов тела.
Нет поля, поле пустое или значение не из словаря ⇒ ``UNKNOWN`` — и это не мягкий
дефолт, а директива: карточка без объявленной темы — дефект очереди, который
разбирает агент, а не угаданный владельцем вопрос (ADR-285: «решай сам» — по
ПРЕДМЕТУ, а не по словам).

Четыре темы + UNKNOWN — ровно три предмета границы ADR-285 плюс «агент физически не
может сделать это сам» (CLAUDE.md, раздел «Граница „решай сам“ / „спроси меня“»):
создать репозиторий, переключить приложение владельца и т. п. — это не решение, а
действие, которое владелец обязан совершить сам.

Только stdlib. LLM_FORBIDDEN — это классификация очереди владельца, не суждение.
"""
# LLM_FORBIDDEN
from __future__ import annotations

from typing import Mapping, Optional

#: Предмет №1 ADR-285 — движение настоящих денег.
MONEY = "MONEY"
#: Предмет №2 — публичные числа доходности, нейминг тиров, юридические формулировки.
PUBLIC_NUMBERS_NAMING_LEGAL = "PUBLIC_NUMBERS_NAMING_LEGAL"
#: Предмет №3 — необратимые действия.
IRREVERSIBLE = "IRREVERSIBLE"
#: «Плюс» границы — агент физически не может сделать это сам (завести канал,
#: переключить своё приложение…). Это не решение владельца, а его ДЕЙСТВИЕ.
PHYSICAL_ACTION = "PHYSICAL_ACTION"
#: Тема не объявлена, или объявлена нераспознаваемым значением — дефект очереди.
UNKNOWN = "UNKNOWN"

SUBJECTS = (MONEY, PUBLIC_NUMBERS_NAMING_LEGAL, IRREVERSIBLE, PHYSICAL_ACTION, UNKNOWN)

#: Frontmatter пишут вручную (Telegram-интейк, оркестратор, владелец), поэтому у
#: каждой темы несколько принятых написаний — но это СЛОВАРЬ ОБЪЯВЛЕНИЙ, а не приметы
#: в прозе: значение обязано стоять в самом поле `subject:`, свободный текст карточки
#: никогда не читается.
_ALIASES: dict[str, str] = {
    "money": MONEY, "real_money": MONEY, "real money": MONEY, "1": MONEY,
    PUBLIC_NUMBERS_NAMING_LEGAL.lower(): PUBLIC_NUMBERS_NAMING_LEGAL,
    "public": PUBLIC_NUMBERS_NAMING_LEGAL, "public_numbers": PUBLIC_NUMBERS_NAMING_LEGAL,
    "legal": PUBLIC_NUMBERS_NAMING_LEGAL, "naming": PUBLIC_NUMBERS_NAMING_LEGAL, "2": PUBLIC_NUMBERS_NAMING_LEGAL,
    "irreversible": IRREVERSIBLE, "3": IRREVERSIBLE,
    "physical_action": PHYSICAL_ACTION, "physical": PHYSICAL_ACTION, "4": PHYSICAL_ACTION,
    "unknown": UNKNOWN, "none": UNKNOWN,
}


def subject_of(card_frontmatter: Optional[Mapping]) -> str:
    """ADR-285 тема ОДНОЙ карточки владельца — ОБЪЯВЛЕННАЯ, никогда не угаданная.

    ``card_frontmatter`` — разобранный frontmatter карточки (например,
    ``queue.load_card(...).fields``, или уже-сведённый плоский словарь, который
    строит ``cartographer.owner_decisions.from_tracker``). Читается ТОЛЬКО ключ
    ``subject``. Нет ключа, значение пустое или не из словаря ⇒ :data:`UNKNOWN` —
    единственный fail-CLOSED исход; карточка в этом состоянии дефект очереди,
    возвращаемый агенту, а не угаданный предмет владельца (CLAUDE.md, ADR-285).
    """
    if not isinstance(card_frontmatter, Mapping):
        return UNKNOWN
    raw = card_frontmatter.get("subject")
    if raw is None:
        return UNKNOWN
    key = str(raw).strip().strip("\"'").lower()
    if not key:
        return UNKNOWN
    return _ALIASES.get(key, UNKNOWN)


#: Подпись Mission Control (`decision_item["risk_class"]`) — та же строковая форма,
#: что печатал прежний `risk_class()`, чтобы все читатели поля (дашборд, тесты)
#: не заметили смену писателя. Меняется ТОЛЬКО то, откуда берётся тема.
_MC_LABEL = {
    MONEY: "1 · real money",
    PUBLIC_NUMBERS_NAMING_LEGAL: "2 · public numbers / naming / legal",
    IRREVERSIBLE: "3 · irreversible / external",
    PHYSICAL_ACTION: "4 · agent physically cannot do this",
    UNKNOWN: "UNKNOWN",
}


def mission_control_label(card_frontmatter: Optional[Mapping]) -> str:
    """Строка `risk_class` Mission Control — объявленная тема, ``UNKNOWN`` без неё."""
    return _MC_LABEL.get(subject_of(card_frontmatter), UNKNOWN)


#: Словарь Director (`scripts/cartographer/owner_decisions.SUBJECTS`) — коды '1'/'2'/'3'/
#: 'UNDECLARED'. `PHYSICAL_ACTION` сворачивается в '3' (необратимое/внешнее): у словаря
#: нет четвёртого кода, а обе темы объединяет «владелец обязан действовать сам».
#:
#: ``UNKNOWN`` → ``"UNDECLARED"``, а НЕ ``"NONE"`` (найдено integration review F2,
#: 2026-10-05). ``"NONE"`` у Director'а — исход ЭВРИСТИКИ других источников (гейты
#: моста, json-флаги), означающий «ни один из трёх предметов, это дефект очереди —
#: работа агента» (`classify_item`: `subject == 'NONE' → CLASS_SYSTEM`). Ни одна
#: реальная карточка `needs-owner` сегодня не объявляет `subject:` во frontmatter, то
#: есть КАЖДАЯ приходит сюда как `UNKNOWN`; отдать ей код `"NONE"` значило бы, что
#: Director классифицирует ВСЕ 12/12 настоящих вопросов владельцу как работу агента и
#: прячет их из «ждёт вашего решения» — замерено: OWNER_DECISION_REQUIRED упал с 2 до 0.
#: `"UNDECLARED"` — отдельный код: он не «ни один из предметов» (это неизвестно, а не
#: отрицательный ответ), и `classify_item` обязан различать эти два исхода.
_DIRECTOR_CODE = {
    MONEY: "1",
    PUBLIC_NUMBERS_NAMING_LEGAL: "2",
    IRREVERSIBLE: "3",
    PHYSICAL_ACTION: "3",
    UNKNOWN: "UNDECLARED",
}


def director_subject(card_frontmatter: Optional[Mapping]) -> tuple[str, str, str]:
    """(код '1'/'2'/'3'/'UNDECLARED', основание, причина словами) — форма Director'а.

    Основание всегда ``DECLARED`` (объявлено frontmatter) либо, для ``UNKNOWN``,
    ``NOT_DECLARED`` — ни один исход больше не несёт основание ``HEURISTIC``: угадывать
    по словам эта функция не умеет по построению.
    """
    subj = subject_of(card_frontmatter)
    code = _DIRECTOR_CODE.get(subj, "UNDECLARED")
    if subj == UNKNOWN:
        return code, "NOT_DECLARED", ("карточка не объявила `subject:` во frontmatter — "
                                      "тема не угадывается по словам (C5, ADR-580)")
    declared = None
    if isinstance(card_frontmatter, Mapping):
        declared = card_frontmatter.get("subject")
    return code, "DECLARED", f"frontmatter объявляет `subject: {declared}`"
