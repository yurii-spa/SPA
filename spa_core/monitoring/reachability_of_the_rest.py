"""Тот же вопрос — у ОСТАЛЬНЫХ открытых счётчиков: стык читателя и писателя.

Заказ владельца **G98 п. 2** (хвост `ADR-517`, 29.09) дословно:

> «Тот же вопрос, заданный ОСТАЛЬНЫМ 149 открытым счётчикам. Шаг спрашивает
> достижимость только у девяти расколов — то есть у тех, кого ряд успел
> довести до читателя. У остальных читатель НЕ ИЗМЕРЕН, и достижимость их
> вреда не измерена тем более; складывать эти два незнания в одно нельзя.»

Вред, ради которого прибор написан
---------------------------------------------------------------------------
Над одним населением открытых счётчиков работают ДВА независимых замера, и
каждый отвечает на свою половину вопроса:

* **ось читателя** (`ADR-460`/`G77.1`, шаг `open_counter_reader_harm`) — делит
  ли читатель счётчик по ОБЪЯВЛЕННЫМ классам, то есть становится ли
  незнакомый класс молча ДРУГИМ исходом;
* **ось писателя** (`ADR-469`/`G84.2`, шаг `writer_harm_form`) — впускает ли
  писатель незнакомый класс молча или падает на нём `KeyError` раньше.

Вред живёт в СТЫКЕ: молчащий писатель плюс расколотый читатель и есть
«незнакомый класс тихо стал другим исходом». Шаг `ADR-517` стык сделал — но
ровно у тех узлов, которые нашли шаги одного межпроцедурного разбора
(`G81.1`/`G82.1`). Их девять. Остальные **196** (197 на дереве, несущем сам
прибор) не соединял никто: у них два замера лежат рядом и не смотрят друг на
друга.

Что НЕ надо делать с двумя незнаниями
---------------------------------------------------------------------------
Заказ запрещает прямо: «складывать эти два незнания в одно нельзя». Поэтому у
прибора не один третий исход, а ТРИ независимых, и они не суммируются:

* читатель не измерен (ось читателя, причины у соседа);
* род накопителя не измерен (ось писателя, причины у соседа);
* **узел не состыкован** — он есть в одной переписи и отсутствует в другой.

Последний опаснее двух первых и потому имеет собственное имя: потеря узла при
стыке выглядит как уменьшение населения, то есть как ЧИСТОТА. Клетка «оба не
измерены» (:data:`CELL_BOTH_UNMEASURED`) печатается тоже отдельно, и
складывать её с краевыми незнаниями запрещено арифметическим инвариантом, а не
просьбой: она обязана быть не больше каждого из них по построению, и это
проверяется (`do_not_sum`).

ПРЕДПОСЫЛКА ЗАКАЗА ОПРОВЕРГНУТА — замером, и опровержение есть поле ответа
---------------------------------------------------------------------------
Заказ утверждал: «у остальных читатель НЕ ИЗМЕРЕН». Замер 05.10 говорит
обратное, и ровно наоборот:

* у остальных 196 читатель измерен у **82** (55 с ДОКАЗАННЫМ расколом, 27 —
  лишняя строка отчёта) и не измерен у 114 — то есть «не измерен» верно для
  двух третей, а не для всех (на дереве с прибором: 82 и 115);
* а вот у ДЕВЯТИ состыкованных читатель не измерен у **9 из 9**.

Два населения оказались не вложенными, а ПОЧТИ ДОПОЛНИТЕЛЬНЫМИ: шаг, зовущий
себя «достижимость раскола», соединил писателя с теми узлами, чья читательская
половина как раз и не измерена, а 55 узлов с доказанным расколом не получили
вердикта писателя вовсе. Поэтому поле `premise_of_the_order` стои́т в ответе
наравне с числами: заказ ставил вопрос об остатке, а остаток оказался не тем,
чем его называли.

Главное число ответа
---------------------------------------------------------------------------
:data:`CELL_HARM_REACHABLE` — раскол ДОКАЗАН читателем, писатель МОЛЧИТ,
достижимость не спрашивал никто. Замер 05.10: **33**. По правилу самого
`ADR-517` это достижимый вред, и он в его число «5 достижимых» не входит,
потому что соседний шаг до этих узлов не доходит.

ПРИБОР СТОИ́Т В НАСЕЛЕНИИ, КОТОРОЕ МЕРИТ
---------------------------------------------------------------------------
Его файл живёт в ``spa_core/monitoring`` — там же, где население, — поэтому
его собственные накопители суть члены замера, и головное число молча зависело
бы от того, доставлен прибор или нет. Так и было: первый живой прогон цикла
#776 на дереве С ПРИБОРОМ дал **36** против **33** на дереве без него, и
разница — ровно три СВОИХ накопителя открытой формы (``rest_reader``,
``rest_writer``, ``asked_reader``), вставшие в ГОЛОВНУЮ клетку собственного
замера. Автор объявил верное правило для ``cross`` и нарушил его в четырёх
соседних строках.

Поэтому раскладки строги (:func:`_tally`): незнакомый класс у соседа —
третий исход с названной причиной, а не тихая строка. Это убрало прибор из
головной клетки (своих накопителей там 0) и сделало ответ устойчивым к
доставке: **33 и с прибором, и без него**. Свои строки объявлены полем
``own_counters``, головное число печатается двумя числами, а не одним, —
потому что «замер, выданный за константу» и есть та форма, которой число
перестаёт быть правдой молча.

Ни одного своего правила
---------------------------------------------------------------------------
Население, вердикт читателя, вердикт писателя и набор состыкованных узлов
приходят соседскими функциями (`_reader_sites`, `_writer_kind_sites`,
`_reach_sites`). Здесь нет ни строки о том, какой счётчик открыт, что есть
раскол и каков род накопителя: вторая копия такого правила и была бы тем
предметом, который весь ряд `ADR-459`…`ADR-565` ищет.

Стык идёт по **УЗЛУ** — файл, строка и имя счётчика, — а не по имени счётчика:
«имя не есть адрес» (урок `ADR-465`), и в одном файле счётчиков с именем
``counts`` живёт много.

Население СВЕРЯЕТСЯ с опубликованным у соседа, и не только числом
---------------------------------------------------------------------------
Свой обход есть ВТОРАЯ дорога к тому же населению: разойдясь с первой, он
отвечал бы на другой вопрос. Поэтому сверяются три числа населения И обе
КРАЕВЫЕ раскладки соседей (`reader_verdicts`, `writer_outcomes`). Краевая
сверка — не украшение: она единственная ловит стык, потерявший или удвоивший
узел, потому что потеря узла население не меняет, а раскладку меняет.
Разошлось что-либо ⇒ шаг отказывает ЦЕЛИКОМ (`UNMEASURED`), а не выбирает себе
удобное число.

Чего прибор НЕ говорит
---------------------------------------------------------------------------
* **«Раскола не нашли» не означает «раскола нет».** Свидетель оси читателя
  односторонний — так сказал её собственный шаг, — и прибор это свойство
  наследует целиком.
* **Сверка идёт с артефактом, и у артефакта есть ВОЗРАСТ.** Опубликованные
  числа сняты соседом в свой такт; возраст печатается полем
  (`neighbour_age_hours`), а не сноской, потому что паритет сверяет СЕГОДНЯШНЕЕ
  дерево с ВЧЕРАШНИМ замером.
* **Он не судит, прав ли сосед.** Оба вердикта берутся как есть.
* **Он ничего не чинит** (``applied=False``): ни счётчика, ни читателя, ни
  гейта. Ни одна строка risk-логики, стоп-крана, аллокатора, живого трека или
  ``landing/`` этой работой не затронута.
"""

from __future__ import annotations

import argparse
import ast
import datetime as dt
import json
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:  # запуск ПО ПУТИ, а не пакетом
    sys.path.insert(0, str(_ROOT))

from spa_core.monitoring import rule_second_copy_census as census  # noqa: E402
from spa_core.monitoring.call_provenance import call_provenance  # noqa: E402
from spa_core.monitoring.call_provenance import describe as provenance_line  # noqa: E402,E501
from spa_core.utils.atomic import atomic_save  # noqa: E402
from spa_core.utils.observation import observed  # noqa: E402

ARTIFACT = "reachability_of_the_rest.json"
PRODUCER = "spa_core/monitoring/reachability_of_the_rest.py"
ORDER = "G98 п. 2 (хвост ADR-517)"

#: Артефакт соседа: оттуда берутся ОПУБЛИКОВАННЫЕ числа всех трёх шагов.
NEIGHBOUR_ARTIFACT = "data/rule_second_copy_census.json"
#: Имена соседских шагов в его артефакте — соседские, не свои.
STEP_READER = "open_counter_reader_harm"
STEP_WRITER = "writer_harm_form"
STEP_ASKED = "split_reachability_at_the_writer"

#: Сколько клеток и строк печатать поимённо. Обрезка показа — ВЫБОР, и он
#: назван: судить население по обрезке показа значило бы выдать цену печати за
#: замер (урок `COSTED_SAMPLE = 3` у соседа, ADR-565).
NAMED_ROWS = 10

# --- клетки стыка. Каждая — своё утверждение, потому и своё имя ------------
#: Раскол ДОКАЗАН читателем, писатель МОЛЧИТ: незнакомый класс тихо становится
#: другим исходом, и достижимость этого никто не спрашивал. ГЛАВНОЕ ЧИСЛО.
CELL_HARM_REACHABLE = "split_proven_writer_silent_reachability_never_asked"
#: Раскол доказан, но писатель падает `KeyError` раньше — вред ГРОМКИЙ.
CELL_HARM_UNREACHABLE = "split_proven_but_the_writer_raises_first"
#: Раскол доказан, род накопителя не измерен: достижимость — третий исход.
CELL_HARM_WRITER_UNMEASURED = "split_proven_writer_kind_not_measured"
#: Читатель не измерен, писатель молчит: класс тихо посчитан, а кто его читает
#: — не мерил никто. Самая тёмная клетка, и она НЕ «вреда нет».
CELL_DARK = "reader_not_measured_writer_silent"
#: Читатель не измерен, писатель падает: вред, если он есть, будет громким.
CELL_READER_UNMEASURED_LOUD = "reader_not_measured_writer_raises"
#: ОБА не измерены. Отдельное имя и отдельное число: складывать его с
#: краевыми незнаниями запрещено (`do_not_sum`).
CELL_BOTH_UNMEASURED = "neither_axis_is_measured"
#: Читатель доказал, что незнакомый класс — лишь лишняя строка отчёта.
CELL_EXTRA_LINE = "unknown_class_is_only_an_extra_line_at_the_reader"
#: Узел есть в одной переписи и отсутствует в другой. ТРЕТИЙ ИСХОД СТЫКА:
#: потеря узла уменьшает население, то есть выглядит чистотой.
CELL_UNJOINED = "the_node_is_in_one_census_and_absent_from_the_other"

#: Классы вердикта у соседа — ОБЪЯВЛЕННЫЕ перечни, по одному на ось. Свои
#: раскладки ниже открыты ПО ЭТИМ перечням и строги: см. :func:`_tally`.
READER_CLASSES = (census.READER_SPLITS_DECLARED,
                  census.READER_WHOLESALE_ONLY,
                  census.READER_UNRESOLVED)
WRITER_CLASSES = (census.WRITER_SILENT, census.WRITER_LOUD,
                  census.WRITER_UNRESOLVED)
#: Состыкованный узел, которого в переписи читателя нет ВОВСЕ. Своё имя, а не
#: строка ``None``: отсутствие узла не есть вердикт о нём.
READER_ABSENT = "the_asked_node_is_absent_from_the_reader_census"

# --- отказы САМОГО шага. Ни один из них не есть ноль -----------------------
UNMEASURED_NEIGHBOUR = "a_neighbour_step_is_absent_or_unmeasured"
UNMEASURED_POPULATION = "second_walk_disagrees_with_the_published_population"
UNMEASURED_MARGINS = "second_walk_disagrees_with_a_published_margin"
UNMEASURED_FILES = "a_file_or_directory_of_the_population_is_unreadable"
UNMEASURED_CONTROL = "the_declared_join_rule_failed_its_positive_control"
UNMEASURED_ARITHMETIC = "the_cross_and_the_margins_disagree"
UNMEASURED_CLASS = "a_neighbour_verdict_class_is_outside_the_declared_list"


class NotMeasured(RuntimeError):
    """Отказ шага: предпосылка не обеспечена. Третий исход, не вердикт."""


def _utcnow() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def node_of(row: dict) -> Tuple[str, int, str]:
    """УЗЕЛ счётчика: файл, строка, имя.

    Стык идёт по узлу, а не по имени: «имя не есть адрес» (урок `ADR-465`), и
    счётчиков с именем ``counts`` в дереве десятки.
    """
    return (str(row.get("file")), int(row.get("line") or 0),
            str(row.get("counter")))


def _cell(reader_verdict: Optional[str],
          writer_verdict: Optional[str]) -> str:
    """Клетка стыка по паре соседских вердиктов. ВСЁ правило шага — здесь."""
    if reader_verdict is None or writer_verdict is None:
        return CELL_UNJOINED
    if reader_verdict == census.READER_SPLITS_DECLARED:
        if writer_verdict == census.WRITER_SILENT:
            return CELL_HARM_REACHABLE
        if writer_verdict == census.WRITER_LOUD:
            return CELL_HARM_UNREACHABLE
        return CELL_HARM_WRITER_UNMEASURED
    if reader_verdict == census.READER_UNRESOLVED:
        if writer_verdict == census.WRITER_SILENT:
            return CELL_DARK
        if writer_verdict == census.WRITER_LOUD:
            return CELL_READER_UNMEASURED_LOUD
        return CELL_BOTH_UNMEASURED
    return CELL_EXTRA_LINE


def _tally(values: List[str], declared: Tuple[str, ...], *,
           axis: str) -> Dict[str, int]:
    """Раскладка по ОБЪЯВЛЕННЫМ классам. Незнакомый класс — третий исход.

    Накопитель строгий НАМЕРЕННО, и это не стилистика. Открытая раскладка
    (``tally.get(cls, 0) + 1``), читаемая потом объявленным ключом
    (``rest_reader.get(READER_UNRESOLVED, 0)``), и есть ровно тот вред, который
    этот прибор мерит у других: переименуй сосед класс — и «у остатка читатель
    не измерен у N» молча стало бы нулём, а `premise_of_the_order` объявил бы
    предпосылку заказа опровергнутой по ложному счёту. Громкий отказ (верная
    форма по `ADR-469`) переводит эту форму вреда в НЕ ИЗМЕРЕНО с названной
    причиной — и выводит САМ прибор из головной клетки своего же замера
    (поле ``own_counters``).
    """
    tally = {cls: 0 for cls in declared}
    for value in values:
        if value not in tally:
            raise NotMeasured(
                f"{UNMEASURED_CLASS}: ось {axis} вернула класс `{value}`, "
                f"которого нет в объявленном перечне {list(declared)} — "
                f"раскладки по нему нет, и ноль ответом не является")
        tally[value] += 1
    return tally


_CELLS = (CELL_HARM_REACHABLE, CELL_HARM_UNREACHABLE,
          CELL_HARM_WRITER_UNMEASURED, CELL_DARK,
          CELL_READER_UNMEASURED_LOUD, CELL_BOTH_UNMEASURED,
          CELL_EXTRA_LINE, CELL_UNJOINED)


def _published(root: Path) -> Tuple[Optional[dict], Optional[str]]:
    """ОПУБЛИКОВАННЫЕ соседом числа трёх шагов плюс возраст его артефакта.

    Своего правила здесь нет ни строки: шаг только ЧИТАЕТ соседский артефакт.
    Нет шага, нет поля, шаг не измерен ⇒ своя причина, а не ноль.
    """
    path = root / NEIGHBOUR_ARTIFACT
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        return None, f"{NEIGHBOUR_ARTIFACT}: {type(exc).__name__}: {exc}"
    out: Dict[str, object] = {}
    for key, step_name, margin in (
            ("reader", STEP_READER, "reader_verdicts"),
            ("writer", STEP_WRITER, "writer_outcomes"),
            ("asked", STEP_ASKED, None)):
        step = observed(doc, step_name, kind=dict)
        if step is None:
            return None, (f"в {NEIGHBOUR_ARTIFACT} нет шага `{step_name}` — "
                          f"его населения не существует; это НЕ ноль")
        if str(step.get("status")) != "MEASURED":
            return None, (f"шаг `{step_name}` соседа не измерен "
                          f"({step.get('status')}) — это НЕ «вреда нет»")
        population = observed(step, "population", kind=int)
        if population is None:
            return None, (f"у шага `{step_name}` нет поля `population`: "
                          f"отсутствие поля не есть ноль счётчиков")
        out[f"{key}_population"] = population
        if margin is not None:
            tally = observed(step, margin, kind=dict)
            if tally is None:
                return None, (f"у шага `{step_name}` нет раскладки "
                              f"`{margin}` — краевую сверку делать не с чем")
            out[f"{key}_margin"] = dict(tally)
    stamp = observed(doc, "generated_at", kind=str)
    out["generated_at"] = stamp
    return out, None


def _age_hours(stamp: Optional[str], now: dt.datetime) -> Optional[float]:
    """Возраст соседского замера. Отметки нет ⇒ `None`, а не ноль часов."""
    if not stamp:
        return None
    try:
        seen = dt.datetime.fromisoformat(str(stamp).replace("Z", "+00:00"))
    except ValueError:
        return None
    if seen.tzinfo is None:
        seen = seen.replace(tzinfo=dt.timezone.utc)
    return round((now - seen).total_seconds() / 3600.0, 2)


def _walk(root: Path) -> Tuple[List[dict], List[dict], List[dict],
                               List[dict], int]:
    """Три соседских обхода по ОДНОМУ проходу дерева, без своего правила."""
    reader: List[dict] = []
    writer: List[dict] = []
    asked: List[dict] = []
    unreadable: List[dict] = []
    scanned = 0
    for sub in census.OPEN_COUNTER_DIRS:
        base = root / sub
        if not base.is_dir():
            unreadable.append({"file": sub, "reason": "каталога нет в дереве"})
            continue
        for path in sorted(base.rglob("*.py")):
            rel = path.relative_to(root).as_posix()
            if any(rel.startswith(skip) for skip in census.OPEN_COUNTER_SKIP):
                continue
            scanned += 1
            try:
                tree = ast.parse(path.read_text(encoding="utf-8"))
            except (OSError, SyntaxError, UnicodeDecodeError) as exc:
                unreadable.append({"file": rel,
                                   "reason": f"{type(exc).__name__}: {exc}"})
                continue
            reader.extend(census._reader_sites(rel, tree))
            writer.extend(census._writer_kind_sites(rel, tree))
            asked.extend(census._reach_sites(rel, tree))
    return reader, writer, asked, unreadable, scanned


# --- ПОЛОЖИТЕЛЬНЫЙ КОНТРОЛЬ правила стыка ---------------------------------
#: Сцена контроля подаётся СТРОКАМИ, а не исходником: предмет шага — стык
#: двух готовых вердиктов, и мерить на этой сцене разбор кода значило бы
#: проверять соседа, а не себя.
def _join_control() -> dict:
    """Красен на КАЖДОМ порванном звене стыка, с названным звеном.

    Контроль не декоративен: он ловит ровно те три поломки, которыми стык
    тихо выглядит чистым, — потерю узла, зачёт асимметрии измеренным исходом
    и обрезку остатка состыкованными узлами.
    """
    rd = [
        {"file": "a.py", "line": 1, "counter": "c",
         "verdict": census.READER_SPLITS_DECLARED},
        {"file": "a.py", "line": 2, "counter": "c",
         "verdict": census.READER_UNRESOLVED},
        {"file": "a.py", "line": 3, "counter": "c",
         "verdict": census.READER_UNRESOLVED},
        {"file": "a.py", "line": 4, "counter": "c",
         "verdict": census.READER_WHOLESALE_ONLY},
        # узел ТОЛЬКО у читателя: писателя в его переписи нет
        {"file": "a.py", "line": 5, "counter": "c",
         "verdict": census.READER_SPLITS_DECLARED},
    ]
    wr = [
        {"file": "a.py", "line": 1, "counter": "c",
         "writer": census.WRITER_SILENT},
        {"file": "a.py", "line": 2, "counter": "c",
         "writer": census.WRITER_SILENT},
        {"file": "a.py", "line": 3, "counter": "c",
         "writer": census.WRITER_UNRESOLVED},
        {"file": "a.py", "line": 4, "counter": "c",
         "writer": census.WRITER_LOUD},
    ]
    asked = [{"file": "a.py", "line": 1, "counter": "c"}]
    # Правило могло не произвести стыка ВОВСЕ — например, клетка перестала
    # быть объявленной. Это тоже ПОРВАННОЕ ЗВЕНО, и контроль обязан НАЗВАТЬ
    # его, а не упасть: трассировка вместо вердикта читается как «упало», а
    # не как «правило сломано». Перехват живёт ТОЛЬКО в контроле — в замере
    # тот же `KeyError` остаётся громким по построению (ADR-469).
    try:
        cross = _cross(rd, wr, {node_of(r) for r in asked})
    except Exception as exc:                      # noqa: BLE001 — см. выше
        return {"passed": False, "checks": {}, "broken": ["cross_not_built"],
                "reason": (f"порванные звенья: cross_not_built "
                           f"({type(exc).__name__}: {exc})")}
    checks = {
        # звено 1: состыкованный узел ИСКЛЮЧЁН из остатка
        "asked_node_is_out_of_the_rest": cross["the_rest"] == 4,
        # звено 2: клетки считаются по ПАРЕ, а не по одной оси
        "dark_cell_is_counted": cross["cross"].get(CELL_DARK) == 1,
        "both_unmeasured_is_its_own_cell":
            cross["cross"].get(CELL_BOTH_UNMEASURED) == 1,
        "extra_line_is_not_harm": cross["cross"].get(CELL_EXTRA_LINE) == 1,
        # звено 3: узел без пары НЕ пропадает и НЕ зачитывается измеренным
        "unjoined_node_is_a_third_outcome":
            cross["cross"].get(CELL_UNJOINED) == 1,
        "unjoined_is_not_counted_as_harm":
            cross["cross"].get(CELL_HARM_REACHABLE) == 0,
    }
    broken = sorted(k for k, ok in checks.items() if not ok)
    return {"passed": not broken, "checks": checks, "broken": broken,
            "reason": (f"порванные звенья: {', '.join(broken)}"
                       if broken else None)}


def _cross(reader_rows: List[dict], writer_rows: List[dict],
           asked: set) -> dict:
    """Стык двух осей по узлу. ОСТАТОК — всё, чего сосед не спрашивал."""
    by_writer = {node_of(r): r for r in writer_rows}
    by_reader = {node_of(r): r for r in reader_rows}
    nodes = sorted(set(by_reader) | set(by_writer))
    rest = [n for n in nodes if n not in asked]
    # Накопитель СТРОГИЙ, и это выбор, а не недосмотр: `_cell` возвращает
    # ровно одно из восьми объявленных имён, поэтому незнакомая клетка здесь
    # означает, что перечень разошёлся с правилом. Громкий `KeyError` — верная
    # форма такого вреда (ADR-469); открыть счётчик `.get(cell, 0) + 1` значило
    # бы завести ЗДЕСЬ ровно тот предмет, который прибор и мерит.
    cross = {cell: 0 for cell in _CELLS}
    rows: List[dict] = []
    for n in rest:
        rv = (by_reader.get(n) or {}).get("verdict")
        wv = (by_writer.get(n) or {}).get("writer")
        cell = _cell(rv, wv)
        cross[cell] += 1
        rows.append({"file": n[0], "line": n[1], "counter": n[2],
                     "reader": rv, "writer": wv, "cell": cell,
                     "reader_gap": (by_reader.get(n) or {}).get("gap"),
                     "writer_gap": (by_writer.get(n) or {}).get("writer_gap")})
    return {"the_rest": len(rest), "cross": cross, "rows": rows,
            "nodes_total": len(nodes)}


def measure(root: Path, *, now: Optional[dt.datetime] = None,
            published: Optional[dict] = None,
            reader_rows: Optional[List[dict]] = None,
            writer_rows: Optional[List[dict]] = None,
            asked_rows: Optional[List[dict]] = None) -> dict:
    """Стык двух осей у ОСТАЛЬНЫХ открытых счётчиков (**заказ G98 п. 2**).

    `published`, `reader_rows`, `writer_rows`, `asked_rows` — ВХОДЫ, а не
    окружение: сцена подаёт их прямо, потому что ни соседского артефакта, ни
    боевого дерева в одноразовой копии нет по построению. Умолчание —
    настоящий артефакт и настоящий обход.
    """
    now = now or _utcnow()
    head = {
        "generated_at": now.isoformat(),
        "generated_by": PRODUCER,
        "invoked_by": call_provenance(tree_root=root),
        "question": ("что говорят ОБЕ оси — читателя и писателя — у тех "
                     "открытых счётчиков, которых шаг достижимости не "
                     "спрашивал, и сколько из них стои́т в каждой клетке "
                     "стыка"),
        "order": ORDER,
        "applied": False,
        "dirs": list(census.OPEN_COUNTER_DIRS),
        "skipped_dirs": list(census.OPEN_COUNTER_SKIP),
    }
    injected = (reader_rows is not None and writer_rows is not None
                and asked_rows is not None)
    if published is None:
        published, why = _published(root)
        if published is None:
            raise NotMeasured(why or "соседский артефакт не прочитан")
    control = _join_control()
    head["control"] = control
    if not control.get("passed"):
        raise NotMeasured(f"объявленное правило стыка не прошло контроль: "
                          f"{control.get('reason')}")
    head["neighbour_age_hours"] = _age_hours(
        published.get("generated_at") if isinstance(published, dict) else None,
        now)

    if injected:
        reader, writer, asked = (list(reader_rows), list(writer_rows),
                                 list(asked_rows))
        unreadable, scanned = [], 0
    else:
        reader, writer, asked, unreadable, scanned = _walk(root)
    if unreadable:
        raise NotMeasured(
            f"{len(unreadable)} файл(ов) или каталог(ов) не прочитано — "
            f"население неполно, а неполное население не есть измеренное: "
            f"{unreadable[0]['file']} ({unreadable[0]['reason']})")

    # --- ПАРИТЕТ населения: три числа, и каждое своё -----------------------
    for name, walked, key in (("читателя", reader, "reader_population"),
                              ("писателя", writer, "writer_population"),
                              ("достижимости", asked, "asked_population")):
        declared = observed(published, key, kind=int)
        if declared is None:
            raise NotMeasured(f"сосед не назвал населения `{key}` — сверять "
                              f"обход не с чем")
        if len(walked) != declared:
            raise NotMeasured(
                f"свой обход оси {name} нашёл {len(walked)} счётчик(ов), "
                f"сосед опубликовал {declared} — это ДВЕ дороги к одному "
                f"населению, и разойдясь, они отвечают на разные вопросы")

    # --- ПАРИТЕТ КРАЕВЫХ раскладок: единственное, что ловит потерю узла ---
    for axis, rows, field, published_key, classes in (
            ("читателя", reader, "verdict", "reader_margin", READER_CLASSES),
            ("писателя", writer, "writer", "writer_margin", WRITER_CLASSES)):
        declared = observed(published, published_key, kind=dict)
        if declared is None:
            raise NotMeasured(f"сосед не назвал раскладки `{published_key}`")
        mine = _tally([str(row.get(field)) for row in rows], classes,
                      axis=axis)
        for cls, count in declared.items():
            if mine.get(str(cls), 0) != count:
                raise NotMeasured(
                    f"краевая раскладка оси {axis} разошлась на классе "
                    f"`{cls}`: свой обход {mine.get(str(cls), 0)}, сосед "
                    f"{count} — населения совпали, а состав нет, то есть "
                    f"стык потерял или удвоил узел")

    asked_nodes = {node_of(r) for r in asked}
    joined = _cross(reader, writer, asked_nodes)
    cross, rows = joined["cross"], joined["rows"]

    # --- АРИФМЕТИКА стыка: клетки обязаны сойтись с остатком --------------
    if sum(cross.values()) != joined["the_rest"]:
        raise NotMeasured(
            f"сумма клеток {sum(cross.values())} не равна остатку "
            f"{joined['the_rest']} — клетка потеряна или посчитана дважды")

    reader_by_node = {node_of(r): r for r in reader}
    rest_reader = _tally(
        [str(reader_by_node[n]["verdict"]) for n in reader_by_node
         if n not in asked_nodes], READER_CLASSES, axis="читателя")
    writer_by_node = {node_of(r): r for r in writer}
    rest_writer = _tally(
        [str(writer_by_node[n]["writer"]) for n in writer_by_node
         if n not in asked_nodes], WRITER_CLASSES, axis="писателя")

    # Ключ объявленный, и раскладка строгая: исчезни класс у соседа — отказ
    # громкий, а не ноль (см. :func:`_tally`).
    reader_unmeasured = rest_reader[census.READER_UNRESOLVED]
    writer_unmeasured = rest_writer[census.WRITER_UNRESOLVED]
    both = cross[CELL_BOTH_UNMEASURED]
    # Клетка «оба не измерены» обязана быть не больше каждого краевого
    # незнания: больше — значит стык выдумал пары, которых нет.
    if both > min(reader_unmeasured, writer_unmeasured):
        raise NotMeasured(
            f"клетка `{CELL_BOTH_UNMEASURED}` = {both} больше краевого "
            f"незнания (читатель {reader_unmeasured}, писатель "
            f"{writer_unmeasured}) — стык выдумал пару")

    # --- ПРЕДПОСЫЛКА ЗАКАЗА: мерится, а не принимается на слово -----------
    asked_reader = _tally(
        [(str(reader_by_node[n]["verdict"]) if n in reader_by_node
          else READER_ABSENT) for n in asked_nodes],
        READER_CLASSES + (READER_ABSENT,), axis="читателя у состыкованных")
    measured_reader = sum(c for v, c in rest_reader.items()
                          if v != census.READER_UNRESOLVED)

    named = [r for r in rows if r["cell"] == CELL_HARM_REACHABLE]
    # --- САМ ПРИБОР стои́т в населении, которое мерит ----------------------
    # Его файл живёт в `spa_core/monitoring`, поэтому его собственные
    # накопители — члены этого же населения, и головное число зависело бы от
    # того, доставлен прибор или нет. Молча это и есть «замер, выданный за
    # константу»: до доставки 33, после — 36, и причина не названа нигде.
    # Поэтому свои строки объявлены полем, а головное число печатается ДВАЖДЫ
    # — с прибором и без него; расхождение между ними обязано быть нулём, и
    # держит это не слово, а строгая раскладка выше (`_tally`): громкий
    # писатель выводит собственные накопители из головной клетки.
    own = [r for r in rows if r["file"] == PRODUCER]
    own_in_the_head_cell = [r for r in own
                            if r["cell"] == CELL_HARM_REACHABLE]
    return {
        **head,
        "status": "MEASURED",
        "files_scanned": scanned,
        "population": joined["nodes_total"],
        "asked_by_the_neighbour": len(asked_nodes),
        "the_rest": joined["the_rest"],
        "cross": cross,
        "reader_axis_over_the_rest": rest_reader,
        "writer_axis_over_the_rest": rest_writer,
        "premise_of_the_order": {
            "claim": ("заказ утверждал: «у остальных читатель НЕ ИЗМЕРЕН»"),
            "reader_measured_among_the_rest": measured_reader,
            "reader_unmeasured_among_the_rest": reader_unmeasured,
            "asked_nodes_by_reader_verdict": asked_reader,
            "verdict": ("ОПРОВЕРГНУТА"
                        if measured_reader > 0 else "ПОДТВЕРЖДЕНА"),
        },
        "do_not_sum": {
            "rule": ("заказ запрещает складывать два незнания в одно: три "
                     "третьих исхода ниже суть РАЗНЫЕ утверждения и "
                     "суммированию не подлежат"),
            "reader_axis_unmeasured": reader_unmeasured,
            "writer_axis_unmeasured": writer_unmeasured,
            "both_axes_unmeasured": both,
            "the_join_itself_failed": cross[CELL_UNJOINED],
        },
        "named_rows": [
            {"file": r["file"], "line": r["line"], "counter": r["counter"],
             "cell": r["cell"]}
            for r in named[:NAMED_ROWS]],
        "named_rows_shown": min(len(named), NAMED_ROWS),
        "named_rows_total": len(named),
        "own_counters": {
            "rule": ("прибор живёт в том же каталоге, что и население, "
                     "поэтому его собственные накопители — члены замера; "
                     "головное число печатается и с ним, и без него, потому "
                     "что иначе доставка молча меняла бы ответ"),
            "producer": PRODUCER,
            "rows": [{"line": r["line"], "counter": r["counter"],
                      "cell": r["cell"]} for r in own],
            "count": len(own),
            "in_the_head_cell": len(own_in_the_head_cell),
            "head_cell_without_the_step": len(named) - len(own_in_the_head_cell),
        },
        "blind": [
            ("«раскола не нашли» НЕ есть «раскола нет»: свидетель оси "
             "читателя односторонний по собственному признанию её шага, и "
             "прибор наследует это свойство целиком"),
            ("паритет сверяет СЕГОДНЯШНЕЕ дерево с ВЧЕРАШНИМ замером соседа "
             "— возраст стои́т полем `neighbour_age_hours`, а не сноской"),
            ("прибор не судит, ПРАВ ли сосед: оба вердикта берутся как есть, "
             "и ошибка любой из осей проходит сквозь стык незамеченной"),
            (f"`{CELL_UNJOINED}` есть отказ СТЫКА, а не свойство счётчика: "
             f"узел без пары не доказывает ни вреда, ни его отсутствия"),
            ("межпроцедурного разбора здесь нет вовсе — ни одного своего "
             "правила о счётчике, расколе или роде накопителя"),
        ],
    }


def report(doc: dict) -> List[str]:
    """Человеческий отчёт. Третий исход печатается ИСХОДОМ, а не пустотой."""
    out: List[str] = []
    if str(doc.get("status")) != "MEASURED":
        out.append(f"[НЕ ИЗМЕРЕНО] стык двух осей у остальных открытых "
                   f"счётчиков (заказ {doc.get('order')}): "
                   f"{doc.get('reason')}")
        return out
    cross = doc.get("cross") or {}
    premise = doc.get("premise_of_the_order") or {}
    dns = doc.get("do_not_sum") or {}
    age = doc.get("neighbour_age_hours")
    out.append(f"стык двух осей у ОСТАЛЬНЫХ открытых счётчиков (заказ "
               f"{doc.get('order')}): население {doc.get('population')}, "
               f"сосед спрашивал {doc.get('asked_by_the_neighbour')}, "
               f"остаток {doc.get('the_rest')}")
    out.append(f"  ❗ОТВЕТ: раскол ДОКАЗАН, писатель МОЛЧИТ, достижимость не "
               f"спрашивал никто — {cross.get(CELL_HARM_REACHABLE)}; из них "
               f"громких (писатель падает) {cross.get(CELL_HARM_UNREACHABLE)}")
    own = doc.get("own_counters") or {}
    if own:
        out.append(f"  САМ ПРИБОР в населении: {own.get('count')} "
                   f"накопитель(ей), из них в головной клетке "
                   f"{own.get('in_the_head_cell')} ⇒ головное число без "
                   f"прибора {own.get('head_cell_without_the_step')} "
                   f"(доставка ответа не меняет)")
    out.append("  клетки: " + " · ".join(
        f"{k} {v}" for k, v in cross.items() if v))
    out.append(f"  ПРЕДПОСЫЛКА ЗАКАЗА {premise.get('verdict')}: у остатка "
               f"читатель ИЗМЕРЕН у "
               f"{premise.get('reader_measured_among_the_rest')} и не измерен "
               f"у {premise.get('reader_unmeasured_among_the_rest')}; у "
               f"состыкованных узлов по читателю — "
               f"{premise.get('asked_nodes_by_reader_verdict')}")
    out.append(f"  НЕ СКЛАДЫВАТЬ: читатель не измерен "
               f"{dns.get('reader_axis_unmeasured')} · писатель не измерен "
               f"{dns.get('writer_axis_unmeasured')} · оба "
               f"{dns.get('both_axes_unmeasured')} · стык не состоялся "
               f"{dns.get('the_join_itself_failed')} — это РАЗНЫЕ утверждения")
    out.append(f"  возраст соседского замера: "
               f"{'НЕ ИЗМЕРЕН' if age is None else f'{age}ч'}")
    for row in (doc.get("named_rows") or []):
        out.append(f"  [{row['cell']}] {row['file']}:{row['line']} "
                   f"{row['counter']}")
    if (doc.get("named_rows_total") or 0) > (doc.get("named_rows_shown") or 0):
        out.append(f"  … ещё {doc['named_rows_total'] - doc['named_rows_shown']}"
                   f" того же вида (обрезка ПОКАЗА, не населения)")
    for line in (doc.get("blind") or []):
        out.append(f"  НЕ ДОКЛАДЫВАЕТ: {line}")
    out.append(f"  ADVISORY: прибор только ЧИТАЕТ (applied="
               f"{doc.get('applied')})")
    if doc.get("invoked_by"):
        out.append(f"  {provenance_line(doc['invoked_by'])}")
    return out


def format_report(doc: dict, *, max_rows: int = 4) -> List[str]:
    """Короткая форма для шага 0-офис.

    Отбор ИМЕННОЙ, а не срезом по длине: срез тих и теряет то, что окажется
    ниже предела, — а ниже предела у этого шага лежат ровно `ADVISORY` и
    запрет складывать. Обрезается ТОЛЬКО поимённый перечень строк, и его
    обрезка названа в самой строке.
    """
    lines = report(doc)
    if str(doc.get("status")) != "MEASURED":
        return lines
    out, named = [], 0
    for line in lines:
        if line.startswith("  НЕ ДОКЛАДЫВАЕТ"):
            continue
        if line.startswith("  ["):
            named += 1
            if named > max_rows:
                continue
        out.append(line)
    return out


def run(root: str | Path = _ROOT, *, dest: Optional[Path] = None,
        write: bool = True, now: Optional[dt.datetime] = None,
        published: Optional[dict] = None,
        reader_rows: Optional[List[dict]] = None,
        writer_rows: Optional[List[dict]] = None,
        asked_rows: Optional[List[dict]] = None) -> dict:
    root = Path(root)
    target = Path(dest) if dest is not None else root / "data" / ARTIFACT
    try:
        doc = measure(root, now=now, published=published,
                      reader_rows=reader_rows, writer_rows=writer_rows,
                      asked_rows=asked_rows)
    except (NotMeasured, census.NotMeasured) as exc:
        # Третий исход обязан быть ИСХОДОМ на любой глубине: трассировка
        # вместо вердикта читается как «упало», а не как «не измерено».
        doc = {
            "generated_at": (now or _utcnow()).isoformat(),
            "generated_by": PRODUCER,
            "invoked_by": call_provenance(tree_root=root),
            "status": "UNMEASURED",
            "order": ORDER,
            "applied": False,
            "reason": str(exc),
            "cross": {},
        }
    if write:
        atomic_save(doc, str(target))
    return {"measured": doc.get("status") == "MEASURED", "doc": doc,
            "artifact": str(target)}


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(
        description=("стык читателя и писателя у остальных открытых "
                     "счётчиков (заказ G98 п. 2)"))
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
