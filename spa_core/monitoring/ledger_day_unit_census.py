"""Перепись ЕДИНИЦЫ у читателей ленты вердиктов: запись или день (заказ G765 п. 3).

Тень советника ADR-060 ведёт по каждой книге append-only ленту вердиктов
(``allocation_rationale_history[_<book>].jsonl``). Лента — журнал ПРОГОНОВ, а не
дней, и плотность у книг РАЗНАЯ. Замер 16.10 по живому ``data/``:

===========  =========  =====  ====================  ==========
книга        записей    дней   записей на день       за 15.10
===========  =========  =====  ====================  ==========
conservative       138     72   1.92                  3
balanced           727     45   **16.16**             **24**
aggressive         727     45   **16.16**             **24**
===========  =========  =====  ====================  ==========

Цикл #881 ([ADR-765]) починил ОДНОГО читателя — выдачу владельцу: там серия
«323-й день подряд без изменений» была посчитана в ЗАПИСЯХ на ленте возрастом
45 дней. Остальные читатели не переписывались ни разу, и заказ G765 п. 3 именно
об этом: *«лента пишется ≈16 раз за цикл, и любой прибор, считающий по записям,
завышает в ~16 раз; починен один читатель — выдача владельцу»*.

**Почему это не ловится грепом.** Счёт живёт не в одном выражении: ``len(rows)``
может быть верным (строк действительно столько), а неверным — СЛОВО рядом с
числом. Структура отвечает «есть ли здесь len», предмет же — «какую единицу
читатель НАЗЫВАЕТ, когда печатает это число». Поэтому перепись меряет ИСХОДОМ
(`.claude/rules/acceptance.md`, п. 3), на двух стендах.

## Два стенда, различающиеся РОВНО плотностью

``s_one``  — один прогон в день;
``s_many`` — ``factor`` прогонов того же дня.

Инварианты стендов, и они держат весь вывод:

* **состав ДНЕЙ тождествен** — ни один день не появился и не исчез;
* **последняя строка каждого дня ПОБАЙТНО та же** — то есть всякий читатель,
  схлопывающий день по правилу писателя (:func:`allocation_rationale.
  run_identity`, «позже — главнее»), обязан получить ОДИН И ТОТ ЖЕ ответ;
* материал подложки — настоящие строки ТОГО ЖЕ дня, перештампованные по
  ``generated_at`` строго РАНЬШЕ последней строки дня. Выдуманная строка
  проверяла бы читателя на том, чего писатель никогда не писал.

Отсюда вывод строгий: ответ, РАЗОШЕДШИЙСЯ между стендами, зависит от числа
прогонов в дне и ни от чего другого.

## Две оси, и смешивать их нельзя

Чувствительность к плотности сама по себе НЕ есть дефект: читатель оси прогонов
(``cio_shadow_replay``, ``run_identity_key_price``) обязан её иметь — для него
прогон и есть предмет. Дефект — ПЕРЕСЕЧЕНИЕ:

1. **ось плотности** — разошёлся ли ответ (замер, стенды выше);
2. **ось имени** — называет ли читатель свою единицу ДНЁМ, и спрашивается это у
   КЛЮЧЕЙ его собственного ответа (``unchanged_days``, ``evidenced_days``), а
   не у прозы. Проза может сказать «дней» и при этом не нести поля вовсе
   ([ADR-333]: зачёт меряется значением, а не подстрокой).

Находка :data:`F_RECORDS_AS_DAYS` — координата, чьё ИМЯ говорит «день» и чьё
ЗНАЧЕНИЕ сдвинулось от одной лишь плотности. Это ровно дефект, найденный
ADR-765 у выдачи владельцу, — и теперь он ищется у ВСЕХ.

Читатель, чувствительный к плотности и НЕ назвавший единицу ни одним ключом,
попадает в отдельный перечень :data:`NEEDS_READING`: находкой он не объявляется
(судить нечем — третий исход, инв. #17), но и не растворяется в «чисто».

## Чего перепись НЕ доказывает

* Не доказывает, что читатель, названный ``day_invariant``, вообще что-то
  считает: ответ мог не зависеть от ленты ни одним полем. Вопрос «читает ли он
  ленту» решается НАСЕЛЕНИЕМ (две дороги, :func:`run_identity_key_price.
  reader_population`), а не этой осью.
* Не доказывает отсутствия дефекта у читателя, чей ответ перепись снять не
  смогла: такой читатель — ``unmeasured`` с названной причиной, и это НЕ зачёт.
* Не судит ПИСАТЕЛЕЙ ленты и не чинит ни одного: прибор только ЧИТАЕТ.

LLM forbidden. Pure stdlib. Прибор ADVISORY: ни один гейт его не читает.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import argparse
import collections
import copy
import datetime as dt
import importlib
import json
import re
import shutil
import signal
import tempfile
import time
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Set, Tuple

from spa_core.monitoring.run_identity_key_price import (
    CAUSE_ENTRY_RAISED,
    CAUSE_IMPORT_FAILED,
    CAUSE_RESTS_ON_UNSTABLE,
    CAUSE_SELF,
    CAUSE_WOULD_ACT,
    CLOCK_FIELDS,
    STAND_EXCLUDE,
    _NEVER_CALL,
    _STABILITY_PROBE_DELAY_S,
    clock_kwarg,
    mask_coords,
    module_driver,
    no_entry_cause,
    reader_population,
    unstable_coords,
)
from spa_core.monitoring.timeout_door_census import is_foreign_failure
from spa_core.paper_trading.allocation_rationale import history_filename, run_identity
from spa_core.utils.atomic import atomic_save

VERSION = "ledger-day-unit-census-v1"

#: Артефакт и его производитель — ОБЪЯВЛЕНИЕ, а не вывод из кода (ADR-154/158).
#: Сверяется с `findings_bridge.CENSUS_PRODUCT` и с конституцией
#: (`architecture/manifest.json`).
ARTIFACT = "ledger_day_unit_census.json"
PRODUCER = "spa_core/monitoring/ledger_day_unit_census.py"

_ROOT = Path(__file__).resolve().parents[2]

#: Такт переизмерения. Прогон зовёт КАЖДОГО читателя населения дважды и копирует
#: `data/` два раза — он стои́т минуты, а не доли секунды. Срок решает ФАЙЛ
#: (:func:`measurement_due`), а не расписание бегуна: иначе «раз в неделю»
#: держалось бы на том, что никто не трогал cron.
MEASUREMENT_TACT_DAYS = 8

#: Книги, у которых есть своя лента. ``None`` — Conservative (исходное имя).
#: Тот же список, что у `vacuous_advice_census.BOOKS`, и он тут НЕ копия ради
#: копии: маршрутизацию имени файла обе переписи берут у ПИСАТЕЛЯ
#: (`history_filename`), поэтому разойтись с ним они не могут.
BOOKS: Tuple[Tuple[str, Optional[str]], ...] = (
    ("conservative", None),
    ("balanced", "balanced"),
    ("aggressive", "aggressive"),
)

# ── исходы читателя ──────────────────────────────────────────────────────────
OUT_DAY_INVARIANT = "day_invariant"
OUT_RECORD_SENSITIVE = "record_sensitive"
OUT_UNMEASURED = "unmeasured"

#: Отказ ЗВАТЬ соседа, который сам гоняет перепись по населению. Это не «не
#: удалось измерить»: точка входа у него есть, и именно поэтому её нельзя
#: приводить — зов поднял бы полную перепись на КАЖДОМ из двух стендов, а внутри
#: неё поднялся бы следующий такой сосед. Причина своя, а не общее ведро.
CAUSE_SWEEPS_POPULATION = "sweeps_a_reader_population"

#: Население не прочитано/пусто — третий исход у самой переписи.
CAUSE_NO_STANDS = "stands_not_built"

# ── находки ──────────────────────────────────────────────────────────────────
#: Дефект класса ADR-765: координата с именем дня, сдвинувшаяся от плотности.
F_RECORDS_AS_DAYS = "records_counted_as_days"

#: Не находка, а перечень к ЧТЕНИЮ: чувствителен, но единицу не назвал.
NEEDS_READING = "record_sensitive_unit_unnamed"

STATUS_CLEAN = "CLEAN"
STATUS_FINDINGS = "FINDINGS"
STATUS_UNMEASURED = "UNMEASURED"

#: Корни имён, по которым координата ответа признаётся НАЗВАННОЙ в днях.
#: Список именной и узкий НАМЕРЕННО. Образец «что-нибудь про время» захватил бы
#: `age_s`, `hours`, `ttl` — у них единица названа ВЕРНО и к предмету заказа они
#: не относятся; расширение в эту сторону покрасило бы исправных читателей и
#: научило бы гасить перепись. Обратная ошибка (пропустить читателя, назвавшего
#: день словом не из списка) остаётся названной границей, а не тишиной:
#: такой читатель попадает в `NEEDS_READING`, то есть НА учёт, а не в «чисто».
DAY_NAME_TOKENS: Tuple[str, ...] = ("day", "days", "дн", "дней", "дня", "день",
                                    "сутк", "daily")

#: Координата опознаётся по ПОСЛЕДНЕМУ сегменту имени — тому, который и печатает
#: число. Полный путь ловил бы всё поддерево под ключом `days`, то есть считал бы
#: названным в днях и то, что названо иначе внутри него.
_SEG = re.compile(r"[.\[]")

#: Минимальная плотность стенда ``s_many``. Два прогона в дне — уже différence;
#: ниже двух стенды тождественны и мерить нечем.
_MIN_FACTOR = 2

#: Потолок плотности. Нужен не ради скорости: лента 45 дней × factor строк
#: читается каждым из ~110 читателей, и неограниченный factor превратил бы
#: перепись в нагрузочный тест вместо замера. Замеренный максимум (24) лежит
#: далеко внутри потолка, поэтому потолок сегодня ни на что не влияет — и это
#: сказано вслух, чтобы завтра он не повлиял молча.
_MAX_FACTOR = 48


#: Бюджет ОДНОГО зова читателя, в секундах. Нужен не для скорости, а чтобы у
#: прогона был КОНЕЦ: замер 16.10 — безбюджетный обход всего населения на
#: наблюдённой плотности (1728 строк у Conservative, 1080 у рукавов) шёл более
#: 35 минут при 99 % CPU и не закончился, потому что часть читателей строит
#: внутри себя СВОИ стенды и копии `data/`. Прибор без конца не работает вовсе,
#: а «не измерено» с названной причиной — исход, который можно читать.
CALL_BUDGET_S = 90.0

#: Зов не уложился в бюджет. ТРЕТИЙ исход, а не «чисто» и не находка: что
#: читатель ответил бы, не наблюдено.
CAUSE_OVER_BUDGET = "entry_exceeded_budget"

#: Окно ленты для ПОВТОРНОГО зова тех, кто не уложился в бюджет (ADR-767,
#: заказ G766 п. 3). Бюджет дал прогону КОНЕЦ, но не дал ОТВЕТА: строка
#: `entry_exceeded_budget` не говорит о читателе ничего. Предмет вопроса —
#: сдвиг координаты от ОДНОЙ ЛИШЬ плотности записей — не требует всей ленты:
#: он виден и на горстке дней, если плотность между стендами та же. Поэтому
#: второй зов идёт по УРЕЗАННОМУ окну, а не по щедрому бюджету: щедрый бюджет
#: платит временем за тот же самый неответ, а урезанное окно меняет ЦЕНУ
#: вопроса.
#:
#: Семь дней — вход с названной причиной, а не константа из головы: окно обязано
#: нести хотя бы один день с подложкой (иначе стенды тождественны и мерить
#: нечем) и остаться заметно дешевле ленты в 45–72 дня. Число подаётся
#: аргументом (``short_window_days``) именно потому, что оно спорно.
SHORT_WINDOW_DAYS = 7

#: Зов не уложился в бюджет И на урезанном окне. Цена читателя лежит НЕ в ленте
#: (он строит внутри себя свои стенды или копии `data/`), поэтому средство из
#: заказа G766 п. 3 на него не действует — и это сказано, а не замаскировано
#: под «дорого, но когда-нибудь измерим».
CAUSE_OVER_BUDGET_SHORT = "entry_exceeded_budget_on_short_window"

#: Координата с именем дня НЕ сдвинулась — но наблюдение снято на урезанном
#: окне. Это НЕ «чисто»: «не сдвинулось на 7 днях» не доказывает «не сдвинется
#: на 45». Читатель с оглядкой назад длиннее окна (30-дневный lookback) на
#: коротком окне инвариантен ПО ПОСТРОЕНИЮ. Поэтому исход — третий (инв. #17),
#: а не зачёт; ПОЛОЖИТЕЛЬНАЯ же сторона (сдвиг найден) на коротком окне
#: полноценна: сдвиг есть сдвиг.
CAUSE_INVARIANT_SHORT_ONLY = "day_invariant_only_on_short_window"

#: Урезанное окно не построилось (ленты короче окна нечем резать, стенд не
#: записался). Своя причина, а не общее ведро.
CAUSE_SHORT_STAND_ABSENT = "short_window_stand_not_built"

#: Бюджет не удалось установить (не главный поток). Записывается ФАКТОМ, потому
#: что безбюджетный зов и зов под бюджетом — разные наблюдения, и выдать первый
#: за второй значило бы соврать о том, что прогон ограничен.
BUDGET_NOT_INSTALLED = "budget_not_installable_off_main_thread"


class _OverBudget(BaseException):
    """Срок зова, а не отказ модуля: поднимается будильником прибора."""


def _budget_installable() -> bool:
    """Можно ли поставить будильник — спрашиваем у ОС, а не угадываем по имени."""
    try:
        signal.signal(signal.SIGALRM, signal.getsignal(signal.SIGALRM))
    except (ValueError, OSError, AttributeError):
        return False
    return True


def _call_within_budget(call, stand: Path, budget: float):
    """Позвать читателя под будильником. Не уложился ⇒ :class:`_OverBudget`.

    ГРАНИЦА, названная вслух: читатель, который сам пользуется ``SIGALRM``,
    перебьёт этот будильник, и тогда зов снова безграничен. Такой читатель
    по-прежнему будет измерен, но утверждение «прогон ограничен» про него не
    верно — поэтому факт установки пишется в строку (``budget_s``), а не
    подразумевается.
    """
    def _fire(_sig, _frame):
        raise _OverBudget(f"зов не уложился в {budget:g} с")

    previous = signal.signal(signal.SIGALRM, _fire)
    signal.setitimer(signal.ITIMER_REAL, budget)
    try:
        return call(stand)
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0.0)
        signal.signal(signal.SIGALRM, previous)


def _utcnow() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def _sweepers(tree_root: Path) -> Dict[str, str]:
    """Модули, которые САМИ гоняют перепись по населению, — замером по исходнику.

    Мера СТРУКТУРНАЯ, и это осознанный выбор направления: она служит ОТКАЗУ
    звать (fail-CLOSED). Ошибка в сторону лишнего отказа стои́т одной строки
    `unmeasured` с названной причиной; ошибка в другую сторону стои́т рекурсии
    по всему населению на каждом стенде. Поэтому здесь структура допустима там,
    где для ЗАЧЁТА она была бы запрещена.
    """
    needles = ("reader_population(", "classify_reader(", "classify_http_reader(")
    out: Dict[str, str] = {}
    for pkg in ("spa_core", "scripts"):
        base = Path(tree_root) / pkg
        if not base.exists():
            continue
        for path in sorted(base.rglob("*.py")):
            rel = path.relative_to(tree_root).as_posix()
            if "/tests/" in rel:
                continue
            try:
                src = path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            hit = [n for n in needles if n in src]
            if not hit:
                continue
            # Объявление самих помощников — не их зов.
            if rel == "spa_core/monitoring/run_identity_key_price.py":
                hit = ["объявляет и гоняет перепись читателей"]
            out[rel[:-3].replace("/", ".")] = (
                "гоняет перепись по населению (" + ", ".join(hit) + ")")
    return out


def read_book_rows(data_dir: Path, book_id: Optional[str]
                   ) -> Tuple[Optional[List[dict]], str]:
    """Строки ленты книги в порядке ФАЙЛА — или названная причина их отсутствия.

    Порядок файла, а не отсортированный: стенд обязан воспроизводить то, что
    писатель написал. Нечитаемая строка СЧИТАЕТСЯ и не роняет замер, но и не
    попадает в стенд — иначе стенд унёс бы в себя чужую поломку.
    """
    path = Path(data_dir) / history_filename(book_id)
    if not path.is_file():
        return None, f"ленты {path.name} нет"
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        return None, f"лента {path.name} не прочитана: {type(exc).__name__}"
    rows: List[dict] = []
    bad = 0
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except ValueError:
            bad += 1
            continue
        if isinstance(obj, dict):
            rows.append(obj)
        else:
            bad += 1
    if not rows:
        return None, f"лента {path.name} не несёт ни одной разобранной строки"
    return rows, (f"нечитаемых строк {bad}" if bad else "")


def density(rows: Sequence[dict]) -> dict:
    """Записей, дней и плотность — ЗАМЕР ленты, а не константа правила.

    ``days`` считается по ``cycle_date``; строка без даты даёт ТРЕТИЙ исход
    (``undated``), а не свой день и не ноль: выдать её за день значило бы
    придумать наблюдение, а молча выбросить — занизить знаменатель.
    """
    per_day: "collections.Counter[str]" = collections.Counter()
    undated = 0
    for row in rows:
        raw = row.get("cycle_date")
        if raw is None or str(raw).strip() == "":
            undated += 1
            continue
        per_day[str(raw)] += 1
    counts = sorted(per_day.values())
    return {
        "records": len(rows),
        "days": len(per_day),
        "undated_records": undated,
        "records_per_day_mean": (round(sum(counts) / len(counts), 4)
                                 if counts else None),
        "records_per_day_max": (counts[-1] if counts else None),
        "latest_day": (max(per_day) if per_day else None),
    }


def measured_factor(books: Dict[str, dict]) -> Tuple[int, str]:
    """Плотность стенда ``s_many`` — ИЗМЕРЕННАЯ, а не выбранная.

    Берётся наибольший наблюдённый «записей в день» по всем лентам: стенд обязан
    воспроизводить ту плотность, которая у нас УЖЕ есть, иначе он проверял бы
    читателя на вымышленной нагрузке. Ни одной ленты не прочитано ⇒ третий исход
    (``None``-повода нет: причина называется строкой).
    """
    seen = [(name, b["density"]["records_per_day_max"])
            for name, b in sorted(books.items())
            if b.get("density", {}).get("records_per_day_max")]
    if not seen:
        return _MIN_FACTOR, ("плотность не измерена ни по одной ленте — "
                             f"стенд взят минимальным ({_MIN_FACTOR})")
    name, top = max(seen, key=lambda item: item[1])
    if top >= _MAX_FACTOR:
        return _MAX_FACTOR, (f"наблюдённый максимум {top} у ленты {name} выше "
                             f"потолка — стенд урезан до {_MAX_FACTOR}")
    if top < _MIN_FACTOR:
        return _MIN_FACTOR, (f"наблюдённый максимум {top} у ленты {name} ниже "
                             f"двух — стенд поднят до {_MIN_FACTOR}: при одном "
                             f"прогоне в дне стенды тождественны")
    return int(top), f"наблюдённый максимум записей в день: {top} (лента {name})"


def _shift_stamp(raw, seconds: int) -> Optional[str]:
    """Отметка прогона, сдвинутая НАЗАД на *seconds*. Не разобрали — ``None``."""
    text = str(raw or "").strip()
    if not text:
        return None
    try:
        moment = dt.datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    return (moment - dt.timedelta(seconds=seconds)).isoformat()


def thicken(rows: Sequence[dict], factor: int) -> Tuple[List[dict], List[dict], dict]:
    """Две ленты из одной: ``one`` (1 прогон в дне) и ``many`` (*factor* прогонов).

    Инварианты (на них стои́т весь вывод переписи, поэтому они проверяются
    тестом в обе стороны):

    * состав дней у обеих лент ТОЖДЕСТВЕН;
    * последняя строка дня у обеих ПОБАЙТНО одна и та же;
    * подложка — настоящие строки ТОГО ЖЕ дня, перештампованные по
      ``generated_at`` строго раньше последней строки дня, то есть у каждой
      своя :func:`run_identity` и ни одна не сталкивается с главной.

    День, чью отметку разобрать не удалось, в подложку НЕ попадает: он
    возвращается причиной (``days_not_thickened``) — третий исход вместо тихой
    подстановки выдуманного времени.
    """
    by_day: "collections.OrderedDict[str, List[dict]]" = collections.OrderedDict()
    undated: List[dict] = []
    for row in rows:
        raw = row.get("cycle_date")
        if raw is None or str(raw).strip() == "":
            undated.append(row)
            continue
        by_day.setdefault(str(raw), []).append(row)

    one: List[dict] = []
    many: List[dict] = []
    not_thickened: List[str] = []
    for day, day_rows in by_day.items():
        last = day_rows[-1]
        one.append(last)
        pad: List[dict] = []
        pool = day_rows[:-1] or day_rows
        for i in range(max(0, factor - 1)):
            donor = copy.deepcopy(pool[i % len(pool)])
            stamp = _shift_stamp(last.get("generated_at"), seconds=(i + 1) * 60)
            if stamp is None:
                pad = []
                not_thickened.append(day)
                break
            donor["generated_at"] = stamp
            if run_identity(donor) == run_identity(last):
                pad = []
                not_thickened.append(day)
                break
            pad.append(donor)
        many.extend(pad)
        many.append(last)
    # Строки без даты лежат в ОБЕИХ лентах одинаково: они не день и не прогон
    # дня, и трогать их значило бы менять ВТОРУЮ вещь между стендами.
    one.extend(undated)
    many.extend(undated)
    return one, many, {
        "days": len(by_day),
        "undated_records": len(undated),
        "records_one": len(one),
        "records_many": len(many),
        "days_not_thickened": sorted(set(not_thickened)),
    }


def tail_days(rows: Sequence[dict], window_days: Optional[int]
              ) -> Tuple[List[dict], dict]:
    """Хвост ленты в *window_days* ПОСЛЕДНИХ днях — или вся лента при ``None``.

    Режется по ДНЯМ, а не по записям: предмет переписи — сдвиг от плотности при
    неизменном составе дней, поэтому обрезка записями смешала бы обрезку с тем
    самым вторым изменением, которое мерить нельзя.

    Берётся ХВОСТ, а не голова: читатель ленты судит о свежем, и окно из начала
    истории отвечало бы на другой вопрос. «Последние» считаются в порядке ФАЙЛА
    (лента append-only, порядок файла и есть хронология) — то же допущение, на
    котором стои́т :func:`thicken`, и оно названо здесь вслух, а не подразумевается.

    Строки без даты остаются В ОБЕИХ лентах целиком: они не день и не прогон дня
    (см. :func:`thicken`), поэтому окно их не касается — иначе обрезка меняла бы
    ВТОРУЮ вещь между стендами.
    """
    order: List[str] = []
    for row in rows:
        raw = row.get("cycle_date")
        if raw is None or str(raw).strip() == "":
            continue
        day = str(raw)
        if day not in order:
            order.append(day)
    note = {"days_before": len(order), "window_days": window_days}
    if window_days is None:
        note.update(days_after=len(order), truncated=False,
                    reason="окно не задано — лента целиком")
        return list(rows), note
    if window_days <= 0:
        note.update(days_after=len(order), truncated=False,
                    reason=f"окно {window_days} дн не положительно — лента целиком")
        return list(rows), note
    if len(order) <= window_days:
        note.update(days_after=len(order), truncated=False,
                    reason=(f"дней {len(order)} не больше окна {window_days} — "
                            "резать нечего"))
        return list(rows), note
    keep = set(order[-window_days:])
    out = [row for row in rows
           if str(row.get("cycle_date") or "").strip() == ""
           or str(row.get("cycle_date")) in keep]
    note.update(days_after=len(keep), truncated=True,
                reason=f"оставлены {window_days} последних дн из {len(order)}")
    return out, note


def build_stands(source_data_dir: Path, dest: Path, *, factor: int,
                 window_days: Optional[int] = None,
                 prefix: str = "") -> Tuple[Optional[dict], str]:
    """Два стенда на КОПИИ ``data/``, различающиеся РОВНО плотностью лент.

    ``window_days`` режет ленту до последних N дней (:func:`tail_days`) — ОДНО И
    ТО ЖЕ окно у обоих стендов, поэтому единственная разница между ними остаётся
    плотностью. ``prefix`` разводит каталоги стендов, когда в одном прогоне их
    два набора (полное окно и урезанное).
    """
    source = Path(source_data_dir)
    if not source.is_dir():
        return None, f"каталога {source} нет — стенды не построены"
    tapes: Dict[str, Tuple[List[dict], List[dict], dict]] = {}
    notes: Dict[str, str] = {}
    windows: Dict[str, dict] = {}
    for name, book_id in BOOKS:
        rows, why = read_book_rows(source, book_id)
        if rows is None:
            notes[name] = why
            continue
        kept, window_note = tail_days(rows, window_days)
        windows[name] = window_note
        tapes[name] = thicken(kept, factor)
        if why:
            notes[name] = why
    if not tapes:
        return None, ("ни одна лента не прочитана: "
                      + "; ".join(f"{k}: {v}" for k, v in sorted(notes.items())))

    def _write(stand_name: str, pick: int) -> Path:
        stand = Path(dest) / f"{prefix}{stand_name}"
        data = stand / "data"
        data.mkdir(parents=True, exist_ok=True)
        for item in sorted(source.iterdir()):
            if item.name in STAND_EXCLUDE:
                continue
            dst = data / item.name
            if item.is_dir():
                shutil.copytree(item, dst, dirs_exist_ok=True)
            else:
                shutil.copy2(item, dst)
        for name, book_id in BOOKS:
            if name not in tapes:
                continue
            rows = tapes[name][pick]
            (data / history_filename(book_id)).write_text(
                "\n".join(json.dumps(r, sort_keys=True, default=str)
                          for r in rows) + "\n",
                encoding="utf-8")
        return stand

    return {
        "factor": factor,
        "window_days": window_days,
        "s_one": _write("s_one", 0),
        "s_many": _write("s_many", 1),
        "tapes": {name: tapes[name][2] for name in sorted(tapes)},
        "tapes_absent": notes,
        "windows": windows,
    }, ""


def day_named(coords: Set[str]) -> Set[str]:
    """Координаты, чей ПОСЛЕДНИЙ сегмент имени называет дни."""
    out: Set[str] = set()
    for coord in coords:
        seg = _SEG.split(coord.rstrip("]"))[-1].strip().lower()
        if any(token in seg for token in DAY_NAME_TOKENS):
            out.add(coord)
    return out


def _strip_clocks(answer):
    """Ответ без НАЗВАННЫХ ПОИМЁННО стенных полей верхнего уровня."""
    obj = copy.deepcopy(answer)
    if isinstance(obj, dict):
        for key in CLOCK_FIELDS:
            obj.pop(key, None)
    return obj


def classify_reader(module_name: str, stands: dict, *, sweepers: Dict[str, str],
                    now: Optional[dt.datetime] = None,
                    budget_s: float = CALL_BUDGET_S) -> dict:
    """Вердикт одному читателю — по ИСХОДУ на двух стендах.

    Проб три, а не две, и третья не лишняя: ``s_one`` зовётся ДВАЖДЫ, чтобы
    координаты, плывущие при тождественном входе, были ИЗМЕРЕНЫ и сняты. Без
    этого всякий читатель со стенными часами в ответе объявлялся бы
    чувствительным к плотности — то есть перепись сообщала бы о себе, а не о нём
    (`.claude/rules/deployment.md`, «половина инъекции — та же бомба»).

    ``now`` проводится В САМОГО читателя там, где он часы принимает; где не
    принимает — это записано причиной, а не выдано за проведённые часы.
    """
    row: Dict[str, object] = {"module": module_name}
    if module_name == __name__:
        row.update(outcome=OUT_UNMEASURED, cause=CAUSE_SELF,
                   reason="сама перепись: зов изнутри своего прогона")
        return row
    sweeps = sweepers.get(module_name)
    if sweeps:
        row.update(outcome=OUT_UNMEASURED, cause=CAUSE_SWEEPS_POPULATION,
                   reason=sweeps)
        return row
    never = _NEVER_CALL.get(module_name)
    if never:
        row.update(outcome=OUT_UNMEASURED, cause=CAUSE_WOULD_ACT, reason=never)
        return row
    try:
        mod = importlib.import_module(module_name)
    except BaseException as exc:  # noqa: BLE001 — любой отказ = «не измерено»
        if not is_foreign_failure(exc):
            raise                  # СРОК прогона, а не отказ модуля (ADR-676)
        row.update(outcome=OUT_UNMEASURED, cause=CAUSE_IMPORT_FAILED,
                   reason=f"импорт не удался: {type(exc).__name__}")
        return row
    entry, call = module_driver(mod, now=now)
    if call is None:
        cause, reason = no_entry_cause(mod)
        row.update(outcome=OUT_UNMEASURED, cause=cause, reason=reason)
        return row
    row["entry"] = entry
    injected = bool(clock_kwarg(getattr(mod, entry), now))
    row["clock_injected"] = injected
    if not injected:
        row["clock_reason"] = ("точка входа часов не принимает" if now is not None
                               else "часы прогона прибору не переданы")
    bounded = _budget_installable()
    row["budget_s"] = budget_s if bounded else None
    if not bounded:
        row["budget_reason"] = BUDGET_NOT_INSTALLED
    ring = ((lambda stand: _call_within_budget(call, stand, budget_s))
            if bounded else call)
    try:
        first = ring(stands["s_one"])
        time.sleep(_STABILITY_PROBE_DELAY_S)
        again = ring(stands["s_one"])
        many = ring(stands["s_many"])
    except _OverBudget as exc:
        row.update(outcome=OUT_UNMEASURED, cause=CAUSE_OVER_BUDGET,
                   reason=f"{entry}(): {exc}")
        return row
    except BaseException as exc:  # noqa: BLE001
        if not is_foreign_failure(exc):
            raise                  # СРОК прогона, а не отказ модуля (ADR-676)
        row.update(outcome=OUT_UNMEASURED, cause=CAUSE_ENTRY_RAISED,
                   reason=f"{entry}() упал: {type(exc).__name__}")
        return row
    return verdict_from_probes(row, first, again, many)


def verdict_from_probes(row: dict, first, again, many) -> dict:
    """Вердикт по ТРЁМ ответам: ``s_one``, ``s_one`` повторно, ``s_many``.

    Выделено из :func:`classify_reader` НАМЕРЕННО: красную сторону проверки
    нечем было бы закрепить, если бы единственный путь к вердикту лежал через
    настоящие стенды и настоящий импорт. Положительный контроль подаёт три
    ответа прямо.
    """
    unstable = unstable_coords(_strip_clocks(first), _strip_clocks(again))
    row["unstable_coords"] = sorted(unstable)
    masked_one = mask_coords(_strip_clocks(first), unstable)
    masked_many = mask_coords(_strip_clocks(many), unstable)
    moved = unstable_coords(masked_one, masked_many)
    # Координата, измеренная как плывущая, не свидетельствует ни о чём о стенде:
    # её сняли с ОБЕИХ сторон. Но снять её МОЛЧА можно только там, где она не
    # является предметом вопроса. Координата, чьё ИМЯ говорит «день», и есть
    # предмет: если она плывёт при тождественном входе, то судить о ней нечем —
    # третий исход, а не зачёт (инв. #17). Иначе зачёт выдавался бы читателю,
    # который пересчитывает серию по стенным часам.
    named_unstable = day_named(unstable)
    if named_unstable:
        row.update(outcome=OUT_UNMEASURED, cause=CAUSE_RESTS_ON_UNSTABLE,
                   reason=("координаты с именем дня плывут при тождественном "
                           "входе: " + ", ".join(sorted(named_unstable))))
        return row
    if not moved:
        row.update(outcome=OUT_DAY_INVARIANT, moved_coords=[], day_named_moved=[])
        return row
    named = day_named(moved)
    row.update(outcome=OUT_RECORD_SENSITIVE,
               moved_coords=sorted(moved)[:40],
               moved_coords_total=len(moved),
               day_named_moved=sorted(named))
    return row


def merge_short_window_row(full_row: dict, short_row: dict,
                           window_days: int) -> dict:
    """Строка читателя, перемеренного на УРЕЗАННОМ окне (ADR-767, G766 п. 3).

    Правило одно и несимметричное НАМЕРЕННО, потому что несимметричен сам
    предмет:

    * сдвиг НАЙДЕН ⇒ наблюдение полноценно. Координата, сдвинувшаяся от одной
      лишь плотности на семи днях, сдвигается от неё и на сорока пяти: короткое
      окно сужает, что мы УСПЕЛИ посмотреть, но не делает увиденное неправдой;
    * сдвиг НЕ найден ⇒ наблюдение НЕ полноценно и в «чисто» не идёт
      (:data:`CAUSE_INVARIANT_SHORT_ONLY`). Читатель с оглядкой назад длиннее
      окна инвариантен на коротком окне ПО ПОСТРОЕНИЮ, и зачесть ему это
      значило бы выдать слепоту прибора за исправность читателя;
    * не уложился и тут ⇒ цена лежит НЕ в ленте
      (:data:`CAUSE_OVER_BUDGET_SHORT`), средство заказа на него не действует.

    Наблюдение полного окна НЕ затирается: оно остаётся в ``full_window``, иначе
    строка выдавала бы дешёвый замер за тот, которого не было.
    """
    row = dict(short_row)
    row["module"] = full_row.get("module", short_row.get("module"))
    row["short_window_days"] = window_days
    row["measured_on_short_window"] = True
    row["full_window"] = {"outcome": full_row.get("outcome"),
                          "cause": full_row.get("cause"),
                          "reason": full_row.get("reason")}
    outcome = short_row.get("outcome")
    if outcome == OUT_RECORD_SENSITIVE:
        return row
    if outcome == OUT_DAY_INVARIANT:
        row.update(outcome=OUT_UNMEASURED, cause=CAUSE_INVARIANT_SHORT_ONLY,
                   reason=(f"на окне {window_days} дн ни одна координата с именем "
                           "дня не сдвинулась — но полное окно не измерено, и "
                           "короткое окно инвариантности на нём не доказывает"))
        return row
    if short_row.get("cause") == CAUSE_OVER_BUDGET:
        row.update(outcome=OUT_UNMEASURED, cause=CAUSE_OVER_BUDGET_SHORT,
                   reason=(f"не уложился в бюджет и на окне {window_days} дн: "
                           "цена зова лежит не в длине ленты"))
        return row
    return row


def rescue_over_budget(rows: Sequence[dict], source: Path,
                       parent: Path, *, factor: int, sweepers: Dict[str, str],
                       now: Optional[dt.datetime], budget_s: float,
                       short_window_days: int) -> Tuple[List[dict], dict]:
    """Перемерить ДЕШЕВЛЕ тех, кто не уложился в бюджет на полной ленте.

    Средство из заказа G766 п. 3: урезанное окно, а не щедрый бюджет. Стенды
    короткого окна строятся ОДИН раз на всех спасаемых; плотность берётся та же,
    что у полного окна, — иначе между двумя наблюдениями менялись бы ДВЕ вещи,
    и сдвиг нельзя было бы отнести ни к одной.
    """
    targets = [r for r in rows if r.get("cause") == CAUSE_OVER_BUDGET]
    report: Dict[str, object] = {
        "attempted": len(targets),
        "short_window_days": short_window_days,
        "modules": [r["module"] for r in targets],
    }
    if not targets:
        report["reason"] = "ни один зов не вышел за бюджет — спасать некого"
        return list(rows), report
    stands, why = build_stands(source, parent, factor=factor,
                               window_days=short_window_days, prefix="w_")
    if stands is None:
        report["reason"] = why
        out = []
        for row in rows:
            if row.get("cause") != CAUSE_OVER_BUDGET:
                out.append(row)
                continue
            fixed = dict(row)
            fixed.update(cause=CAUSE_SHORT_STAND_ABSENT,
                         reason=f"урезанное окно не построено: {why}")
            out.append(fixed)
        return out, report
    report["stand"] = {"factor": stands["factor"],
                       "window_days": stands["window_days"],
                       "windows": stands["windows"],
                       "tapes": stands["tapes"]}
    rescued: Dict[str, dict] = {}
    for row in targets:
        short = classify_reader(row["module"], stands, sweepers=sweepers,
                               now=now, budget_s=budget_s)
        rescued[row["module"]] = merge_short_window_row(row, short,
                                                        short_window_days)
    out = [rescued.get(str(r.get("module")), r)
           if r.get("cause") == CAUSE_OVER_BUDGET else r for r in rows]
    answered = [r for r in rescued.values()
                if r.get("outcome") != OUT_UNMEASURED]
    report["answered"] = len(answered)
    report["still_unmeasured"] = dict(sorted(collections.Counter(
        str(r.get("cause")) for r in rescued.values()
        if r.get("outcome") == OUT_UNMEASURED).items()))
    report["findings_on_short_window"] = sorted(
        r["module"] for r in rescued.values()
        if r.get("outcome") == OUT_RECORD_SENSITIVE and r.get("day_named_moved"))
    return out, report


def measure(data_dir: Path, tree_root: Path, *,
            now: Optional[dt.datetime] = None,
            stand_dest: Optional[Path] = None,
            population: Optional[Sequence[str]] = None,
            budget_s: float = CALL_BUDGET_S,
            short_window_days: int = SHORT_WINDOW_DAYS) -> dict:
    """Замер целиком: плотность лент · стенды · вердикт каждому читателю."""
    moment = now or _utcnow()
    source = Path(data_dir)
    root = Path(tree_root)
    doc: Dict[str, object] = {
        "version": VERSION,
        "generated_at": moment.isoformat(),
        "producer": PRODUCER,
        "artifact": ARTIFACT,
        "data_dir": str(source),
        "tree_root": str(root),
        "advisory": True,
        "call_budget_s": budget_s,
        "short_window_days": short_window_days,
        "what_it_does_not_prove": [
            "«day_invariant» НЕ означает, что читатель что-нибудь считает: его "
            "ответ мог не зависеть от ленты ни одним полем",
            "«unmeasured» НЕ есть зачёт: причина названа, читатель остаётся на учёте",
            "перепись не судит ПИСАТЕЛЕЙ ленты и ни одного из них не чинит",
            "вердикт, снятый на УРЕЗАННОМ окне (`measured_on_short_window`), не "
            "равен вердикту на полной ленте: сдвиг на нём доказан, а отсутствие "
            "сдвига — нет, и поэтому второе идёт в «не измерено», а не в «чисто»",
        ],
    }

    books: Dict[str, dict] = {}
    for name, book_id in BOOKS:
        rows, why = read_book_rows(source, book_id)
        entry: Dict[str, object] = {"file": history_filename(book_id)}
        if rows is None:
            entry["measured"] = False
            entry["reason"] = why
        else:
            entry["measured"] = True
            entry["density"] = density(rows)
            if why:
                entry["note"] = why
        books[name] = entry
    doc["books"] = books

    factor, factor_why = measured_factor(
        {k: v for k, v in books.items() if v.get("measured")})
    doc["factor"] = factor
    doc["factor_reason"] = factor_why

    sweepers = _sweepers(root)
    doc["sweepers"] = dict(sorted(sweepers.items()))

    roads, stats = reader_population(root)
    doc["population_stats"] = stats
    names = sorted(population) if population is not None else sorted(roads)
    doc["population"] = len(names)

    holder = None
    parent = Path(stand_dest) if stand_dest else None
    if parent is None:
        holder = tempfile.TemporaryDirectory(prefix="spa_g765_stands_")
        parent = Path(holder.name)
    try:
        stands, why = build_stands(source, parent, factor=factor)
        if stands is None:
            doc.update(measured=False, status=STATUS_UNMEASURED,
                       cause=CAUSE_NO_STANDS, reason=why)
            return doc
        doc["stand"] = {
            "factor": stands["factor"],
            "tapes": stands["tapes"],
            "tapes_absent": stands["tapes_absent"],
        }
        rows_out: List[dict] = []
        for name in names:
            rows_out.append(classify_reader(name, stands, sweepers=sweepers,
                                            now=moment, budget_s=budget_s))
        # Бюджет дал прогону конец, но не дал ответа (ADR-767, заказ G766 п. 3):
        # перемерить вышедших за него ДЕШЕВЛЕ — урезанным окном ленты.
        rows_out, rescue = rescue_over_budget(
            rows_out, source, parent, factor=factor, sweepers=sweepers,
            now=moment, budget_s=budget_s,
            short_window_days=short_window_days)
        doc["short_window_rescue"] = rescue
    finally:
        if holder is not None:
            holder.cleanup()

    doc["readers"] = rows_out
    tally: "collections.Counter[str]" = collections.Counter(
        str(r["outcome"]) for r in rows_out)
    doc["tally"] = dict(sorted(tally.items()))
    causes: "collections.Counter[str]" = collections.Counter(
        str(r.get("cause")) for r in rows_out if r["outcome"] == OUT_UNMEASURED)
    doc["unmeasured_causes"] = dict(sorted(causes.items()))

    findings = [
        {"finding": F_RECORDS_AS_DAYS, "module": r["module"],
         "entry": r.get("entry"),
         "coords": list(r.get("day_named_moved") or []),
         # Окно наблюдения — часть находки, а не сноска: находка на урезанном
         # окне полноценна (сдвиг есть сдвиг), но читатель вправе знать, на
         # скольких днях её видели.
         "short_window_days": (r.get("short_window_days")
                               if r.get("measured_on_short_window") else None),
         "detail": ("координаты с именем дня сдвинулись от ОДНОЙ ЛИШЬ плотности "
                    "записей: " + ", ".join(r.get("day_named_moved") or []))}
        for r in rows_out
        if r["outcome"] == OUT_RECORD_SENSITIVE and r.get("day_named_moved")
    ]
    doc["findings"] = findings
    doc["needs_reading"] = [
        {"kind": NEEDS_READING, "module": r["module"],
         "moved_coords": list(r.get("moved_coords") or [])[:8],
         "moved_coords_total": r.get("moved_coords_total")}
        for r in rows_out
        if r["outcome"] == OUT_RECORD_SENSITIVE and not r.get("day_named_moved")
    ]
    doc["measured"] = True
    doc["status"] = STATUS_FINDINGS if findings else STATUS_CLEAN
    return doc


def measurement_due(out: Path, *, now: Optional[dt.datetime] = None,
                    tact_days: int = MEASUREMENT_TACT_DAYS) -> Tuple[bool, str]:
    """Пора ли переизмерять — решает ФАЙЛ, а не расписание запуска.

    Три исхода различимы (инв. #17): артефакта нет ⇒ пора; отметка не разобрана
    ⇒ тоже пора, потому что «не смогли прочитать, когда мерили» не имеет права
    означать «мерили недавно»; отметка свежее такта ⇒ не пора, и это ЗАМЕР.
    """
    moment = now if now is not None else _utcnow()
    target = Path(out)
    if not target.is_file():
        return True, "артефакта нет — первый замер"
    try:
        raw = json.loads(target.read_text(encoding="utf-8")).get("generated_at")
        last = dt.datetime.fromisoformat(str(raw))
    except (OSError, ValueError, TypeError) as exc:
        return True, f"отметка прошлого замера не прочитана ({type(exc).__name__}) — мерим"
    if last.tzinfo is None:
        return True, "отметка прошлого замера без пояса — мерим"
    age_days = (moment - last).total_seconds() / 86400.0
    if age_days >= tact_days:
        return True, (f"со дня замера {last.isoformat()} прошло "
                      f"{age_days:.1f} дн (такт {tact_days})")
    return False, (f"со дня замера {last.isoformat()} прошло {age_days:.1f} дн "
                   f"из {tact_days}")


def run(root: Optional[str] = None, *, data_dir: Optional[str] = None,
        dest: Optional[str] = None, write: bool = True,
        if_due: bool = False, now: Optional[dt.datetime] = None,
        tact_days: int = MEASUREMENT_TACT_DAYS,
        population: Optional[Sequence[str]] = None,
        budget_s: float = CALL_BUDGET_S,
        short_window_days: int = SHORT_WINDOW_DAYS) -> dict:
    """Шаг: внутри такта НЕ мерить и НЕ выдумывать вердикт."""
    tree = Path(root) if root else _ROOT
    source = Path(data_dir) if data_dir is not None else tree / "data"
    target = Path(dest) if dest is not None else source / ARTIFACT
    if if_due:
        due, why = measurement_due(target, now=now, tact_days=tact_days)
        if not due:
            return {"measured": False, "reason": why, "artifact": str(target)}
    doc = measure(source, tree, now=now, population=population,
                  budget_s=budget_s, short_window_days=short_window_days)
    if write:
        atomic_save(doc, str(target))
    return {"measured": True, "doc": doc, "artifact": str(target)}


def format_report(doc: dict) -> List[str]:
    out = [f"ЕДИНИЦА у читателей ленты вердиктов — запись или день ({VERSION})"]
    if not doc.get("measured"):
        out.append(f"  НЕ ИЗМЕРЕНО: {doc.get('reason')}")
        return out
    for name, book in sorted((doc.get("books") or {}).items()):
        if not book.get("measured"):
            out.append(f"  {name}: НЕ ИЗМЕРЕНО — {book.get('reason')}")
            continue
        den = book["density"]
        out.append(f"  {name}: записей {den['records']} · дней {den['days']} · "
                   f"на день сред. {den['records_per_day_mean']} · "
                   f"макс {den['records_per_day_max']}")
    out.append(f"  стенд: плотность {doc.get('factor')} — {doc.get('factor_reason')}")
    out.append(f"  бюджет одного зова: {doc.get('call_budget_s')} с")
    rescue = doc.get("short_window_rescue") or {}
    if rescue:
        attempted = rescue.get("attempted") or 0
        if not attempted:
            out.append("  урезанное окно: не понадобилось — за бюджет не вышел никто")
        else:
            out.append(f"  урезанное окно {rescue.get('short_window_days')} дн: "
                       f"перемерено {attempted} · получили ОТВЕТ "
                       f"{rescue.get('answered', 0)}")
            still = rescue.get("still_unmeasured") or {}
            if still:
                out.append("     осталось «не измерено»: "
                           + " · ".join(f"{k} {v}" for k, v in still.items()))
            found = rescue.get("findings_on_short_window") or []
            if found:
                out.append("     🔴 находки на урезанном окне: " + ", ".join(found))
            if rescue.get("reason") and not rescue.get("stand"):
                out.append(f"     НЕ ИЗМЕРЕНО: {rescue['reason']}")
    tally = doc.get("tally") or {}
    out.append("  вердикты: " + " · ".join(f"{k} {v}" for k, v in tally.items()))
    if doc.get("unmeasured_causes"):
        out.append("  причины «не измерено»: "
                   + " · ".join(f"{k} {v}" for k, v in doc["unmeasured_causes"].items()))
    findings = doc.get("findings") or []
    if findings:
        out.append(f"  🔴 НАХОДОК {len(findings)}: записи считаются под словом «день»")
        for f in findings:
            out.append(f"     {f['module']} :: {', '.join(f['coords'])}")
    else:
        out.append("  ✅ ни одна координата с именем дня не движется от плотности")
    reading = doc.get("needs_reading") or []
    if reading:
        out.append(f"  ⚠️ к ЧТЕНИЮ {len(reading)} (чувствителен, единицу не назвал): "
                   + ", ".join(r["module"] for r in reading[:8]))
    out.append("  ADVISORY: прибор только ЧИТАЕТ (ни один гейт его не читает)")
    return out


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(
        description="перепись единицы у читателей ленты вердиктов (заказ G765 п. 3)")
    ap.add_argument("--data-dir", default=None,
                    help="каталог data/, с которого строятся стенды (КОПИЯ, не правится)")
    ap.add_argument("--tree-root", default=str(_ROOT))
    ap.add_argument("--out", default=None)
    ap.add_argument("--no-write", action="store_true")
    ap.add_argument("--if-due", action="store_true",
                    help=f"мерить только если со дня прошлого замера прошло "
                         f"{MEASUREMENT_TACT_DAYS} дн (прогон стои́т минуты)")
    ap.add_argument("--short-window-days", type=int, default=SHORT_WINDOW_DAYS,
                    help=("окно ленты для ПОВТОРНОГО зова тех, кто не уложился "
                          f"в бюджет (по умолчанию {SHORT_WINDOW_DAYS}); "
                          "предмет мерится дешевле, а не бюджетом щедрее"))
    args = ap.parse_args(argv)
    res = run(root=args.tree_root, data_dir=args.data_dir, dest=args.out,
              write=not args.no_write, if_due=args.if_due,
              short_window_days=args.short_window_days)
    if not res.get("measured"):
        print(f"перепись не проводилась: {res.get('reason')}")
        return 0
    doc = res["doc"]
    print("\n".join(format_report(doc)))
    if not doc.get("measured"):
        return 2
    return 1 if doc.get("findings") else 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
