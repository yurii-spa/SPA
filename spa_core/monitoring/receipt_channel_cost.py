#!/usr/bin/env python3
"""Цена КАНАЛА квитанции, спрошенная у ЧИТАТЕЛЯ — заказ **G110 п. 1** (ADR-535).

Заказ дословно:

    **Канал квитанции — ОТДЕЛЬНЫЙ, и это решение с измеренным основанием.** Общий
    журнал запрещён замером (ответы 4–5). У канала два кандидата, и у каждого своя
    цена: третье состояние записи (``asked``) меняет единственного писателя
    ``session_changes.jsonl`` и всех его читателей; второй файл оставляет писателя в
    покое и заводит артефакт, которого может не быть. Спросить надо **у читателя**:
    что сломается у оси B переписи, если квитанция придёт не записью журнала. Мерить
    ИСХОДОМ на одноразовой копии, три исхода обязательны.

Сосед (``claim_guard_receipt_readers``, ADR-535) остановился здесь намеренно и сказал
это вслух: «ось D говорит про ОДИН канал — общий журнал; что наивный канал вредит, не
есть утверждение, что вредит любой; **про отдельный канал прибор молчит**». Этот прибор
и спрашивает про отдельный — у того же читателя и тем же способом (ИСХОДОМ), чтобы два
ответа были сравнимы, а не выглядели сравнимыми.

## Кто здесь ЧИТАТЕЛЬ и почему он один

Читатель назван не догадкой: ось C соседа доказала его ИСХОДОМ —
``duplicate_subject_census.measure_receipts`` (ось B переписи дублей), поле
``window_takings_without_receipt`` 1 → 0 от ОДНОЙ добавленной квитанции. Поэтому
«спросить у читателя» здесь означает ровно: поднять одноразовую сцену, провести
квитанцию КАЖДЫМ из двух каналов и посмотреть на ЧИСЛО, которое читатель вернёт.

**Путь к читателю берётся целиком**, а не с середины: сцена пишет настоящий
``session_changes.jsonl`` настоящим писателем, а число снимается через
``load_journal`` → ``measure_receipts``. Подать записи прямо в ``measure_receipts``
списком было бы удобнее и неверно: вопрос заказа — про ФАЙЛ, который загрузчик
открывает, поэтому загрузчик обязан быть внутри замера, иначе инъектированный вход
обошёл бы ровно ту дверь, о которой спрашивают.

## Три оси, и ни одна не заменяет другую

===== ======================================== ======================================
ось   вопрос                                   чем меряется
===== ======================================== ======================================
A     ВИДИТ ли читатель квитанцию, пришедшую   ДИФФЕРЕНЦИАЛЬНО, четыре сцены: без
      каждым из двух каналов?                  квитанции · журнальная ``claim``
                                               (положительный контроль) · журнальная
                                               ``asked`` · второй файл
B     что читатель ТРЕБУЕТ от квитанции?       отъёмом по одному: приставка, предмет,
      (контракт канала, а не догадка о нём)    личность — каждое снимается у
                                               НАСТОЯЩЕГО писателя и мерится исходом
C     во что канал обходится у ДВЕРИ сторожа?  ДИФФЕРЕНЦИАЛЬНО: вердикт ``check`` без
      (вопрос не должен становиться захватом)  квитанции против вердикта с ней — по
                                               каждому каналу отдельно
===== ======================================== ======================================

Ось A без оси B назвала бы канал видимым и промолчала о том, ЧТО именно канал обязан
нести, — а «квитанция дошла» и «квитанция дошла при любой форме записи» разные
утверждения. Ось B без оси C описала бы контракт каналу, который сам по себе вреден.
Ось C без оси A вернула бы ответ соседа (ADR-535) и ничего не добавила: безвредный
канал, которого читатель не видит, вопрос заказа не закрывает.

## Третий исход обязателен (инв. #17), и у каждой оси он свой

* ось A — ``unmeasured``, если сцена не собралась, журнал не разобран **или
  положительный контроль не различает**: когда журнальная ``claim`` не сдвинула поле,
  «второй файл невидим» верно потому, что читатель не работал вовсе, а не потому, что
  канал слеп. Это самое успокоительное из прочтений, и оно запрещено;
* ось B — ``unmeasured``, если полная квитанция не дала нуля: отнимать поля у
  квитанции, которая и так не читается, бессмысленно;
* ось C — ``unmeasured``, если базовый вердикт сцены не ``free`` (урок оси D соседа:
  на занятой карточке переворот нечем увидеть) или если личность сцены опознана
  сторожем как МОЯ — тогда мерился бы самозахват, который сторож блокирующим не
  считает.

## Одностороннее названо заранее

* **Прибор не решает, какой канал заводить.** Он меряет цену каждого у читателя и у
  двери; «что выбрать» — решение, и оно идёт заказом, а не следствием замера.
* **Второго файла в живом дереве прибор НЕ СОЗДАЁТ.** Имя
  :data:`SECOND_FILE_NAME` существует ровно для того, чтобы у сцены был второй адрес;
  артефакта с этим именем в ``data/`` нет, и прибор его не заводит.
* **«Читатель не видит» — свойство СЕГОДНЯШНЕГО читателя.** Это замер, а не приговор
  каналу: цена названа как ОДИН новый вход у одного названного читателя, и во что
  обойдётся правка остальных его читателей, прибор не мерит.
* **Ось C судит ОДНУ дверь — сторожа захвата.** Сколько ещё читателей у поля
  ``card_state`` и что изменится у них от третьего состояния, здесь не измерено
  ВОВСЕ: это соседний вопрос (население читателей поля), и выдавать одну дверь за
  все было бы той же склейкой, из-за которой заказ G110 п. 2 вообще появился.
* **Валидации состояния у писателя нет, и это ИЗМЕРЕНО вызовом.** ``card_state``
  попадает в запись как пришёл; ограничение ``{claim,done}`` живёт только в разборе
  аргументов CLI. Поэтому третье состояние сцена не выдумывает.

## Вердикт

* ``JOURNAL_STATE_STILL_CAPTURES`` — третье состояние записи вред оси D НЕ снимает:
  дверь сторожа читает такую запись как сильный признак и вопрос снова становится
  захватом. Код возврата 1: это находка;
* ``BOTH_CHANNELS_HARMLESS`` — ни один канал вердикта двери не переворачивает. Код 0;
* ``UNMEASURED`` — код 2, перебивает всё.

    python3 -m spa_core.monitoring.receipt_channel_cost
    python3 -m spa_core.monitoring.receipt_channel_cost --json --save
"""
from __future__ import annotations

import argparse
import importlib
import json
import os
import shutil
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

if __package__ in (None, ""):  # pragma: no cover — прямой запуск файла
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from spa_core.monitoring.claim_guard_receipt_readers import (  # noqa: E402
    _ask_guard, _load_guard, _write_sandbox, live_other_anchor,
)
from spa_core.utils.atomic import atomic_save  # noqa: E402
from spa_core.utils.observation import observed  # noqa: E402

ARTIFACT_NAME = "receipt_channel_cost.json"
ORDER = "G110 п. 1 (ADR-535) — цена КАНАЛА квитанции, спрошенная у ЧИТАТЕЛЯ"

STATUS_STATE_STILL_CAPTURES = "JOURNAL_STATE_STILL_CAPTURES"
STATUS_BOTH_HARMLESS = "BOTH_CHANNELS_HARMLESS"
STATUS_UNMEASURED = "UNMEASURED"

#: Читатель, у которого заказ велит спрашивать. Пакетный модуль грузится ВВОЗОМ, а не
#: по пути: ``spec_from_file_location`` рвёт относительные импорты пакета, и четыре
#: двери из девяти ушли бы в «не измерено» как свойство прибора (урок ADR-682).
CENSUS_MODULE = "spa_core.monitoring.duplicate_subject_census"

#: Поле читателя, которым и доказан его читательский статус (ось C соседа, ADR-535).
READER_FIELD = "window_takings_without_receipt"

#: Два кандидата канала — перечень ЗАКРЫТ, потому что закрыт он в самом заказе.
CHANNEL_JOURNAL_STATE = "journal_asked"
CHANNEL_SECOND_FILE = "second_file"
CHANNELS = (CHANNEL_JOURNAL_STATE, CHANNEL_SECOND_FILE)

#: Третье состояние записи — имя из заказа дословно.
STATE_ASKED = "asked"

#: Второй адрес СЦЕНЫ. В живом дереве такого файла нет, и прибор его не заводит.
SECOND_FILE_NAME = "claim_check_receipts.jsonl"

#: Что у квитанции отнимает ось B. Перечень ЗАКРЫТ и выведен из кода читателя:
#: приставка (``summary.startswith``), предмет (``subject_of``), личность
#: (``anchor_of``). Четвёртого требования у читателя нет — и если появится, ось B
#: промолчит, поэтому перечень назван здесь, а не угадывается на месте.
ABLATE_PREFIX = "prefix"
ABLATE_SUBJECT = "subject"
ABLATE_ANCHOR = "anchor"
ABLATIONS = (ABLATE_PREFIX, ABLATE_SUBJECT, ABLATE_ANCHOR)

#: Исходы оси A.
SEEN = "visible"
UNSEEN = "invisible"

_SCENE_CARD = "inbox-proba-kanala-kvitantsii"


# ─────────────────────────── загрузка читателя ───────────────────────────

def load_census(module: str = CENSUS_MODULE):
    """Читатель оси B. Ввозом, а не по пути (см. :data:`CENSUS_MODULE`)."""
    return importlib.import_module(module)


def receipt_prefix(census) -> Optional[str]:
    """Приставка квитанции, взятая У ЧИТАТЕЛЯ.

    Своя копия литерала здесь была бы ровно тем дефектом, который нашёл ADR-682:
    два случайно равных текста выглядят как связанность и расходятся молча. Нет
    приставки у читателя ⇒ ``None``, и ось уходит в третий исход.
    """
    value = getattr(census, "_RECEIPT_PREFIX", None)
    return value if isinstance(value, str) and value else None


def journal_name(census) -> Optional[str]:
    """Имя журнала, которое открывает САМ читатель."""
    value = getattr(census, "JOURNAL_NAME", None)
    return value if isinstance(value, str) and value else None


# ──────────────────────────── одноразовая сцена ───────────────────────────

def _scene_anchor(pid: Optional[int] = None) -> Dict[str, Any]:
    """Личность сцены для осей A и B — живая ПО ПОСТРОЕНИЮ, а не литерал.

    Читатель оси B живость номера не спрашивает вовсе (ему нужна ПАРА), поэтому
    здесь достаточно своего номера: ``os.getpid()`` жив на любом хосте всегда
    (``.claude/rules/deployment.md``, личность процесса). Оси C этого НЕ хватает —
    там номер обязан быть ЧУЖИМ, и она берёт его у ``live_other_anchor``.
    """
    return {"pid": int(pid if pid is not None else os.getpid()),
            "start": "сцена прибора: личность, живая по построению"}


def write_scene(root: Path, *, announcer, prefix: str, journal: str,
                anchor: Dict[str, Any], channel: Optional[str] = None,
                ablate: Optional[str] = None) -> Path:
    """Сцена для осей A и B: ``data``-каталог с журналом НАСТОЯЩЕГО писателя.

    Журнал не собирается строками: его пишет тот самый единственный писатель, чьи
    записи потом читает перепись. Так форма записи не может разойтись со сценой ни
    по одному полю — и прибор остаётся замером читателя, а не замером собственного
    представления о форме.

    ``channel=None`` ⇒ квитанции нет вовсе (отрицательный контроль). Канал
    :data:`CHANNEL_SECOND_FILE` отличается от журнального РОВНО адресом записи:
    пишет его тот же писатель той же формой, меняется только файл — иначе замер
    сравнивал бы канал с каналом плюс ещё с чем-нибудь.
    """
    root.mkdir(parents=True, exist_ok=True)
    log = root / journal
    log.touch()
    # Посторонняя запись без предмета: без неё «взятий ноль» было бы свойством
    # пустого журнала, а не ответом читателя.
    announcer.record("сцена прибора: посторонняя запись без предмета",
                     [str(root / "scene.py")], "сцена", log=str(log))
    process = ({"session_pid": anchor["pid"], "session_pid_start": anchor["start"]},
               "личность сцены, живая по построению")
    announcer.record(f"цикл сцены: взятие карточки {_SCENE_CARD}", [], "",
                     card=_SCENE_CARD, card_state="claim", log=str(log),
                     session=f"pid{anchor['pid']}", process=process)
    if channel is None:
        return log

    summary = f"проверка захвата карточки {_SCENE_CARD} — вердикт free"
    if ablate != ABLATE_PREFIX:
        summary = f"{prefix} {summary}"
    announcer.record(
        summary, [], "квитанция read-only проверки",
        card="" if ablate == ABLATE_SUBJECT else _SCENE_CARD,
        card_state=STATE_ASKED if channel == CHANNEL_JOURNAL_STATE else "claim",
        log=str(root / SECOND_FILE_NAME if channel == CHANNEL_SECOND_FILE else log),
        session=f"pid{anchor['pid']}",
        process=(({}, "личность у квитанции отнята осью B")
                 if ablate == ABLATE_ANCHOR else process))
    return log


def ask_reader(census, log: Path, *, now: Optional[datetime] = None) -> Dict[str, Any]:
    """Число читателя на этой сцене — ЦЕЛИКОМ его путём: загрузчик, потом ось B.

    Часов замер не принимает НАМЕРЕННО, и это решение, а не недосмотр: записи сцены
    только что написал настоящий писатель, то есть их отметка взята у реальных часов
    и свежесть у них ПО ПОСТРОЕНИЮ. Подать далёкий ``now`` значило бы вытолкнуть за
    окно само ВЗЯТИЕ — то есть померить не канал, а окно. ``now`` остаётся входом
    ради симметрии с читателем (он его принимает), но по умолчанию это реальные часы,
    и записка об инъекции здесь была бы неправдой (ADR-479: записка не есть инъекция).
    """
    loaded = census.load_journal(log)
    if not loaded.get("measured"):
        return {"measured": False,
                "reason": f"журнал сцены не разобран: {loaded.get('reason')}"}
    report = census.measure_receipts(loaded["records"], now=now)
    value = observed(report, READER_FIELD, kind=int)
    if value is None:
        return {"measured": False,
                "reason": f"читатель не вернул поле `{READER_FIELD}`"}
    return {"measured": True, "reason": None, "value": int(value),
            "takings": observed(report, "window_takings", kind=int),
            "receipts_in_journal": observed(report, "receipts_in_journal", kind=int),
            "records": len(loaded["records"])}


def _scene_value(census, scene_root: Path, *, announcer, prefix: str, journal: str,
                 anchor: Dict[str, Any], channel: Optional[str],
                 ablate: Optional[str], now: Optional[datetime]) -> Dict[str, Any]:
    """Одна сцена целиком: собрать, спросить читателя, вернуть его число."""
    log = write_scene(scene_root, announcer=announcer, prefix=prefix,
                      journal=journal, anchor=anchor, channel=channel, ablate=ablate)
    return ask_reader(census, log, now=now)


# ────────── ось A: видит ли читатель квитанцию, пришедшую каналом ──────────

def measure_visibility(repo_root: Path, *, census=None, guard_loader=None,
                       anchor: Optional[Dict[str, Any]] = None,
                       now: Optional[datetime] = None) -> Dict[str, Any]:
    """Ось A. Четыре сцены, и две из них — КОНТРОЛЬ, а не данные.

    Различимость обязана быть внутри самого замера: сцена «без квитанции» даёт
    верхнее число, сцена с журнальной ``claim`` — нижнее. Если эти два числа РАВНЫ,
    читатель к квитанции нечувствителен, и «канал невидим» стало бы правдой про
    прибор, а не про канал. Поэтому равенство контролей — ТРЕТИЙ ИСХОД, а не ноль.
    """
    out: Dict[str, Any] = {"measured": False, "reason": None,
                           "field": READER_FIELD, "journal": None,
                           "scenes": {}, "by_channel": {}}
    try:
        census = census or load_census()
        prefix = receipt_prefix(census)
        journal = journal_name(census)
        if prefix is None or journal is None:
            out["reason"] = ("у читателя не объявлена приставка квитанции или имя "
                             "журнала — своей копии литерала прибор не держит")
            return out
        guard = (guard_loader or _load_guard)(repo_root)
        announcer = guard.load_announcer()
    except Exception as exc:  # noqa: BLE001
        out["reason"] = f"читатель или писатель не загружены: {type(exc).__name__}: {exc}"
        return out
    # Имя журнала запоминается ЗДЕСЬ и читается сборкой отсюда: разрешать тот же
    # факт второй раз значило бы завести второй экземпляр мерки (ADR-220).
    out["journal"] = journal

    anchor = anchor or _scene_anchor()
    scene = Path(tempfile.mkdtemp(prefix="spa_receipt_channel_"))
    # Четыре сцены, и первые две — КОНТРОЛЬ: отрицательный (квитанции нет вовсе) и
    # положительный (журнальная квитанция в КАНОНИЧЕСКОМ виде `card_state: claim`,
    # то есть ровно то, что сосед ADR-535 доказал исходом). Без этой пары числа
    # каналов не с чем сравнить.
    plan = (("no_receipt", None),
            ("journal_claim_control", "journal_claim"),
            (CHANNEL_JOURNAL_STATE, CHANNEL_JOURNAL_STATE),
            (CHANNEL_SECOND_FILE, CHANNEL_SECOND_FILE))
    try:
        for name, channel in plan:
            out["scenes"][name] = _scene_value(
                census, scene / name, announcer=announcer, prefix=prefix,
                journal=journal, anchor=anchor, channel=channel,
                ablate=None, now=now)
    except Exception as exc:  # noqa: BLE001
        out["reason"] = f"сцена не отработала: {type(exc).__name__}: {exc}"
        return out
    finally:
        shutil.rmtree(scene, ignore_errors=True)

    unmeasured = [k for k, v in out["scenes"].items() if not v.get("measured")]
    if unmeasured:
        out["reason"] = "; ".join(
            f"{k}: {out['scenes'][k].get('reason')}" for k in unmeasured)
        return out

    base = out["scenes"]["no_receipt"]["value"]
    control = out["scenes"]["journal_claim_control"]["value"]
    out["baseline"] = base
    out["control"] = control
    if base == control:
        out["reason"] = (f"контроль НЕ РАЗЛИЧАЕТ: без квитанции {base}, с журнальной "
                         f"квитанцией {control} — читатель к квитанции нечувствителен, "
                         "и «канал невидим» было бы утверждением о приборе")
        return out

    out["measured"] = True
    for channel in CHANNELS:
        value = out["scenes"][channel]["value"]
        out["by_channel"][channel] = {
            "value": value,
            "outcome": SEEN if value != base else UNSEEN,
        }
    return out


# ───────── ось B: что читатель ТРЕБУЕТ от квитанции (контракт канала) ─────────

def measure_contract(repo_root: Path, *, census=None, guard_loader=None,
                     anchor: Optional[Dict[str, Any]] = None,
                     now: Optional[datetime] = None) -> Dict[str, Any]:
    """Ось B. Отъём по одному полю: что канал ОБЯЗАН нести, чтобы его прочли.

    Контракт меряется ИСХОДОМ, а не чтением кода читателя: у каждой сцены отнято
    РОВНО одно требование, и вердикт выносит сам читатель своим числом. Полная
    квитанция обязана давать нижнее число — иначе отнимать нечего, и ось уходит в
    третий исход.
    """
    out: Dict[str, Any] = {"measured": False, "reason": None,
                           "full": None, "baseline": None, "by_field": {}}
    try:
        census = census or load_census()
        prefix = receipt_prefix(census)
        journal = journal_name(census)
        if prefix is None or journal is None:
            out["reason"] = ("у читателя не объявлена приставка квитанции или имя "
                             "журнала — своей копии литерала прибор не держит")
            return out
        guard = (guard_loader or _load_guard)(repo_root)
        announcer = guard.load_announcer()
    except Exception as exc:  # noqa: BLE001
        out["reason"] = f"читатель или писатель не загружены: {type(exc).__name__}: {exc}"
        return out

    anchor = anchor or _scene_anchor()
    scene = Path(tempfile.mkdtemp(prefix="spa_receipt_contract_"))
    rows: Dict[str, Dict[str, Any]] = {}
    try:
        bare = _scene_value(census, scene / "bare", announcer=announcer, prefix=prefix,
                            journal=journal, anchor=anchor, channel=None,
                            ablate=None, now=now)
        full = _scene_value(census, scene / "full", announcer=announcer, prefix=prefix,
                            journal=journal, anchor=anchor, channel="journal_claim",
                            ablate=None, now=now)
        for field in ABLATIONS:
            rows[field] = _scene_value(
                census, scene / field, announcer=announcer, prefix=prefix,
                journal=journal, anchor=anchor, channel="journal_claim",
                ablate=field, now=now)
    except Exception as exc:  # noqa: BLE001
        out["reason"] = f"сцена не отработала: {type(exc).__name__}: {exc}"
        return out
    finally:
        shutil.rmtree(scene, ignore_errors=True)

    unmeasured = [name for name, row in list(rows.items()) + [("bare", bare), ("full", full)]
                  if not row.get("measured")]
    if unmeasured:
        out["reason"] = "сцены не измерены: " + ", ".join(sorted(unmeasured))
        return out
    out["baseline"] = bare["value"]
    out["full"] = full["value"]
    if full["value"] == bare["value"]:
        out["reason"] = (f"полная квитанция числа не сдвинула ({full['value']} против "
                         f"{bare['value']}) — отнимать у неё поля бессмысленно")
        return out

    out["measured"] = True
    for field, row in rows.items():
        # Поле ТРЕБУЕТСЯ, если без него число вернулось к «квитанции нет».
        out["by_field"][field] = {
            "value": row["value"],
            "required": row["value"] == bare["value"],
        }
    out["required_fields"] = sorted(f for f, r in out["by_field"].items() if r["required"])
    out["optional_fields"] = sorted(f for f, r in out["by_field"].items()
                                    if not r["required"])
    return out


# ────────── ось C: во что канал обходится у ДВЕРИ сторожа захвата ──────────

def measure_door(repo_root: Path, *, guard_loader=None,
                 anchor: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Ось C. Переворачивает ли канал вердикт ``check`` — по каждому каналу отдельно.

    Сцена и способ те же, что у оси D соседа (ADR-535), и это НЕ дубль: вызывается
    ровно его ``_write_sandbox``/``_ask_guard``, то есть второй копии мерки не
    появляется. Ось D ответила про ОДИН канал (журнальная ``claim``); здесь
    спрашивается про два кандидата заказа — третье состояние записи и второй файл.

    Личность сцены обязана быть ЧУЖОЙ и живой: свой захват сторож блокирующим не
    считает, поэтому на своём якоре любой канал выглядел бы безвредным. Это
    проверяется ИСХОДОМ (``self_claims`` в отчёте), а не доверием к номеру.
    """
    out: Dict[str, Any] = {"measured": False, "reason": None,
                           "verdict_without": None, "by_channel": {}, "anchor": None}
    anchor = anchor if anchor is not None else live_other_anchor()
    out["anchor"] = {"pid": anchor.get("pid"), "measured": bool(anchor.get("measured"))}
    if not anchor.get("measured"):
        out["reason"] = (f"личность чужой живой сессии НЕ ИЗМЕРЕНА — {anchor.get('reason')}; "
                         "судить о перевороте вердикта по неизмеренному номеру запрещено")
        return out

    scene = Path(tempfile.mkdtemp(prefix="spa_receipt_door_"))
    answers: Dict[str, Dict[str, Any]] = {}
    try:
        guard = (guard_loader or _load_guard)(repo_root)
        announcer = guard.load_announcer()
        tracker, log = _write_sandbox(scene / "base", _SCENE_CARD, announcer=announcer)
        answers["base"] = _ask_guard(guard, tracker, log, _SCENE_CARD)

        tracker, log = _write_sandbox(scene / CHANNEL_JOURNAL_STATE, _SCENE_CARD,
                                      announcer=announcer, receipt_anchor=anchor,
                                      receipt_state=STATE_ASKED)
        answers[CHANNEL_JOURNAL_STATE] = _ask_guard(guard, tracker, log, _SCENE_CARD)

        side = scene / CHANNEL_SECOND_FILE
        tracker, log = _write_sandbox(side, _SCENE_CARD, announcer=announcer,
                                      receipt_anchor=anchor,
                                      receipt_log=side / SECOND_FILE_NAME)
        answers[CHANNEL_SECOND_FILE] = _ask_guard(guard, tracker, log, _SCENE_CARD)
    except Exception as exc:  # noqa: BLE001
        out["reason"] = f"сцена пробы не отработала: {type(exc).__name__}: {exc}"
        return out
    finally:
        shutil.rmtree(scene, ignore_errors=True)

    verdicts = {name: observed(row["report"], "verdict", kind=str)
                for name, row in answers.items()}
    missing = sorted(name for name, value in verdicts.items() if value is None)
    if missing:
        out["reason"] = "вердикт не произведён на сценах: " + ", ".join(missing)
        return out
    out["verdict_without"] = verdicts["base"]
    if verdicts["base"] != "free":
        out["reason"] = (f"базовый вердикт сцены `{verdicts['base']}`, а не `free` — "
                         "переворот вопроса в захват нечем измерить")
        return out
    for channel in CHANNELS:
        if observed(answers[channel]["report"], "self_claims", kind=list):
            out["reason"] = ("якорь сцены опознан сторожем как МОЙ — переворот мерился "
                             "бы на самозахвате, который сторож блокирующим не считает")
            return out

    out["measured"] = True
    for channel in CHANNELS:
        verdict = verdicts[channel]
        out["by_channel"][channel] = {
            "verdict": verdict,
            "exit_code": answers[channel]["code"],
            "outcome": {"claimed": "question_becomes_claim",
                        "unchecked": "question_becomes_unchecked",
                        "stale": "question_becomes_stale"}.get(verdict, "harmless"),
        }
    return out


# ─────────────────────────────── сборка ──────────────────────────────────

def build_report(repo_root: Path, *, now: Optional[datetime] = None,
                 visibility=None, contract=None, door=None) -> Dict[str, Any]:
    """Отчёт прибора. Форма ПОСТОЯННА: ключи объявлены всегда, «не вычислено» — ``None``."""
    stamp = (now or datetime.now(timezone.utc)).isoformat().replace("+00:00", "Z")
    report: Dict[str, Any] = {
        "generated_at": stamp, "order": ORDER, "measured": False,
        "status": STATUS_UNMEASURED, "reason": None, "applied": False,
        "reader": f"{CENSUS_MODULE.replace('.', '/')}.py::measure_receipts",
        "reader_field": READER_FIELD,
        "visibility": None, "contract": None, "door": None, "answer": None,
    }
    report["visibility"] = (visibility if visibility is not None
                            else measure_visibility(repo_root))
    report["contract"] = (contract if contract is not None
                          else measure_contract(repo_root))
    report["door"] = door if door is not None else measure_door(repo_root)

    unmeasured = [name for name in ("visibility", "contract", "door")
                  if not (report[name] or {}).get("measured")]
    if unmeasured:
        reasons = "; ".join(f"{n}: {(report[n] or {}).get('reason')}"
                            for n in unmeasured)
        report["reason"] = f"не измерено {len(unmeasured)} из 3 осей — {reasons}"
        return report

    report["measured"] = True
    vis = report["visibility"]["by_channel"]
    door_rows = report["door"]["by_channel"]
    captures = door_rows[CHANNEL_JOURNAL_STATE]["outcome"] != "harmless"
    report["status"] = (STATUS_STATE_STILL_CAPTURES if captures
                        else STATUS_BOTH_HARMLESS)
    report["answer"] = {
        "second_file_seen_by_reader": vis[CHANNEL_SECOND_FILE]["outcome"] == SEEN,
        "journal_state_seen_by_reader": vis[CHANNEL_JOURNAL_STATE]["outcome"] == SEEN,
        "second_file_door_outcome": door_rows[CHANNEL_SECOND_FILE]["outcome"],
        "journal_state_door_outcome": door_rows[CHANNEL_JOURNAL_STATE]["outcome"],
        "receipt_required_fields": report["contract"]["required_fields"],
        "reader_input": f"load_journal(data_dir/{report['visibility']['journal']})"
                        " → measure_receipts(records)",
    }
    return report


def save_artifact(report: Dict[str, Any], data_dir: Path) -> Path:
    path = data_dir / ARTIFACT_NAME
    atomic_save(report, str(path))
    return path


def format_report(report: Dict[str, Any]) -> List[str]:
    lines: List[str] = []
    if not report.get("measured"):
        lines.append("цена канала квитанции (заказ G110 п. 1): НЕ ИЗМЕРЕНО — "
                     f"{report.get('reason')}")
        return lines
    vis, contract, door = report["visibility"], report["contract"], report["door"]
    answer = report["answer"]
    lines.append(f"цена канала квитанции (заказ G110 п. 1): {report['status']}")
    lines.append(f"[ЧИТАТЕЛЬ] {report['reader']}, поле `{report['reader_field']}`; "
                 f"путь целиком: {answer['reader_input']}")
    lines.append(f"[ОСЬ A] контроль различает: без квитанции {vis['baseline']} → "
                 f"журнальная квитанция {vis['control']}")
    for channel in CHANNELS:
        row = vis["by_channel"][channel]
        lines.append(f"[ОСЬ A] канал `{channel}`: поле {row['value']} ⇒ "
                     f"{'ВИДЕН читателю' if row['outcome'] == SEEN else 'НЕВИДИМ читателю'}")
    lines.append("[ОСЬ B] контракт квитанции (отъём по одному, вердикт выносит сам "
                 f"читатель): ТРЕБУЕТСЯ {', '.join(contract['required_fields']) or '—'}"
                 + (f" · не требуется {', '.join(contract['optional_fields'])}"
                    if contract["optional_fields"] else ""))
    for field, row in sorted(contract["by_field"].items()):
        lines.append(f"[ОСЬ B] без `{field}`: поле {row['value']} "
                     f"({'квитанция не читается' if row['required'] else 'читается всё равно'})")
    lines.append(f"[ОСЬ C] базовый вердикт сцены `{door['verdict_without']}`; "
                 f"личность сцены чужая и живая (pid {door['anchor']['pid']})")
    for channel in CHANNELS:
        row = door["by_channel"][channel]
        lines.append(f"[ОСЬ C] канал `{channel}`: вердикт `{row['verdict']}` "
                     f"(код {row['exit_code']}) ⇒ {row['outcome']}")
    if report["status"] == STATUS_STATE_STILL_CAPTURES:
        lines.append("ВЫВОД: третье состояние записи вред ADR-535 НЕ снимает — дверь "
                     "сторожа судит по НАЛИЧИЮ поля `card:`, а не по `card_state`, и "
                     "вопрос снова становится захватом. Второй файл у двери безвреден, "
                     "а у читателя невидим: его цена — ОДИН новый вход у названного "
                     "читателя, и этот вход обязан нести "
                     f"{', '.join(answer['receipt_required_fields']) or '—'}")
    lines.append("НЕ ДОКЛАДЫВАЕТ: какой канал ЗАВОДИТЬ (это решение, оно идёт заказом) · "
                 "сколько ещё читателей у поля `card_state` и что изменится у них от "
                 "третьего состояния (население читателей здесь не измерено ВОВСЕ) · "
                 "полезна ли квитанция читателю · во что обойдётся правка остальных "
                 "читателей переписи")
    lines.append("ADVISORY: прибор только ЧИТАЕТ (applied=False) — сцены одноразовые "
                 "(mkdtemp, удаляются в finally), второго файла в живом дереве он НЕ "
                 "СОЗДАЁТ; RiskPolicy v1.0, стоп-кран, аллокатор, живой трек и landing/ "
                 "не трогаются, ни одна строка сторожа не правится")
    return lines


def run(root: Optional[str] = None, *, now: Optional[datetime] = None) -> Dict[str, Any]:
    """Точка входа ступени моста (`findings_bridge`).

    Артефакт оставляется ВСЕГДА, включая третий исход: «не измерено» с названной
    причиной обязано доехать до шага 0-офис, иначе отсутствие файла неотличимо от
    «ступень не запускалась».
    """
    repo_root = Path(root) if root else Path(__file__).resolve().parents[2]
    report = build_report(repo_root, now=now)
    try:
        save_artifact(report, repo_root / "data")
    except Exception as exc:  # noqa: BLE001 — прибор не смеет валить мост
        report = dict(report)
        report["artifact_not_written"] = f"{type(exc).__name__}: {exc}"
    return {"measured": bool(report.get("measured")), "doc": report}


def exit_code_for(report: Dict[str, Any]) -> int:
    if not report.get("measured"):
        return 2
    return 0 if report["status"] == STATUS_BOTH_HARMLESS else 1


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    ap.add_argument("--repo-root", default=None, help="корень дерева (по умолчанию — своё)")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--save", action="store_true", help=f"записать data/{ARTIFACT_NAME}")
    args = ap.parse_args(argv)

    repo_root = Path(args.repo_root) if args.repo_root \
        else Path(__file__).resolve().parents[2]
    report = build_report(repo_root)
    if args.save:
        save_artifact(report, repo_root / "data")
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=1))
    else:
        for line in format_report(report):
            print(line)
    return exit_code_for(report)


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
