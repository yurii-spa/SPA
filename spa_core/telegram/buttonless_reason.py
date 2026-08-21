#!/usr/bin/env python3
"""buttonless_reason.py — ПОЧЕМУ у доставленного вопроса владельцу нет кнопок.

Зачем это отдельный модуль
------------------------------------------------------------------------------
Сторож `owner_decision_pending` умел сказать ровно одно: «N вопросов ждут ответа
БЕЗ КНОПОК — ответить с телефона нельзя». Это верный ответ на СВОЙ вопрос
(«кнопки есть?») и бесполезный для того, кто должен что-то сделать: причин у
такого состояния как минимум четыре, лечатся они по-разному, а различить их с
одного взгляда нельзя вовсе.

Цена измерена 21.08 (цикл #333). Два вопроса стояли без кнопок, и карточка-задание
называла ОДНУ гипотезу на обоих («починка описывала ветку, которая не доехала»).
Ручной разбор дал ДВЕ разные причины, и ни одна не совпала с гипотезой:

* `own-33-plist-marker-for-cycle-origin` — варианты в карточке ЕСТЬ, но только на
  `origin/main` (дописаны циклом #321 в 19:53Z, через 52 минуты после отправки).
  Бот шлёт из ПРОД-дерева, а каталог очереди туда не возит никто (автосинк возит
  `spa_core/`·`scripts/`·`tests/`) ⇒ владельца четыре раза подряд спросили по
  копии, отставшей от источника правды, и каждый раз честно без кнопок.
* `own-2026-08-19-sudba-voronki-chekapa-i-kanal-zayavok` — вариантов нет НИГДЕ:
  они записаны буквами «(а)/(б)» внутри двух РАЗНЫХ решений одной карточки.
  Отказ разбора здесь верен (ADR-075: выдумывать владельцу выбор запрещено),
  и лечится он переписыванием вопроса, а не кодом.

Первую причину не видно ниоткуда, кроме сверки с `origin`; вторую видно только из
разбора тела. Поэтому причина обязана быть ИЗМЕРЕНА и НАЗВАНА в самом отчёте —
иначе каждая следующая сессия тратит полчаса на то же самое и приносит гипотезу.

Правило разбора здесь НЕ дублируется
------------------------------------------------------------------------------
«Когда у вопроса есть кнопки» решает единственный писатель этого правила —
`owner_decisions.prepare` (он же один знает про маячок обработчика и про
переходное послабление). Мы его ВЫЗЫВАЕМ, а не пересказываем: вторая копия
правила разошлась бы с первой, и сторож начал бы объяснять причину состояния,
которого нет.

Fail-CLOSED в форме «не измерено»
------------------------------------------------------------------------------
Ни одна ветка не бросает наружу: сторож не имеет права уронить отчёт. Но и
молчаливого «причин не нашлось» здесь нет — неудача сверки возвращается кодом
``unmeasured`` с причиной словами.

LLM_FORBIDDEN. Только stdlib.
"""
# LLM_FORBIDDEN
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional

#: Варианты в карточке разбираются, обработчик нажатия жив ⇒ кнопки СЕЙЧАС
#: собрались бы. Значит дело не в карточке: досылка кнопок — штатный ремонт
#: `heal_buttonless`, и если запись всё ещё без кнопок, ремонт до неё не дошёл.
CODE_HEAL_PENDING = "buttons_available_not_resent"
#: Варианты есть, но живого обработчика нажатия нет (маячок молчит) — кнопка
#: увела бы владельца в неизвестный `act:`-глагол и стёрла бы сам вопрос.
CODE_HANDLER_UNAVAILABLE = "handler_unavailable"
#: В карточке ЭТОГО дерева вариантов нет, а на ref — есть. Владельца спрашивают
#: по копии, отставшей от источника правды.
CODE_STALE_VS_ORIGIN = "card_stale_vs_origin"
#: Вариантов нет нигде — отказ верен, лечится формой вопроса, а не кодом.
CODE_NO_OPTIONS = "no_options_in_card"
#: Файла карточки нет: нажимать не по чему, и это не «нет вариантов».
CODE_CARD_GONE = "card_gone"
#: Сверка не выполнилась. НЕ «причин не найдено».
CODE_UNMEASURED = "unmeasured"

#: С какой копией очереди сверяемся. Локальный ref, `git fetch` не вызывается.
DEFAULT_REF = "origin/main"

_REMEDY_STALE = ("перенести версию карточки с ref в дерево, из которого шлёт бот "
                 "(каталог очереди автосинком не возится)")
_REMEDY_NO_OPTIONS = ("переписать вопрос перечнем «Вариант 1 / Вариант 2»; карточку "
                      "с ДВУМЯ решениями — разделить надвое (ADR-075: выдумывать "
                      "владельцу выбор запрещено)")
_REMEDY_HANDLER = ("поднять/перезапустить бота, объявляющего умение `act:od:` — "
                   "до этого кнопка стёрла бы сам вопрос")
_REMEDY_HEAL = "штатный ремонт `heal_buttonless` — дослать кнопки к этой записи"


@dataclass(frozen=True)
class Reason:
    """Измеренная причина отсутствия кнопок + чем именно она лечится."""

    code: str
    text: str
    remedy: str

    @property
    def measured(self) -> bool:
        """``False`` только у `unmeasured` — «не измерено» не выдаёт себя за вердикт."""
        return self.code != CODE_UNMEASURED

    def as_dict(self) -> dict:
        return {"code": self.code, "text": self.text, "remedy": self.remedy,
                "measured": self.measured}


def _origin_body(path: Path, ref: str) -> tuple[Optional[str], str]:
    """(тело карточки на ref, sha ref). ``None`` — карточки на ref нет.

    Бросает только `Unmeasured` — её ловит вызывающий и превращает в код с причиной.
    """
    from spa_core.owner_queue.origin_view import Unmeasured, card_sources
    from spa_core.owner_queue.queue import load_card_text

    texts, sha = card_sources(path.parent, [path.stem], ref=ref)
    raw = texts.get(path.stem)
    if raw is None:
        return None, sha
    try:
        card = load_card_text(raw, path.name)
    except ValueError as exc:
        raise Unmeasured(f"карточка на {ref} не разобралась: {exc}") from exc
    return card.body or "", sha


def _explain_no_options(path: Path, ref: str) -> Reason:
    """Вариантов нет в дереве. Есть ли они на ref — вопрос, неразрешимый с диска."""
    from spa_core.owner_queue.origin_view import Unmeasured
    from spa_core.telegram.owner_decisions import parse_options

    try:
        body, sha = _origin_body(path, ref)
    except Unmeasured as exc:
        return Reason(
            CODE_UNMEASURED,
            f"вариантов в карточке дерева нет, а сверить с `{ref}` не удалось: {exc}. "
            f"«Вопрос сформулирован без вариантов» и «дерево отстало от источника» "
            f"отсюда выглядят ОДИНАКОВО, поэтому вердикта нет ни в одну сторону",
            _REMEDY_STALE,
        )
    except Exception as exc:  # noqa: BLE001 — сторож не роняет отчёт
        return Reason(CODE_UNMEASURED,
                      f"сверка карточки с `{ref}` не выполнилась: {exc}", _REMEDY_STALE)

    short = sha[:9] if sha else "?"
    if body is None:
        return Reason(
            CODE_NO_OPTIONS,
            f"в карточке не разобрано ни одного варианта, и на `{ref}` ({short}) "
            f"её нет вовсе — кнопкам неоткуда взяться",
            _REMEDY_NO_OPTIONS,
        )
    origin_options = parse_options(body)
    if origin_options:
        nums = ", ".join(str(o.num) for o in origin_options)
        return Reason(
            CODE_STALE_VS_ORIGIN,
            f"в карточке ЭТОГО дерева вариантов нет, а на `{ref}` ({short}) их "
            f"{len(origin_options)} ({nums}) — владельца спрашивают по копии, "
            f"отставшей от источника правды",
            _REMEDY_STALE,
        )
    return Reason(
        CODE_NO_OPTIONS,
        f"в карточке не разобрано ни одного варианта — ни здесь, ни на `{ref}` "
        f"({short}); отказ верен, выдумывать выбор запрещено (ADR-075)",
        _REMEDY_NO_OPTIONS,
    )


def explain(card_path: str | Path, *,
            now: Optional[datetime] = None,
            beacon_path: Optional[str | Path] = None,
            ref: str = DEFAULT_REF) -> Reason:
    """Почему у этого вопроса владельцу нет кнопок. Никогда не бросает.

    Порядок веток — от «дело не в карточке» к «дело в карточке»: сначала
    спрашиваем ЕДИНСТВЕННОГО писателя правила (`prepare`), собрались бы кнопки
    сейчас или нет, и только его отказ разбираем на причины.
    """
    from spa_core.owner_queue.queue import load_card
    from spa_core.telegram.owner_decisions import ack_allowed, prepare

    path = Path(card_path)
    if not path.is_file():
        return Reason(CODE_CARD_GONE,
                      f"файла карточки нет: {path}", "найти карточку или снять вопрос")
    try:
        card = load_card(path)
    except Exception as exc:  # noqa: BLE001
        return Reason(CODE_UNMEASURED,
                      f"карточка не разобралась ({exc}) — есть ли в ней варианты, "
                      f"НЕ ИЗМЕРЕНО", "починить разметку карточки")
    try:
        # Право на подтверждение меряет тот же единственный писатель правила
        # (`ack_allowed`), что и отправка, — иначе сторож объяснял бы причину
        # состояния, которого у отправителя нет.
        allow_ack, _why = ack_allowed(path, card.body or "", ref=ref)
        prep = prepare(card.title or path.stem, card.body or "", path.stem,
                       card_name=path.name, now=now, beacon_path=beacon_path,
                       allow_ack=allow_ack)
    except Exception as exc:  # noqa: BLE001
        return Reason(CODE_UNMEASURED,
                      f"сборка сообщения не выполнилась ({exc}) — причина отсутствия "
                      f"кнопок НЕ ИЗМЕРЕНА", _REMEDY_HEAL)

    if prep.keyboard is not None:
        what = (f"варианты разбираются ({len(prep.options)})" if prep.options
                # Вариантов нет и не будет — карточка их не предлагает. Но кнопка
                # подтверждения поручения (ADR-115) собралась бы, и «(0) вариантов
                # разбираются» здесь было бы неправдой о собственном же вердикте.
                else "выбора в карточке нет, но это поручение — кнопки подтверждения "
                     "собираются")
        return Reason(
            CODE_HEAL_PENDING,
            f"{what} и обработчик нажатия жив — "
            f"кнопки собрались бы прямо сейчас, значит до этой записи не дошёл ремонт",
            _REMEDY_HEAL,
        )
    if prep.options or prep.ack:
        what = (f"варианты разбираются ({len(prep.options)})" if prep.options
                # Кнопка подтверждения поручения (ADR-115) собралась бы — значит
                # дело НЕ в форме вопроса, и лечится оно ботом, а не переписыванием
                # карточки. До #338 такая запись попадала в `no_options_in_card`
                # («отказ верен, лечится формой»), то есть сторож называл верную
                # причину неверного состояния и отправлял чинить не то.
                else "выбора в карточке нет (поручение), кнопка подтверждения "
                     "собралась бы")
        return Reason(
            CODE_HANDLER_UNAVAILABLE,
            f"{what}, но живого обработчика "
            f"нажатия нет — кнопка увела бы владельца в неизвестный глагол",
            _REMEDY_HANDLER,
        )
    return _explain_no_options(path, ref)
