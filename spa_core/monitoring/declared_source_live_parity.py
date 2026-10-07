"""Верность реестра `SITE_NUMBER_SOURCES`, спрошенная у ЖИВОЙ страницы.

Заказ владельца **G103 п. 1** (хвост `ADR-523`, 30.09) дословно:

> «Реестр объявлен, а его ВЕРНОСТЬ никто не спрашивает у сайта. Таблица
> `SITE_NUMBER_SOURCES` — утверждение о живой разметке, и сегодня оно верно
> потому, что его снял замер 30.09. Через один рефакторинг `landing/` оно
> снова станет неправдой, и узнает об этом сторож — но только когда число
> ИСЧЕЗНЕТ со ВСЕХ объявленных страниц. Переезд id при сохранившемся дубле
> пройдёт молча. Спросить прямо: сколько объявленных источников живая страница
> подтверждает, сколько опровергает, сколько не измерено.»

Вред, ради которого прибор написан
---------------------------------------------------------------------------
`locate_site_number` отвечает на вопрос «откуда взять ОПЕРАНД сверки» и
отвечает честно: операнд берётся у ПЕРВОГО источника, который дал число
(``hits[0]``). Отсюда следствие, которого не называет ни один сторож: пока
хоть один источник того же `label` жив, опровергнутое объявление соседа
невидимо. Красным кустодиан станет лишь тогда, когда замолчат ВСЕ источники
label (`COMPARISON_NOT_MEASURED`) — то есть ровно в том случае, который заказ
и назвал исключением, а не правилом.

Три состояния снаружи выглядят одинаково, а чинятся разным:

* реестр верен, страница несёт объявленное — сказать нечего;
* объявление ОПРОВЕРГНУТО страницей, но сосед по label отвечает — отчёт
  зелёный, запись в реестре мертва, и узнает об этом никто;
* страница не отдана вовсе — сказать нечего И это НЕ «источник подтверждён».

Второе тише первого и потому опаснее: мёртвая строка реестра выглядит как
живая, пока на неё не посмотрят глазами. Замер, с которого прибор начался
(06.10, живой сайт): объявлено **11** источников, страница подтверждает
**7**, ОПРОВЕРГАЕТ **3**, заглушкой отвечает **1**; `number_legs` кустодиана
называл **3** источника из одиннадцати и ни одного опровергнутого.

Три опровергнутых — `home#sl-day`, `home#sl-gates`, `home#sl-apy`. Их
объявление несёт причину дословно: «историчный id главной; элемента в разметке
больше нет, но старая сборка на CDN его несёт». Причина есть УТВЕРЖДЕНИЕ с
датой (30.09), и живая страница 06.10 его не подтверждает. Прибор прозу
причины не судит — он печатает её рядом с исходом, чтобы читатель видел, о
каком именно утверждении идёт речь.

Откуда берётся операнд, и почему прибор НЕ ходит в сеть сам
---------------------------------------------------------------------------
Операнд — ``declared_source_probes`` из отчёта живого кустодиана
(`data/site_freshness_report.json`): исход КАЖДОГО объявленного источника на
том HTML, который кустодиан уже скачал. Свой запрос к сайту отвечал бы о
ДРУГОМ мгновении и от ДРУГОГО скачивателя, а ступень моста стала бы первой,
зависящей от сети, — и «сеть легла» было бы неотличимо от «страница
изменилась». Поэтому сеть здесь — дверь кустодиана, а не прибора.

Отсюда прямое следствие: **ответ есть утверждение о МГНОВЕНИИ, когда
кустодиан скачивал страницу, и возраст этого мгновения есть ПОЛЕ ответа, а не
сноска** (урок `ADR-565`). Отчёт старше :data:`OPERAND_MAX_AGE_H` ⇒ прибор
ОТКАЗЫВАЕТ с названной причиной: судить сегодняшний реестр по позавчерашней
странице значит отвечать на соседний вопрос.

Односторонность — НАЗВАНА ЗАРАНЕЕ, до всякого вердикта
---------------------------------------------------------------------------
* «ОПРОВЕРГНУТ» сказано о СЕРВЕРНОМ HTML. Посетитель может видеть число
  прекрасно: страница дорисовывает элемент клиентом. Для вопроса о реестре это
  верный операнд — кустодиан читает именно серверный HTML и ищет id именно в
  нём, — но утверждением о том, что видит посетитель, он не является.
* Прибор не судит ПРОЗУ причины объявления и не решает, надо ли мёртвую строку
  удалять: удаление записи реестра — работа, а не наблюдение.
* Прибор не спрашивает, ВЕРЕН ли регексп сверх того, дал ли он число.
* Прибор не спрашивает, ПОЛОН ли реестр. Число, которое страница отдаёт под
  НЕОБЪЯВЛЕННЫМ id, этой мере невидимо по построению — это вопрос `G103 п. 2`,
  и отвечать на него обязан следующий шаг, а не этот.
* Он ничего не чинит (``applied=False``): ни реестра, ни кустодиана, ни
  вердикта, ни гейта. Ни одной страницы `landing/**` он не трогает, и ни одно
  публичное число от него не зависит (предмет №2 границы `ADR-285` не задет).

Что мерится ОТДЕЛЬНО и складыванию не подлежит
---------------------------------------------------------------------------
**Дубль id.** ``id_occurrences > 1`` означает, что ответ регекспа решает
порядок элементов в документе, а не объявление. Это НЕ «подтверждён» и НЕ
«опровергнут» — это своё наблюдение со своим числом
(``ambiguous_duplicate_ids``), и сложить его с опровергнутыми значило бы
напечатать выдуманную находку.

**Запись старше реестра.** Реестр мог измениться после того, как кустодиан
снял пробы. Тогда у объявленного источника записи нет (третий исход
:data:`UNMEASURED_NOT_RECORDED`), а у записи есть источник, которого реестр
больше не объявляет (:data:`RECORD_ORPHANS`). Оба направления названы
отдельными числами: сложить их в одно «расхождение» значило бы потерять, какая
из двух сторон устарела.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import argparse
import datetime as dt
import importlib.util
import json
import sys
from pathlib import Path
from typing import Dict, List, Optional

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:  # запуск ПО ПУТИ, а не пакетом
    sys.path.insert(0, str(_ROOT))

from spa_core.monitoring.call_provenance import call_provenance  # noqa: E402
from spa_core.monitoring.call_provenance import describe as provenance_line  # noqa: E402,E501
from spa_core.utils.atomic import atomic_save  # noqa: E402
from spa_core.utils.observation import observed  # noqa: E402

ARTIFACT = "declared_source_live_parity.json"
PRODUCER = "spa_core/monitoring/declared_source_live_parity.py"
ORDER = "G103 п. 1 (хвост ADR-523)"

#: ЕДИНСТВЕННЫЙ источник реестра — модуль кустодиана. Второй копии таблицы
#: здесь нет намеренно: две копии одного правила расходятся молча (ADR-220), а
#: предмет этого прибора — верность ИМЕННО той таблицы, по которой работает
#: живой сторож.
REGISTRY_MODULE = "scripts/site_freshness_monitor.py"
REGISTRY_NAME = "SITE_NUMBER_SOURCES"

#: Отчёт живого кустодиана — операнд. Поле проб добавлено тем же решением,
#: что и этот прибор; отчёт, снятый ДО него, поля не несёт, и это ОТКАЗ с
#: названной причиной, а не ноль находок.
OPERAND = "data/site_freshness_report.json"
OPERAND_FIELD = "declared_source_probes"

#: Такт кустодиана — 6 ч (`StartInterval` 21600 в `com.spa.site_freshness`).
#: Предел возраста операнда — ЧЕТЫРЕ такта, и это ВЫБОР, а не свойство: он
#: равен `PREV_REPORT_MAX_AGE_H` самого кустодиана, то есть тому же сроку, за
#: которым он сам перестаёт верить своему прошлому прогону.
OPERAND_MAX_AGE_H = 24.0

#: Сколько источников печатать поимённо. Обрезка показа — ВЫБОР, и он назван.
NAMED_ROWS = 16

# --- исход по ОДНОМУ объявленному источнику --------------------------------
#: Живая страница несёт объявленный id, и число с него читается.
CONFIRMED = "the_live_page_carries_the_declared_source"
#: Объявленного id на живой странице НЕТ. Реестр утверждает то, чего страница
#: не несёт, — и это находка заказа.
REFUTED = "the_declared_id_is_absent_from_the_live_page"
#: id есть, числа с него не читается: заглушка, которую заполняет клиент.
UNMEASURED_PLACEHOLDER = "the_id_is_present_and_the_value_is_unreadable"
#: Страницу, которую объявляет источник, кустодиан не скачал.
UNMEASURED_PAGE = "the_declared_page_was_not_fetched"
#: Записи об этом объявленном источнике у кустодиана нет вовсе.
UNMEASURED_NOT_RECORDED = "the_record_has_no_entry_for_this_declared_source"
#: Исход записи вне ОБЪЯВЛЕННОГО перевода (:data:`_LEG_TO_OUTCOME`). Третий
#: исход, а не «подтверждён»: новый исход кустодиана обязан быть ВИДЕН, а не
#: угадан по подстроке.
UNMEASURED_LEG_UNKNOWN = "the_record_leg_is_outside_the_declared_translation"
_OUTCOMES = (CONFIRMED, REFUTED, UNMEASURED_PLACEHOLDER, UNMEASURED_PAGE,
             UNMEASURED_NOT_RECORDED, UNMEASURED_LEG_UNKNOWN)

# --- исход по ОДНОМУ label: ГРОМКО или МОЛЧА ------------------------------
#: Ни один источник label не опровергнут.
LABEL_CLEAN = "no_declared_source_of_this_label_is_refuted"
#: ≥1 опровергнут И ≥1 подтверждён: кустодиан отвечает соседом и МОЛЧИТ о
#: мёртвом объявлении. ЭТО и есть вред, названный заказом.
LABEL_SILENT = "a_refuted_source_is_silent_because_a_sibling_answers"
#: Опровергнуты ВСЕ источники label: кустодиан краснеет сам
#: (`COMPARISON_NOT_MEASURED`). Вред ГРОМКИЙ, и с молчаливым он не
#: складывается — у них разное лекарство.
LABEL_LOUD = "every_source_is_refuted_and_the_custodian_says_so_itself"
#: Ни подтверждённых, ни опровергнутых — сказать о label нечего.
LABEL_UNMEASURED = "no_source_of_this_label_is_measured_either_way"
_LABEL_OUTCOMES = (LABEL_CLEAN, LABEL_SILENT, LABEL_LOUD, LABEL_UNMEASURED)

# --- отказы САМОГО шага. Ни один из них не есть ноль находок ---------------
GAP_NO_OPERAND = "the_custodian_report_is_absent"
GAP_OPERAND_UNREADABLE = "the_custodian_report_is_unreadable"
GAP_NO_FIELD = "the_custodian_report_predates_the_per_source_record"
GAP_NO_STAMP = "the_custodian_report_carries_no_readable_timestamp"
GAP_STALE = "the_custodian_report_is_older_than_the_declared_bound"
GAP_NO_REGISTRY = "the_declared_registry_is_not_readable_from_the_custodian"


class NotMeasured(RuntimeError):
    """Отказ шага: предпосылка не обеспечена. Третий исход, не вердикт."""

    def __init__(self, gap: str, why: str) -> None:
        super().__init__(f"{gap}: {why}")
        self.gap = gap
        self.why = why


def _utcnow() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def _age_hours(stamp, now: dt.datetime) -> Optional[float]:
    """Возраст отметки в часах. `None` — отметки нет или она не разобрана.

    Время разбирается ЦЕЛИКОМ, а не режется до даты: вопрос «та ли это
    страница» меняет ответ на часах, а не на сутках.
    """
    if not stamp:
        return None
    text = str(stamp).strip().replace("Z", "+00:00")
    try:
        parsed = dt.datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=dt.timezone.utc)
    return round((now - parsed).total_seconds() / 3600.0, 2)


def load_registry(root: Path) -> Dict[str, tuple]:
    """Реестр, прочитанный У КУСТОДИАНА. Второй копии таблицы здесь нет.

    Кустодиан — скрипт, а не пакет, поэтому грузится по пути. Не прочитан ⇒
    отказ с названной причиной: выдумать таблицу значило бы судить реестр по
    своей копии, то есть ответить на соседний вопрос.
    """
    path = Path(root) / REGISTRY_MODULE
    try:
        spec = importlib.util.spec_from_file_location(
            "_sfm_registry_under_census", path)
        if spec is None or spec.loader is None:
            raise ImportError("спецификация модуля не собрана")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        table = getattr(module, REGISTRY_NAME)
    except Exception as exc:  # noqa: BLE001 — причина уходит в третий исход
        raise NotMeasured(
            GAP_NO_REGISTRY,
            f"{REGISTRY_MODULE}:{REGISTRY_NAME} не прочитан "
            f"({type(exc).__name__}: {exc})") from exc
    if not isinstance(table, dict) or not table:
        raise NotMeasured(
            GAP_NO_REGISTRY,
            f"{REGISTRY_MODULE}:{REGISTRY_NAME} не является непустой таблицей "
            f"(род {type(table).__name__})")
    return table


def load_record(root: Path) -> dict:
    """Отчёт кустодиана — операнд. Каждый отказ назван своей причиной."""
    path = Path(root) / OPERAND
    if not path.exists():
        raise NotMeasured(GAP_NO_OPERAND,
                          f"{OPERAND} не существует — страницу не скачивал "
                          f"никто, и это не «источники подтверждены»")
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        raise NotMeasured(GAP_OPERAND_UNREADABLE,
                          f"{OPERAND}: {type(exc).__name__}: {exc}") from exc
    if not isinstance(doc, dict):
        raise NotMeasured(GAP_OPERAND_UNREADABLE,
                          f"{OPERAND} не словарь, а {type(doc).__name__}")
    return doc


#: Исход кустодиана -> исход этого прибора. Перевод ОБЪЯВЛЕН таблицей, а не
#: угадывается по подстроке «unmeasured» в значении: род вердикта читается по
#: СЛОВУ целиком (ADR-333), иначе новый исход соседа молча стал бы знакомым.
_LEG_TO_OUTCOME = {
    "measured": CONFIRMED,
    "unmeasured:id_absent": REFUTED,
    "unmeasured:id_present_value_unreadable": UNMEASURED_PLACEHOLDER,
    "unmeasured:page_not_fetched": UNMEASURED_PAGE,
}
#: Источник, который запись называет, а реестр больше НЕ объявляет. Своё
#: число: это устарел РЕЕСТР ЗАПИСИ, а не реестр кустодиана.
RECORD_ORPHANS = "record_names_a_source_the_registry_no_longer_declares"


def measure(root: Path, *, now: Optional[dt.datetime] = None,
            record: Optional[dict] = None,
            registry: Optional[Dict[str, tuple]] = None) -> dict:
    """Сколько объявленных источников живая страница подтверждает/опровергает.

    `record` и `registry` — ВХОДЫ с дверью по умолчанию (отчёт кустодиана и его
    же модуль). Сцена подаёт их прямо: окружение одноразового дерева ни того,
    ни другого не несёт по построению, а предпосылка, добытая у окружения, и
    есть та бомба, против которой правило о времени и о pid написано.
    """
    now = now or _utcnow()
    registry = registry if registry is not None else load_registry(Path(root))
    # Пустой реестр — ОТКАЗ, и проверка стои́т ЗДЕСЬ, а не только у двери
    # чтения. Своя батарея поймала прибор на его же правиле: реестр, поданный
    # ВХОДОМ, двери не касается, и «население 0 · опровергнутых 0» уехало бы
    # чистым листом — то есть «не измерено», выданное за «находок нет»
    # (инв. #17). Вход обязан проверяться как дверь, иначе он обходит её.
    if not isinstance(registry, dict) or not registry:
        raise NotMeasured(
            GAP_NO_REGISTRY,
            f"реестр пуст или не таблица (род {type(registry).__name__}, "
            f"записей {len(registry) if hasattr(registry, '__len__') else '?'})"
            f" — ноль объявленных источников есть ОТКАЗ, а не «опровергнутых "
            f"нет»")
    doc = record if record is not None else load_record(Path(root))
    # Тот же урок, что строкой выше, и применён он к ВТОРОМУ входу: род записи
    # проверяет `load_record`, а запись, поданная ВХОДОМ, его не проходит — и
    # не-словарь валил бы разбор `AttributeError`, то есть «упало» вместо
    # названного отказа.
    if not isinstance(doc, dict):
        raise NotMeasured(
            GAP_OPERAND_UNREADABLE,
            f"запись подана как {type(doc).__name__}, а не словарь — это "
            f"отказ с причиной, а не падение разбора")

    stamp = doc.get("ts") or doc.get("generated_at")
    age = _age_hours(stamp, now)
    if age is None:
        raise NotMeasured(
            GAP_NO_STAMP,
            f"{OPERAND} не несёт разобранной отметки (ts={stamp!r}) — возраст "
            f"есть ПОЛЕ этого ответа, и без него ответ был бы о неизвестном "
            f"мгновении")
    if age > OPERAND_MAX_AGE_H:
        raise NotMeasured(
            GAP_STALE,
            f"{OPERAND} снят {age}ч назад при пределе {OPERAND_MAX_AGE_H}ч — "
            f"судить сегодняшний реестр по той странице значит отвечать на "
            f"соседний вопрос")

    probes = doc.get(OPERAND_FIELD)
    if not isinstance(probes, list):
        raise NotMeasured(
            GAP_NO_FIELD,
            f"{OPERAND} не несёт поля `{OPERAND_FIELD}` (род "
            f"{type(probes).__name__}) — отчёт снят до появления записи; это "
            f"отказ, а не «опровергнутых нет»")

    # Запись, у которой нет ВСЕХ трёх частей адреса, в карту не берётся: без
    # них её нельзя сопоставить объявлению, а взять «почти совпавшую» значило
    # бы судить объявление по чужой пробе. Такая запись и не теряется молча —
    # объявление без пробы получает третий исход UNMEASURED_NOT_RECORDED.
    by_key = {}
    for row in probes:
        if not isinstance(row, dict):
            continue
        if row.get("label") and row.get("page") and row.get("elem_id"):
            by_key[(str(row["label"]), str(row["page"]),
                    str(row["elem_id"]))] = row

    rows: List[dict] = []
    seen_keys = set()
    for label, sources in registry.items():
        for source in sources:
            # Форма записи реестра — предпосылка, а не данность. Запись иной
            # арности раньше валила разбор исключением, и «упало» читается как
            # дефект прибора, а не как «реестр изменил форму». Третий исход.
            try:
                page, elem_id, _pattern, why = source
            except (TypeError, ValueError) as exc:
                raise NotMeasured(
                    GAP_NO_REGISTRY,
                    f"запись реестра label={label!r} не разбирается как "
                    f"(страница, id, регексп, причина): {source!r} "
                    f"({type(exc).__name__})") from exc
            key = (str(label), str(page), str(elem_id))
            seen_keys.add(key)
            probe = by_key.get(key)
            if probe is None:
                rows.append({"label": label, "page": page,
                             "elem_id": elem_id, "declared_why": why,
                             "outcome": UNMEASURED_NOT_RECORDED,
                             "leg": None, "value": None,
                             "id_occurrences": None})
                continue
            leg = str(probe.get("leg"))
            outcome = _LEG_TO_OUTCOME.get(leg, UNMEASURED_LEG_UNKNOWN)
            rows.append({"label": label, "page": page, "elem_id": elem_id,
                         "declared_why": why, "outcome": outcome, "leg": leg,
                         "value": probe.get("value"),
                         "id_occurrences": probe.get("id_occurrences")})

    orphans = [{"label": k[0], "page": k[1], "elem_id": k[2]}
               for k in sorted(by_key) if k not in seen_keys]

    outcomes = {cls: sum(1 for r in rows if r["outcome"] == cls)
                for cls in _OUTCOMES}

    labels = {}
    for label in registry:
        mine = [r for r in rows if r["label"] == label]
        refuted = sum(1 for r in mine if r["outcome"] == REFUTED)
        confirmed = sum(1 for r in mine if r["outcome"] == CONFIRMED)
        if refuted and confirmed:
            labels[label] = LABEL_SILENT
        elif refuted and not confirmed:
            labels[label] = LABEL_LOUD
        elif confirmed:
            labels[label] = LABEL_CLEAN
        else:
            labels[label] = LABEL_UNMEASURED
    label_outcomes = {cls: sum(1 for v in labels.values() if v == cls)
                      for cls in _LABEL_OUTCOMES}

    # ОТДЕЛЬНОЕ наблюдение, складыванию с опровергнутыми не подлежит: ответ
    # регекспа решает порядок элементов в документе, а не объявление.
    duplicates = [r for r in rows
                  if isinstance(r.get("id_occurrences"), int)
                  and r["id_occurrences"] > 1]

    refuted_rows = [r for r in rows if r["outcome"] == REFUTED]
    silent_rows = [r for r in refuted_rows if labels.get(r["label"]) == LABEL_SILENT]

    return {
        "generated_at": now.isoformat(),
        "generated_by": PRODUCER,
        "invoked_by": call_provenance(tree_root=Path(root)),
        "status": "MEASURED",
        "question": ("сколько объявленных в SITE_NUMBER_SOURCES источников "
                     "живая страница подтверждает, сколько опровергает и "
                     "сколько не измерено"),
        "order": ORDER,
        "applied": False,
        "registry": f"{REGISTRY_MODULE}:{REGISTRY_NAME}",
        "operand": OPERAND,
        # ВОЗРАСТ — ПОЛЕ ОТВЕТА. Ответ есть утверждение о том мгновении, когда
        # кустодиан скачивал страницу, а не о «сейчас».
        "operand_age_hours": age,
        "operand_max_age_hours": OPERAND_MAX_AGE_H,
        "population": len(rows),
        "recorded_probes": len(by_key),
        "outcomes": outcomes,
        "label_outcomes": label_outcomes,
        "labels": labels,
        # ЧИСЛО ЗАКАЗА: объявлений, которые живая страница ОПРОВЕРГАЕТ.
        "refuted": outcomes[REFUTED],
        # ТО ЖЕ ЧИСЛО, но разделённое по громкости — лекарство у них разное.
        "refuted_silently": len(silent_rows),
        "refuted_loudly": outcomes[REFUTED] - len(silent_rows),
        # ДРУГИЕ УТВЕРЖДЕНИЯ. Складывать с предыдущими ЗАПРЕЩЕНО.
        "ambiguous_duplicate_ids": len(duplicates),
        RECORD_ORPHANS: len(orphans),
        "orphan_rows": orphans[:NAMED_ROWS],
        "rows": rows[:NAMED_ROWS],
        "named_rows_limit": NAMED_ROWS,
        "what_it_does_not_prove": [
            "что ОПРОВЕРГНУТЫЙ источник не виден посетителю: сказано о "
            "СЕРВЕРНОМ HTML, а элемент страница может дорисовать клиентом",
            "что подтверждённый источник ВЕРЕН по существу — подтверждено "
            "лишь то, что id на странице есть и число с него читается",
            "что реестр ПОЛОН: число под НЕОБЪЯВЛЕННЫМ id этой мере невидимо "
            "по построению (это вопрос G103 п. 2, и он не этого шага)",
            "что проза причины объявления верна — она печатается рядом с "
            "исходом, но не судится",
            f"что ответ сказан о «сейчас»: он сказан о мгновении, когда "
            f"кустодиан скачивал страницу ({age}ч назад)",
            "что дубль id есть опровержение: это своё наблюдение со своим "
            "числом, и складывать его с опровергнутыми нельзя",
        ],
    }


def report(doc: dict) -> List[str]:
    status = str(doc.get("status"))
    if status != "MEASURED":
        return [f"НЕ ИЗМЕРЕНО — "
                f"{observed(doc, 'reason', kind=str) or 'причина не записана'}"]
    outcomes = observed(doc, "outcomes", kind=dict) or {}
    labels = observed(doc, "label_outcomes", kind=dict) or {}
    out = [
        f"верность реестра источников, спрошенная у живой страницы (заказ "
        f"{doc.get('order')}): {status} · объявлено "
        f"{doc.get('population')} · ПОДТВЕРЖДАЕТ {outcomes.get(CONFIRMED)} · "
        f"ОПРОВЕРГАЕТ {outcomes.get(REFUTED)} · заглушка "
        f"{outcomes.get(UNMEASURED_PLACEHOLDER)} · страница не скачана "
        f"{outcomes.get(UNMEASURED_PAGE)} · записи нет "
        f"{outcomes.get(UNMEASURED_NOT_RECORDED)} · исход вне перевода "
        f"{outcomes.get(UNMEASURED_LEG_UNKNOWN)}",
        f"[ЗВАВШИЙ] {provenance_line(observed(doc, 'invoked_by', kind=dict))}",
        f"[ЧИСЛО ЗАКАЗА] опровергнутых объявлений {doc.get('refuted')}, из них "
        f"МОЛЧА (сосед по label отвечает, кустодиан зелёный) "
        f"{doc.get('refuted_silently')} · ГРОМКО (кустодиан краснеет сам) "
        f"{doc.get('refuted_loudly')}",
        f"[ПО LABEL] молчаливых {labels.get(LABEL_SILENT)} · громких "
        f"{labels.get(LABEL_LOUD)} · без опровержений "
        f"{labels.get(LABEL_CLEAN)} · не измерено "
        f"{labels.get(LABEL_UNMEASURED)}",
        f"[ВОЗРАСТ ОТВЕТА] страница скачана кустодианом "
        f"{doc.get('operand_age_hours')}ч назад (предел "
        f"{doc.get('operand_max_age_hours')}ч) — ответ о ТОМ мгновении",
        f"[ДРУГИЕ УТВЕРЖДЕНИЯ] дубль id {doc.get('ambiguous_duplicate_ids')} "
        f"(порядок в документе решает за объявление) · запись называет "
        f"источник, которого реестр больше не объявляет "
        f"{doc.get(RECORD_ORPHANS)} — складывать с опровергнутыми нельзя",
    ]
    for row in (observed(doc, "rows", kind=list) or []):
        if not isinstance(row, dict) or row.get("outcome") == CONFIRMED:
            continue
        mark = {REFUTED: "ОПРОВЕРГНУТ",
                UNMEASURED_PLACEHOLDER: "ЗАГЛУШКА",
                UNMEASURED_PAGE: "СТРАНИЦА НЕ СКАЧАНА",
                UNMEASURED_NOT_RECORDED: "ЗАПИСИ НЕТ",
                UNMEASURED_LEG_UNKNOWN: "ИСХОД ВНЕ ПЕРЕВОДА",
                }.get(str(row.get("outcome")), str(row.get("outcome")))
        out.append(f"   [{mark}] {row.get('label')} ← "
                   f"{row.get('page')}#{row.get('elem_id')} — объявлено "
                   f"«{row.get('declared_why')}»")
    out.append("НЕ ДОКЛАДЫВАЕТ: "
               + " · ".join(observed(doc, "what_it_does_not_prove",
                                     kind=list) or []))
    out.append("ADVISORY: прибор только ЧИТАЕТ реестр и отчёт кустодиана "
               "(applied=False) — ни реестра, ни вердикта, ни страницы он не "
               "правит")
    return out


def format_report(doc: dict, *, max_rows: int = 5) -> List[str]:
    """Сжатая отрисовка для шага 0-офис — правило отрисовки У ПРОИЗВОДИТЕЛЯ.

    Вторая копия правила «как это читать» разошлась бы молча (ADR-220), а
    артефакт без ветки отрисовки читается ВХОЛОСТУЮ: квитанция о потреблении
    есть, а ни одного числа читатель не видит.
    """
    lines = report(doc)
    if str(doc.get("status")) != "MEASURED":
        return lines
    head = [line for line in lines if not line.startswith("   ")]
    rows = [line for line in lines if line.startswith("   ")]
    hidden = max(0, len(rows) - max_rows)
    out = head[:1] + rows[:max_rows]
    if hidden:
        out.append(f"   … и ещё {hidden} источник(ов) — обрезка ПОКАЗА, не "
                   f"населения (всё в артефакте)")
    return out + head[1:]


def run(root: str | Path = _ROOT, *, dest: Optional[Path] = None,
        write: bool = True, now: Optional[dt.datetime] = None,
        record: Optional[dict] = None,
        registry: Optional[Dict[str, tuple]] = None) -> dict:
    root = Path(root)
    target = Path(dest) if dest is not None else root / "data" / ARTIFACT
    try:
        doc = measure(root, now=now, record=record, registry=registry)
    except NotMeasured as exc:
        # Третий исход обязан быть ИСХОДОМ на любой глубине, иначе он им не
        # является: трассировка вместо вердикта читается как «упало», а не как
        # «не измерено».
        doc = {
            "generated_at": (now or _utcnow()).isoformat(),
            "generated_by": PRODUCER,
            "invoked_by": call_provenance(tree_root=root),
            "status": "UNMEASURED",
            "order": ORDER,
            "applied": False,
            "gap": exc.gap,
            "reason": str(exc),
            "rows": [],
        }
    if write:
        atomic_save(doc, str(target))
    return {"measured": doc.get("status") == "MEASURED", "doc": doc,
            "artifact": str(target)}


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(
        description=("верность реестра SITE_NUMBER_SOURCES, спрошенная у "
                     "живой страницы (заказ G103 п. 1)"))
    ap.add_argument("--root", default=str(_ROOT))
    ap.add_argument("--out", default=None)
    ap.add_argument("--no-write", action="store_true")
    args = ap.parse_args(argv)
    outcome = run(Path(args.root), dest=Path(args.out) if args.out else None,
                  write=not args.no_write)
    for line in report(outcome["doc"]):
        print(line)
    return 0 if outcome["measured"] else 2


if __name__ == "__main__":   # pragma: no cover
    raise SystemExit(main())
