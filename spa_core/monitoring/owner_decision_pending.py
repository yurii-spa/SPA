#!/usr/bin/env python3
"""owner_decision_pending.py — у остановки должен быть ЖИВОЙ вопрос владельцу.

Вопрос, на который отвечает этот модуль, — РОВНО ОДИН и больше никакой:

    если система остановлена, есть ли у неё заданный, доставленный и НАЖИМАЕМЫЙ
    вопрос владельцу — и сколько он уже ждёт ответа?

Почему он понадобился (замер 10.08.2026, цикл #195)
------------------------------------------------------------------------------
Прод встал в **00:52 UTC** (`data/kill_switch_active.json`, «threat_reactor: emergency
breaker: HALT»). Снять остановку может ТОЛЬКО владелец (инв. 1–3 CLAUDE.md, ADR-078) —
у системы нет и не должно быть права поднять себя самой. Вопрос владельцу ушёл в
**12:23 UTC**. Одиннадцать с половиной часов книга стояла в кэше, а вопроса, без которого
она не поднимется, в очереди владельца просто не было — и этого разрыва не измерял НИКТО.

Соседние сторожа отвечают честно и мимо (тот же класс, что `.claude/rules/deployment.md`
разбирает на трёх вопросах доставки):

  * `agent_health`            — агенты живы?            (остановка агентов не касается)
  * `cycle_health`            — цикл сходил?            (назовёт падение, не его причину)
  * `deployment_acceptance`   — флот способен стартовать? (способен, и это верно)
  * `house_view_gap`          — офис расходится с книгой? (расходится, но не про путь вверх)

Ни один не спрашивает про ПУТЬ ВВЕРХ. Худший случай — остановка вообще без вопроса
владельцу: тупик, из которого система не выйдет никогда, и сказать об этом некому.

Что модуль делает и чего НЕ делает
------------------------------------------------------------------------------
Только НАЗЫВАЕТ. Он не снимает остановку, не трогает пороги RiskPolicy, не двигает
капитал, не пишет в карточки и не отправляет ничего сам: возвращает отчёт, который
пишется в `data/owner_decision_pending.json` и потребляется `agent_health_monitor`
(ежечасно) и обязательным шагом 0-офис оркестратора (через `architecture/manifest.json`).

Находки:

  H1  CRITICAL  остановка активна, ждущих ответа вопросов НЕТ ВОВСЕ — тупик.
  H1u CRITICAL  остановка активна, а ждут ли вопросы ответа — НЕ ИЗМЕРЕНО (карточек
                пушей нет в дереве). Неизмеримый путь вверх во время остановки не
                лучше отсутствующего, но называется он ОТДЕЛЬНО: «не измерено» и
                «нет» — разные факты (fail-CLOSED, не fail-OPEN и не поклёп).
  H2  WARNING   остановка активна, вопрос отправлен и ждёт ответа —
      CRITICAL   после `PENDING_CRITICAL_H` часов ожидания: молчание такой длины
                 перестаёт быть «владелец сейчас ответит».
  H3  WARNING   ждущий ответа вопрос ушёл БЕЗ КНОПОК — владелец не может ответить
                с телефона вовсе. Непрерывная версия разового замера карточки
                `inbox-vosem-kartochek-vse-esche-zhdut-vladelts` (цикл #191).
  H4  WARNING   вопрос ЕСТЬ В ОЧЕРЕДИ, а доставки нет: владельцу его не отправляли
      CRITICAL  ни разу. Во время остановки — CRITICAL: путь вверх существует
                только на бумаге, нажимать владельцу физически нечего.
  H5  WARNING   ответ нажатием получен, а карточка всё ещё `needs-owner` — ответ
                не доехал до очереди (инжест не сделан либо запись потерялась).
  H8  WARNING   очередь ЭТОГО дерева НЕПОЛНА: вопрос владельцу `needs-owner`
      CRITICAL  живёт на `origin/main`, а файла в дереве нет. Во время остановки —
                CRITICAL: невидимый путь вверх не лучше отсутствующего.
  H9  WARNING   ОТПРАВЛЕННЫЙ вопрос жив на `origin/main` (`needs-owner`), а файла в
      CRITICAL  дереве нет: владелец его ВИДИТ, а нажатие отвечает «карточка
                исчезла». Найдено со стороны журнала отправок, поэтому не сводится
                к H8 (тот фильтрует тип и считает в хвосте НЕотправленные).
  H11 (без      вопрос владельцу живёт ТОЛЬКО на ВЕТКЕ: его нет ни в дереве, ни на
      статуса)  `origin/main`, и потому он невидим И этому сторожу (H8 сверяет с
                `origin/main`), И отправителю (`resend.open_questions` читает дерево
                + `origin/main`, #330). Третье плечо класса, и самое немое: вопрос
                нельзя ни задать, ни закрыть. Замер 23.08: 18 таких на 36 ветках,
                один заперт в своём же открытом PR. Статус СОЗНАТЕЛЬНО не поднимаем
                (прецедент H7/H10/ADR-084 плюс: 17 из 18 живут на ОДНОЙ известной
                ветке под ручным разбором, и вечный WARNING приучил бы пролистывать
                блок, в котором однажды окажется свежая потеря).
  H10 (без      поручения, ПРИНЯТЫЕ владельцем и ещё не исполненные (`owner-accepted`,
      статуса)  ADR-124). Не вопрос владельцу — НАШЕ обещание, и читатель у него один:
                обязательный шаг 0-офис протокола. Статус отчёта СОЗНАТЕЛЬНО не
                поднимаем — прецедент H7/ADR-084: файл ежечасно читает
                `agent_health_monitor`, умеющий звонить владельцу, а звать владельца
                из-за нашего невыполненного обещания — ровно наоборот.

Очередь дерева ≠ очередь владельца (цикл #270, 17.08.2026)
------------------------------------------------------------------------------
Тот же самоподдерживающийся класс, что #199 закрыл на журнале отправок, оказался
этажом выше — **на самом дереве**. Карточки заводят сессии в изолированных worktree
и пушат прямо на `origin`; автосинк прод-дерева возит `spa_core/` · `scripts/` ·
`tests/` и НЕ возит `nimbalyst-local/tracker/`. Замер 17.08: в проде 416 карточек,
на `origin/main` — 481, невидимых дереву — **109**.

Среди них был живой вопрос владельцу `own-34` (`needs-owner` на origin), и сторож
доложил `undelivered_count: 0`. Вопрос был невидим В ОБЕ СТОРОНЫ: в `pending` не
попал (файла нет), в `unchecked` не попал (обход журнала видит только ОТПРАВЛЕННОЕ,
а его не отправляли ни разу). Петля замкнулась ровно как в #199: не синкнуто ⇒ нет
файла ⇒ не в очереди ⇒ никто не заметил ⇒ не синкнуто. Зелёное число было правдой
про КАТАЛОГ и неправдой про ОЧЕРЕДЬ.

Лечится не синхронизацией (массовый `checkout origin/main -- tracker` стёр бы
карточки, живущие только в дереве), а тем, что расхождение НАЗЫВАЕТСЯ:
`spa_core/owner_queue/origin_view.py` читает версию очереди на `origin/main`
локальным git, без сети, и невидимые дереву вопросы `needs-owner` попадают в отчёт
отдельным полем и отдельной находкой.

Пропавшая карточка: три исхода вместо одного «не измерено» (цикл #273)
------------------------------------------------------------------------------
Обход журнала отправок находит карточки, которых в дереве НЕТ, и до #273 все они
одинаково ложились в `unchecked`. Формулировка была честная — «вопрос закрыт, а
карточка не доехала» и «вопрос открыт и потерян» с диска действительно неразличимы,
— но ответ лежал в одном запросе от нас. Замер 17.08: из трёх таких строк ДВЕ были
доброкачественным дрейфом (`ingested` на origin) и держали сторожа в WARNING неделю.

Постоянное предупреждение по доброкачественной причине — тот же класс «сторож
отвечает не на тот вопрос»: настоящая находка того же ранга тонет в строках,
которые все привыкли пролистывать. Теперь `origin_view.cards_by_id` спрашивает ту
же локальную копию `origin/main`, и исходов ТРИ, каждый назван отдельно:

  * статус на origin ЗАКРЫВАЮЩИЙ (`_TERMINAL_CARD_STATUS`) ⇒ не находка, а факт
    дрейфа: строка уходит из `unchecked`, но остаётся в `closed_on_origin` и
    ПЕЧАТАЕТСЯ (объяснение, которого не видно, ничего не стоит);
  * статус на origin `needs-owner` ⇒ находка H9, СИЛЬНЕЕ прежней;
  * карточки нет и на origin, статус незнакомый, либо сверка не выполнилась
    (не git-дерево, ref не разрешается) ⇒ честное `НЕ ИЗМЕРЕНО` с причиной.

Карточки с origin в `pending_count` НЕ подмешиваются — граница #270 сохраняется
намеренно: это очередь ЭТОГО дерева, и число, которого нет ни у одного читателя,
хуже отсутствующего.

Источник списка — ОЧЕРЕДЬ, а не журнал отправок (цикл #199)
------------------------------------------------------------------------------
До #199 весь список `pending` строился ОБХОДОМ ЖУРНАЛА ОТПРАВОК: карточка попадала
в поле зрения сторожа, только если её однажды отправили. Вопрос, рождённый в очереди
и не доехавший до Телеграма, для сторожа не существовал НИ В ОДНУ сторону — ни в
`pending`, ни в `unchecked`; молчание выглядело как порядок. Замер 10.08 (#198):
очередь держала ПЯТЬ карточек `needs-owner`, сторож называл три — `own-33` и `own-34`
владелец не получал НИКОГДА. Потеря самоподдерживающаяся: не отправлено ⇒ не в
журнале ⇒ не в `pending` ⇒ никто не заметил ⇒ не отправлено.

Тот же класс, что #146–#198: сторож называется «ждут ли вопросы владельца ответа»
и читается ИМЕННО так (шаг 0-офис оркестратора, `agent_health_monitor`), а отвечал
на более узкий вопрос — «ждут ли ответа ОТПРАВЛЕННЫЕ вопросы»; разница между этими
двумя вопросами и есть потерянный вопрос владельцу. Поэтому теперь:

  * список `pending` — карточки типа `owner-decision` со статусом `needs-owner`
    в живом дереве: ровно то множество, которое владельцу показывают `_BOARD.md`
    и `orchestrator_queue.py list --type owner-decision --status needs-owner`;
  * журнал отправок — АТРИБУТ записи (`delivered`, `pushed_at`, `buttons`), а не
    источник списка. Статус карточки главнее журнала в ОБЕ стороны: закрыта —
    вопрос снят; открыта при отвеченном пуше — ответ не доехал (H5);
  * обратную сторону (пуш есть, а карточки в дереве нет) по-прежнему ловит обход
    журнала — сторожу она видна только оттуда.

**Без остановки ждущие вопросы тревогой НЕ являются** — только полями отчёта. Владелец
бывает в отъезде (сейчас — до ~19.08), и WARN, который не может погаснуть девять дней, —
это шум, а не сигнал; ровно так очередь и глохнет (урок «нестираемое „не измерено“
морит очередь голодом»). Тревога поднимается там, где ожидание СТОИТ системе денег
или трека, — то есть при остановке.

Честность (fail-CLOSED)
------------------------------------------------------------------------------
Нечитаемый журнал отправок, отсутствующая карточка пуша ⇒ запись в `unchecked` с
причиной, а не молчаливое «ждущих нет». `status: OK` возможен ТОЛЬКО когда всё
вычислено и всё прошло.

Время — ВХОД (`now=`), не окружение (`.claude/rules/deployment.md`): и вердикт, и
отметки в фикстурах закрепляются тестом с обеих сторон.

CLI::  python3 -m spa_core.monitoring.owner_decision_pending [--json] [--no-write]

Exit: 0 — OK · 1 — WARNING/UNCHECKED · 2 — CRITICAL.
LLM_FORBIDDEN. Только stdlib.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from pathlib import Path
from typing import Any, Optional

from spa_core.governance.kill_switch import KILL_SWITCH_ACTIVE_FILENAME
from spa_core.utils.atomic import atomic_save
from spa_core.utils.live_paths import live_data_dir

_REPO_ROOT = Path(__file__).resolve().parents[2]

OK = "OK"
WARNING = "WARNING"
CRITICAL = "CRITICAL"
_SEVERITY = {OK: 0, WARNING: 1, CRITICAL: 2}

#: Журнал отправленных владельцу решений (пишет `spa_core/telegram/owner_decisions.py`).
PUSH_JOURNAL = "telegram_owner_decisions.json"
#: Куда пишется отчёт этого модуля.
REPORT_REL = "data/owner_decision_pending.json"

#: Сколько часов ожидания ответа ВО ВРЕМЯ ОСТАНОВКИ ещё читается как «владелец
#: сейчас ответит». Это порог ОТЧЁТНОСТИ, а не риска: ни RiskPolicy, ни ступени
#: выключателя он не касается и касаться не может.
PENDING_CRITICAL_H = 12.0

#: Статус карточки, означающий «вопрос владельцу ещё открыт».
_OPEN_CARD_STATUS = "needs-owner"

#: Статусы, означающие «вопрос ЗАКРЫТ и ответа больше не ждёт». Список ЗАКРЫТЫЙ и
#: перечислен поимённо СОЗНАТЕЛЬНО: «всё, что не `needs-owner`, — закрыто» было бы
#: fail-OPEN (опечатка в статусе, новый промежуточный статус или пустая строка
#: молча погасили бы живой вопрос). Незнакомый статус остаётся НЕ ИЗМЕРЕНО.
_TERMINAL_CARD_STATUS = frozenset({"ingested", "done", "owner-done"})

#: Владелец ОТВЕТИЛ («принято — беру в работу»), а работа ещё впереди (#350). Это
#: третье состояние, и оба прежних читали бы его неверно: как «ждёт владельца» —
#: значит слать ему уже отвеченный вопрос; как «закрыто» — значит потерять ровно то,
#: ради чего статус и заведён (обещанная перепроверка без исполнителя).
_ACCEPTED_CARD_STATUS = "owner-accepted"


def _worst(*statuses: str) -> str:
    return max(statuses, key=lambda s: _SEVERITY.get(s, 0)) if statuses else OK


def _parse_ts(value: Any) -> Optional[dt.datetime]:
    try:
        parsed = dt.datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=dt.timezone.utc)


def _hours_since(value: Any, now: dt.datetime) -> Optional[float]:
    parsed = _parse_ts(value)
    if parsed is None:
        return None
    return (now - parsed).total_seconds() / 3600.0


#: Карточка на диске есть, но не разобралась. НЕ «закрыта»: пустая строка сравнилась
#: бы с `needs-owner` как «не равно» и вопрос молча выпал бы из очереди — fail-OPEN
#: ровно того вида, ради которого этот модуль и написан.
_UNREADABLE = "\x00unreadable"


def _card_status(tracker_dir: Path, card_id: str) -> tuple[Optional[str], Optional[str]]:
    """(status, title) карточки по её идентификатору. (None, None) — карточки нет.

    Идентификатор, а не путь из журнала: путь там абсолютный и принадлежит дереву
    ОТПРАВИТЕЛЯ (сессия шлёт из своего worktree), а спрашиваем мы про живое дерево,
    в котором нажимает владелец. Ровно на этом расхождении 10.08 нажатие получало
    «карточка исчезла» (цикл #194).
    """
    path = Path(tracker_dir) / f"{card_id}.md"
    if not path.is_file():
        return None, None
    try:
        from spa_core.owner_queue.queue import load_card

        card = load_card(path)
        return (card.status or _UNREADABLE), (card.title or card_id)
    except Exception:  # noqa: BLE001 — нечитаемая карточка = НЕ измерено, не «закрыта»
        return _UNREADABLE, None


#: Тип карточки, которая ЕСТЬ вопрос владельцу. Резолвится тем же общим
#: `resolve_tracker_type` (вложенный `trackerStatus.type` → плоский `type:` →
#: префикс имени), что и CLI с доской: два читателя одного каталога не должны
#: расходиться — на этом уже теряли три карточки `own-rnd-*` (#143–#145).
_QUEUE_CARD_TYPE = "owner-decision"

# ── Карточка-ФАНТОМ: вопрос, которого никто не задавал (авария 11.08.2026) ────
#
# `ask_router` отдавал падение headless `claude` как обычный на вид вердикт
# `("unclear", …)`, интейк исполнял его как вердикт — и за день выпустил 44 карточки
# «Уточнение по заметке: …», у которых на месте вопроса стоит служебный текст упавшего
# классификатора. Для ЭТОГО сторожа они выглядели полноценной очередью: он честно
# доложил «44 из 48 вопросов владельцу не отправлены», и это была правда о карточках —
# но не о владельце, которому НИ ОДИН из этих 44 вопросов не был нужен.
#
# Причина закрыта в коде (`ask_router.UNAVAILABLE`), но сторож обязан узнавать этот класс
# сам: иначе следующая такая пачка снова растворится среди настоящих вопросов, и найдут
# её опять руками. Признак — СОВОКУПНОСТЬ; при любом несовпадении карточка считается
# НАСТОЯЩИМ вопросом (fail-CLOSED: занизить очередь владельца опаснее, чем завысить).
_PHANTOM_TITLE_PREFIX = "Уточнение по заметке: "
_PHANTOM_SOURCE = "intake"
_PHANTOM_SIGNATURES = (
    "Не смог обработать сообщение. Переформулируй или пришли как /task <текст>.",
    "Пустой ответ. Переформулируй или пришли как /task <текст>.",
)
#: Чем лечится — называем в самой находке, чтобы не искать инструмент по журналам.
_PHANTOM_REMEDY = "scripts/repair_phantom_intake_cards.py"


def _is_phantom(card) -> bool:
    """Карточка — след упавшего классификатора, а не вопрос владельцу."""
    if (card.fields.get("source") or "").strip() != _PHANTOM_SOURCE:
        return False
    if not (card.title or "").startswith(_PHANTOM_TITLE_PREFIX):
        return False
    body = card.body or ""
    return any(sig in body for sig in _PHANTOM_SIGNATURES)


def _scan_queue(tracker_dir: Path) -> tuple[list[dict], list[dict], list[dict], bool]:
    """Очередь владельца из ЖИВОГО дерева. → (ждущие, ПРИНЯТЫЕ, unchecked, есть_ли_каталог).

    Три состояния, а не два (#350): «ждёт владельца» (`needs-owner`), «владелец принял,
    работа впереди» (`owner-accepted`) и «закрыто». Слить принятые с любым из соседей
    значило бы либо снова слать владельцу отвеченный вопрос, либо потерять обещание.

    Каталога нет ⇒ очереди нет: это законное состояние песочницы/чистой установки,
    и объявлять его «не измерено» значило бы жечь предупреждение там, где мерить
    нечего (та же развилка, что с отсутствующим журналом отправок). Каталог ЕСТЬ,
    а карточка в нём не разобралась или лишена статуса ⇒ вот это находка: карточка
    без `status:` невидима ЛЮБОМУ фильтру, включая очередь владельца.
    """
    queue: list[dict] = []
    accepted: list[dict] = []
    unchecked: list[dict] = []
    if not tracker_dir.is_dir():
        return queue, accepted, unchecked, False

    from spa_core.owner_queue.queue import load_card

    for path in sorted(tracker_dir.glob("*.md")):
        card_id = path.stem
        try:
            card = load_card(path)
        except Exception:  # noqa: BLE001 — нечитаемая карточка = НЕ измерено
            # Только для файлов, которые ПО ИМЕНИ являются вопросом владельцу:
            # иначе любой посторонний .md в каталоге (доска, заметка) навсегда
            # поселился бы в «не измерено», а нестираемое «не измерено» морит
            # очередь голодом ровно так же, как молчание.
            if card_id.startswith(("own-", "owner-decision-")):
                unchecked.append({
                    "check": f"queue_card_unreadable:{card_id}",
                    "reason": "карточка вопроса владельцу не разобрана — ждёт ли она "
                              "ответа, НЕ ИЗМЕРЕНО",
                })
            continue
        if (card.tracker_type or "") != _QUEUE_CARD_TYPE:
            continue
        status = (card.status or "").strip()
        if not status:
            unchecked.append({
                "check": f"queue_card_status_missing:{card_id}",
                "reason": "карточка вопроса владельцу без статуса — она невидима "
                          "любому фильтру очереди, ждёт ли она ответа, НЕ ИЗМЕРЕНО",
            })
            continue
        if status == _ACCEPTED_CARD_STATUS:
            # Не вопрос владельцу (он ответил) и не закрытая карточка (работа впереди).
            # Ждёт АГЕНТА — и потому едет в отчёт отдельным списком, а не растворяется
            # ни в очереди, ни в тишине.
            accepted.append({
                "card_id": card_id,
                "title": card.title or card_id,
                "accepted_at": card.fields.get("owner_answered_at"),
            })
            continue
        if status != _OPEN_CARD_STATUS:
            continue
        queue.append({
            "card_id": card_id,
            "title": card.title or card_id,
            "created": card.fields.get("created"),
            "phantom": _is_phantom(card),
        })
    return queue, accepted, unchecked, True


#: С какой копией очереди сверяемся. Локальный ref, `git fetch` НЕ вызывается:
#: сторож в сеть не ходит, и sha этой копии печатается в отчёте — «сверено с origin»
#: не должно читаться как «сверено со свежайшим origin».
ORIGIN_REF = "origin/main"


def _scan_origin_gap(tracker_dir: Path, pushes_by_card: dict[str, list[dict]]) -> dict:
    """Вопросы владельцу, которые есть на `origin/main` и которых НЕТ в этом дереве.

    Fail-CLOSED и никогда не бросает наружу. «Сверять не с чем» (нет git-репозитория,
    ref не разрешается, каталога очереди нет) — законное состояние песочницы, CI и
    чистой установки: тогда ``measured=False`` и причина СЛОВАМИ, ровно как у
    ``_scan_channel_buttons``. Молчаливого «дереву видно всё» здесь не будет ни в
    одном исходе — отсутствие поля и пустой список означают разные вещи.

    `delivered` у найденной карточки считается по журналу отправок ЭТОГО дерева:
    журнал живёт в `data/` и с деревом не расходится, а вопрос, которого нет ни в
    дереве, ни в журнале, — это и есть потерянный вопрос (`own-34`, 10.08–17.08).
    """
    try:
        from spa_core.owner_queue.origin_view import Unmeasured, unreachable_cards
    except Exception as exc:  # noqa: BLE001 — сторож не роняет отчёт из-за импорта
        return {"measured": False, "reason": f"сверка с {ORIGIN_REF} недоступна: {exc}"}
    try:
        cards, sha = unreachable_cards(Path(tracker_dir), ref=ORIGIN_REF,
                                       tracker_type=_QUEUE_CARD_TYPE,
                                       status=_OPEN_CARD_STATUS)
    except Unmeasured as exc:
        return {"measured": False, "reason": f"очередь на {ORIGIN_REF} не прочитана: {exc}"}
    except Exception as exc:  # noqa: BLE001 — неожиданное тоже «не измерено», не «чисто»
        return {"measured": False, "reason": f"сверка с {ORIGIN_REF} не выполнена: {exc}"}
    return {
        "measured": True,
        "ref": ORIGIN_REF,
        "ref_sha": sha,
        "count": len(cards),
        # Ключ остался прежним — его читают три места отчёта и шаг 0-офис, — но
        # ВОПРОС под ним теперь верный: не «есть ли файл с таким именем», а «дойдёт
        # ли живой вопрос до владельца и туда ли попадёт ответ» (цикл #439). Поэтому
        # у каждой записи есть `kind`: чинятся исходы по-разному, и слепить их в одно
        # число значило бы повторить ту же ошибку этажом выше.
        "hidden": [{"card_id": c.card_id, "title": c.title, "kind": c.kind,
                    "tree_status": c.tree_status, "detail": c.detail,
                    "delivered": bool(pushes_by_card.get(c.card_id))}
                   for c in cards],
    }


def _scan_branch_queue(tracker_dir: Path) -> dict:
    """Вопросы владельцу, которых нет НИ в дереве, НИ на `origin/main` — только на ветках.

    ТРЕТЬЕ плечо класса «вопрос владельцу невидим», и самое немое из трёх. Два
    первых уже меряются: `_scan_origin_gap` («есть на origin, нет в дереве», #270)
    и `closed_on_origin`/`open_on_origin` (дрейф прод↔origin, #273). Карточка,
    живущая ТОЛЬКО на ветке, не встречается ни одной из этих сверок — и ни
    отправителю (`resend.open_questions` читает дерево + `origin/main`, #330).
    Вопрос нельзя ни задать, ни закрыть, и молчания об этом никто не замечает:
    строка шага 0-офис «очередь полна: невидимых дереву вопросов нет» была
    утверждением о полноте, на которое замера не существовало.

    Замер 23.08.2026 (цикл #351, 36 веток): **18** `needs-owner` не были на
    `origin/main` ни минуты. Один из них — `own-2026-08-22-snyat-changelog-so-saita`
    внутри ОТКРЫТОГО PR #35: карточка просит подпись владельца, без которой этот же
    PR не вливают, то есть вопрос заперт в том, что сам же разблокирует.

    `ever_on_base` отделяет потерянный вопрос от НАМЕРЕННО снятого: наш тест-зонд
    `owner-decision-test-prizrak-ne-rozhdaetsya` лежит на двух влитых ветках, а с
    `main` убран коммитом `029627b46` — это не потеря. Признак измеримый (история
    пути на базовом ref), а не эвристика.

    **Третий исход — «прочитано и осознанно не везём»** (карточка
    `inbox-storozh-voprosy-vladeltsa-na-vetke-ne-zn`, цикл #376). Двух имён не
    хватало на самый частый и совершенно ПРАВИЛЬНЫЙ исход разбора ветки: дубль уже
    разобранного, устаревшая премиса, замер приложен к карточке на `main`. Такая
    карточка на `main` не лежала НИКОГДА ⇒ ``ever_on_base = False`` ⇒ она попадала
    в `count` НАВСЕГДА, и число не могло дойти до нуля даже после полного разбора
    ветки. Замер 23.08 (цикл #356): 12 карточек, все 12 — с ветки
    `origin/claude/work-status-check-xfnbew`, разбор которой цикл #355 в тот же день
    ЗАКОНЧИЛ; 25.08 их оставалось 3, и все три названы поимённо в теле
    карточки-разбора с починкой (ADR-125 / ADR-116) или совпадением.

    Цена молчания тут не «лишняя строка»: постоянный житель раздела находок
    приучает пролистывать раздел, в котором однажды окажется настоящая потеря
    вопроса владельца, — тот же механизм, которым глохнут сторожа (#354).
    Ослаблением это не является: решение обязано быть ЗАПИСАНО с автором, датой и
    основанием, иначе объявлением не считается вовсе, — и незаписанное решение
    по-прежнему потеря. Строка с меткой, но без обязательного поля, НЕ выбрасывается
    молча: она едет в `declaration_issues`.

    Fail-CLOSED и никогда не бросает наружу — ровно как соседи по файлу: сверять не
    с чем (не git-дерево, ref не разрешается) ⇒ ``measured=False`` и причина
    СЛОВАМИ. Отдельная нечитаемая ветка замер по остальным не отменяет, но и не
    исчезает: она названа в `unreadable`.
    """
    try:
        from spa_core.owner_queue.origin_view import Unmeasured, branch_only_cards
    except Exception as exc:  # noqa: BLE001 — сторож не роняет отчёт из-за импорта
        return {"measured": False, "reason": f"обход веток недоступен: {exc}"}
    try:
        scan = branch_only_cards(Path(tracker_dir), base_ref=ORIGIN_REF,
                                 tracker_type=_QUEUE_CARD_TYPE,
                                 status=_OPEN_CARD_STATUS)
    except Unmeasured as exc:
        return {"measured": False, "reason": f"ветки не прочитаны: {exc}"}
    except Exception as exc:  # noqa: BLE001 — неожиданное тоже «не измерено», не «чисто»
        return {"measured": False, "reason": f"обход веток не выполнен: {exc}"}
    on_base = [c for c in scan.cards if c.ever_on_base]
    dropped = [c for c in scan.cards if not c.ever_on_base and c.dropped is not None]
    lost = [c for c in scan.cards if not c.ever_on_base and c.dropped is None]
    return {
        "measured": True,
        "ref": scan.base_ref,
        "ref_sha": scan.base_sha,
        "branches_read": len(scan.branches_read),
        # Число ПОТЕРЯННЫХ, а не всех найденных: намеренно снятая карточка и
        # осознанно не привезённая стоят рядом отдельными числами, чтобы «мы это
        # решили сами» нельзя было прочитать как находку и наоборот.
        "count": len(lost),
        "removed_on_base_count": len(on_base),
        "dropped_count": len(dropped),
        "cards": [{"card_id": c.card_id, "title": c.title,
                   "branches": list(c.branches)} for c in lost],
        # Автор, дата и основание едут в отчёт ВСЕГДА: решение, основание которого
        # не видно, читателю проверить нечем, и тогда признак закрывает что угодно.
        "dropped": [{"card_id": c.card_id, "title": c.title,
                     "branches": list(c.branches), "by": c.dropped.by,
                     "date": c.dropped.date, "reason": c.dropped.reason,
                     "declared_in": c.dropped.declared_in} for c in dropped],
        # Брак объявлений и объявления, пережившие свой предмет. НЕ находка о
        # владельце — находка о самом реестре: реестр, из которого ничего не уходит
        # и в который можно писать как попало, через год состоит из мусора.
        "declaration_issues": (
            [{"where": w, "reason": r} for w, r in scan.dropped_broken]
            + [{"where": cid, "reason": "объявлено «не везём», но карточки нет ни на "
                                        "одной прочитанной ветке — решение пережило предмет"}
               for cid in scan.dropped_stale]),
        "unreadable": [{"branch": b, "reason": r} for b, r in scan.unreadable],
    }


def _resolve_missing_on_origin(tracker_dir: Path, card_ids: list[str]) -> dict:
    """Чем на самом деле кончились карточки, которых нет в ЖИВОМ дереве.

    Отвечает на вопрос, который сам по себе с диска неразрешим. Дрейф прод↔origin
    возит только `spa_core/`·`scripts/`·`tests/` (урок #193), поэтому «вопрос
    закрыт, а карточка просто не доехала в прод» и «вопрос открыт и потерян»
    снаружи одинаковы — и до цикла #273 обе ветки честно висели в `unchecked`.
    Замер 17.08: из трёх таких строк ДВЕ были доброкачественным дрейфом
    (`ingested` на origin) и держали сторожа в WARNING неделю, приучая
    пролистывать блок, в котором однажды окажется настоящая находка.

    Fail-CLOSED и никогда не бросает наружу — ровно как `_scan_origin_gap`:
    «сверять не с чем» (не git-дерево, ref не разрешается) ⇒ ``measured=False`` и
    причина СЛОВАМИ, а строка остаётся НЕ ИЗМЕРЕНО. «Не смогли посмотреть» не
    имеет права выглядеть как «вопрос закрыт».
    """
    out: dict = {"asked": len(card_ids), "ref": ORIGIN_REF, "found": {}}
    if not card_ids:
        # Спрашивать было нечего — и это НЕ «измерено, расхождений нет»: сверка не
        # выполнялась вовсе. Ноль и «не мерили» обязаны различаться и здесь.
        out.update({"measured": False, "reason": "пропавших карточек нет — сверка не требовалась"})
        return out
    try:
        from spa_core.owner_queue.origin_view import Unmeasured, cards_by_id
    except Exception as exc:  # noqa: BLE001 — сторож не роняет отчёт из-за импорта
        out.update({"measured": False, "reason": f"сверка с {ORIGIN_REF} недоступна: {exc}"})
        return out
    try:
        cards, sha = cards_by_id(Path(tracker_dir), card_ids, ref=ORIGIN_REF)
    except Unmeasured as exc:
        out.update({"measured": False,
                    "reason": f"очередь на {ORIGIN_REF} не прочитана: {exc}"})
        return out
    except Exception as exc:  # noqa: BLE001 — неожиданное тоже «не измерено», не «чисто»
        out.update({"measured": False,
                    "reason": f"сверка с {ORIGIN_REF} не выполнена: {exc}"})
        return out
    out.update({"measured": True, "ref_sha": sha,
                "found": {cid: card.status for cid, card in cards.items()}})
    return out


CHANNEL_HISTORY = "alert_history.json"


def _scan_channel_buttons(ddir: Path, pushes=None) -> dict:
    """Сообщения с вариантами, уехавшие БЕЗ кнопок — по общему журналу канала.

    Fail-CLOSED и никогда не бросает: журнала нет ⇒ ``measured=False`` и причина
    словами; «нет журнала» не имеет права выглядеть как «всё с кнопками».
    """
    path = ddir / CHANNEL_HISTORY
    if not path.is_file():
        return {"measured": False,
                "reason": f"{CHANNEL_HISTORY} отсутствует — канал не измерен"}
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
        entries = doc.get("entries") if isinstance(doc, dict) else None
        if not isinstance(entries, list):
            raise ValueError("нет списка entries")
    except (OSError, ValueError) as exc:
        return {"measured": False,
                "reason": f"{CHANNEL_HISTORY} не читается ({exc}) — канал не измерен"}
    try:
        from spa_core.telegram.buttonless_audit import scan

        # Журнал отправок передаём тем же вызовом: с ним у каждой находки появляется
        # ПРИЧИНА, а без неё строка отчёта зовёт читателя копать два журнала руками
        # (замер #350 — полчаса на две строки).
        out = scan(entries, pushes=pushes)
    except Exception as exc:  # noqa: BLE001 — сторож не роняет отчёт
        return {"measured": False, "reason": f"скан не выполнен: {exc}"}
    out["measured"] = True
    return out


def _buttonless_reason(tracker_dir: Path, card_id: str, *,
                       now: dt.datetime,
                       beacon_path: Optional[str | Path]) -> dict:
    """Измеренная причина отсутствия кнопок у названного вопроса. Не бросает.

    Обёртка нужна ровно затем, чтобы неудача самого измерителя тоже приезжала
    ПРИЧИНОЙ, а не пустым местом: «причин не нашлось» и «померить не смогли» —
    разные факты, и первое здесь было бы ложью.
    """
    try:
        from spa_core.telegram.buttonless_reason import explain

        return explain(tracker_dir / f"{card_id}.md",
                       now=now, beacon_path=beacon_path, ref=ORIGIN_REF).as_dict()
    except Exception as exc:  # noqa: BLE001 — сторож не роняет отчёт
        return {"code": "unmeasured", "measured": False,
                "text": f"измеритель причины не выполнился: {exc}",
                "remedy": "разобрать вручную"}


def _kinds_summary(cards) -> str:
    """«чем именно не доходят» — словами, по исходам.

    Три исхода чинятся по-разному (файла нет · лежит другой текст · ответ пережил
    вопрос), и одно общее число про них лгало бы тем же способом, каким лгало
    `hidden: []`: честный ответ на свой вопрос, прочитанный как ответ на нужный.
    """
    from collections import Counter
    names = {"absent": "файла в дереве нет",
             "differs": "в дереве ДРУГОЙ текст",
             "answer_outlived_question": "ответ пережил свой вопрос"}
    counts = Counter(str(c.get("kind") or "?") for c in cards)
    return ", ".join(f"{names.get(k, k)}: {n}" for k, n in sorted(counts.items()))


def check_pending_owner_decisions(*,
                                  now: Optional[dt.datetime] = None,
                                  data_dir: Optional[str | Path] = None,
                                  tracker_dir: Optional[str | Path] = None,
                                  beacon_path: Optional[str | Path] = None) -> dict:
    """Собрать отчёт «путь вверх». Ничего не пишет — только считает."""
    now = now or dt.datetime.now(dt.timezone.utc)
    ddir = Path(data_dir) if data_dir is not None else live_data_dir(_REPO_ROOT)
    tdir = (Path(tracker_dir) if tracker_dir is not None
            else ddir.parent / "nimbalyst-local" / "tracker")

    issues: list[str] = []
    unchecked: list[dict] = []
    status = OK

    # --- остановка ----------------------------------------------------------
    halt_path = ddir / KILL_SWITCH_ACTIVE_FILENAME
    halted = halt_path.is_file()
    halt_since = halt_reason = None
    halt_age_h = None
    if halted:
        try:
            halt_doc = json.loads(halt_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            halt_doc = {}
        if isinstance(halt_doc, dict):
            halt_since = halt_doc.get("activated_at")
            halt_reason = halt_doc.get("reason")
        halt_age_h = _hours_since(halt_since, now)

    # --- журнал отправленных решений ---------------------------------------
    # «Файла нет» и «файл испорчен» — РАЗНЫЕ факты, и мерить их одинаково нельзя.
    # Журнала нет ⇒ владельцу ничего не отправляли: это законное состояние чистого
    # дерева (CI, песочница, свежая установка), и объявлять его «не измерено» значило
    # бы жечь предупреждение там, где мерить нечего. Журнал ЕСТЬ, но не читается ⇒
    # очередь вопросов действительно неизмерима — вот это находка.
    journal_path = ddir / PUSH_JOURNAL
    journal_present = journal_path.is_file()
    pushes: Optional[list] = None
    if journal_present:
        try:
            doc = json.loads(journal_path.read_text(encoding="utf-8"))
            raw = doc.get("pushes") if isinstance(doc, dict) else None
            if isinstance(raw, list):
                pushes = raw
        except (OSError, ValueError):
            pushes = None
        if pushes is None:
            unchecked.append({
                "check": "push_journal",
                "reason": f"журнал отправок {PUSH_JOURNAL} есть, но не читается — "
                          f"ждут ли вопросы ответа, НЕ ИЗМЕРЕНО",
            })

    # --- обход журнала: ТОЛЬКО обратная сторона (пуш есть, карточки нет) -----
    # Список ждущих вопросов строится НЕ здесь (см. «Источник списка» в шапке):
    # вопрос, которого нет в журнале, отсюда невидим — ровно то слепое пятно,
    # которое стоило владельцу двух неотправленных карточек 10.08.
    pushes_by_card: dict[str, list[dict]] = {}
    #: Пропавшие карточки собираются, а не судятся на месте: вердикт по ним даёт
    #: сверка с `origin/main` НИЖЕ, и спросить её лучше одним пакетом на все
    #: карточки сразу. Ключи `dict` — заодно и дедуп: карточку могли переотправить
    #: (так #198 чинил кнопки `own-33`), и три записи журнала об ОДНОЙ карточке
    #: давали три одинаковые строки «не измерено» об одном и том же факте.
    missing_ids: dict[str, None] = {}
    for push in (pushes or []):
        if not isinstance(push, dict):
            continue
        card_id = str(push.get("card_id") or "").strip()
        if not card_id:
            unchecked.append({"check": "push_without_card_id",
                              "reason": "запись журнала без card_id — карточку не найти"})
            continue
        pushes_by_card.setdefault(card_id, []).append(push)
        if push.get("choice") is not None:
            continue                       # ответ нажатием получен
        card_status, _card_title = _card_status(tdir, card_id)
        if card_status is None:
            missing_ids.setdefault(card_id, None)
        elif card_status == _UNREADABLE:
            unchecked.append({
                "check": f"card_unreadable:{card_id}",
                "reason": "карточка есть, но не разобрана — открыт ли вопрос, НЕ ИЗМЕРЕНО "
                          "(пустой статус читался бы как «закрыт» — это fail-OPEN)",
            })

    # --- пропавшая карточка: чем она кончилась на origin? -------------------
    # H8 считается ЗДЕСЬ, а не перед своей строкой: он называет поимённо часть тех
    # же карточек (открытый вопрос, которого нет в дереве), и без его списка новая
    # находка ниже удвоила бы уже сказанное. Порядок строк отчёта от этого не
    # меняется — issues здесь не дописываются.
    origin_gap = _scan_origin_gap(tdir, pushes_by_card)
    # Третье плечо той же сверки (#351). Статус отчёта СОЗНАТЕЛЬНО не поднимаем —
    # прецедент H7/ADR-084: файл ежечасно читает `agent_health_monitor`, умеющий
    # звонить владельцу, а звонить владельцу о НАШЕЙ недоставке его же вопросов
    # значит ответить на жалобу о спаме новым спамом. Плюс 17 из 18 находок живут
    # на ОДНОЙ известной ветке под ручным разбором: вечный WARNING приучил бы
    # пролистывать блок, в котором однажды окажется свежая потеря. Находка едет в
    # отчёт и в ОБЯЗАТЕЛЬНЫЙ шаг 0-офис, где её читает оркестратор. Закреплено
    # тестом в обе стороны.
    branch_gap = _scan_branch_queue(tdir)
    gap_ids = {str(c.get("card_id")) for c in (origin_gap.get("hidden") or [])}

    missing_on_origin = _resolve_missing_on_origin(tdir, list(missing_ids))
    origin_status_by_card = missing_on_origin.get("found") or {}
    closed_on_origin: list[dict] = []
    open_on_origin: list[dict] = []
    accepted_on_origin: list[dict] = []
    for card_id in missing_ids:
        origin_status = origin_status_by_card.get(card_id)
        if origin_status in _TERMINAL_CARD_STATUS:
            # Доброкачественная ветка: вопрос закрыт, а файл просто не доехал в
            # прод. Не находка — но и не молчание: факт дрейфа остаётся в отчёте
            # и печатается отдельной строкой (иначе он «исчезнет молча», а прод
            # так и будет отвечать «карточка исчезла» на нажатие).
            closed_on_origin.append({"card_id": card_id, "origin_status": origin_status})
            continue
        if origin_status == _ACCEPTED_CARD_STATUS:
            # Владелец ответил, файла в дереве нет: вопроса к нему больше нет, а
            # работа есть. Молчать нельзя (иначе принятое поручение испарится вместе
            # с дрейфом прод↔origin), но и «не измерено» здесь ложно — измерено точно.
            accepted_on_origin.append({"card_id": card_id,
                                       "origin_status": origin_status})
            continue
        if origin_status == _OPEN_CARD_STATUS:
            # Находка СИЛЬНЕЕ прежней «не измерено»: вопрос ЖИВОЙ, владельцу его
            # отправляли, а нажать он не может — файла в дереве нет.
            open_on_origin.append({"card_id": card_id, "origin_status": origin_status})
            continue
        if not missing_on_origin.get("measured"):
            why = (f"сверка с {ORIGIN_REF} не выполнена — "
                   f"{missing_on_origin.get('reason', 'причина не названа')}")
        elif origin_status is None:
            why = (f"на {ORIGIN_REF} ({str(missing_on_origin.get('ref_sha'))[:9]}) "
                   f"карточки тоже нет")
        else:
            why = (f"на {ORIGIN_REF} у неё статус `{origin_status}` — ни `"
                   f"{_OPEN_CARD_STATUS}`, ни один из закрывающих")
        unchecked.append({
            "check": f"card_missing:{card_id}",
            "reason": f"карточки нет в живом дереве и {why} — открыт ли вопрос, "
                      "НЕ ИЗМЕРЕНО. Отсюда «вопрос закрыт, а карточка просто не "
                      "доехала в прод» и «вопрос открыт и потерян» выглядят "
                      "ОДИНАКОВО, поэтому вердикта здесь нет ни в одну сторону; "
                      "нажатие по такой карточке владельцу отвечает «карточка исчезла»",
        })

    # --- очередь: ИСТОЧНИК списка ждущих вопросов ---------------------------
    queue_cards, accepted_cards, queue_unchecked, queue_present = _scan_queue(tdir)
    unchecked.extend(queue_unchecked)

    # Фантомы вынимаем ДО подсчёта очереди: это не вопросы, и складывать их с
    # настоящими — значит показывать владельцу очередь, которой у него нет.
    phantom_cards = [c for c in queue_cards if c.get("phantom")]
    queue_cards = [c for c in queue_cards if not c.get("phantom")]

    pending: list[dict] = []
    for card in queue_cards:
        card_id = card["card_id"]
        card_pushes = pushes_by_card.get(card_id) or []
        # Свежайшая отправка — по ней считается ВСЁ: и ожидание, и кнопки, и
        # ответ. Карточку могли переотправить, починив кнопки (так #198 чинил
        # `own-33`) или переспросив после ответа, — и тогда судить по старой
        # записи значило бы жаловаться на уже починенное. Порядок — по времени,
        # а не по строке: отметки с разным смещением сравнились бы как текст.
        last = max(card_pushes,
                   key=lambda p: (_parse_ts(p.get("pushed_at"))
                                  or dt.datetime.min.replace(tzinfo=dt.timezone.utc)),
                   default=None)
        age_h = _hours_since((last or {}).get("pushed_at"), now)
        pending.append({
            "card_id": card_id,
            "title": card["title"],
            "created": card.get("created"),
            "delivered": bool(card_pushes),
            "pushed_at": (last or {}).get("pushed_at"),
            "age_h": None if age_h is None else round(age_h, 2),
            "buttons": bool((last or {}).get("buttons")),
            "answered_but_open": (last or {}).get("choice") is not None,
        })

    pending.sort(key=lambda p: (p["age_h"] is None, -(p["age_h"] or 0.0)))

    delivered = [p for p in pending if p["delivered"]]
    undelivered = [p for p in pending if not p["delivered"]]
    answered_open = [p for p in pending if p["answered_but_open"]]

    # Возраст ожидания есть только у ДОСТАВЛЕННОГО вопроса: у неотправленного
    # ждать нечего — его никто не видел. Смешивать их одним числом значило бы
    # выдавать неотправленный вопрос за молчание владельца.
    oldest = delivered[0] if delivered else None
    oldest_age_h = oldest["age_h"] if oldest else None

    buttonless = [p for p in delivered if not p["buttons"]]

    # --- ПОЧЕМУ кнопок нет: причина измеряется, а не гадается -----------------
    # «Кнопок нет» — верный ответ на свой вопрос и бесполезный для того, кто
    # должен что-то сделать: причин минимум четыре и лечатся они по-разному.
    # Замер 21.08 (#333): у двух вопросов подряд причины оказались РАЗНЫЕ, и
    # обе не совпали с единственной гипотезой карточки-задания. Одна из них
    # (дерево отстало от `origin`) с диска не видна вовсе — поэтому спрашиваем
    # ref. Мерим только те, у кого кнопок нет: сверка стоит процесса git.
    for p in buttonless:
        p["buttons_reason"] = _buttonless_reason(tdir, p["card_id"],
                                                 now=now, beacon_path=beacon_path)

    # --- H1/H2: путь вверх во время остановки -------------------------------
    # Идут ПЕРВЫМИ: `reason` отчёта — это issues[0], и первой строкой обязана
    # стоять остановка, а не второстепенная жалоба на кнопки.
    if halted:
        halt_age_txt = ("возраст НЕ ИЗМЕРЕН" if halt_age_h is None
                        else f"{halt_age_h:.1f}ч")
        if delivered:
            age_txt = ("возраст НЕ ИЗМЕРЕН" if oldest_age_h is None
                       else f"{oldest_age_h:.1f}ч")
            # Часы считает ПРОСТОЙ, а не возраст вопроса. Стоит системе именно
            # остановка; вопрос — лишь способ из неё выйти, и заданный минуту
            # назад вопрос не делает 30-часовой простой свежим. Возраст вопроса
            # остаётся вторым сроком (и печатается) — на случай, когда возраст
            # самой остановки не измерен.
            clock_h = halt_age_h if halt_age_h is not None else oldest_age_h
            sev = (CRITICAL if (clock_h is not None
                                and clock_h >= PENDING_CRITICAL_H) else WARNING)
            issues.append(
                f"owner_decision_pending: система ОСТАНОВЛЕНА ({halt_age_txt}, "
                f"{halt_reason or 'причина НЕ ИЗМЕРЕНА'}) и ждёт ЧЕЛОВЕКА: снять может "
                f"только владелец, ему отправлено {len(delivered)} вопрос(ов), старейший "
                f"без ответа {age_txt} — «{oldest['title']}»")
            status = _worst(status, sev)
        elif undelivered:
            # ТУПИК НА ДЕЛЕ: вопрос в очереди есть, но владелец его не видел ни
            # разу — нажимать ему нечего. От «вопроса не задано» отличается только
            # тем, где именно оборвался путь вверх, и это различие обязано звучать.
            names = ", ".join(p["card_id"] for p in undelivered[:3])
            more = f" (и ещё {len(undelivered) - 3})" if len(undelivered) > 3 else ""
            issues.append(
                f"owner_decision_pending: система ОСТАНОВЛЕНА ({halt_age_txt}, "
                f"{halt_reason or 'причина НЕ ИЗМЕРЕНА'}), вопрос(ов) в очереди "
                f"{len(undelivered)} — и НИ ОДИН НЕ ОТПРАВЛЕН владельцу: путь вверх "
                f"есть только на бумаге, нажать нечего ({names}{more})")
            status = _worst(status, CRITICAL)
        elif unchecked:
            issues.append(
                f"owner_decision_pending: система ОСТАНОВЛЕНА ({halt_age_txt}), а есть ли "
                f"у неё путь вверх — НЕ ИЗМЕРЕНО ({len(unchecked)} причин(ы) ниже). "
                f"Неизмеримый путь вверх во время остановки не лучше отсутствующего")
            status = _worst(status, CRITICAL)
        else:
            issues.append(
                f"owner_decision_pending: ТУПИК — система ОСТАНОВЛЕНА ({halt_age_txt}, "
                f"{halt_reason or 'причина НЕ ИЗМЕРЕНА'}), а вопроса владельцу, которым её "
                f"можно поднять, НЕ ЗАДАНО НИ ОДНОГО. Путь вниз есть, пути вверх нет")
            status = _worst(status, CRITICAL)
    elif unchecked:
        # Без остановки неизмеримость очереди — предупреждение, не тревога.
        status = _worst(status, WARNING)

    # --- H4: вопрос есть, доставки нет --------------------------------------
    # Во время остановки без единого доставленного вопроса это уже сказано выше
    # первой строкой — повторять не надо. Во всех остальных случаях говорится
    # здесь, И БЕЗ ОСТАНОВКИ ТОЖЕ: это не «владелец молчит девять дней» (шум,
    # который не может погаснуть), а НАШЕ упущение, которое гасится одной
    # отправкой — `orchestrator_queue.py notify <карточка>`.
    if undelivered and not (halted and not delivered):
        names = ", ".join(p["card_id"] for p in undelivered[:3])
        more = f" (и ещё {len(undelivered) - 3})" if len(undelivered) > 3 else ""
        issues.append(
            f"owner_decision_pending: {len(undelivered)} из {len(pending)} вопрос(ов) "
            f"владельцу НЕ ОТПРАВЛЕНЫ НИ РАЗУ — он о них не знает и ответить не может: "
            f"{names}{more}")
        status = _worst(status, CRITICAL if halted else WARNING)

    # --- H8: очередь ЭТОГО дерева неполна -----------------------------------
    # Идёт СРАЗУ за H4: обе находки об одном — вопрос владельцу существует, а
    # владелец его не видел; отличие лишь в том, где оборвался путь. Считать
    # такие карточки в `pending` нельзя (это очередь дерева, и подмешивать в неё
    # чужое множество значило бы показывать число, которого нет ни у одного
    # читателя), но и молчать нельзя — молчанием и был потерян `own-34`.
    gap_cards = origin_gap.get("hidden") or []
    if origin_gap.get("measured") and gap_cards:
        names = ", ".join(c["card_id"] for c in gap_cards[:3])
        more = f" (и ещё {len(gap_cards) - 3})" if len(gap_cards) > 3 else ""
        never_sent = [c for c in gap_cards if not c["delivered"]]
        tail = (f"; из них НИ РАЗУ не отправлены владельцу: {len(never_sent)}"
                if never_sent else "")
        issues.append(
            f"owner_decision_pending: очередь этого дерева НЕПОЛНА — "
            f"{len(gap_cards)} вопрос(ов) владельцу `{_OPEN_CARD_STATUS}` живут на "
            f"{origin_gap['ref']} ({origin_gap['ref_sha'][:9]}) и до владельца из "
            f"этого дерева НЕ доходят ({_kinds_summary(gap_cards)}): здешние счётчики "
            f"про них не знают ВООБЩЕ{tail}: {names}{more}")
        status = _worst(status, CRITICAL if halted else WARNING)

    # --- H9: ОТПРАВЛЕННЫЙ вопрос жив на origin, а файла в дереве нет ---------
    # До #273 такая карточка молча лежала в `unchecked` вместе с доброкачественным
    # дрейфом. Пересечение с H8 не подавляется СОЗНАТЕЛЬНО: утверждения разные и
    # ни одно не следует из другого. H8 говорит «очередь дерева неполна» и считает
    # в хвосте НЕотправленные; H9 говорит ровно обратное про те же файлы — вопрос
    # владельцу ОТПРАВЛЕН, он его видит, и нажатие отвечает «карточка исчезла».
    # Плюс H9 не ограничен типом `owner-decision`: фильтр H8 такую карточку
    # пропустил бы вовсе.
    if open_on_origin:
        names = ", ".join(c["card_id"] for c in open_on_origin[:3])
        more = f" (и ещё {len(open_on_origin) - 3})" if len(open_on_origin) > 3 else ""
        also = (f"; из них уже названы выше как неполнота очереди: "
                f"{len([c for c in open_on_origin if c['card_id'] in gap_ids])}"
                if gap_ids & {c["card_id"] for c in open_on_origin} else "")
        issues.append(
            f"owner_decision_pending: {len(open_on_origin)} вопрос(ов) владельцу ЖИВЫ на "
            f"{ORIGIN_REF} (`{_OPEN_CARD_STATUS}`) и владельцу ОТПРАВЛЕНЫ, а файла в "
            f"дереве нет — нажатие отвечает «карточка исчезла», ответить нечем{also}: "
            f"{names}{more}")
        status = _worst(status, CRITICAL if halted else WARNING)

    # --- H5: ответ нажатием есть, а вопрос в очереди всё ещё открыт ---------
    # Статус карточки главнее журнала (инв. #14 — закрыть может только владелец),
    # поэтому вопрос остаётся ждущим; но расхождение двух источников называется,
    # а не сглаживается: 10.08 ответы владельца лежали неинжестированными.
    if answered_open:
        names = ", ".join(p["card_id"] for p in answered_open[:3])
        more = f" (и ещё {len(answered_open) - 3})" if len(answered_open) > 3 else ""
        issues.append(
            f"owner_decision_pending: {len(answered_open)} вопрос(ов) ОТВЕЧЕНЫ нажатием, "
            f"а карточка всё ещё ждёт владельца — ответ не доехал до очереди "
            f"(инжест не сделан): {names}{more}")
        status = _worst(status, WARNING)

    # --- H3: вопрос, на который владелец физически не может ответить --------
    if buttonless:
        # Причина печатается РЯДОМ с именем карточки, а не лежит в отчёте молча:
        # одинаковые с виду строки лечатся по-разному, и читатель обязан узнать
        # это ЗДЕСЬ, не открывая json и не разбирая карточку руками полчаса.
        names = ", ".join(
            f"{p['card_id']} [{(p.get('buttons_reason') or {}).get('code', 'unmeasured')}: "
            f"{(p.get('buttons_reason') or {}).get('text', 'причина НЕ ИЗМЕРЕНА')}]"
            for p in buttonless[:3])
        more = f" (и ещё {len(buttonless) - 3})" if len(buttonless) > 3 else ""
        issues.append(
            f"owner_decision_pending: {len(buttonless)} вопрос(ов) владельцу ждут ответа "
            f"БЕЗ КНОПОК — ответить с телефона нельзя: {names}{more}")
        status = _worst(status, WARNING)

    # --- H6: очередь засорена карточками, которых никто не спрашивал ---------
    # Не вопрос владельцу и не «не измерено»: измерено ТОЧНО — это след аварии
    # классификатора. Молчать нельзя (11.08 такие 44 штуки выдавали себя за очередь
    # владельца), но и в счёт вопросов их брать нельзя — поэтому отдельная строка,
    # сразу с лекарством.
    if phantom_cards:
        names = ", ".join(c["card_id"] for c in phantom_cards[:3])
        more = f" (и ещё {len(phantom_cards) - 3})" if len(phantom_cards) > 3 else ""
        issues.append(
            f"owner_decision_pending: {len(phantom_cards)} карточк(и) в очереди — НЕ вопросы, "
            f"а след упавшего классификатора (на месте вопроса его служебный текст). В счёт "
            f"вопросов владельцу не берутся; лечится `{_PHANTOM_REMEDY}`: {names}{more}")
        status = _worst(status, WARNING)

    # --- H7: тот же вопрос, измеренный СО СТОРОНЫ КАНАЛА --------------------
    # H3 выше судит по журналу пушей — а он знает ровно один путь отправки
    # (`owner_decisions.register_push`). Жалоба владельца 14.08 («пишет варианты
    # ответов — кнопок нету») по этому журналу не воспроизводится: после 10.08 там
    # всё с кнопками. Значит либо жаловались на ДРУГОГО отправителя (сырой POST из
    # GitHub Actions — у него кнопок нет и быть не может), либо мы этого не видим.
    # Скан по общему журналу канала отвечает про ВСЕХ отправителей сразу.
    #
    # Статус НЕ трогаем СОЗНАТЕЛЬНО. Этот отчёт ежечасно читает `agent_health_monitor`,
    # а тот умеет звонить владельцу; поднять из-за оформления сообщений WARNING —
    # значит ответить на жалобу о спаме новым спамом. Направление таблички решает
    # (прецедент ADR-084): находка едет в отчёт и в обязательный шаг 0-офис, где её
    # читает оркестратор, а не в чат. Закреплено тестом в обе стороны.
    channel = _scan_channel_buttons(ddir, pushes)

    return {
        "generated_at": now.isoformat(),
        "status": status,
        "phantom_count": len(phantom_cards),
        "halted": halted,
        "halt_since": halt_since,
        "halt_age_h": None if halt_age_h is None else round(halt_age_h, 2),
        "halt_reason": halt_reason,
        "journal_present": journal_present,
        "queue_present": queue_present,
        # ВСЯ очередь `needs-owner`, а не только отправленное: до #199 здесь
        # стояло число из журнала отправок, и оно расходилось с очередью
        # (5 против 3) в пользу молчания.
        "pending_count": len(pending),
        "delivered_count": len(delivered),
        "undelivered_count": len(undelivered),
        "answered_but_open_count": len(answered_open),
        "oldest_pending_age_h": oldest_age_h,
        "buttonless_count": len(buttonless),
        # Число вопросов владельцу, которых очередь этого дерева не видит вовсе.
        # `None` — не измерено (см. `origin_queue.reason`): ноль и «не мерили»
        # обязаны быть различимы, иначе сломанная сверка выглядит как порядок.
        "queue_gap_count": (len(gap_cards) if origin_gap.get("measured") else None),
        "origin_queue": origin_gap,
        # Вопросы владельцу, живущие ТОЛЬКО на ветке (#351): их не видит ни
        # `origin_queue` выше, ни отправитель. `None` — не измерено: ноль и «не
        # мерили» обязаны быть различимы и здесь.
        "branch_queue_count": (branch_gap.get("count")
                               if branch_gap.get("measured") else None),
        "branch_queue": branch_gap,
        # Пропавшие карточки, разложенные по трём исходам (#273). `closed_on_origin`
        # — НЕ находка, а факт дрейфа прод↔origin: вопрос закрыт, файл не доехал.
        # Он остаётся в отчёте и печатается, потому что молча исчезнувший факт
        # означал бы, что прод и дальше отвечает «карточка исчезла» на нажатие.
        "missing_cards": missing_on_origin,
        "closed_on_origin": closed_on_origin,
        "open_on_origin": open_on_origin,
        "accepted_on_origin": accepted_on_origin,
        # Поручения, ПРИНЯТЫЕ владельцем и ещё не исполненные (#350). Не вопросы
        # владельцу — работа агента; читатель — обязательный шаг 0-офис протокола.
        # Статус отчёта СОЗНАТЕЛЬНО не поднимаем (прецедент H7/ADR-084): этот файл
        # ежечасно читает `agent_health_monitor`, умеющий звонить владельцу, а звать
        # владельца из-за НАШЕГО невыполненного обещания — ровно наоборот.
        "accepted": accepted_cards,
        "accepted_count": len(accepted_cards),
        "channel_buttons": channel,
        "pending": pending,
        "issues": issues,
        "unchecked": unchecked,
        # `reason` — первая строка находок; когда находок нет, потерянных
        # доставок не бывает по построению (H4 срабатывает всегда), поэтому
        # приписки «из них не отправлено» здесь нет: она была бы мёртвой веткой.
        # Зато оговорка о полноте очереди нужна: когда находок нет, число вопросов
        # печатается ВМЕСТЕ с оговоркой о полноте очереди: до #270 оно читалось
        # как «вопросов ровно столько», хотя означало «столько в этом каталоге».
        "reason": (issues[0] if issues else
                   ("остановки нет; вопросов владельцу без ответа: "
                    f"{len(pending)}"
                    # Принятые поручения — НЕ вопросы владельцу, поэтому в счёт выше
                    # они не идут; но и промолчать о них нельзя: это наше обещание,
                    # у которого до #350 не было ни статуса, ни читателя.
                    + (f"; принятых поручений в работе: {len(accepted_cards)}"
                       if accepted_cards else "")
                    + ("" if origin_gap.get("measured")
                       else f" (полнота очереди НЕ ИЗМЕРЕНА: "
                            f"{origin_gap.get('reason', 'причина не названа')})"))),
        "thresholds": {"pending_critical_h": PENDING_CRITICAL_H},
    }


def run(*, now: Optional[dt.datetime] = None,
        data_dir: Optional[str | Path] = None,
        tracker_dir: Optional[str | Path] = None) -> tuple[dict, Path]:
    """Посчитать и записать отчёт атомарно. Возвращает (отчёт, путь)."""
    ddir = Path(data_dir) if data_dir is not None else live_data_dir(_REPO_ROOT)
    doc = check_pending_owner_decisions(now=now, data_dir=ddir, tracker_dir=tracker_dir)
    path = ddir / Path(REPORT_REL).name
    atomic_save(doc, str(path))
    return doc, path


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="python3 -m spa_core.monitoring.owner_decision_pending",
                                 description=__doc__.splitlines()[0])
    ap.add_argument("--json", action="store_true", help="печатать весь отчёт JSON-ом")
    ap.add_argument("--no-write", action="store_true", help="только посчитать и напечатать")
    ap.add_argument("--data-dir", default=None)
    args = ap.parse_args(argv)

    if args.no_write:
        doc = check_pending_owner_decisions(data_dir=args.data_dir)
    else:
        doc, _ = run(data_dir=args.data_dir)

    if args.json:
        print(json.dumps(doc, ensure_ascii=False, indent=2))
    else:
        print(f"{doc['status']}: {doc['reason']}")
        for line in doc["issues"][1:]:
            print(f"  · {line}")
        for u in doc["unchecked"]:
            print(f"  [НЕ ИЗМЕРЕНО] {u['check']}: {u['reason']}")
        # Факт дрейфа, а не находка — но печатается всегда, когда есть: строка
        # ушла из «не измерено» именно потому, что мы её ОБЪЯСНИЛИ, и объяснение
        # обязано быть видно. Молча исчезнувшая строка — та же слепота.
        for c in doc.get("closed_on_origin") or []:
            print(f"  [дрейф прод↔origin] {c['card_id']}: вопрос закрыт на "
                  f"{ORIGIN_REF} (`{c['origin_status']}`), файл в прод-дерево не доехал")
    return {OK: 0, WARNING: 1, CRITICAL: 2}[doc["status"]]


if __name__ == "__main__":
    raise SystemExit(main())
