"""Предмет захвата — НОМЕР ЗАКАЗА, а не путь файла. Заказ **G109 п. 2** (ADR-534).

Заказ поставлен дословно так:

    Две сессии одного цикла построили один прибор (класс G38 п. 3, рецидив).
    Сторож захвата (``log_session_change``) запись о захвате ПРИНЯЛ у обеих и ни
    одной не сказал, что предмет уже занят. Спросить надо у двери: видит ли шаг
    0a чужой **живой или недавно мёртвый** захват по ПРЕДМЕТУ (номер заказа), а
    не по пути файла, — и мерить население таких пересечений, а не объявлять его
    нулём.

## Почему это НЕ перепись дублей и не её второй экземпляр

Рядом живёт :mod:`spa_core.monitoring.duplicate_subject_census` (заказ G38 п. 3,
ADR-413), и предмет у неё ДРУГОЙ: она меряет **координату** — файл, объявленный
двумя сессиями. Её собственный docstring объясняет, почему она намеренно НЕ
считает сессии на карточке: стоячий приказ владельца по инв. #14 остаётся
``in-progress`` вечно, и сто шестьдесят сессий подряд на нём — передача, а не
столкновение.

Ровно в этом зазоре и живёт заказ G109 п. 2. Внутри ОДНОЙ карточки — стоячего
приказа — работа нарезана на **заказы** (G1…G677), и предмет работы есть номер
заказа, а не путь карточки. Дверь шага 0a/0b (``scripts/check_card_claim.py``)
ключуется на идентификатор карточки; у карточки приказа **113 захватов**, и
вердикт о ней не несёт ни байта о том, какой именно заказ занят. Поэтому:

* перепись дублей отвечает «сколько стоило» в координатах — и ответит верно;
* эта перепись отвечает «виден ли предмет ДВЕРИ и сколько пересечений ПО
  ПРЕДМЕТУ» — и на первый вопрос перепись дублей не отвечает по построению.

Общие помощники (чтение журнала, личность сессии, дерево базового ref,
приведение координаты, родня, снятые координаты) берутся У СОСЕДА и здесь НЕ
переписываются: второй экземпляр мерки расходится молча (ADR-220).

## Две оси, и ни одна не выводится из другой

===== ================================= =========================================
ось   вопрос                            чем меряется
===== ================================= =========================================
A     ВИДИТ ЛИ ДВЕРЬ предмет?           дифференциально, ПО ИСХОДУ: настоящая
                                        дверь на одноразовой сцене, два журнала,
                                        различающиеся ТОЛЬКО номером заказа
B     СКОЛЬКО ПЕРЕСЕЧЕНИЙ по предмету?  журнал объявлений: один номер заказа у
                                        двух и более различных долгоживущих
                                        сессий, в ТРЁХ неслиянных формах
===== ================================= =========================================

Ось A без оси B назвала бы слепоту, не назвав её цены. Ось B без оси A назвала
бы цену, не назвав рычага. И ни одна не имеет права быть выведена из чтения
кода: читатель доказывается ИСХОДОМ (ADR-535, ось C).

## Ось A меряется ИСХОДОМ, и у неё обязателен контроль В ОБЕ СТОРОНЫ

Статический признак («в двери нет ни одного литерала с номером заказа») —
ПРИЗНАК, и у признака нет права быть ответом: дверь могла бы получать предмет
через помощника. Поэтому слепота здесь ЗАМЕР:

1. одноразовая сцена: карточка + журнал, две различные сессии берут ОДНУ
   карточку и в тексте объявления называют ОДИН номер заказа;
2. зовётся НАСТОЯЩАЯ дверь (``check_card_claim.gather``), снимается **решающая
   проекция** отчёта (вердикт + перечень опознанных захватов с их
   классификацией активности) — именно то, на чём дверь решает;
3. второй прогон отличается ТОЛЬКО номером заказа у второй сессии. Проекция
   та же ⇒ **номер заказа до вердикта не доходит**;
4. **положительный контроль**: третий прогон отличается КАРТОЧКОЙ. Проекция
   обязана измениться. Не изменилась ⇒ сцена неспособна двигать вердикт, и
   тогда пп. 2–3 зелены ПО ПОСТРОЕНИЮ — это третий исход
   ``scene_cannot_move_verdict``, объявляемый ГРОМКО, а не «дверь слепа».

Урок, по которому п. 4 обязателен, записан дословно: выживший мутант почти
всегда есть дыра СЦЕНЫ, а не прибора.

## Ось B: формы пересечения РАЗНЫЕ, и склеить их значило бы потерять предмет

``live_overlap``
    наблюдённые отрезки жизни двух сессий ПЕРЕСЕКАЮТСЯ. Отрезок — нижняя
    граница: от старта объявленного долгоживущего процесса до ПОСЛЕДНЕГО
    объявления этой сессии.

    **Ноль здесь ложен ПО ПОСТРОЕНИЮ, и прибор говорит это сам.** Сессия,
    умершая посреди работы, объявлений больше не делает, поэтому её
    наблюдённый отрезок кончается там, где работа только началась, — ровно
    форма рецидива, который заказ и цитирует. Ноль по этой оси публикуется
    вместе со своим опровержением и НИКОГДА не закрывает класс.

``recently_dead``
    заказ сказал «живой ИЛИ НЕДАВНО МЁРТВЫЙ». Предшественник на том же номере
    заказа, чьё последнее объявление отстоит от первого объявления следующей
    сессии не больше чем на окно. Окно — ВХОД, и умолчание у него не из головы:
    :data:`DOOR_GRACE_HOURS` — то же окно свежести 3 ч, которым судит сама
    дверь, поэтому число сравнимо с её вердиктом. Население публикуется на
    НЕСКОЛЬКИХ окнах сразу: зависимость числа от окна обязана быть видна, а не
    спрятана в умолчании.

``succession_undelivered``
    форма, которая НЕ зависит ни от какого окна и потому сильнее двух первых:
    на одном номере заказа работала сессия, чьи объявленные координаты на базе
    ОТСУТСТВУЮТ, а потом тот же номер взяла другая сессия. Это и есть
    наблюдённый вред: работа сделана дважды и первый раз не доехал.

## Предмет читается из СВОБОДНОЙ ПРОЗЫ — и это сказано, а не умолчано

Номера заказа в схеме записи НЕТ: поля ``card``/``files`` его не несут, он живёт
в тексте ``summary``. Отсюда три следствия, названные заранее:

* **население — НИЖНЯЯ граница.** Запись, не назвавшая заказ, считается
  отдельно (``subject_not_named``), а не нулём;
* **один токен — ДВА предмета.** ``G1``…``G5`` в этом приказе суть ЭТАПЫ самого
  приказа («гэп G1», «шаг G5»), а ``G6``…``G677`` — номера ряда заказов. Формы
  считаются ПОРОЗНЬ и не смешиваются: смешать их значило бы изготовить
  столкновение из омонимии;
* **сам прибор предмет НЕ ВВОДИТ в схему.** Завести поле ``order:`` — решение,
  а не замер, и оно идёт заказом, а не этой доставкой.

## Третий исход у каждой оси свой (инв. #17)

* журнала нет / не разобран ⇒ ``UNMEASURED``, код 2;
* дерево базового ref не прочитано ⇒ третья форма ``None``, а не 0;
* ``session_pid_start`` не разобран ⇒ отрезок сессии ``None``, считается отдельно;
* старт ПОЗЖЕ первого объявления ⇒ пересчёт часового пояса под сомнением,
  отрезок НЕ ИЗМЕРЕН (а не подрезан молча); доля подтверждённых пересчётов
  публикуется и есть положительный контроль самого пересчёта;
* личности сессии нет (ярлык личностью не является) ⇒ считается отдельно;
* дверь не загружена / сцена не способна двигать вердикт ⇒ ось A ``None``
  с названной причиной, и это НЕ «дверь видит предмет».

## Что перепись НЕ утверждает

* что каждое пересечение есть потеря: работа бывает передана осознанно;
* что журнал полон — он добровольный, и полноту его прибор не проверяет;
* что дверь ОБЯЗАНА видеть предмет: заводить гейт «нельзя взять занятый заказ»
  эта доставка НЕ предлагает. Причина не менялась с ADR-498 п. 4 и ADR-535
  п. 4 (квитанция в общем журнале превращает ВОПРОС в ЗАХВАТ) — решение идёт
  заказом с измеренным основанием, а не прицепом к замеру;
* что найденные координаты потеряны окончательно: вопрос «списано или
  потеряно» задаётся соседней дверью и его третий исход сохраняется.

ADVISORY: прибор ТОЛЬКО ЧИТАЕТ (``applied=False``), stdlib-only, сети не
трогает, сцены одноразовые (``mkdtemp``). RiskPolicy v1.0, стоп-кран,
аллокатор, живой трек и ``landing/`` не задеты.
"""

from __future__ import annotations

import argparse
import importlib.util
import itertools
import json
import re
import sys
import tempfile
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence, Tuple

from spa_core.monitoring import duplicate_subject_census as dsc
from spa_core.utils.atomic import atomic_save
from spa_core.utils.observation import observed

ARTIFACT_NAME = "order_subject_census.json"
JOURNAL_NAME = dsc.JOURNAL_NAME
ORDER = "G109 п. 2 (ADR-534) — виден ли ДВЕРИ предмет захвата (номер заказа)"

STATUS_OPEN = "CLASS_OPEN"
STATUS_CLOSED = "CLASS_CLOSED"
STATUS_UNMEASURED = "UNMEASURED"

#: Окно свежести, которым судит САМА дверь (`check_card_claim.DEFAULT_GRACE_HOURS`,
#: та же семантика у шага 0a). Умолчание взято у двери, а не выбрано: число
#: населения обязано быть сравнимо с вердиктом, который дверь выдаёт.
DOOR_GRACE_HOURS = 3.0

#: Окна, на которых население «недавно мёртвого» публикуется СРАЗУ. Зависимость
#: числа от окна обязана быть видимой: одно число при одном умолчании выглядит
#: как свойство мира, хотя является свойством выбора.
GRACE_LADDER_HOURS: Tuple[float, ...] = (1.0, DOOR_GRACE_HOURS, 6.0, 24.0)

#: Предмет РЯДА: «заказ G<n>» / «ЗАКАЗ #590 (G7)». Форма ЗАКРЫТА литералом —
#: вычисляемый шаблон тут гадать нечего, а омонимию (ниже) он бы проглотил.
_ORDER_RE = re.compile(r"(?i)\bзаказ[а-яё]*\s+(?:#\d+\s*\(\s*)?G(\d{1,4})\b")

#: Предмет ЭТАПА того же приказа: «гэп G1», «шаг G5», «этап G3». ДРУГОЙ предмет
#: под тем же токеном — считается порознь и с рядом не смешивается.
_STAGE_RE = re.compile(r"(?i)\b(?:гэп|шаг|этап)[а-яё]*\s+G(\d{1,4})\b")

#: Любое упоминание токена. Нужно ровно для одного: отличить «заказ не назван
#: вовсе» от «токен назван формой, которую прибор не разбирает» — второе есть
#: НЕ ИЗМЕРЕНО, а не ноль.
_LOOSE_RE = re.compile(r"\bG(\d{1,4})\b")

#: Поля записи, в которых ищется предмет. `summary` — единственное, где номер
#: заказа вообще бывает; остальные перечислены, чтобы отсутствие было измерено,
#: а не предположено.
_SUBJECT_FIELDS = ("summary", "verified")

#: Решающая проекция отчёта двери — ровно те поля, на которых дверь РЕШАЕТ.
#: Сравнивать отчёт целиком нельзя: он эхом печатает текст объявления, и тогда
#: «номер заказа дошёл до вердикта» подтвердилось бы собственным эхом.
_DECISION_FIELDS = ("verdict", "grace_hours", "card_status")


# ─────────────────────────── предмет записи ───────────────────────────────

def subjects_of(record: Any) -> Dict[str, Any]:
    """Предметы, названные записью: номера РЯДА, номера ЭТАПОВ, и остаток.

    Возвращает ``{"orders": {...}, "stages": {...}, "loose_only": {...}}``.
    ``loose_only`` — токены, найденные свободным поиском и НЕ объяснённые ни
    одной разобранной формой: это «названо формой, которую прибор не читает»,
    то есть НЕ ИЗМЕРЕНО, и в население ряда такой токен не идёт.
    """
    blob = " ".join(str(observed(record, field, kind=str) or "")
                    for field in _SUBJECT_FIELDS)
    orders = {m.group(1) for m in _ORDER_RE.finditer(blob)}
    stages = {m.group(1) for m in _STAGE_RE.finditer(blob)}
    loose = {m.group(1) for m in _LOOSE_RE.finditer(blob)}
    return {"orders": orders, "stages": stages,
            "loose_only": loose - orders - stages}


# ────────────────────── отрезок жизни сессии ──────────────────────────────

def parse_lstart(value: str, *, mktime: Optional[Callable] = None) -> Optional[datetime]:
    """``ps lstart`` («Fri Oct  9 16:06:05 2026») → UTC, или ``None``.

    Отметка НАИВНА: часового пояса в ней нет вовсе, и это свойство ``ps``, а не
    записи. Поэтому пересчёт объявлен ВХОДОМ (``mktime``; умолчание — зона
    хоста), а его правота не предполагается: :func:`intervals_of` проверяет
    каждый пересчёт утверждением «процесс не может писать раньше, чем начался»
    и публикует долю подтверждённых. Пересчёт, не прошедший проверку, даёт
    третий исход, а не подрезанный отрезок.
    """
    try:
        parts = time.strptime(str(value).strip(), "%a %b %d %H:%M:%S %Y")
    except (ValueError, TypeError):
        return None
    try:
        seconds = (mktime or time.mktime)(parts)
    except (OverflowError, ValueError, OSError, TypeError):
        return None
    return datetime.fromtimestamp(seconds, timezone.utc)


def intervals_of(records: Sequence[Dict[str, Any]], *,
                 mktime: Optional[Callable] = None) -> Dict[str, Any]:
    """Наблюдённые отрезки жизни сессий — НИЖНЯЯ граница, с третьими исходами.

    Отрезок сессии считается по ВСЕМ её записям, а не только по тем, что назвали
    заказ: сессия, живая в момент T, жива независимо от того, о чём она в тот
    момент объявляла. Сужение до записей о заказе занизило бы отрезок на
    собственную тему разговора.
    """
    first: Dict[Tuple[int, str], datetime] = {}
    last: Dict[Tuple[int, str], datetime] = {}
    start: Dict[Tuple[int, str], Optional[datetime]] = {}
    no_anchor = 0
    no_stamp = 0
    for record in records:
        anchor = dsc.anchor_of(record)
        if anchor is None:
            no_anchor += 1
            continue
        stamp = dsc._parse_ts(str(observed(record, "ts", kind=str) or ""))
        if stamp is None:
            no_stamp += 1
            continue
        if anchor not in first or stamp < first[anchor]:
            first[anchor] = stamp
        if anchor not in last or stamp > last[anchor]:
            last[anchor] = stamp
        if anchor not in start:
            start[anchor] = parse_lstart(anchor[1], mktime=mktime)

    spans: Dict[Tuple[int, str], Tuple[datetime, datetime]] = {}
    unparsed_start: List[str] = []
    start_after_first: List[str] = []
    corroborated = 0
    for anchor, began in start.items():
        if began is None:
            unparsed_start.append(f"pid{anchor[0]} {anchor[1]!r}")
            # Отметки старта нет ⇒ отрезок считается от ПЕРВОГО объявления. Это
            # по-прежнему нижняя граница, только короче; выдавать её за полную
            # нельзя, поэтому запись об этом идёт в отчёт.
            spans[anchor] = (first[anchor], last[anchor])
            continue
        if began > first[anchor]:
            # Процесс не может писать раньше, чем начался ⇒ пересчёт пояса
            # неверен. Подрезать молча значило бы спрятать поломку меры.
            start_after_first.append(f"pid{anchor[0]} старт {began.isoformat()} "
                                     f"> первое объявление {first[anchor].isoformat()}")
            continue
        corroborated += 1
        spans[anchor] = (began, last[anchor])

    return {"spans": spans,
            "sessions": len(spans),
            "records_without_anchor": no_anchor,
            "records_without_stamp": no_stamp,
            "unparsed_start": sorted(unparsed_start)[:5],
            "unparsed_start_count": len(unparsed_start),
            "conversion_corroborated": corroborated,
            "conversion_refuted": len(start_after_first),
            "conversion_refuted_examples": sorted(start_after_first)[:5]}


# ──────────────────── ось B: население по предмету ────────────────────────

#: Пороги, на которых публикуется ВТОРАЯ дверь родни (ниже). Лестница, а не
#: одно число: порог есть ВЫБОР, и зависимость населения от выбора обязана быть
#: видна читателю, а не спрятана в умолчании.
SET_KIN_LADDER: Tuple[float, ...] = (0.3, 0.5, 0.7)


def kin_by_token_set(coordinate: str, base_paths: Iterable[str],
                     threshold: float) -> Optional[Tuple[float, str]]:
    """ВТОРАЯ дверь родни: НАБОР токенов, а не их НАЧАЛО. Лучший кандидат или ``None``.

    **Зачем вторая дверь.** Родня соседа (:func:`dsc.kin_of`) сравнивает ОБЩЕЕ
    НАЧАЛО имени (порог :data:`dsc._KIN_TOKENS` = 3), и у этого правила есть
    измеренная односторонность: оно слепо к переименованию, которое начало
    имени ТРОГАЕТ. Замер этого цикла — все ШЕСТЬ координат, названных формой 3
    потерянными, суть переименования, и ни одну из них начало имени не видит,
    причём в трёх разных формах:

    * **вставка токена в ГОЛОВУ слага** — объявлено
      ``ADR-506-price-of-an-unmeasured-s49-criterion.md``, на базе лежит
      ``ADR-506-the-price-of-…`` (и то же у ADR-523). Номер ТОТ ЖЕ, слаг
      отличается одним артиклем впереди, общее начало слага — НОЛЬ токенов;
    * **выпадение токена из головы имени** — объявлено
      ``monitoring/test_step_time_census.py``, доставлено
      ``monitoring/step_time_census.py``;
    * **замена токена в середине** — объявлено ``timeout_swallow_census.py``,
      доставлено ``timeout_door_census.py`` (ADR-676): общее начало — один
      токен из трёх.

    Поэтому «потеряно» у соседа есть ВЕРХНЯЯ граница, и прибор говорит это
    числом, а не оговоркой: форма 3 публикуется И по правилу соседа (ведущее
    число, сравнимое с его артефактом), И по этой двери на лестнице порогов.

    **Это по-прежнему ПОДОЗРЕНИЕ, а не доказательство.** Набор токенов не
    знает, та же это работа или соседняя: ``test_series_population_probe``
    против ``test_series_denominator_probe`` делит 0.60, и тем же числом
    делилась бы ДРУГАЯ проба того же ряда. Вторая дверь снимает односторонность
    в одну сторону и ВВОДИТ её в другую — поэтому правило соседа не заменяется,
    а ставится РЯДОМ, и ни одно из двух чисел не объявлено ответом.

    Сосед НЕ правится этой доставкой намеренно: его ``kin_of`` зовут его
    собственные тесты и его артефакт, и расширение родни УМЕНЬШИЛО бы его
    число потерь — то есть выглядело бы как ослабление чужой меры рукой
    соседа (инв. #16). Правка идёт заказом, с этим замером как основанием.
    """
    directory, _, leaf = coordinate.rpartition("/")
    mine = set(dsc._tokens(leaf))
    if not mine:
        return None
    best: Optional[Tuple[float, str]] = None
    for path in base_paths:
        other_dir, _, other_leaf = path.rpartition("/")
        if other_dir != directory or other_leaf == leaf:
            continue
        theirs = set(dsc._tokens(other_leaf))
        union = mine | theirs
        if not union:
            continue
        score = len(mine & theirs) / len(union)
        if score >= threshold and (best is None or score > best[0]):
            best = (round(score, 3), path)
    return best


def _is_directory(coordinate: str, base_paths: Iterable[str]) -> bool:
    """Объявленная координата есть КАТАЛОГ базы, а не файл.

    ``git ls-tree -r`` перечисляет ФАЙЛЫ, поэтому каталог в составе дерева
    отсутствует всегда, и «на базе нет» про каталог — утверждение о форме
    перечня, а не о работе. Замер: сессия на G91 объявила ``docs/decisions``,
    и перепись звала каталог потерей. Односторонне и в сторону завышения цены.
    """
    prefix = coordinate.rstrip("/") + "/"
    return any(path.startswith(prefix) for path in base_paths)


def _coordinates_by_anchor(records: Sequence[Dict[str, Any]],
                           top_level: Iterable[str]) -> Dict[Tuple[int, str], set]:
    out: Dict[Tuple[int, str], set] = {}
    unnormalisable = 0
    for record in records:
        anchor = dsc.anchor_of(record)
        if anchor is None:
            continue
        bucket = out.setdefault(anchor, set())
        for declared in (observed(record, "files", kind=list) or []):
            coordinate = dsc.normalise(str(declared), top_level)
            if coordinate is None:
                unnormalisable += 1
            else:
                bucket.add(coordinate)
    out["_unnormalisable"] = unnormalisable        # type: ignore[index]
    return out


def measure_population(records: Sequence[Dict[str, Any]],
                       base: Optional[Dict[str, Any]], *,
                       mktime: Optional[Callable] = None,
                       grace_ladder: Sequence[float] = GRACE_LADDER_HOURS,
                       set_kin_ladder: Sequence[float] = SET_KIN_LADDER,
                       retirement=None) -> Dict[str, Any]:
    """Ось B: пересечения по номеру заказа в трёх НЕСЛИЯННЫХ формах."""
    intervals = intervals_of(records, mktime=mktime)
    spans = intervals["spans"]

    by_order: Dict[str, List[Tuple[datetime, Tuple[int, str]]]] = {}
    by_stage: Dict[str, set] = {}
    subject_not_named = 0
    loose_only_records = 0
    anchorless_with_order = 0
    for record in records:
        found = subjects_of(record)
        if found["loose_only"]:
            loose_only_records += 1
        if not found["orders"] and not found["stages"]:
            subject_not_named += 1
            continue
        anchor = dsc.anchor_of(record)
        stamp = dsc._parse_ts(str(observed(record, "ts", kind=str) or ""))
        for number in found["stages"]:
            if anchor is not None:
                by_stage.setdefault(number, set()).add(anchor)
        if not found["orders"]:
            continue
        if anchor is None or stamp is None:
            anchorless_with_order += 1
            continue
        for number in found["orders"]:
            by_order.setdefault(number, []).append((stamp, anchor))

    # ── форма 1: отрезки жизни ПЕРЕСЕКАЮТСЯ ──────────────────────────────
    live_overlap: List[Dict[str, Any]] = []
    for number, rows in by_order.items():
        anchors = sorted({a for _, a in rows if a in spans})
        for left, right in itertools.combinations(anchors, 2):
            lo1, hi1 = spans[left]
            lo2, hi2 = spans[right]
            if lo1 <= hi2 and lo2 <= hi1:
                overlap = min(hi1, hi2) - max(lo1, lo2)
                live_overlap.append({
                    "order": number, "sessions": [f"pid{left[0]}", f"pid{right[0]}"],
                    "overlap_hours": round(overlap.total_seconds() / 3600.0, 3)})

    # ── форма 2: предшественник «недавно мёртв» ──────────────────────────
    recently_dead: Dict[str, List[Dict[str, Any]]] = {}
    for hours in grace_ladder:
        window = timedelta(hours=float(hours))
        hits: List[Dict[str, Any]] = []
        for number, rows in by_order.items():
            anchors = sorted({a for _, a in rows if a in spans})
            for left, right in itertools.permutations(anchors, 2):
                gap = spans[right][0] - spans[left][1]
                if timedelta(0) < gap <= window:
                    hits.append({"order": number,
                                 "predecessor": f"pid{left[0]}",
                                 "successor": f"pid{right[0]}",
                                 "gap_hours": round(gap.total_seconds() / 3600.0, 3)})
        recently_dead[f"{float(hours):g}h"] = hits

    # ── форма 3: преемство с НЕДОСТАВЛЕННЫМ предшественником ─────────────
    succession: Optional[List[Dict[str, Any]]] = None
    unnormalisable = 0
    if base is not None and base.get("measured"):
        coords = _coordinates_by_anchor(records, base["top_level"])
        unnormalisable = int(coords.pop("_unnormalisable", 0))   # type: ignore[arg-type]
        dropped = dsc._dropped_coordinates(records, base["top_level"])
        directories = 0
        set_kin_hits: Dict[str, int] = {}
        succession = []
        for number, rows in by_order.items():
            ordered: List[Tuple[int, str]] = []
            for _stamp, anchor in sorted(rows, key=lambda row: row[0]):
                if anchor not in ordered:
                    ordered.append(anchor)
            if len(ordered) < 2:
                continue
            first_seen = {anchor: min(s for s, a in rows if a == anchor)
                          for anchor in ordered}
            for index, anchor in enumerate(ordered[:-1]):
                declared = sorted(coords.get(anchor, set()))
                if not declared:
                    continue
                lost: List[Dict[str, Any]] = []
                for coordinate in declared:
                    if coordinate in base["paths"]:
                        continue
                    if coordinate in dropped:
                        continue                       # объявленное СНЯТИЕ — решение
                    if _is_directory(coordinate, base["paths"]):
                        # Объявлен КАТАЛОГ, а не файл (замер: `docs/decisions` у
                        # G91). «На базе отсутствует» про каталог есть
                        # категориальная ошибка, а не потеря: каталог лежит на
                        # базе, просто `ls-tree` перечисляет файлы. Считать это
                        # потерей значило бы завышать цену односторонне.
                        directories += 1
                        continue
                    if dsc.kin_of(coordinate, base["paths"]):
                        continue                       # подозрение на переименование
                    verdict, note = dsc._retirement_verdict(
                        coordinate,
                        first_seen[anchor].isoformat().replace("+00:00", "Z"),
                        retirement)
                    if verdict == "retired_at_base":
                        continue                       # доставленное списание
                    best = kin_by_token_set(coordinate, base["paths"],
                                            min(set_kin_ladder))
                    for level in set_kin_ladder:
                        if best is not None and best[0] >= level:
                            set_kin_hits[f"{level:g}"] = set_kin_hits.get(
                                f"{level:g}", 0) + 1
                    lost.append({"coordinate": coordinate,
                                 "verdict": verdict, "note": note,
                                 "set_kin_best": best})
                if lost:
                    succession.append({
                        "order": number,
                        "predecessor": f"pid{anchor[0]}",
                        "successor": f"pid{ordered[index + 1][0]}",
                        "declared": len(declared),
                        "lost": lost[:4],
                        "lost_count": len(lost)})

    return {
        "orders_named": len(by_order),
        "orders_with_two_or_more_sessions":
            sum(1 for rows in by_order.values() if len({a for _, a in rows}) > 1),
        "stages_named": len(by_stage),
        "stage_numbers_colliding_with_orders":
            sorted(set(by_stage) & set(by_order), key=lambda s: int(s)),
        "records_total": len(records),
        "records_subject_not_named": subject_not_named,
        "records_token_in_unread_form": loose_only_records,
        "records_with_order_without_identity": anchorless_with_order,
        "coordinates_unnormalisable": unnormalisable,
        "coordinates_declared_as_directory": None if base is None or not base.get("measured")
                                             else directories,
        "intervals": {k: v for k, v in intervals.items() if k != "spans"},
        "live_overlap": live_overlap,
        "live_overlap_count": len(live_overlap),
        "live_overlap_zero_is_false_by_construction": not live_overlap,
        "recently_dead": {k: len(v) for k, v in recently_dead.items()},
        "recently_dead_examples": {k: v[:3] for k, v in recently_dead.items() if v},
        "succession_undelivered": succession,
        "succession_undelivered_count": None if succession is None else len(succession),
        # Сколько ПОТЕРЯННЫХ координат вторая дверь родни объясняет
        # переименованием. Разность и есть измеренная односторонность правила
        # соседа; ни одно из двух чисел ответом не объявлено.
        "lost_explained_by_set_kin": None if succession is None else {
            f"{level:g}": set_kin_hits.get(f"{level:g}", 0)
            for level in set_kin_ladder},
        "lost_coordinates_total": None if succession is None else sum(
            hit["lost_count"] for hit in succession),
    }


# ───────────────────── ось A: видит ли дверь предмет ──────────────────────

def load_door(repo_root: Path):
    """Модуль двери шага 0b (``scripts/check_card_claim.py``), или ``None``."""
    path = Path(repo_root) / "scripts" / "check_card_claim.py"
    if not path.exists():
        return None, f"двери нет по пути {path}"
    try:
        spec = importlib.util.spec_from_file_location("_osc_door", str(path))
        if spec is None or spec.loader is None:           # pragma: no cover
            return None, f"дверь {path} не загружается: спецификация пуста"
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    except Exception as exc:                              # noqa: BLE001
        return None, f"дверь {path} не загружается: {type(exc).__name__}: {exc}"
    return module, None


def _scene(root: Path, *, card: str, orders: Sequence[str], anchors: Sequence[Tuple[int, str]],
           cards_declared: Sequence[str], stamps: Sequence[str]) -> Path:
    """Одноразовая сцена: карточка(и) + журнал двух объявлений. Ничего не правит."""
    tracker = root / "tracker"
    tracker.mkdir(parents=True, exist_ok=True)
    for name in sorted({card, *cards_declared}):
        (tracker / f"{name}.md").write_text(
            "---\ntrackerStatus:\n  type: inbox\n"
            f"title: \"TASK — {name}\"\nstatus: in-progress\n---\n\nтело\n",
            encoding="utf-8")
    log = root / JOURNAL_NAME
    lines = []
    for order, anchor, declared, stamp in zip(orders, anchors, cards_declared, stamps):
        lines.append(json.dumps({
            "ts": stamp,
            "session": f"cycle-{anchor[0]}",
            "summary": f"цикл #{anchor[0]}, ЗАКАЗ G{order} приказа владельца Portfolio CIO",
            "files": [f"/tmp/spa_scene/spa_core/monitoring/thing_{order}.py"],
            "verified": "сцена",
            "card": declared,
            "card_state": "claim",
            "session_pid": anchor[0],
            "session_pid_start": anchor[1],
        }, ensure_ascii=False))
    log.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return log


def _decision_digest(report: Dict[str, Any]) -> Tuple:
    """Решающая проекция отчёта двери: вердикт + опознанные захваты.

    Проекция, а не отчёт целиком, и это объявлено: отчёт печатает ЭХОМ текст
    объявления, поэтому сравнение целиком подтвердило бы «номер дошёл до
    вердикта» собственным эхом, ничего не измерив.
    """
    head = tuple(str(report.get(field)) for field in _DECISION_FIELDS)
    claims = []
    for claim in (report.get("claims") or []):
        if not isinstance(claim, dict):
            continue
        claims.append((str(claim.get("session")), str(claim.get("signal")),
                       str(claim.get("state") or claim.get("verdict") or ""),
                       str(claim.get("active") if "active" in claim else "")))
    return (head, tuple(sorted(claims)))


def measure_door(repo_root: Path, *, door=None, now: Optional[datetime] = None,
                 scene_root: Optional[Path] = None) -> Dict[str, Any]:
    """Ось A: доходит ли НОМЕР ЗАКАЗА до вердикта двери. Замер по ИСХОДУ."""
    out: Dict[str, Any] = {"measured": False, "reason": None,
                           "door_sees_order": None,
                           "subject_parameters": None,
                           "control_moved_verdict": None}
    module = door
    if module is None:
        module, reason = load_door(repo_root)
        if module is None:
            out["reason"] = reason
            return out

    gather = getattr(module, "gather", None)
    if not callable(gather):
        out["reason"] = "у двери нет входа `gather` — спрашивать нечего"
        return out

    # Какими ИМЕНОВАННЫМИ входами дверь вообще принимает предмет. Это НЕ
    # ответ (имя параметра — соглашение), а корроборация к замеру ниже.
    try:
        import inspect
        names = list(inspect.signature(gather).parameters)
    except (TypeError, ValueError):                       # pragma: no cover
        names = []
    out["subject_parameters"] = [n for n in names if n in ("card", "order", "subject")]

    stamp = (now or datetime(2026, 10, 9, 12, 0, tzinfo=timezone.utc))
    # Живость обеих сессий — ВХОД, а не вопрос к живой машине: литеральный
    # номер процесса и есть бомба из `.claude/rules/deployment.md`.
    anchors = [(40001, "Fri Oct  9 13:30:00 2026"), (40002, "Fri Oct  9 13:40:00 2026")]
    stamps = [(stamp - timedelta(minutes=40)).isoformat().replace("+00:00", "Z"),
              (stamp - timedelta(minutes=20)).isoformat().replace("+00:00", "Z")]
    probe = {anchors[0][0]: anchors[0][1], anchors[1][0]: anchors[1][1]}

    def ps(pid):
        value = probe.get(int(pid))
        return (0, value) if value else (1, "")

    base_card = "inbox-scene-standing-order"
    other_card = "inbox-scene-other-card"

    def ask(orders: Sequence[str], declared: Sequence[str]) -> Tuple:
        holder = Path(tempfile.mkdtemp(prefix="osc_scene_",
                                       dir=str(scene_root) if scene_root else None))
        try:
            log = _scene(holder, card=base_card, orders=orders, anchors=anchors,
                         cards_declared=declared, stamps=stamps)
            report = gather(base_card, log=str(log), tracker_dir=str(holder / "tracker"),
                            now=stamp, self_anchor=None, ps=ps, shared_trees=None,
                            repo_root=holder, base_ref="")
            return _decision_digest(report)
        finally:
            for path in sorted(holder.rglob("*"), reverse=True):
                path.unlink() if path.is_file() else path.rmdir()
            holder.rmdir()

    try:
        same = ask(["901", "901"], [base_card, base_card])
        differ = ask(["901", "902"], [base_card, base_card])
        control = ask(["901", "901"], [base_card, other_card])
    except Exception as exc:                              # noqa: BLE001
        out["reason"] = f"дверь не ответила на сцене: {type(exc).__name__}: {exc}"
        return out

    out["control_moved_verdict"] = control != same
    if control == same:
        # Сцена не способна двигать вердикт ⇒ равенство выше зелено ПО
        # ПОСТРОЕНИЮ и слепотой двери НЕ является. Громко и третьим исходом.
        out["reason"] = ("scene_cannot_move_verdict: подмена КАРТОЧКИ вердикта не "
                         "изменила — сцена не способна двигать решение, и равенство "
                         "по номеру заказа ничего не измеряет")
        return out

    out["measured"] = True
    out["door_sees_order"] = same != differ
    out["digests"] = {"same_order": str(same)[:200], "other_order": str(differ)[:200],
                      "other_card": str(control)[:200]}
    return out


# ─────────────────────────────── сборка ──────────────────────────────────

def run_census(data_dir: Path, *, repo_root: Path,
               base_ref: str = dsc.DEFAULT_BASE_REF,
               now: Optional[datetime] = None,
               grace_ladder: Sequence[float] = GRACE_LADDER_HOURS,
               mktime: Optional[Callable] = None,
               door=None,
               history_root: Optional[Path] = None) -> Dict[str, Any]:
    """Отчёт переписи. ``measured=False`` ⇒ вердикта нет вовсе."""
    stamp = (now or datetime.now(timezone.utc)).isoformat().replace("+00:00", "Z")
    report: Dict[str, Any] = {
        "generated_at": stamp,
        "order": ORDER,
        "measured": False,
        "status": STATUS_UNMEASURED,
        "reason": None,
        # Форма отчёта ПОСТОЯННА: ключ объявлен всегда, «не вычислено» — это
        # `None`, а не отсутствие ключа (инв. #17; та же причина, что у соседа).
        "base_ref": None,
        "door": None,
        "population": None,
    }

    journal = dsc.load_journal(data_dir / JOURNAL_NAME)
    report["journal"] = {"records": len(journal["records"]),
                         "unparsed_lines": journal.get("unparsed_lines", 0)}
    if not journal["measured"]:
        report["reason"] = journal["reason"]
        return report

    base = dsc.read_base_tree(repo_root, base_ref)
    report["base_ref"] = ({"ref": base["ref"], "sha": base["sha"],
                           "committed_at": base["committed_at"],
                           "files": len(base["paths"]), "measured": True}
                          if base["measured"]
                          else {"ref": base_ref, "measured": False,
                                "reason": base["reason"]})

    population = measure_population(
        journal["records"], base if base["measured"] else None,
        mktime=mktime, grace_ladder=grace_ladder,
        retirement=(dsc.retirement_door(history_root or repo_root, base["ref"])
                    if base["measured"] else None))
    report["population"] = population
    report["door"] = measure_door(repo_root, door=door, now=now)

    if population["orders_named"] == 0:
        # Слепой проход: ни одного предмета не прочитано ⇒ «пересечений нет»
        # верно ПО ПОСТРОЕНИЮ и ответом не является.
        report["reason"] = ("ни одного номера заказа не прочитано из журнала — "
                            "предмет не измерен, а не отсутствует")
        return report
    if not report["door"]["measured"]:
        report["reason"] = f"ось A не измерена: {report['door']['reason']}"
        return report

    report["measured"] = True
    # Три формы НЕ складываются, когда одна из них не измерена: `... or 0`
    # здесь и есть ровно то, что запрещает инв. #17 — «не измерено» выдало бы
    # себя за «измерено и равно нулю», и сумма занизилась бы МОЛЧА.
    third = population["succession_undelivered_count"]
    windowed = population["live_overlap_count"] + sum(population["recently_dead"].values())
    report["intersections_windowed"] = windowed
    report["intersections_total"] = None if third is None else windowed + third
    # **Класс закрывает ТОЛЬКО ось A, и это решение, а не упрощение.** Нулевое
    # население класс закрыть не вправе ни при каких числах: ноль формы 1 ложен
    # ПО ПОСТРОЕНИЮ (сессия, умершая посреди работы, объявлений не делает), а
    # формы 2 и 3 читают предмет из СВОБОДНОЙ ПРОЗЫ и дают нижнюю границу —
    # 2288 записей заказа не называют вовсе. Закрыть класс по такому нулю
    # значило бы выдать «не измерено» за «измерено и равно нулю» (инв. #17).
    # Поэтому закрытие требует ровно одного: чтобы дверь предмет ВИДЕЛА.
    # Третий исход третьей формы при этом закрыть тоже не вправе (fail-CLOSED:
    # обрезанный клон тише красного теста — урок `pyflakes`).
    report["status"] = (
        STATUS_CLOSED
        if report["door"]["door_sees_order"]
           and population["succession_undelivered_count"] is not None
        else STATUS_OPEN)
    return report


def save_artifact(report: Dict[str, Any], data_dir: Path) -> Path:
    path = Path(data_dir) / ARTIFACT_NAME
    atomic_save(report, str(path))
    return path


def format_report(report: Dict[str, Any]) -> List[str]:
    lines: List[str] = []
    population = report.get("population")
    door = report.get("door")
    if not report.get("measured"):
        lines.append(f"предмет захвата — номер заказа (заказ G109 п. 2): НЕ ИЗМЕРЕНО — "
                     f"{report.get('reason')}")
        if not population:
            return lines
    else:
        lines.append(
            f"предмет захвата — НОМЕР ЗАКАЗА, а не путь файла (заказ G109 п. 2): "
            f"{report['status']} · заказов названо {population['orders_named']} · "
            f"из них у двух и более сессий "
            f"{population['orders_with_two_or_more_sessions']} · "
            + ("пересечений всего НЕ ИЗМЕРЕНО (третья форма не измерена; "
               f"по двум оконным формам {report.get('intersections_windowed')})"
               if report.get("intersections_total") is None
               else f"пересечений всего {report['intersections_total']}"))

    if door and door.get("measured"):
        lines.append(
            "[ОСЬ A · ДВЕРЬ] "
            + ("ВИДИТ номер заказа" if door["door_sees_order"]
               else "НЕ ВИДИТ номер заказа: подмена номера вердикт не меняет")
            + f"; именованные входы предмета: {door['subject_parameters'] or '—'}"
            + "; положительный контроль (подмена КАРТОЧКИ) вердикт "
            + ("сдвинул" if door["control_moved_verdict"] else "НЕ сдвинул"))
    elif door:
        lines.append(f"[ОСЬ A · ДВЕРЬ] НЕ ИЗМЕРЕНО — {door.get('reason')}")

    if population:
        lines.append(
            f"[ОСЬ B · форма 1 · живое пересечение] {population['live_overlap_count']}"
            + (" — и этот НОЛЬ ЛОЖЕН ПО ПОСТРОЕНИЮ: сессия, умершая посреди работы, "
               "объявлений больше не делает, поэтому её наблюдённый отрезок кончается "
               "там, где работа только началась"
               if population["live_overlap_zero_is_false_by_construction"] else ""))
        lines.append("[ОСЬ B · форма 2 · недавно мёртвый предшественник] " + " · ".join(
            f"окно {window}: {count}"
            for window, count in population["recently_dead"].items())
            + f" — окно есть ВХОД; умолчание {DOOR_GRACE_HOURS}ч взято у самой двери")
        if population["succession_undelivered_count"] is None:
            lines.append("[ОСЬ B · форма 3 · преемство с недоставленным предшественником] "
                         "НЕ ИЗМЕРЕНО — дерево базового ref не прочитано; это НЕ ноль")
        else:
            lines.append(
                "[ОСЬ B · форма 3 · преемство с недоставленным предшественником] "
                f"{population['succession_undelivered_count']} — форма, НЕ зависящая "
                "ни от какого окна, и потому сильнейшая из трёх")
            for hit in (population["succession_undelivered"] or [])[:8]:
                head = hit["lost"][0]
                kin = head.get("set_kin_best")
                lines.append(f"  [G{hit['order']}] {hit['predecessor']} объявил "
                             f"{hit['declared']} координат, НЕ доехало {hit['lost_count']}"
                             f" ({head['coordinate']}) → далее {hit['successor']}"
                             + (f" · вторая дверь родни: {kin[1]} ({kin[0]})"
                                if kin else " · родни не нашла ни одна дверь"))
            explained = population.get("lost_explained_by_set_kin") or {}
            lines.append(
                f"[ОДНОСТОРОННОСТЬ · ИЗМЕРЕНА] потерянных координат всего "
                f"{population.get('lost_coordinates_total')}; вторая дверь родни "
                "(НАБОР токенов, а не их НАЧАЛО) объясняет переименованием: "
                + " · ".join(f"порог {k}: {v}" for k, v in explained.items())
                + " — значит «потеряно» по правилу соседа есть ВЕРХНЯЯ граница; "
                  "оба числа стоят рядом, ответом не объявлено ни одно")
        lines.append(
            f"[ПРЕДМЕТ ИЗ ПРОЗЫ · нижняя граница] записей всего "
            f"{population['records_total']} · заказ НЕ НАЗВАН у "
            f"{population['records_subject_not_named']} · токен в форме, которую прибор "
            f"НЕ ЧИТАЕТ (НЕ ИЗМЕРЕНО, не ноль) у "
            f"{population['records_token_in_unread_form']} · заказ назван без личности "
            f"сессии у {population['records_with_order_without_identity']}")
        lines.append(
            f"[ОМОНИМИЯ] этапов приказа названо {population['stages_named']}; номера, "
            f"стоящие И как этап, И как заказ: "
            f"{population['stage_numbers_colliding_with_orders'] or '—'} — считаются "
            "ПОРОЗНЬ: смешать значило бы изготовить столкновение из омонимии")
        intervals = population["intervals"]
        lines.append(
            f"[ОТРЕЗКИ ЖИЗНИ] сессий с измеренным отрезком {intervals['sessions']} · "
            f"пересчёт пояса подтверждён у {intervals['conversion_corroborated']}, "
            f"ОПРОВЕРГНУТ у {intervals['conversion_refuted']} (отрезок НЕ ИЗМЕРЕН, "
            f"а не подрезан) · старт не разобран у {intervals['unparsed_start_count']} · "
            f"записей без личности {intervals['records_without_anchor']}")
        if population.get("coordinates_declared_as_directory"):
            lines.append(f"[НЕ ПОТЕРЯ] объявленных КАТАЛОГОВ (а не файлов): "
                         f"{population['coordinates_declared_as_directory']} — «на базе "
                         "нет» про каталог есть утверждение о форме перечня `ls-tree`, "
                         "а не о работе; в цену не идут")
        if population["coordinates_unnormalisable"]:
            lines.append(f"[НЕ ИЗМЕРЕНО] координат, не приведённых к пути репозитория: "
                         f"{population['coordinates_unnormalisable']} — форма 3 на них "
                         "не судит вовсе")

    lines.append("НЕ ДОКЛАДЫВАЕТ: полноту добровольного журнала · была ли пара сессий "
                 "передачей или переделкой · верность самой двери · ЦЕНУ в координатах "
                 "(это предмет соседа `duplicate_subject_census`, и второй экземпляр "
                 "мерки запрещён)")
    lines.append("НЕ ПРЕДЛАГАЕТ гейт «нельзя взять занятый заказ»: причина не менялась "
                 "с ADR-498 п. 4 и ADR-535 п. 4 — квитанция в ОБЩЕМ журнале превращает "
                 "ВОПРОС в ЗАХВАТ. Решение идёт заказом, а не прицепом к замеру")
    lines.append("ADVISORY: прибор только ЧИТАЕТ журнал и дерево базового ref; "
                 "RiskPolicy v1.0, стоп-кран, аллокатор, живой трек и landing/ не тронуты")
    return lines


def run(root: Optional[str] = None, *, now: Optional[datetime] = None) -> Dict[str, Any]:
    """Точка входа ступени моста (`findings_bridge`).

    Артефакт оставляется ВСЕГДА, включая третий исход: «не измерено» с
    названной причиной обязано доехать до читателя, иначе шаг 0-офис увидит
    отсутствие файла и не отличит его от «ступень не запускалась».
    """
    repo_root = Path(root) if root else Path(__file__).resolve().parents[2]
    data_dir = repo_root / "data"
    report = run_census(data_dir, repo_root=repo_root, now=now)
    try:
        save_artifact(report, data_dir)
    except Exception as exc:  # noqa: BLE001 — перепись не смеет валить мост
        report = dict(report)
        report["artifact_not_written"] = f"{type(exc).__name__}: {exc}"
    return {"measured": bool(report.get("measured")), "doc": report}


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    ap.add_argument("--data-dir", default=None, help="каталог данных (по умолчанию — свой)")
    ap.add_argument("--repo-root", default=None, help="корень дерева (по умолчанию — свой)")
    ap.add_argument("--history-root", default=None,
                    help=("корень ПОЛНОГО клона для вопроса «координату списали или "
                          "потеряли» (обрезанное дерево честно отвечает НЕ ИЗМЕРЕНО)"))
    ap.add_argument("--base-ref", default=dsc.DEFAULT_BASE_REF, help="базовый ref доставки")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--save", action="store_true", help=f"записать {ARTIFACT_NAME}")
    args = ap.parse_args(argv)

    repo_root = Path(args.repo_root) if args.repo_root else Path(__file__).resolve().parents[2]
    data_dir = Path(args.data_dir) if args.data_dir else (repo_root / "data")
    report = run_census(data_dir, repo_root=repo_root, base_ref=args.base_ref,
                        history_root=Path(args.history_root) if args.history_root else None)
    if args.save:
        save_artifact(report, data_dir)
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=1, default=str))
    else:
        for line in format_report(report):
            print(line)
    if not report.get("measured"):
        return 2
    return 1 if report["status"] == STATUS_OPEN else 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
