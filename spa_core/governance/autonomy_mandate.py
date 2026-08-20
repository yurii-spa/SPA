"""autonomy_mandate.py — у мандата автономии есть СРОК, и знает его код.

Зачем модуль вообще существует
------------------------------
Мандат автономии (широта того, что оркестратор решает без карточки владельцу)
дважды жил ТОЛЬКО прозой ADR:

* **ADR-078** (09.08) дал десять дней — «до ~19.08». Ни один сторож этого срока
  не знал. Вопрос о продлении задал ЦИКЛ РУКАМИ 19.08 (#302) — в последний день,
  а не заранее; заметил его человекоподобный разбор, а не проверка.
* **ADR-088** (19.08) закрыл мандат — и возврат к базовому протоколу состоялся
  тоже потому, что кто-то это написал, а не потому, что срок истёк сам.

То есть у ширины собственных полномочий агента не было ни срока годности, ни
читателя. Пока владелец рядом, это стоит недорого; ровно в этом классе («сторож
отвечает не на тот вопрос» / «сторожа нет вовсе») система уже теряла дни.

Решение владельца 2026-08-20 (мандат №2, 30 дней, ADR-101) содержит пункт,
который прозой исполнить нельзя честно:

    «Отзыв — в любой момент одной кнопкой владельца, автопродление ЗАПРЕЩЕНО:
     за 3 дня до конца — карточка-вопрос о продлении.»

«Автопродление запрещено» — это утверждение о ПОВЕДЕНИИ СИСТЕМЫ, а не о нашей
дисциплине. Здесь оно становится свойством: истёкший мандат перестаёт быть
широким сам, без участия того, кто должен был вспомнить.

Что модуль ДЕЛАЕТ и чего НЕ делает
----------------------------------
Делает: отвечает на вопрос «какой мандат действует ПРЯМО СЕЙЧАС и сколько ему
осталось». Ничего не исполняет, ничего не пишет, сеть не трогает.

НЕ делает: не гейтит исполнение, не двигает капитал, не касается RiskPolicy и
kill-switch. Широта мандата — про то, спрашивает ли агент владельца ПЕРЕД
работой; запреты инвариантов (`CLAUDE.md`) от мандата не зависят вовсе и
мандатом не ослабляются НИКОГДА. Самый широкий мандат не разрешает ни порогов
RiskPolicy, ни kill-switch, ни живого капитала, ни чисел/тиров/legal на сайте.

Fail-CLOSED здесь — это УЗКИЙ протокол
--------------------------------------
Любая неопределённость (мандата нет · записи противоречат друг другу · дата не
разбирается) даёт `NONE` ⇒ базовый протокол: ОДНА безопасная задача за цикл,
остальное карточкой. Ошибиться в сторону «работаем широко» нельзя: это молча
расширяет полномочия агента, и заметить это будет некому — ровно та авария,
от которой модуль и заведён.

Время — ВХОД (`.claude/rules/deployment.md`, предпочтение №1): любая функция
принимает `now`, по умолчанию — реальные часы. Литеральные даты в `MANDATES` —
исторический реестр решений владельца, а не фикстура.

LLM_FORBIDDEN — governance-слой, детерминированная арифметика дат.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field

__all__ = [
    "Mandate",
    "MANDATES",
    "RENEWAL_LEAD_DAYS",
    "STATE_ACTIVE",
    "STATE_ASK_RENEWAL",
    "STATE_EXPIRED",
    "STATE_REVOKED",
    "STATE_NONE",
    "mandate_status",
    "summary_lines",
]

#: За сколько дней до конца задаётся вопрос о продлении. Число — из решения
#: владельца 2026-08-20 (мандат №2), не из соображений удобства.
RENEWAL_LEAD_DAYS = 3

STATE_ACTIVE = "ACTIVE"
STATE_ASK_RENEWAL = "ASK_RENEWAL"
STATE_EXPIRED = "EXPIRED"
STATE_REVOKED = "REVOKED"
STATE_NONE = "NONE"

#: Сколько задач за цикл разрешено в каждом состоянии. «Много» — это НЕ «сколько
#: угодно и без правил»: протокол (worktree, зелёные тесты, объявление владения,
#: карточка на спорное) действует одинаково при любом мандате.
TASKS_MANY = "many"
TASKS_ONE = "one"


@dataclass(frozen=True)
class Mandate:
    """Одно решение владельца о ширине автономии, с началом и концом.

    ``end`` — ВКЛЮЧИТЕЛЬНО: «с 2026-08-20 по 2026-09-19» означает, что 19.09
    мандат ещё действует, а 20.09 — уже нет.

    ``revoked_on`` — дата отзыва владельцем, если он случился раньше срока
    (решение владельца, зафиксированное как всё остальное — файлом в git).
    """

    adr: str
    start: dt.date
    end: dt.date
    title: str
    #: Что мандат разрешает решать без карточки — дословно рамка решения.
    scope: str = ""
    #: Что мандатом НЕ разрешается ни при какой ширине (инварианты).
    never: str = ""
    revoked_on: dt.date | None = None
    notes: str = ""


def _d(s: str) -> dt.date:
    return dt.date.fromisoformat(s)


_SCOPE_078 = (
    "архитектура · код · тесты · флот агентов · paper-книги · приоритеты · R&D · "
    "тексты сайта БЕЗ новых чисел"
)
_NEVER_078 = (
    "пороги RiskPolicy · kill-switch · реальный капитал · числа доходности / "
    "нейминг тиров / legal на сайте · активация HoI · секреты"
)

#: РЕЕСТР решений владельца о ширине автономии. Дописывается только по решению
#: владельца (ADR), задним числом не правится: это след, а не настройка.
MANDATES: tuple[Mandate, ...] = (
    Mandate(
        adr="ADR-078",
        start=_d("2026-08-09"),
        end=_d("2026-08-19"),
        title="Мандат десятидневной автономии (перед отъездом владельца)",
        scope=_SCOPE_078,
        never=_NEVER_078,
        notes=(
            "Истёк по сроку. Продлевать владелец отказался — ADR-088, вариант 3, "
            "возврат к базовому протоколу. Вопрос о продлении был задан РУКАМИ и "
            "в последний день: срока этого мандата не знал никто, кроме прозы."
        ),
    ),
    Mandate(
        adr="ADR-101",
        start=_d("2026-08-20"),
        end=_d("2026-09-19"),
        title="Мандат автономии №2 — 30 дней («активный цех», темп ADR-078)",
        scope=_SCOPE_078,
        never=_NEVER_078,
        notes=(
            "Решение владельца 2026-08-20 (cloud-сессия, кнопка «Да, на 30 дней»), "
            "карточка own-mandat-avtonomii-vozobnovlen-30-dnei. Рамки — ДОСЛОВНО "
            "ADR-078. Автопродление запрещено; за RENEWAL_LEAD_DAYS дней до конца "
            "цикл обязан завести карточку-вопрос о продлении."
        ),
    ),
)


def _as_date(now: dt.date | dt.datetime | None) -> dt.date:
    if now is None:
        return dt.datetime.now(dt.timezone.utc).date()
    if isinstance(now, dt.datetime):
        return now.date()
    if isinstance(now, dt.date):
        return now
    raise TypeError(f"now: ожидалась дата/датавремя, получено {type(now).__name__}")


def _base_protocol(reason: str, **extra) -> dict:
    """Ответ «широких полномочий нет» — единственная форма отказа.

    Одна форма на все причины намеренно: у читателя не должно быть ветки, в
    которой «не измерено» выглядит иначе, чем «истёк». Причина при этом
    НАЗЫВАЕТСЯ (`reason`) — молчаливого отказа тоже быть не должно.
    """
    out = {
        "state": STATE_NONE,
        "adr": None,
        "start": None,
        "end": None,
        "days_left": None,
        "ask_renewal": False,
        "tasks_per_cycle": TASKS_ONE,
        "scope": "",
        "never": _NEVER_078,
        "reason": reason,
    }
    out.update(extra)
    return out


def mandate_status(now: dt.date | dt.datetime | None = None,
                   mandates: tuple[Mandate, ...] | None = None) -> dict:
    """Какой мандат действует на дату `now` и сколько ему осталось.

    Возвращает словарь; ключевые поля:

    ``state``
        `ACTIVE` · `ASK_RENEWAL` (действует, но осталось ≤ RENEWAL_LEAD_DAYS) ·
        `EXPIRED` (был и кончился) · `REVOKED` (отозван владельцем досрочно) ·
        `NONE` (широкого мандата нет / не измерено).
    ``tasks_per_cycle``
        `"many"` только при действующем мандате, иначе `"one"` — базовый протокол.
    ``ask_renewal``
        True ⇒ цикл ОБЯЗАН завести карточку-вопрос о продлении (или убедиться,
        что она уже заведена). Автопродления нет.
    ``reason``
        Человеческая строка: почему именно такое состояние.
    """
    today = _as_date(now)
    regs = MANDATES if mandates is None else tuple(mandates)

    # Записи, чьё окно накрывает сегодня. Противоречие (две сразу) — НЕ повод
    # выбрать «ту, что пошире»: это неизмеренное состояние, отвечаем узко.
    covering = [m for m in regs if m.start <= today <= m.end]
    if len(covering) > 1:
        names = ", ".join(m.adr for m in covering)
        return _base_protocol(
            f"реестр мандатов противоречив: на {today.isoformat()} действуют сразу "
            f"{len(covering)} записи ({names}) — широта не измерена, работаем узко")

    if not covering:
        past = [m for m in regs if m.end < today]
        if past:
            last = max(past, key=lambda m: m.end)
            gone = (today - last.end).days
            return _base_protocol(
                f"мандат {last.adr} истёк {last.end.isoformat()} "
                f"({gone} дн. назад) и НЕ продлён — базовый протокол",
                state=STATE_EXPIRED, adr=last.adr, start=last.start, end=last.end,
                days_left=-gone)
        future = [m for m in regs if m.start > today]
        if future:
            nxt = min(future, key=lambda m: m.start)
            return _base_protocol(
                f"мандат {nxt.adr} ещё не начался (с {nxt.start.isoformat()}) — "
                f"базовый протокол")
        return _base_protocol("реестр мандатов пуст — базовый протокол")

    m = covering[0]

    if m.revoked_on is not None and m.revoked_on <= today:
        return _base_protocol(
            f"мандат {m.adr} ОТОЗВАН владельцем {m.revoked_on.isoformat()} "
            f"досрочно — базовый протокол",
            state=STATE_REVOKED, adr=m.adr, start=m.start, end=m.end, days_left=0)

    days_left = (m.end - today).days
    ask = days_left <= RENEWAL_LEAD_DAYS
    return {
        "state": STATE_ASK_RENEWAL if ask else STATE_ACTIVE,
        "adr": m.adr,
        "start": m.start,
        "end": m.end,
        "days_left": days_left,
        "ask_renewal": ask,
        "tasks_per_cycle": TASKS_MANY,
        "scope": m.scope,
        "never": m.never,
        "reason": (
            f"мандат {m.adr} действует до {m.end.isoformat()} включительно, "
            f"осталось {days_left} дн."
            + (f" — ≤{RENEWAL_LEAD_DAYS}, ЗАВЕСТИ карточку-вопрос о продлении "
               f"(автопродления нет)" if ask else "")
        ),
    }


def summary_lines(now: dt.date | dt.datetime | None = None,
                  mandates: tuple[Mandate, ...] | None = None) -> list[str]:
    """Строки для обязательного шага 0-офис — то, что читает оркестратор.

    Печатается СУЖДЕНИЕ («сколько задач за цикл»), а не только даты: читателю
    нужен ответ на «как мне сегодня работать», и выводить его самому из двух
    дат — ровно тот зазор, в котором сторож выглядит зелёным, не ответив.
    """
    st = mandate_status(now=now, mandates=mandates)
    tasks = ("несколько задач за цикл" if st["tasks_per_cycle"] == TASKS_MANY
             else "ОДНА безопасная задача за цикл (базовый протокол)")
    head = {
        STATE_ACTIVE: "✅",
        STATE_ASK_RENEWAL: "⚠️",
        STATE_EXPIRED: "⏹",
        STATE_REVOKED: "⏹",
        STATE_NONE: "⏹",
    }[st["state"]]
    lines = [f"{head} мандат автономии: {st['state']} — {st['reason']}",
             f"   режим цикла: {tasks}"]
    if st["ask_renewal"]:
        lines.append(
            "   ⚠️ ПУНКТ РЕШЕНИЯ ВЛАДЕЛЬЦА: автопродление запрещено — завести "
            "карточку-вопрос о продлении (own-*, needs-owner) + notify")
    if st["state"] in (STATE_ACTIVE, STATE_ASK_RENEWAL):
        lines.append(f"   сам: {st['scope']}")
    lines.append(f"   НИКОГДА (мандат не расширяет): {st['never']}")
    return lines
