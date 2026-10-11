"""Цена АДРЕСА находки: место («производитель + поле») против имени.

Заказ **G115, п. 1** приказа владельца «Portfolio CIO» (хвост
[ADR-541](../../docs/decisions/ADR-541-the-quadruple-rotted-before-it-was-adjudicated.md)).

## Вопрос, на который прибор отвечает

Заказ назвал ВРЕД так: «три отказа подряд спотыкаются об одно: признак
отвечает о МЕСТЕ в коде, кортеж личностей адресуется ИМЕНЕМ». И потребовал
замер, а не четвёртый признак рода:

1. сколько находок переписи разрешилось бы адресацией «производитель + поле»
   вместо «поле»;
2. во что обошлась бы такая координата читателям.

Разница двух адресов ровно одна. ``_IDENTITY_FIELDS``
(``run_identity_key_price``) есть кортеж ИМЁН, и дописанное имя действует
ВСЮДУ; поэтому имя обязано быть подпёрто населением — «длина одного списка
населением не является» ([ADR-503](../../docs/decisions/ADR-503-identity-fields-extended-by-measurement.md)).
Адрес «производитель + поле» действует в ОДНОМ месте, и населения ему не нужно
вовсе: свидетельство у него и есть то самое наблюдение, которым перепись
находку нашла.

Отсюда ответ, который прибор ВЫЧИСЛЯЕТ, а не предполагает: находка, у которой
кандидат годен ЗДЕСЬ и нигде больше, сегодня отказана **свойством глобальной
координаты**, а не свойством поля. Таких находок и есть «разрешимые только
местом».

## Два прочтения населения — и оба печатаются

[ADR-695](../../docs/decisions/ADR-695-the-population-of-a-name-was-right-for-another-question.md)
измерил, что «население имени» читалось двумя разными числами:

* **узкое** (``counted``, оно же ``candidate_fields_outside`` переписи) —
  «сколько БЕЗЫМЯННЫХ списков это имя спасло бы»;
* **широкое** (``eligible_anywhere``) — «насколько широко имя подпёрто
  данными», включая списки, у которых личность уже есть.

Мерило ADR-503 судило узким, а спрашивало о широком. Поэтому здесь считаются
ОБА, и расхождение между ними — отдельное число, а не выбор одного на вкус:
выбрать молча значило бы повторить тот же дефект на новом вопросе.

## Чего прибор НЕ доказывает

* **«Разрешимо местом» — про АДРЕС, а не про верность личности.** Годность
  поля есть наблюдение ОДНОГО ответа читателя (та же односторонность, что у
  переписи): «годного поля нет» — свойство, «поле годно» — наблюдение.
* **Устойчивость самого места меряется ФОРМОЙ координаты, а не прогоном.**
  Координата без позиционного звена всё ещё может поехать от переименования
  ключа словаря; найденное позиционное звено есть доказанный МИНИМУМ
  неустойчивости, а не её полная мера.
* **Цена читателям меряется ИМЕНАМИ, связанными в области вызова, а не
  потоком значения.** Место, доступное под другим именем, прибор прочтёт как
  «недоступно»; поэтому цена есть ВЕРХНЯЯ граница. Обратной ошибки нет: имя в
  области не означает, что в нём лежит нужное место, и это сказано вслух.
* **Ни одно имя не дописывается в ``_IDENTITY_FIELDS``, ни один адрес не
  заводится, порога не назначается.** Прибор только ЧИТАЕТ: правило — после
  замера, как и требует заказ.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import ast
import re
import sys
from pathlib import Path
from typing import Dict, FrozenSet, Iterable, List, Optional, Sequence, Tuple

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

# Строка третьего исхода рода читается У СОСЕДА, а не перепечатывается: имя
# исхода — его утверждение, и вторая копия разошлась бы с первой молча.
from spa_core.monitoring.identity_field_kind import (  # noqa: E402
    UNMEASURED as _KIND_UNMEASURED,
)

#: Исходы зонда, у которых находка переписи ОСМЫСЛЕННА: элементы — словари, а
#: значит могли бы назвать себя полем, и личности у списка нет. Тот же перечень,
#: что у ``_DICT_OUTCOMES`` переписи, и по той же причине: список скаляров
#: назван не полем вовсе (``BY_VALUE``), и адрес поля ему не нужен.
FINDING_OUTCOMES: Tuple[str, ...] = ("unnamed_candidate_outside",
                                     "unnamed_no_candidate")

#: Пустая причина = поле годно. Та же условность, что у ``scalar_refusal`` и у
#: ``candidate_denominator.ELIGIBLE``.
ELIGIBLE = ""

#: Ключ состава имён вне кортежа у строки зонда.
COMPOSITION_KEY = "outside_fields"

#: Порог «имя подпёрто населением». ВЗЯТ ДОСЛОВНО из причины отказа ADR-503
#: («население его — ОДИН список из 1703; длина одного списка населением не
#: является»), а не назначен здесь: назначить порог значило бы подменить
#: предмет замера. Чувствительность вердикта к порогу печатается рядом
#: (``population_histogram``) — именно затем, чтобы ответ не держался на числе 2.
GLOBAL_EVIDENCE_MIN = 2

#: Два прочтения населения (ADR-695). Ключи строк ``candidate_denominator``.
BROAD_READING = "eligible_anywhere"
NARROW_READING = "counted"
READINGS: Tuple[str, ...] = (BROAD_READING, NARROW_READING)

#: Позиционное звено координаты: ``[8]``. Именно от него личность и спасает, и
#: найти его в адресе САМОГО места значит найти координату, которая поедет тем
#: же способом, каким ехала бы находка.
_POSITIONAL = re.compile(r"\[\d+\]")

#: Имена, которыми в дереве зовётся КООРДИНАТА внутри обхода, и имена, которыми
#: зовётся ПРОИЗВОДИТЕЛЬ. Перечни раздельные: место есть ПАРА, и «координата
#: есть, производителя нет» — это не половина цены, а другая цена (одну строку
#: пришлось бы протащить через обход, другую — через вызов читателя).
_COORD_NAMES: FrozenSet[str] = frozenset({"path", "coord", "coordinate"})
_PRODUCER_NAMES: FrozenSet[str] = frozenset({"module", "reader", "producer",
                                             "rel"})

#: Двери правила личности: обе зовутся из обхода и обе строят координату.
#: ``indexed`` рядом с ``element_identity`` намеренно — он и есть место, где
#: личность превращается в адрес, и цена адреса платится ИМЕННО там.
IDENTITY_DOORS: Tuple[str, ...] = ("element_identity", "indexed")

#: Каталоги дерева, в которых ищутся двери. Те же, что у соседних приборов
#: семьи: `landing/` питоньих читателей не содержит.
DEFAULT_ROOTS: Tuple[str, ...] = ("spa_core", "scripts")


def composition_of(row: dict) -> Optional[Dict[str, str]]:
    """Состав имён вне кортежа у ОДНОЙ строки зонда либо ``None``.

    ``None`` и пустой словарь — РАЗНЫЕ ответы: первый значит «зонд состава не
    поставил» (расхождение зонда со сводом), второй — «вне кортежа у списка нет
    ни одного поля». Слить их значило бы сделать отсутствие замера неотличимым
    от наблюдённого нуля (инв. #17). Правило читается тем же ключом, что у
    ``candidate_denominator``, и это не вторая копия правила: там считается
    население ИМЕНИ, здесь — адрес НАХОДКИ, и общего у них ровно имя ключа.
    """
    composition = row.get(COMPOSITION_KEY)
    if not isinstance(composition, dict):
        return None
    return {str(k): str(v) for k, v in composition.items()}


def positional_links(coord) -> List[str]:
    """Позиционные звенья В САМОЙ координате места — ``[8]``, ``[12]``…

    Пустой список значит «позиционных звеньев не найдено», а не «координата
    устойчива»: переименование ключа словаря эту меру не задевает (сказано в
    докстринге модуля). Координата, которой нет вовсе, даёт ``None`` — третий
    исход, потому что место без адреса в таблицу адресов не ложится.
    """
    if not isinstance(coord, str):
        return []
    return _POSITIONAL.findall(coord)


def population_of(axis) -> Optional[Dict[str, Dict[str, Optional[int]]]]:
    """Население каждого имени ОБОИМИ прочтениями — вход, а не пересчёт.

    Берётся готовым у ``candidate_denominator``: правило «что считать
    населением» живёт там ОДНОЙ копией, и вторая здесь расходилась бы с первой
    молча — ровно тот класс, который вся эта семья ловит у читателей.

    ``None`` значит «оси не дали вовсе либо она сама НЕ ИЗМЕРЕНА»: судить о
    населении не от чего, и это не «население ноль».
    """
    if not isinstance(axis, dict):
        return None
    if str(axis.get("status")) != "MEASURED":
        return None
    rows = axis.get("rows")
    if not isinstance(rows, list):
        return None
    out: Dict[str, Dict[str, Optional[int]]] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        name = str(row.get("field"))
        broad = row.get(BROAD_READING)
        narrow = row.get(NARROW_READING)
        out[name] = {
            BROAD_READING: int(broad) if isinstance(broad, int) else None,
            # `counted is None` у соседа означает «перепись имя не печатает»
            # (третий исход), и обратить его в ноль значило бы напечатать
            # «население ноль» там, где население не измерено.
            NARROW_READING: int(narrow) if isinstance(narrow, int) else None,
        }
    return out or None


def _supported(name: str, population: Dict[str, Dict[str, Optional[int]]],
               reading: str) -> Optional[bool]:
    """Подпёрто ли ИМЯ населением по этому прочтению. ``None`` — не измерено."""
    row = population.get(name)
    if row is None:
        return None
    value = row.get(reading)
    if value is None:
        return None
    return value >= GLOBAL_EVIDENCE_MIN


def classify(row: dict, population: Dict[str, Dict[str, Optional[int]]],
             identity_fields: Sequence[str], reading: str) -> dict:
    """Чем разрешается ОДНА находка: именем, только местом, ничем.

    Вердикты:

    * ``no_candidate`` — годного поля вне кортежа нет ни одного. Ни имя, ни
      место не помогают: это остаток, о котором адрес не спор.
    * ``name_addressable`` — есть кандидат, подпёртый населением ⇒ дописанное
      ИМЯ разрешило бы находку, и место не покупает ничего.
    * ``place_only`` — кандидаты есть, и ни один не подпёрт населением ⇒
      сегодня находка отказана свойством ГЛОБАЛЬНОЙ координаты, которого у
      адреса места нет вовсе. **Это и есть число заказа.**
    * ``unmeasured`` — состава зонд не поставил, либо населения кандидата нет
      в оси: третий исход с причиной, а не ноль.
    """
    outcome = str(row.get("outcome"))
    place = {"module": row.get("module"), "coord": row.get("coord"),
             "n": row.get("n"), "outcome": outcome}
    composition = composition_of(row)
    if composition is None:
        return dict(place, verdict="unmeasured", candidates=[],
                    reason="зонд не поставил состав имён вне кортежа")
    known = set(identity_fields)
    candidates = sorted(name for name, cause in composition.items()
                        if cause == ELIGIBLE and name not in known)
    if not candidates:
        return dict(place, verdict="no_candidate", candidates=[],
                    reason="годного поля вне кортежа нет ни одного")
    supported = {name: _supported(name, population, reading)
                 for name in candidates}
    if any(value is True for value in supported.values()):
        return dict(place, verdict="name_addressable",
                    candidates=candidates,
                    supported_names=sorted(n for n, v in supported.items()
                                           if v is True),
                    reason="")
    if all(value is None for value in supported.values()):
        return dict(place, verdict="unmeasured", candidates=candidates,
                    reason=("ни у одного кандидата населения в оси нет — "
                            "судить о глобальном имени не от чего"))
    return dict(place, verdict="place_only", candidates=candidates,
                # Поимённо: спор об адресе решается составом, а не числом.
                unsupported_names=sorted(n for n, v in supported.items()
                                         if v is False),
                population_unmeasured=sorted(n for n, v in supported.items()
                                             if v is None),
                reason="")


def _reading_tally(rows: Iterable[dict],
                   population: Dict[str, Dict[str, Optional[int]]],
                   identity_fields: Sequence[str], reading: str) -> dict:
    verdicts: Dict[str, int] = {}
    place_only: List[dict] = []
    unmeasured: List[dict] = []
    for row in rows:
        verdict_row = classify(row, population, identity_fields, reading)
        verdict = str(verdict_row["verdict"])
        verdicts[verdict] = verdicts.get(verdict, 0) + 1
        if verdict == "place_only":
            place_only.append(verdict_row)
        elif verdict == "unmeasured":
            unmeasured.append(verdict_row)
    return {"verdicts": verdicts, "place_only": place_only,
            "unmeasured": unmeasured}


def _findings(rows: Iterable[dict]) -> Tuple[List[dict], List[dict]]:
    """Находки (словари длиннее одного) и строки, у которых длины НЕТ.

    Длина — наблюдение, и её отсутствие не есть «один элемент»: ``int(n or 0)``
    отправил бы строку без длины в синглтоны, то есть молча вынес бы её из
    знаменателя (инв. #17, урок соседа).
    """
    findings: List[dict] = []
    without_length: List[dict] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        if str(row.get("outcome")) not in FINDING_OUTCOMES:
            continue
        n = row.get("n")
        if not isinstance(n, int):
            without_length.append({"module": row.get("module"),
                                   "coord": row.get("coord"),
                                   "outcome": str(row.get("outcome")),
                                   "reason": "у строки нет длины"})
            continue
        if n <= 1:
            continue
        findings.append(row)
    return findings, without_length


def _histogram(findings: Sequence[dict],
               population: Dict[str, Dict[str, Optional[int]]],
               identity_fields: Sequence[str], reading: str) -> dict:
    """Распределение ЛУЧШЕГО населения кандидата по находкам.

    Печатается затем, чтобы вердикт не держался на пороге
    ``GLOBAL_EVIDENCE_MIN``: читающий видит, что сдвиг порога сделал бы с
    числом. Находка без кандидатов в распределение не входит — у неё лучшего
    населения нет; находка, чьё лучшее население НЕ ИЗМЕРЕНО, считается
    отдельным ключом, а не нулём.
    """
    buckets: Dict[str, int] = {}
    known = set(identity_fields)
    for row in findings:
        composition = composition_of(row)
        if composition is None:
            continue
        candidates = [name for name, cause in composition.items()
                      if cause == ELIGIBLE and name not in known]
        if not candidates:
            continue
        values = [population.get(name, {}).get(reading) for name in candidates]
        measured = [v for v in values if v is not None]
        if not measured:
            buckets["unmeasured"] = buckets.get("unmeasured", 0) + 1
            continue
        best = max(measured)
        key = str(best) if best < 5 else "5+"
        buckets[key] = buckets.get(key, 0) + 1
    return dict(sorted(buckets.items()))


def place_key_stability(place_only: Sequence[dict]) -> dict:
    """Устойчив ли адрес САМОГО места — по форме его координаты.

    Таблица адресов «производитель + поле» ключуется координатой списка, и
    координата эта бывает позиционной сама. Тогда ключ таблицы поедет ровно тем
    способом, от которого личность и спасает, — и это не довод против адреса, а
    названная его цена.
    """
    positional: List[dict] = []
    without_coord: List[dict] = []
    producers: Dict[str, int] = {}
    for row in place_only:
        module = row.get("module")
        producers[str(module)] = producers.get(str(module), 0) + 1
        coord = row.get("coord")
        if not isinstance(coord, str) or not coord:
            without_coord.append({"module": module, "coord": coord,
                                  "reason": "у места нет адреса-координаты"})
            continue
        links = positional_links(coord)
        if links:
            positional.append({"module": module, "coord": coord,
                               "positional_links": links})
    return {
        "rows_needed": len(place_only),
        "producers_touched": len(producers),
        "key_positional": positional,
        "key_unmeasured": without_coord,
    }


def producer_file(module) -> Optional[str]:
    """Файл производителя ответа по точечному имени читателя переписи.

    ``None`` — имени нет вовсе: место без производителя в таблицу адресов не
    ложится, и это третий исход, а не «файл не найден».
    """
    if not isinstance(module, str) or not module:
        return None
    return module.replace(".", "/") + ".py"


def clock_at_place(name: str, module, kind_row) -> Tuple[str, str]:
    """Есть ли у ИМЕНИ стенные часы В ФАЙЛЕ ЭТОГО производителя.

    Возвращает (исход, причина). Исходы:

    * ``clock_here`` — часы найдены в файле самого производителя: адрес места
      НЕ лечит отказ, координата поехала бы каждый прогон ЭТОГО производителя;
    * ``clean_here`` — часов в этом файле нет, и перечень мест НЕ усечён;
    * ``imported_refusal`` — часы у имени есть, но в ДРУГИХ файлах: отказ
      по роду привезён сюда из чужого места, и адрес места его снимает. **Это
      и есть вред, названный заказом, в числах.**
    * ``unmeasured`` — перечень мест усечён, вердикт рода не измерен либо имени
      в документе нет: «не измерено» никогда не выдаётся за «чисто».

    Род спрашивается у ``identity_field_kind`` (ADR-539) ВХОДОМ: вторая копия
    правила рода расходилась бы с первой молча.
    """
    path = producer_file(module)
    if path is None:
        return "unmeasured", "у места нет имени производителя"
    if not isinstance(kind_row, dict):
        return "unmeasured", f"рода имени «{name}» в документе нет вовсе"
    verdict = str(kind_row.get("verdict"))
    if verdict == _KIND_UNMEASURED:
        return "unmeasured", (f"род имени «{name}» НЕ ИЗМЕРЕН: "
                              f"{kind_row.get('why_unmeasured')}")
    sites: List[str] = []
    counted = 0
    for key, count_key in (("wall_clock_sites", "wall_clock_count"),
                           ("clock_named_read_sites", "clock_named_read_count")):
        rows = kind_row.get(key)
        rows = rows if isinstance(rows, list) else []
        sites.extend(str(r) for r in rows)
        count = kind_row.get(count_key)
        counted += int(count) if isinstance(count, int) else 0
    if not counted:
        return "clean_here", ""
    # Перечень мест у соседа УКОРОЧЕН по построению (первые восемь). Укорочение
    # не имеет права читаться как «в моём файле часов нет» — это ровно тот
    # класс, против которого написано правило о недосмотренном обходе.
    if len(sites) < counted:
        return "unmeasured", (f"перечень мест часов у «{name}» укорочен "
                              f"({len(sites)} из {counted}) — «в этом файле "
                              f"часов нет» по нему не доказуемо")
    if any(site.startswith(f"{path}:") for site in sites):
        return "clock_here", (f"часы у «{name}» стоя́т в файле самого "
                              f"производителя — адрес места отказ не лечит")
    return "imported_refusal", (f"часы у «{name}» есть, но в ДРУГИХ файлах "
                                f"({len(sites)}) — отказ по роду привезён из "
                                f"чужого места")


def kind_at_place(place_only: Sequence[dict], kind_doc) -> dict:
    """Лечит ли адрес места ВТОРОЙ отказ — по роду поля у производителя.

    Первый отказ (население) адрес снимает по построению: населения ему не
    нужно. Второй (род) — не всегда: поле, которое ЗДЕСЬ же пишется стенными
    часами, под любым адресом останется координатой, едущей каждый прогон.
    Поэтому число заказа раскладывается на два, и складывать их обратно
    нельзя — чинятся они разным.
    """
    if not isinstance(kind_doc, dict) or not isinstance(kind_doc.get("fields"),
                                                        dict):
        return {"status": "UNMEASURED",
                "reason": ("рода кандидатов не дали вовсе — лечит ли адрес "
                           "ВТОРОЙ отказ, судить не от чего; это не «лечит»")}
    fields = kind_doc["fields"]
    classes: Dict[str, int] = {}
    rows_out: List[dict] = []
    for row in place_only:
        module = row.get("module")
        per_candidate = {}
        for name in (row.get("candidates") or []):
            outcome, why = clock_at_place(str(name), module, fields.get(name))
            per_candidate[str(name)] = {"outcome": outcome, "why": why}
        outcomes = {v["outcome"] for v in per_candidate.values()}
        if "clean_here" in outcomes or "imported_refusal" in outcomes:
            verdict = "place_resolves"
        elif outcomes == {"clock_here"}:
            verdict = "place_refused_by_clock"
        else:
            verdict = "unmeasured"
        classes[verdict] = classes.get(verdict, 0) + 1
        rows_out.append({"module": module, "coord": row.get("coord"),
                         "verdict": verdict, "candidates": per_candidate})
    imported = [r for r in rows_out
                if any(v["outcome"] == "imported_refusal"
                       for v in r["candidates"].values())]
    return {
        "status": "MEASURED",
        "verdicts": dict(sorted(classes.items())),
        # Имена, чей отказ по роду привезён из ЧУЖОГО файла. Отдельное число:
        # это и есть вред, названный заказом («признак о месте, кортеж об
        # имени»), и он тут не прозой, а счётом.
        "imported_refusals": len(imported),
        "rows": rows_out,
    }


def _scope_names(chain: Sequence[ast.AST]) -> FrozenSet[str]:
    """Имена, СВЯЗАННЫЕ в цепочке областей вокруг вызова.

    Считаются параметры функций цепочки и цели присваиваний их собственных
    тел. Поток значения здесь не прослеживается намеренно: прибор отвечает
    «доступно ли место под нужным именем», а не «лежит ли в нём место», и
    односторонность названа в докстринге модуля.
    """
    names: set = set()
    for scope in chain:
        args = getattr(scope, "args", None)
        if isinstance(args, ast.arguments):
            for arg in (list(args.posonlyargs) + list(args.args)
                        + list(args.kwonlyargs)):
                names.add(arg.arg)
            for extra in (args.vararg, args.kwarg):
                if extra is not None:
                    names.add(extra.arg)
        for node in ast.walk(scope):
            if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store):
                names.add(node.id)
    return frozenset(names)


def _door_name(node: ast.AST) -> Optional[str]:
    func = getattr(node, "func", None)
    if isinstance(func, ast.Name):
        return func.id if func.id in IDENTITY_DOORS else None
    if isinstance(func, ast.Attribute):
        return func.attr if func.attr in IDENTITY_DOORS else None
    return None


def door_sites(source: str) -> Tuple[List[dict], Optional[str]]:
    """Все зовы дверей личности в ОДНОМ файле и доступность места у каждого.

    Второй член кортежа — причина, по которой файл НЕ разобран; тогда первый
    пуст, и ноль находок у такого файла читать как «дверей нет» запрещено.
    """
    try:
        tree = ast.parse(source)
    except SyntaxError as exc:
        return [], f"не разобран: {type(exc).__name__}"
    parents: Dict[int, ast.AST] = {}
    for node in ast.walk(tree):
        for child in ast.iter_child_nodes(node):
            parents[id(child)] = node
    sites: List[dict] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        door = _door_name(node)
        if door is None:
            continue
        chain: List[ast.AST] = []
        cursor: Optional[ast.AST] = parents.get(id(node))
        while cursor is not None:
            if isinstance(cursor, (ast.FunctionDef, ast.AsyncFunctionDef)):
                chain.append(cursor)
            cursor = parents.get(id(cursor))
        bound = _scope_names(chain)
        has_coord = bool(bound & _COORD_NAMES)
        has_producer = bool(bound & _PRODUCER_NAMES)
        sites.append({
            "door": door,
            "line": node.lineno,
            "function": getattr(chain[0], "name", None) if chain else None,
            "coord_in_scope": has_coord,
            "producer_in_scope": has_producer,
            "place_available": ("both" if has_coord and has_producer
                                else "coord_only" if has_coord
                                else "producer_only" if has_producer
                                else "neither"),
        })
    return sites, None


def reader_price(tree_root: Path,
                 roots: Sequence[str] = DEFAULT_ROOTS) -> dict:
    """Цена координаты читателям — по ЗОВАМ дверей личности в дереве.

    Меряется то, что заказ и спросил: сколько мест в коде пришлось бы тронуть,
    чтобы адрес стал парой. Разделение «в тестах / в рантайме» намеренно: зов в
    тесте переписать дешевле, но переписать его всё равно придётся, и спрятать
    эти зовы из знаменателя значило бы занизить цену.
    """
    sites: List[dict] = []
    unmeasured: Dict[str, str] = {}
    files_parsed = 0
    for root in roots:
        base = Path(tree_root) / root
        if not base.is_dir():
            unmeasured[root] = "каталога нет в дереве"
            continue
        for path in sorted(base.rglob("*.py")):
            rel = str(path.relative_to(tree_root))
            try:
                source = path.read_text(encoding="utf-8")
            except OSError as exc:
                unmeasured[rel] = f"не прочитано: {type(exc).__name__}"
                continue
            found, why = door_sites(source)
            if why:
                unmeasured[rel] = why
                continue
            files_parsed += 1
            is_test = "/tests/" in f"/{rel}" or Path(rel).name.startswith("test_")
            for site in found:
                sites.append(dict(site, module=rel, in_tests=is_test))
    if not files_parsed:
        return {"status": "UNMEASURED",
                "reason": "ни один файл дерева не разобран",
                "files_unmeasured": unmeasured}
    runtime = [s for s in sites if not s["in_tests"]]
    classes: Dict[str, int] = {}
    for site in runtime:
        key = str(site["place_available"])
        classes[key] = classes.get(key, 0) + 1
    return {
        "status": "MEASURED",
        "files_parsed": files_parsed,
        "files_unmeasured": unmeasured,
        "sites_total": len(sites),
        "sites_in_tests": len(sites) - len(runtime),
        "sites_runtime": len(runtime),
        "place_available": dict(sorted(classes.items())),
        "runtime_sites": runtime,
        "one_sidedness": (
            "место, доступное под ДРУГИМ именем, прочтено как «недоступно» ⇒ "
            "цена есть ВЕРХНЯЯ граница; обратной ошибки нет — связанное имя не "
            "означает, что в нём лежит нужное место"),
    }


def tally(rows: Iterable[dict], axis, identity_fields: Sequence[str], *,
          price: Optional[dict] = None, kind_census=None) -> dict:
    """Замер заказа целиком: чем разрешается находка и чего стои́т адрес.

    ``rows`` — строки списков зонда (``module``, ``coord``, ``outcome``, ``n``,
    ``outside_fields``). ``axis`` — ось ``candidate_denominator`` (население
    ВХОДОМ, не пересчёт). ``price`` — замер цены читателям; ``None`` значит
    «цену не мерили», и это третий исход, а не нулевая цена. ``kind_census`` —
    вызываемое ``(имена) -> документ рода`` (``identity_field_kind.census``);
    ``None`` значит «род не спрошен», и это снова третий исход, а не «род
    адресу не мешает».
    """
    rows = list(rows)
    population = population_of(axis)
    if population is None:
        return {"status": "UNMEASURED",
                "reason": ("населения имён не дали вовсе (оси "
                           "candidate_denominator нет либо она сама НЕ "
                           "ИЗМЕРЕНА) — адрес сравнивать не с чем; это не "
                           "«разрешимых местом ноль»"),
                "reader_price": price if price is not None else {
                    "status": "UNMEASURED",
                    "reason": "цену читателям в этом зове не мерили"}}
    findings, without_length = _findings(rows)
    readings = {
        reading: _reading_tally(findings, population, identity_fields, reading)
        for reading in READINGS
    }
    histograms = {
        reading: _histogram(findings, population, identity_fields, reading)
        for reading in READINGS
    }
    broad = readings[BROAD_READING]
    narrow = readings[NARROW_READING]
    place_only_broad = len(broad["place_only"])
    place_only_narrow = len(narrow["place_only"])
    # Расхождение двух прочтений — ОТДЕЛЬНОЕ число. Выбрать одно молча значило
    # бы повторить дефект ADR-503/541 на новом вопросе (ADR-695).
    disagreement = {
        "place_only_broad": place_only_broad,
        "place_only_narrow": place_only_narrow,
        "gap": place_only_narrow - place_only_broad,
        "places_only_narrow_says": sorted(
            f"{r['module']}{r['coord']}" for r in narrow["place_only"]
            if (r["module"], r["coord"]) not in
            {(b["module"], b["coord"]) for b in broad["place_only"]}),
    }
    stability = place_key_stability(broad["place_only"])
    # ВТОРОЙ отказ — род поля у производителя. Население адрес снимает по
    # построению, род — не всегда, и спросить его можно только у КОДА.
    kind_section: dict
    if kind_census is None:
        kind_section = {"status": "UNMEASURED",
                        "reason": ("рода кандидатов в этом зове не спрашивали "
                                   "— лечит ли адрес ВТОРОЙ отказ, судить не "
                                   "от чего; это не «лечит»")}
    else:
        names = sorted({str(name) for row in broad["place_only"]
                        for name in (row.get("candidates") or [])})
        kind_section = kind_at_place(broad["place_only"],
                                     kind_census(names) if names else
                                     {"fields": {}})
    reasons: List[str] = []
    if place_only_broad:
        reasons.append(
            f"{place_only_broad} находок разрешимы ТОЛЬКО адресом места: "
            f"кандидат годен здесь, а населения у его имени меньше "
            f"{GLOBAL_EVIDENCE_MIN} ⇒ отказ сегодня есть свойство глобальной "
            f"координаты, а не поля")
    if stability["key_positional"]:
        reasons.append(
            f"у {len(stability['key_positional'])} из этих мест координата "
            f"САМА позиционна — ключ таблицы адресов поехал бы тем же "
            f"способом, от которого личность и спасает")
    if disagreement["gap"]:
        reasons.append(
            f"два прочтения населения дают РАЗНОЕ число разрешимых только "
            f"местом ({place_only_narrow} узким против {place_only_broad} "
            f"широким) — выбрать прочтение молча значило бы повторить дефект "
            f"ADR-503 (ADR-695)")
    if str(kind_section.get("status")) == "MEASURED":
        by_clock = (kind_section.get("verdicts") or {}).get(
            "place_refused_by_clock", 0)
        if by_clock:
            reasons.append(
                f"из них {by_clock} адрес места НЕ лечит: кандидат пишется "
                f"стенными часами в файле САМОГО производителя, и координата "
                f"поедет каждый его прогон")
        if kind_section.get("imported_refusals"):
            reasons.append(
                f"у {kind_section['imported_refusals']} находок отказ по роду "
                f"привезён из ЧУЖОГО файла — признак отвечает о МЕСТЕ, а "
                f"кортеж адресуется ИМЕНЕМ, и это ровно вред, названный "
                f"заказом")
    verdict = ("PLACE_RESOLVES_WHAT_A_NAME_CANNOT" if place_only_broad
               else "NO_POPULATION_FOR_PLACE_ADDRESSING")
    return {
        "status": "MEASURED",
        "findings_total": len(findings),
        "findings_without_length": without_length,
        "identity_fields_today": len(list(identity_fields)),
        "global_evidence_min": GLOBAL_EVIDENCE_MIN,
        # Главное число заказа — широким прочтением (исправленным ADR-695).
        "place_only": place_only_broad,
        "verdicts": broad["verdicts"],
        "verdicts_narrow_reading": narrow["verdicts"],
        "reading_disagreement": disagreement,
        "population_histogram": histograms,
        "place_key": stability,
        # ВТОРОЙ отказ рядом с первым, а не вместо него: «населения нет» и
        # «часы у производителя» чинятся разным, и сложить их в одно число
        # значило бы спрятать, что часть находок адрес НЕ лечит.
        "kind_at_place": kind_section,
        "place_only_rows": broad["place_only"],
        "unmeasured_rows": broad["unmeasured"],
        "reader_price": price if price is not None else {
            "status": "UNMEASURED",
            "reason": "цену читателям в этом зове не мерили"},
        "verdict": verdict,
        "verdict_reasons": reasons,
        "what_it_does_not_prove": [
            "«разрешимо местом» — про АДРЕС находки, а не про верность "
            "личности: годность поля есть наблюдение одного ответа",
            "позиционное звено в координате места есть доказанный МИНИМУМ "
            "неустойчивости ключа, а не полная её мера",
            "цена читателям меряется связанными ИМЕНАМИ, а не потоком "
            "значения ⇒ она верхняя граница",
            "ни одно имя не дописано в _IDENTITY_FIELDS и ни один адрес не "
            "заведён: замер, а не правило",
        ],
    }


def report(axis, *, max_rows: Optional[int] = 8) -> List[str]:
    """Строки отчёта. Печатает производитель, а не читатель (одна копия).

    ``axis`` намеренно без объявленного типа: раздела может не быть в документе
    ВОВСЕ (отчёт старого образца), и ветвь третьего исхода обязана исполняться,
    а не считаться недостижимой по объявлению.
    """
    if not isinstance(axis, dict):
        return ["  цена адреса находки (заказ G115 п. 1): НЕ ИЗМЕРЕНО — "
                "раздела нет в документе"]
    if str(axis.get("status")) != "MEASURED":
        return [f"  цена адреса находки (заказ G115 п. 1): НЕ ИЗМЕРЕНО — "
                f"{axis.get('reason')}"]
    lines = [
        f"  цена адреса находки (заказ G115 п. 1): {axis['verdict']} · "
        f"находок {axis['findings_total']} · разрешимы ТОЛЬКО местом "
        f"{axis['place_only']} · порог населения {axis['global_evidence_min']}",
        "    вердикты (широкое прочтение): " + " · ".join(
            f"{k} {v}" for k, v in sorted(axis["verdicts"].items())),
    ]
    key = axis.get("place_key") or {}
    lines.append(
        f"    таблица адресов: строк {key.get('rows_needed')} · "
        f"производителей {key.get('producers_touched')} · ключ САМ позиционен у "
        f"{len(key.get('key_positional') or [])} · ключа нет у "
        f"{len(key.get('key_unmeasured') or [])}")
    price = axis.get("reader_price") or {}
    if str(price.get("status")) == "MEASURED":
        lines.append(
            f"    цена читателям: зовов дверей {price.get('sites_total')} "
            f"(в рантайме {price.get('sites_runtime')} · в тестах "
            f"{price.get('sites_in_tests')}) · место доступно: " + " · ".join(
                f"{k} {v}" for k, v in
                sorted((price.get("place_available") or {}).items())))
    else:
        lines.append(f"    цена читателям: НЕ ИЗМЕРЕНО — {price.get('reason')}")
    disagree = axis.get("reading_disagreement") or {}
    lines.append(
        f"    два прочтения населения: узкое {disagree.get('place_only_narrow')} "
        f"против широкого {disagree.get('place_only_broad')} "
        f"(расхождение {disagree.get('gap')})")
    kind = axis.get("kind_at_place") or {}
    if str(kind.get("status")) == "MEASURED":
        lines.append(
            "    ВТОРОЙ отказ (род у производителя): " + " · ".join(
                f"{k} {v}" for k, v in
                sorted((kind.get("verdicts") or {}).items()))
            + f" · отказ привезён из чужого файла у "
              f"{kind.get('imported_refusals')}")
    else:
        lines.append(f"    ВТОРОЙ отказ (род у производителя): НЕ ИЗМЕРЕНО — "
                     f"{kind.get('reason')}")
    for reason in (axis.get("verdict_reasons") or []):
        lines.append(f"    [ПОЧЕМУ] {reason}")
    rows = axis.get("place_only_rows") or []
    shown = rows if max_rows is None else rows[:max_rows]
    for row in shown:
        lines.append(
            f"      {row.get('module')}{row.get('coord')} n={row.get('n')} "
            f"кандидаты: {', '.join(row.get('candidates') or [])}")
    if max_rows is not None and len(rows) > len(shown):
        lines.append(f"      … ещё {len(rows) - len(shown)} мест (укорочено)")
    for row in (axis.get("unmeasured_rows") or [])[:4]:
        lines.append(f"      [НЕ ИЗМЕРЕНО] {row.get('module')}"
                     f"{row.get('coord')}: {row.get('reason')}")
    lines.append("    НЕ ДОКАЗЫВАЕТ: " + " · ".join(
        axis.get("what_it_does_not_prove") or []))
    return lines
