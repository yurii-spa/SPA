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


def _scan_queue(tracker_dir: Path) -> tuple[list[dict], list[dict], bool]:
    """Очередь вопросов владельцу из ЖИВОГО дерева. → (карточки, unchecked, есть_ли_каталог).

    Каталога нет ⇒ очереди нет: это законное состояние песочницы/чистой установки,
    и объявлять его «не измерено» значило бы жечь предупреждение там, где мерить
    нечего (та же развилка, что с отсутствующим журналом отправок). Каталог ЕСТЬ,
    а карточка в нём не разобралась или лишена статуса ⇒ вот это находка: карточка
    без `status:` невидима ЛЮБОМУ фильтру, включая очередь владельца.
    """
    queue: list[dict] = []
    unchecked: list[dict] = []
    if not tracker_dir.is_dir():
        return queue, unchecked, False

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
        if status != _OPEN_CARD_STATUS:
            continue
        queue.append({
            "card_id": card_id,
            "title": card.title or card_id,
            "created": card.fields.get("created"),
            "phantom": _is_phantom(card),
        })
    return queue, unchecked, True


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
        from spa_core.owner_queue.origin_view import Unmeasured, hidden_cards
    except Exception as exc:  # noqa: BLE001 — сторож не роняет отчёт из-за импорта
        return {"measured": False, "reason": f"сверка с {ORIGIN_REF} недоступна: {exc}"}
    try:
        cards, sha = hidden_cards(Path(tracker_dir), ref=ORIGIN_REF,
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
        "hidden": [{"card_id": c.card_id, "title": c.title,
                    "delivered": bool(pushes_by_card.get(c.card_id))}
                   for c in cards],
    }


CHANNEL_HISTORY = "alert_history.json"


def _scan_channel_buttons(ddir: Path) -> dict:
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

        out = scan(entries)
    except Exception as exc:  # noqa: BLE001 — сторож не роняет отчёт
        return {"measured": False, "reason": f"скан не выполнен: {exc}"}
    out["measured"] = True
    return out


def check_pending_owner_decisions(*,
                                  now: Optional[dt.datetime] = None,
                                  data_dir: Optional[str | Path] = None,
                                  tracker_dir: Optional[str | Path] = None) -> dict:
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
            unchecked.append({
                "check": f"card_missing:{card_id}",
                "reason": "карточки нет в живом дереве — открыт ли вопрос, НЕ ИЗМЕРЕНО. "
                          "Отсюда «вопрос закрыт, а карточка просто не доехала в прод» "
                          "и «вопрос открыт и потерян» выглядят ОДИНАКОВО, поэтому "
                          "вердикта здесь нет ни в одну сторону; нажатие по такой "
                          "карточке владельцу отвечает «карточка исчезла»",
            })
        elif card_status == _UNREADABLE:
            unchecked.append({
                "check": f"card_unreadable:{card_id}",
                "reason": "карточка есть, но не разобрана — открыт ли вопрос, НЕ ИЗМЕРЕНО "
                          "(пустой статус читался бы как «закрыт» — это fail-OPEN)",
            })

    # --- очередь: ИСТОЧНИК списка ждущих вопросов ---------------------------
    queue_cards, queue_unchecked, queue_present = _scan_queue(tdir)
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
    origin_gap = _scan_origin_gap(tdir, pushes_by_card)
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
            f"{origin_gap['ref']} ({origin_gap['ref_sha'][:9]}), а файла в дереве нет: "
            f"здешние счётчики про них не знают ВООБЩЕ{tail}: {names}{more}")
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
        names = ", ".join(p["card_id"] for p in buttonless[:3])
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
    channel = _scan_channel_buttons(ddir)

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
    return {OK: 0, WARNING: 1, CRITICAL: 2}[doc["status"]]


if __name__ == "__main__":
    raise SystemExit(main())
