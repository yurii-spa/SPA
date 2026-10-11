"""Ряд ли это: совпадает ли множество элементов списка с множеством ДНЕЙ.

Заказ **G113 п. 2** приказа владельца «Portfolio CIO» (поставлен ADR-539,
02.10; п. 3 закрыт ADR-691, п. 1 остаётся).

## Вопрос, на который прибор отвечает — и чей это вопрос

ADR-539 спросил у КОДА производителя род поля-личности и **отверг замером**
правило «род ⇒ годность»: имплика­ция ложна в обе стороны. Вывод того ADR
дороже самого признака и записан там дословно:

> Водораздел проходит не по «производят ли значение часы», а по тому, **чей
> предмет этот момент — РЯДА или ЗАПИСИ**. Такого признака у меры нет, и
> выдумывать его эвристикой запрещено.

ADR-691 перемерил слабую ось и подтвердил остаток: водораздел «ряда или
записи» он **не строит и не притворяется**, что строит. Заказ G113 п. 2 назвал
ПЕРВОЕ, что у дорогой половины можно спросить замером:

> совпадает ли множество элементов списка с множеством ДНЕЙ (то есть ряд ли
> это), и сколько списков населения отвечают «да». Пороги не назначать:
> сначала замер, потом правило.

Здесь живёт ровно этот признак и ровно этот замер. **Правила «ряд ⇒ годность»
тут нет и гейта нет ни одного** — это запрещено тем же заказом и закреплено
составом публичных имён (``_NO_GATE_NAMES``), а не обещанием в этом абзаце.

## Почему признак отвечает на вопрос заказа

Если элементам списка отвечают ДНИ **один к одному**, то день элемент
РАЗЛИЧАЕТ: координата ``[day="2026-10-02"]`` переезжает не потому, что
переименовался тот же элемент, а потому, что пришёл новый день — предмет
момента принадлежит РЯДУ. Если дни ПОВТОРЯЮТСЯ, день различить элементы не в
силах ни при каком списке имён: в одном дне их несколько, и момент есть
свойство ЗАПИСИ, а не её место в ряду.

Это утверждение о НАБЛЮДЁННЫХ значениях, и ничего кроме. Оно не говорит, какое
имя годно в личность, — у годности свой прибор (``element_identity``) и своя
перепись (``list_identity_census``).

## Имя поля — ВЫХОД замера, а не его вход

Списка «датных имён» здесь нет НАМЕРЕННО, и это главный выбор модуля.
Спрашивать «ряд ли это» у заранее названных имён значило бы решить на глаз
ровно то, что заказ велел измерить; а узнавать день «датным видом» значения
ADR-539 уже отверг у соседа («регулярка по датному виду глушила бы и входные
отметки»). Поэтому вопрос задаётся КАЖДОМУ полю, присутствующему у всех
элементов, а имена полей, оказавшихся осью дня, прибор ДОКЛАДЫВАЕТ.

## Чего признак НЕ доказывает

* **Биекция сегодня ≠ обещание писателя.** Прибор меряет СОСТАВ одного
  наблюдённого ответа. Поэтому вывод односторонний, и сильная сторона —
  отрицательная: «дни повторяются» есть свойство (день не различает элементы
  ни при каком наблюдении), «дни один к одному» — наблюдение.
* **Длина есть сила свидетельства.** На двух элементах различность дней почти
  неизбежна, на сорока трёх — говорит много. Длина хранится рядом с именем, и
  **синглтоны считаются ОТДЕЛЬНО**: список из одного элемента есть ряд
  тривиально, по построению, а не по свойству (тот же довод и та же развязка,
  что у знаменателя ``list_identity_census``).
* **Основной формат узнаётся НЕ весь.** Днём считается только отметка,
  начинающаяся с ``ГГГГ-ММ-ДД`` (плюс настоящие ``date``/``datetime``).
  ``"20261002"`` питоньим разбором в дату проходит, но восьмизначное число
  куда чаще есть КОД, чем день, и принять его значило бы изготовить находку из
  формата. Отказ односторонний и ЗАНИЖАЕТ число «да».
* **Разрыв в днях рядом не отменяет.** Дни ``{01, 03}`` различны, но не
  смежны; требовать смежности значило бы назначить порог, который заказ
  запретил. Смежность поэтому НАБЛЮДАЕТСЯ рядом (``contiguous``) и вердиктом
  не является.
* **Пояс решает день у отметки со временем.** У осознанных отметок день берётся
  по UTC, у наивных — как написано; пояса наивной отметке прибор НЕ выдумывает.
  Список, смешавший осознанные с наивными, помечается (``mixed_awareness``) —
  биекция в нём может быть следствием соглашения, а не ряда.

Прибор только ЧИТАЕТ значения, уже лежащие в ответе читателя: сети нет, часов
нет, ``data/`` не трогается, капитал не двигается. Только stdlib.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import datetime as dt
from typing import Dict, List, Optional, Tuple

#: Исход списка: дни отвечают элементам один к одному (и элементов больше одного).
DAY_SERIES = "day_series"
#: То же, но личность НЕ поле — днями являются сами значения списка-скаляров.
DAY_SERIES_BY_VALUE = "day_series_by_value"
#: Ряд тривиально: один элемент. Считается ОТДЕЛЬНО и в число-находку не идёт.
TRIVIAL_SINGLETON = "day_series_trivial_singleton"
#: Дни есть, но повторяются либо разобраны не у всех ⇒ рядом по дню список не является.
NOT_DAY_SERIES = "not_day_series"
#: Вопрос к списку неприменим: пуст, либо элементы не словари и не дни.
NOT_APPLICABLE = "not_applicable"
#: Третий исход (инв. #17): разобрать не удалось, причина названа.
UNMEASURED = "unmeasured"

#: Имена, которых у публичной поверхности модуля быть НЕ ДОЛЖНО. Прибор
#: отвечает «ряд ли это», а НЕ «годно ли имя»: порога нет ни одного, и
#: назначить его вправе только решение (заказ: сначала замер, потом правило).
#: Пин состава — тот же приём, что у соседей (ADR-539/ADR-410): прозаическая
#: оговорка в докстринге ветшает молча, а состав имён краснеет тестом.
_NO_GATE_NAMES = ("is_fit", "admit_field", "reject_field", "apply_threshold",
                  "unfit_for_identity", "series_gate", "must_be_series")

#: Наименьшая длина отметки, у которой день записан целиком: ``ГГГГ-ММ-ДД``.
_DAY_PREFIX_LEN = 10


def day_of(value) -> Tuple[Optional[dt.date], bool, str]:
    """Значение → (день, осознана ли отметка, причина отказа).

    Три исхода различимы по построению: день назван · дня нет с названной
    причиной. Числа, строки основного формата (``20261002``) и отметки короче
    ``ГГГГ-ММ-ДД`` отвергаются НАЗВАННОЙ причиной, а не молча — иначе «день не
    узнан» было бы не отличить от «дня нет».
    """
    if isinstance(value, bool):
        # Тот же довод, по которому `element_identity` исключает `bool`:
        # `True` не день ни в каком прочтении, а `isinstance(True, int)` истинно.
        return None, False, "not_a_day_bool"
    if isinstance(value, dt.datetime):
        aware = value.tzinfo is not None
        moment = value.astimezone(dt.timezone.utc) if aware else value
        return moment.date(), aware, ""
    if isinstance(value, dt.date):
        return value, False, ""
    if not isinstance(value, str):
        return None, False, "not_a_day_not_text"
    text = value.strip()
    if len(text) < _DAY_PREFIX_LEN:
        return None, False, "not_a_day_too_short"
    head = text[:_DAY_PREFIX_LEN]
    # Основной формат (`20261002`) ОТВЕРГАЕТСЯ здесь: питоний разбор его
    # принимает, но восьмизначное число куда чаще код, чем день. Отказ
    # односторонний и занижает число «да» — цена названа в докстринге модуля.
    if not (head[4] == "-" and head[7] == "-"):
        return None, False, "not_a_day_unhyphenated"
    try:
        parsed = dt.datetime.fromisoformat(head)
    except ValueError:
        return None, False, "not_a_day_unparsed"
    rest = text[_DAY_PREFIX_LEN:]
    if not rest:
        return parsed.date(), False, ""
    try:
        full = dt.datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        # День записан целиком, а хвост не разобран. День всё равно НАЗВАН:
        # отвергать его значило бы потерять наблюдение из-за хвоста, который
        # на день не влияет. Осознанность при этом не утверждается.
        return parsed.date(), False, ""
    aware = full.tzinfo is not None
    moment = full.astimezone(dt.timezone.utc) if aware else full
    return moment.date(), aware, ""


def day_axis_of_field(items: List[dict], field: str) -> dict:
    """Ось ли дня это поле у ЭТОГО списка — и ПОЧЕМУ нет, если нет.

    Вердикт решает, причина объясняет: «поля нет» и «значение не день» —
    разные причины и один вердикт, та же развязка, что у ``field_verdict``
    зонда переписи.
    """
    row: dict = {"field": field, "n": len(items)}
    days: List[dt.date] = []
    aware_seen = False
    naive_seen = False
    for item in items:
        if field not in item:
            row.update(axis=False, reason="field_absent")
            return row
        day, aware, cause = day_of(item[field])
        if day is None:
            row.update(axis=False, reason=cause)
            return row
        days.append(day)
        aware_seen = aware_seen or aware
        naive_seen = naive_seen or not aware
    distinct = sorted(set(days))
    row["days"] = len(distinct)
    row["mixed_awareness"] = bool(aware_seen and naive_seen)
    if len(distinct) != len(items):
        # Дни ПОВТОРЯЮТСЯ: день не различает элементы ни при каком списке имён.
        # Это сильная, отрицательная половина замера.
        row.update(axis=False, reason="day_repeats")
        return row
    span = (distinct[-1] - distinct[0]).days + 1 if distinct else 0
    row.update(axis=True, reason="", span_days=span,
               # Смежность НАБЛЮДАЕТСЯ, вердиктом не является: требовать её
               # значило бы назначить порог, запрещённый заказом.
               contiguous=bool(distinct) and span == len(distinct),
               first_day=distinct[0].isoformat(),
               last_day=distinct[-1].isoformat())
    return row


def _candidate_fields(items: List[dict]) -> List[str]:
    """Поля, присутствующие У ВСЕХ элементов.

    Население — ПЕРЕСЕЧЕНИЕ ключей, а не ключи первого элемента: поле,
    которого у кого-то нет, осью дня быть не может (``field_absent``), и брать
    ключи одного элемента значило бы решать состав населения порядком обхода.
    """
    common: Optional[set] = None
    for item in items:
        keys = {k for k in item if isinstance(k, str)}
        common = keys if common is None else (common & keys)
        if not common:
            return []
    return sorted(common or ())


def day_axis_of_list(items) -> dict:
    """Один список — один исход, и их шесть, а не два.

    * ``day_series`` — элементов больше одного, и КАКОЕ-ТО поле отвечает им
      днями один к одному. Это и есть «да» заказа;
    * ``day_series_by_value`` — элементы сами суть дни и различны: ряд есть, а
      поля у него нет вовсе. Отдельный исход, а не подвид: слить их значило бы
      доложить про поле там, где поля нет (та же развязка, что у
      ``named_by_value`` у соседа);
    * ``day_series_trivial_singleton`` — один элемент: ряд по построению, не по
      свойству. Считается ОТДЕЛЬНО и в число-находку не идёт;
    * ``not_day_series`` — элементы-словари, и ни одно поле днями их не
      различает. Причины по полям названы;
    * ``not_applicable`` — спрашивать нечего: список пуст либо элементы не
      словари и днями не являются;
    * ``unmeasured`` — разобрать не удалось, причина названа (инв. #17).
    """
    if not isinstance(items, list):
        return {"outcome": UNMEASURED, "n": 0,
                "reason": f"не список: {type(items).__name__}"}
    row: dict = {"n": len(items)}
    if not items:
        row.update(outcome=NOT_APPLICABLE, reason="empty")
        return row
    if not all(isinstance(item, dict) for item in items):
        # Личность, которая НЕ ЕСТЬ ПОЛЕ: сами значения могут быть днями.
        days, ok = [], True
        for item in items:
            day, _aware, _cause = day_of(item)
            if day is None:
                ok = False
                break
            days.append(day)
        if ok and len(set(days)) == len(items):
            row.update(outcome=(TRIVIAL_SINGLETON if len(items) == 1
                                else DAY_SERIES_BY_VALUE),
                       identity="by_value", days=len(set(days)))
            return row
        row.update(outcome=NOT_APPLICABLE,
                   reason="not_dicts_and_values_are_not_distinct_days")
        return row
    axes = [day_axis_of_field(items, field)
            for field in _candidate_fields(items)]
    hit = [row_ for row_ in axes if row_.get("axis")]
    if hit:
        row["fields"] = sorted(str(row_["field"]) for row_ in hit)
        row["axes"] = hit
        # Синглтон различается ДО вердикта: биекция в нём тривиальна, и
        # положить его в «да» значило бы разводить находку водой.
        row["outcome"] = TRIVIAL_SINGLETON if len(items) == 1 else DAY_SERIES
        return row
    row["outcome"] = (TRIVIAL_SINGLETON if len(items) == 1 else NOT_DAY_SERIES)
    # Причины по полям — диагноз, а не вердикт: без него «рядом не является»
    # не отличить от «датного поля тут нет вовсе».
    reasons: Dict[str, int] = {}
    for row_ in axes:
        cause = str(row_.get("reason") or "")
        # Отсева `field_absent` здесь НЕТ, и это замер, а не упущение:
        # `_candidate_fields` отдаёт ПЕРЕСЕЧЕНИЕ ключей, поэтому кандидат
        # присутствует у каждого элемента ПО ПОСТРОЕНИЮ и причина
        # `field_absent` тут не возникает ни при каком списке. Прежняя
        # редакция её отсеивала — мутация показала, что ветвь недостижима
        # (подмена `and` на `or` не меняла ни одного ответа), а член без
        # наблюдаемого следствия есть украшение: держать его «для симметрии»
        # значило бы оставить в приборе утверждение, которое ни один контроль
        # не в силах опровергнуть.
        if cause:
            reasons[cause] = reasons.get(cause, 0) + 1
    if reasons:
        row["reasons"] = reasons
    row["fields_examined"] = len(axes)
    return row


def tally(rows: List[dict]) -> dict:
    """Свод по СПИСКАМ: сколько населения отвечает «да» — и из чего знаменатель.

    Знаменатель назван явно и он УЖЕ полного населения: из него вычтены
    синглтоны (ряд в них тривиален) и неприменимые списки (днями себя не
    называют по построению). Складывать их в один знаменатель значило бы
    развести находку водой — тот же порядок, что у ``list_identity_census``.
    """
    outcomes: Dict[str, int] = {}
    axis_fields: Dict[str, int] = {}
    # Население имени — ДВА числа, и одного мало. Замер 11.10: `forward_date`
    # и `cycle_date` оба дают 11 списков, но первый — у ОДНОГО читателя
    # (вложенные `pairs` одной структуры, повторённые 11 раз), второй — у
    # девяти. По числу СПИСКОВ они равны, по числу ЧИТАТЕЛЕЙ различаются в
    # девять раз, и это ровно та слабость «население = один счётчик», на
    # которой ряд заказов уже спотыкался (G83). Поэтому читатели считаются
    # рядом, а не вместо: сложить их в один балл значило бы выбрать вес на глаз.
    axis_readers: Dict[str, set] = {}
    strength: Dict[str, int] = {}
    reasons: Dict[str, int] = {}
    unmeasured: Dict[str, int] = {}
    series_rows: List[dict] = []
    mixed_awareness = 0
    non_contiguous = 0
    for row in rows:
        outcome = str(row.get("outcome"))
        outcomes[outcome] = outcomes.get(outcome, 0) + 1
        if outcome == UNMEASURED:
            cause = str(row.get("reason") or "безымянная причина")
            unmeasured[cause] = unmeasured.get(cause, 0) + 1
            continue
        if outcome == DAY_SERIES:
            n = int(row.get("n") or 0)
            module = row.get("module")
            for field in (row.get("fields") or []):
                axis_fields[str(field)] = axis_fields.get(str(field), 0) + 1
                # Читатель, которого не назвали, НЕ считается читателем: пустое
                # имя сложилось бы в одного фантомного и завысило бы разброс.
                if module:
                    axis_readers.setdefault(str(field), set()).add(str(module))
                # Сила свидетельства — ДЛИНА списка, на котором поле оказалось
                # осью дня. Хранится максимум: он и есть лучшее наблюдение.
                strength[str(field)] = max(strength.get(str(field), 0), n)
            for axis in (row.get("axes") or []):
                if axis.get("mixed_awareness"):
                    mixed_awareness += 1
                if axis.get("contiguous") is False:
                    non_contiguous += 1
            series_rows.append({"coord": row.get("coord"), "n": n,
                                "module": row.get("module"),
                                "fields": row.get("fields")})
        if outcome == NOT_DAY_SERIES:
            for cause, count in (row.get("reasons") or {}).items():
                reasons[str(cause)] = reasons.get(str(cause), 0) + int(count)
    answered_yes = outcomes.get(DAY_SERIES, 0)
    by_value = outcomes.get(DAY_SERIES_BY_VALUE, 0)
    denominator = answered_yes + outcomes.get(NOT_DAY_SERIES, 0)
    return {
        "lists_seen": len(rows),
        "outcomes": outcomes,
        # Число-находка заказа и его знаменатель — рядом, и ни одно без другого
        # не печатается: доля без населения есть «не измерено», выданное за ответ.
        "answered_yes": answered_yes,
        "denominator_of_finding": denominator,
        "day_series_by_value": by_value,
        "trivial_singletons": outcomes.get(TRIVIAL_SINGLETON, 0),
        "not_applicable": outcomes.get(NOT_APPLICABLE, 0),
        "axis_fields": axis_fields,
        "axis_field_readers": {k: len(v) for k, v in sorted(axis_readers.items())},
        "axis_field_strength": strength,
        "refusal_reasons": reasons,
        "mixed_awareness_axes": mixed_awareness,
        "non_contiguous_axes": non_contiguous,
        "unmeasured_causes": unmeasured,
        "series_rows": series_rows,
    }


def report(doc: dict, *, max_fields: int = 6, max_rows: int = 5) -> List[str]:
    """Строки отчёта. Знаменатель ПЕРЕД числителем — порядок вопроса."""
    if not isinstance(doc, dict) or not doc:
        return ["ось дня: НЕ ИЗМЕРЕНО — свода нет"]
    yes = int(doc.get("answered_yes") or 0)
    den = int(doc.get("denominator_of_finding") or 0)
    out = [
        f"ось дня (заказ G113 п. 2): применимых списков {den} · "
        f"РЯД ПО ДНЮ {yes}" + (f" = {100.0 * yes / den:.1f}%" if den else
                               " — доли НЕТ: применимых списков ноль"),
        f"  тривиальных синглтонов {doc.get('trivial_singletons', 0)} "
        f"(в знаменатель не идут) · ряд САМИМИ значениями "
        f"{doc.get('day_series_by_value', 0)} · неприменимо "
        f"{doc.get('not_applicable', 0)}",
    ]
    fields = doc.get("axis_fields") or {}
    strength = doc.get("axis_field_strength") or {}
    readers = doc.get("axis_field_readers") or {}
    if fields:
        head = sorted(fields.items(), key=lambda kv: (-kv[1], kv[0]))[:max_fields]
        # Печатаются ОБА населения. Имя, у которого списков много, а читателей
        # один, свидетельствует слабее — и увидеть это можно только рядом.
        out.append("  осью дня оказались: " + " · ".join(
            f"{name}×{count} списк. у {readers.get(name, 0)} читател. "
            f"(макс. длина {strength.get(name, 0)})"
            for name, count in head))
        if len(fields) > max_fields:
            out.append(f"  …перечень имён укорочен: всего {len(fields)}")
    mixed = int(doc.get("mixed_awareness_axes") or 0)
    gaps = int(doc.get("non_contiguous_axes") or 0)
    if mixed or gaps:
        out.append(f"  оговорки-наблюдения: смешанный пояс {mixed} · "
                   f"с разрывом в днях {gaps} (вердикт не меняют)")
    reasons = doc.get("refusal_reasons") or {}
    if reasons:
        head = sorted(reasons.items(), key=lambda kv: (-kv[1], kv[0]))[:max_fields]
        out.append("  почему НЕ ряд: " + " · ".join(
            f"{cause}×{count}" for cause, count in head))
    rows = doc.get("series_rows") or []
    for row in rows[:max_rows]:
        out.append(f"  [РЯД] {row.get('module')} {row.get('coord')} "
                   f"длина {row.get('n')} по {row.get('fields')}")
    if len(rows) > max_rows:
        out.append(f"  …перечень рядов укорочен: всего {len(rows)}")
    unmeasured = doc.get("unmeasured_causes") or {}
    if unmeasured:
        out.append("  НЕ ИЗМЕРЕНО: " + " · ".join(
            f"{cause}×{count}" for cause, count in sorted(unmeasured.items())))
    out.append("  порога НЕТ намеренно: заказ требует сначала замер, потом "
               "правило — «ряд ⇒ годность» здесь не утверждается")
    return out
