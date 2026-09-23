"""Заказ G78 п. 1 — ОДИН шаг межпроцедурного разбора у убежавшего счётчика.

ADR-461 назвал главным числом **95**: столько открытых счётчиков имеют
читателя, которого шаг соседа НЕ ИЗМЕРИЛ. Шестьдесят шесть из них «убегают из
области», и заказ спросил числом: сколько разрешает ОДИН шаг («счётчик
возвращён — читатель у зовущего»), а сколько остаётся третьим исходом.

Каждый тест здесь — положительный контроль: он воспроизводит либо форму уже
случившегося дефекта (принять запись за чтение; выдать НЕ ИЗМЕРЕНО за
измеренный исход; объявить разрешённым то, что уехало дальше), либо форму,
которую правило ОБЯЗАНО не спутать с другой.

**Три числа, которые набор держит РАЗДЕЛЬНО** — и слить любые два значило бы
совершить ровно тот дефект, против которого написан весь ряд ADR-459…461:

* «шаг довёл до читателя, и читатель делит класс» — измеренный вред;
* «шаг довёл до читателя, и он безвреден» — измеренная безвредность;
* «шаг не довёл» — НЕ ИЗМЕРЕНО, и у каждой причины недохода своё имя.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from spa_core.monitoring import rule_second_copy_census as census
from spa_core.monitoring.rule_second_copy_census import (
    ONE_STEP_CONTROL_CLEAN,
    ONE_STEP_CONTROL_SOURCE,
    ONE_STEP_SPLITS,
    ONE_STEP_UNRESOLVED,
    ONE_STEP_WHOLESALE,
    READER_GAP_DYNAMIC,
    READER_GAP_ESCAPES,
    ROUTE_ARGUMENT_FOREIGN,
    ROUTE_ARGUMENT_LOCAL,
    ROUTE_CONTAINER,
    ROUTE_NOT_A_DEPARTURE,
    ROUTE_RETURNED,
    ROUTE_UNKNOWN,
    STEP_GAP_AMBIGUOUS_CALLEE,
    STEP_GAP_ARG_UNMAPPED,
    STEP_GAP_CONTAINER,
    STEP_GAP_ESCAPES_AGAIN,
    STEP_GAP_FOREIGN_CALLEE,
    STEP_GAP_NOT_A_DEPARTURE,
    STEP_GAP_NO_CALLER,
    STEP_GAP_NO_READ,
    STEP_GAP_RESULT_UNBOUND,
    STEP_GAP_ROUTE_UNKNOWN,
    STEP_GAP_SITES_DISAGREE,
    UNMEASURED_STEP_CONTROL,
    UNMEASURED_STEP_HARM,
    UNMEASURED_STEP_POPULATION,
    WHOLE_USE_ESCAPE,
    WHOLE_USE_WHOLESALE,
    _ESCAPE_ROUTES,
    _ONE_STEP_OUTCOMES,
    _STEP_GAPS,
    _counter_whole_use,
    _one_step_control,
    _one_step_sites,
    _reader_sites,
    _reader_site_nodes,
    escaped_counter_one_step,
)

REPO_ROOT = Path(__file__).resolve().parents[2]

#: Открытый счётчик ровно той формы, которую считает открытой сосед: ключ
#: приходит из артефакта и принадлежностью не сверен. Без этого мерить было бы
#: НЕ У ЧЕГО — сосед не признал бы счётчик открытым.
COUNTER = (
    "    counts = {}\n"
    "    for row in rows:\n"
    "        cls = str(row.get('outcome'))\n"
    "        counts[cls] = counts.get(cls, 0) + 1\n"
)


def sites(source: str):
    return _one_step_sites("<scene>", ast.parse(source))


def only(source: str) -> dict:
    found = sites(source)
    assert len(found) == 1, [(s["file"], s["line"], s["counter"]) for s in found]
    return found[0]


# ---------------------------------------------------------------------------
# 1. КОНТРОЛЬ ПРАВИЛА — объявлен ДО замера и проверяется обеими половинами
# ---------------------------------------------------------------------------

def test_declared_rule_resolves_both_forms_of_the_known_case():
    """Обе разрешимые формы побега — возврат И аргумент. Найдя одну, правило
    ответило бы на половину вопроса заказа, а число выдало бы за полный."""
    control = _one_step_control()
    assert control["passed"], control
    assert control["known_case_resolved"] == 2
    assert sorted(control["routes"]) == sorted((ROUTE_ARGUMENT_LOCAL,
                                                ROUTE_RETURNED))


def test_control_scene_counters_are_open_and_escaping():
    """Предпосылка сцены проверяется, а не предполагается: счётчик, который
    сосед не считает убежавшим, мерить этим шагом НЕЧЕГО, и зелёный контроль
    на таком счётчике был бы свойством сцены, а не правила."""
    for source in (ONE_STEP_CONTROL_SOURCE, ONE_STEP_CONTROL_CLEAN):
        rows = _reader_sites("<scene>", ast.parse(source))
        escaping = [r for r in rows if r.get("gap") == READER_GAP_ESCAPES]
        assert escaping, source[:60]


def test_negative_half_separates_four_refusals_by_name():
    """Отрицательная половина обязана развести отказы РАЗНЫМИ именами: они
    чинятся разным, и одно имя на всех вернуло бы счётчик, открытый любой
    строке, — внутрь прибора, который такие счётчики и ищет."""
    control = _one_step_control()
    assert control["clean_false_splits"] == 0
    assert sorted(control["clean_refusal_names"]) == sorted((
        STEP_GAP_CONTAINER, STEP_GAP_FOREIGN_CALLEE,
        STEP_GAP_NOT_A_DEPARTURE, STEP_GAP_ROUTE_UNKNOWN))
    assert control["clean_benign"] == 1


# ---------------------------------------------------------------------------
# 2. РАЗРЕШИМЫЕ МАРШРУТЫ — ради них заказ и поставлен
# ---------------------------------------------------------------------------

def test_returned_counter_read_by_a_declared_key_at_the_caller_splits():
    row = only(
        "LIVE = 'live'\n"
        "def tally(rows):\n" + COUNTER +
        "    return counts\n"
        "def verdict(rows):\n"
        "    totals = tally(rows)\n"
        "    return totals[LIVE]\n")
    assert row["one_step"] == ONE_STEP_SPLITS
    assert row["routes"] == [ROUTE_RETURNED]


def test_counter_passed_to_a_local_function_read_by_declared_key_splits():
    row = only(
        "LIVE = 'live'\n"
        "def tally(rows):\n" + COUNTER +
        "    return judge(counts)\n"
        "def judge(seen):\n"
        "    return seen.get(LIVE, 0)\n")
    assert row["one_step"] == ONE_STEP_SPLITS
    assert row["routes"] == [ROUTE_ARGUMENT_LOCAL]


def test_keyword_argument_maps_to_its_parameter_by_name():
    """Аргумент по ИМЕНИ — не позиция: свести его к позиции значило бы читать
    чужой параметр и судить о читателе, которого на этом пути нет."""
    row = only(
        "LIVE = 'live'\n"
        "def tally(rows):\n" + COUNTER +
        "    return judge(rows, seen=counts)\n"
        "def judge(rows, seen=None):\n"
        "    return seen.get(LIVE, 0)\n")
    assert row["one_step"] == ONE_STEP_SPLITS


def test_caller_that_reads_the_counter_wholesale_is_measured_benign():
    row = only(
        "def tally(rows):\n" + COUNTER +
        "    return counts\n"
        "def show(rows, report):\n"
        "    totals = tally(rows)\n"
        "    for name, hits in sorted(totals.items()):\n"
        "        report.append(f'{name}: {hits}')\n")
    assert row["one_step"] == ONE_STEP_WHOLESALE
    assert row["step_gap"] is None


# ---------------------------------------------------------------------------
# 3. ТРЕТИЙ ИСХОД — и у каждой причины СВОЁ имя, потому что чинятся разным
# ---------------------------------------------------------------------------

def test_counter_placed_in_a_container_first_is_not_called_benign():
    """`return {'tally': counts}` — счётчик уехал сперва ПОЛЕМ. Одного шага
    вызова тут мало, и назвать это безвредным значило бы выдать НЕ ИЗМЕРЕНО
    за измеренный исход (инв. #17)."""
    row = only("def tally(rows):\n" + COUNTER + "    return {'tally': counts}\n")
    assert row["one_step"] == ONE_STEP_UNRESOLVED
    assert row["step_gap"] == STEP_GAP_CONTAINER
    assert row["routes"] == [ROUTE_CONTAINER]


def test_callee_not_defined_in_this_file_refuses_by_its_own_name():
    row = only("def tally(rows):\n" + COUNTER + "    publish(counts)\n")
    assert row["step_gap"] == STEP_GAP_FOREIGN_CALLEE
    assert row["routes"] == [ROUTE_ARGUMENT_FOREIGN]


def test_callee_name_defined_twice_is_a_third_outcome_not_a_choice():
    """«Какое из двух» есть третий исход. Молчаливый выбор первого дал бы
    читателя, которого на этом пути может не быть вовсе."""
    row = only(
        "LIVE = 'live'\n"
        "def tally(rows):\n" + COUNTER +
        "    return judge(counts)\n"
        "def judge(seen):\n"
        "    return seen.get(LIVE, 0)\n"
        "def judge(seen):\n"
        "    return len(seen)\n")
    assert row["step_gap"] == STEP_GAP_AMBIGUOUS_CALLEE


def test_returned_counter_without_a_caller_in_this_file():
    row = only("def tally(rows):\n" + COUNTER + "    return counts\n")
    assert row["step_gap"] == STEP_GAP_NO_CALLER


def test_returned_value_used_inline_is_not_bound_to_a_name():
    row = only(
        "def tally(rows):\n" + COUNTER +
        "    return counts\n"
        "def show(rows):\n"
        "    return sorted(tally(rows))\n")
    assert row["step_gap"] == STEP_GAP_RESULT_UNBOUND


def test_argument_beyond_the_parameter_list_is_unmapped():
    row = only(
        "def tally(rows):\n" + COUNTER +
        "    return judge(rows, counts)\n"
        "def judge(rows, *extra):\n"
        "    return len(extra)\n")
    assert row["step_gap"] == STEP_GAP_ARG_UNMAPPED


def test_counter_that_escapes_again_needs_more_than_one_step():
    row = only(
        "def tally(rows):\n" + COUNTER +
        "    return counts\n"
        "def show(rows):\n"
        "    totals = tally(rows)\n"
        "    return {'totals': totals}\n")
    assert row["step_gap"] == STEP_GAP_ESCAPES_AGAIN


def test_next_scope_that_never_reads_the_counter():
    row = only(
        "def tally(rows):\n" + COUNTER +
        "    return counts\n"
        "def show(rows):\n"
        "    totals = tally(rows)\n"
        "    return 1\n")
    assert row["step_gap"] == STEP_GAP_NO_READ


def test_caller_reading_by_an_unresolvable_key_is_not_a_split():
    """Читатель НАЙДЕН, но ключ его чтения не разобран — это НЕ доказанный
    раскол и НЕ безвредность."""
    row = only(
        "def tally(rows):\n" + COUNTER +
        "    return counts\n"
        "def show(rows, wanted):\n"
        "    totals = tally(rows)\n"
        "    return totals[wanted]\n")
    assert row["one_step"] == ONE_STEP_UNRESOLVED
    assert row["step_gap"] == READER_GAP_DYNAMIC


# ---------------------------------------------------------------------------
# 4. «НИКУДА НЕ УЕХАЛ» — класс, найденный ЗАПУСКОМ на живом дереве
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("tail, why", [
    ("    if not counts:\n        return None\n", "истинность через not"),
    ("    return f'классов: {counts}'\n", "печать целиком в строку"),
    ("    return len(counts) if counts else 0\n", "истинность в IfExp"),
    ("    while counts:\n        counts.popitem()\n", "истинность в while"),
    ("    assert counts\n", "истинность в assert"),
])
def test_counter_used_whole_without_leaving_the_scope(tail, why):
    """Правило соседа перечисляет ПРОБЕГ поимённо и всякое остальное
    использование целиком зовёт побегом — поэтому `if not counts:` попало в
    класс «убежал». Счётчик при этом не уехал никуда, и назвать это побегом
    значит завысить соседское население СВЕРХУ."""
    row = only("def tally(rows):\n" + COUNTER + tail)
    assert row["routes"] == [ROUTE_NOT_A_DEPARTURE], why
    assert row["step_gap"] == STEP_GAP_NOT_A_DEPARTURE, why


def test_boolean_default_really_departs_and_must_stay_unresolved():
    """`counts or {}` уезжает ПО-НАСТОЯЩЕМУ. Принять его за «никуда не уехал»
    значило бы спрятать настоящий побег под новым именем — ровно тот дефект,
    ради которого у нового класса есть отрицательная половина контроля."""
    row = only("def tally(rows):\n" + COUNTER + "    return counts or {}\n")
    assert row["routes"] == [ROUTE_UNKNOWN]
    assert row["step_gap"] == STEP_GAP_ROUTE_UNKNOWN


def test_ifexp_body_is_a_value_not_a_test():
    """В `X if cond else Y` счётчик на месте ЗНАЧЕНИЯ уезжает наружу, а на
    месте условия — нет. Проверять надо позицию, а не тип узла."""
    row = only(
        "def tally(rows, flag):\n" + COUNTER +
        "    return counts if flag else {}\n")
    assert ROUTE_NOT_A_DEPARTURE not in row["routes"]


# ---------------------------------------------------------------------------
# 5. ЛОВУШКИ, НА КОТОРЫХ ПРИБОР УЖЕ ЛОВИЛ СЕБЯ
# ---------------------------------------------------------------------------

def test_a_write_at_the_next_scope_is_not_a_read():
    """Сосед ловил себя на том, что мерил ПИСАТЕЛЯ под именем читателя: правая
    часть всякого счётчика содержит `X.get(k, 0)`. На следующей области
    ловушка та же."""
    row = only(
        "def tally(rows):\n" + COUNTER +
        "    return counts\n"
        "def more(rows):\n"
        "    totals = tally(rows)\n"
        "    totals['total'] = totals.get('total', 0) + 1\n"
        "    return totals\n")
    assert row["one_step"] != ONE_STEP_SPLITS
    assert row["step_gap"] == STEP_GAP_ESCAPES_AGAIN


def test_split_at_any_caller_proves_the_split_for_the_counter():
    """Свидетель односторонний: раскол, доказанный ОДНИМ зовущим, доказан."""
    row = only(
        "LIVE = 'live'\n"
        "def tally(rows):\n" + COUNTER +
        "    return counts\n"
        "def quiet(rows):\n"
        "    totals = tally(rows)\n"
        "    return len(totals)\n"
        "def loud(rows):\n"
        "    totals = tally(rows)\n"
        "    return totals[LIVE]\n")
    assert row["one_step"] == ONE_STEP_SPLITS


def test_one_unmeasured_caller_keeps_the_whole_counter_unmeasured():
    """Объявить счётчик безвредным по ИЗМЕРЕННОЙ половине читателей — ровно та
    подмена, против которой шаг написан."""
    row = only(
        "def tally(rows):\n" + COUNTER +
        "    return counts\n"
        "def quiet(rows):\n"
        "    totals = tally(rows)\n"
        "    return len(totals)\n"
        "def hidden(rows, wanted):\n"
        "    totals = tally(rows)\n"
        "    return totals[wanted]\n")
    assert row["one_step"] == ONE_STEP_UNRESOLVED
    assert row["step_gap"] == READER_GAP_DYNAMIC


def test_counter_guarded_by_membership_is_not_in_the_population():
    """Население берётся У СОСЕДА целиком: счётчик, ключ которого сверен
    принадлежностью, открытым не считается, и мерить его шаг не вправе."""
    assert sites(
        "DECLARED = ('a', 'b')\n"
        "def tally(rows):\n"
        "    counts = {}\n"
        "    for row in rows:\n"
        "        cls = str(row.get('outcome'))\n"
        "        if cls not in DECLARED:\n"
        "            continue\n"
        "        counts[cls] = counts.get(cls, 0) + 1\n"
        "    return counts\n") == []


def test_counter_whose_reader_lives_in_its_own_scope_is_not_ours():
    """Шаг мерит ТОЛЬКО убежавших: счётчик, читателя которого сосед уже
    разобрал, здесь населением не является."""
    assert sites(
        "LIVE = 'live'\n"
        "def tally(rows):\n" + COUNTER +
        "    return counts[LIVE]\n") == []


# ---------------------------------------------------------------------------
# 6. ОДНО ПРАВИЛО — ОДНА КОПИЯ (прибор не вправе совершать свой же класс)
# ---------------------------------------------------------------------------

def test_escape_rule_has_exactly_one_copy():
    """Правило побега извлечено в `_counter_whole_use` и зовётся ОБОИМИ
    шагами. Вторая копия правила внутри прибора, который ищет вторые копии
    правил, — дефект, уже дважды случившийся в этом файле."""
    source = (REPO_ROOT / "spa_core/monitoring/rule_second_copy_census.py"
              ).read_text(encoding="utf-8")
    tree = ast.parse(source)
    defs = [n for n in ast.walk(tree)
            if isinstance(n, ast.FunctionDef)
            and n.name == "_counter_whole_use"]
    assert len(defs) == 1
    callers = {n.name for n in ast.walk(tree)
               if isinstance(n, ast.FunctionDef)
               and any(isinstance(c, ast.Call) and isinstance(c.func, ast.Name)
                       and c.func.id == "_counter_whole_use"
                       for c in ast.walk(n))}
    assert {"_counter_reader_touches", "_escape_sites",
            "_one_step_reader"} <= callers


def test_extraction_did_not_change_the_neighbour_verdicts():
    """Извлечение обязано быть ДОСЛОВНЫМ: те же сцены — те же вердикты соседа."""
    rows = _reader_sites("<scene>", ast.parse(ONE_STEP_CONTROL_CLEAN))
    assert [r["gap"] for r in rows] == [READER_GAP_ESCAPES] * len(rows)


@pytest.mark.parametrize("parent, expected", [
    (ast.Call(func=ast.Name(id="sum", ctx=ast.Load()), args=[], keywords=[]),
     WHOLE_USE_WHOLESALE),
    (ast.Call(func=ast.Name(id="publish", ctx=ast.Load()), args=[],
              keywords=[]), WHOLE_USE_ESCAPE),
    (ast.Subscript(value=ast.Name(id="x", ctx=ast.Load()),
                   slice=ast.Constant(value=1), ctx=ast.Load()), None),
])
def test_whole_use_rule_answers_three_ways(parent, expected):
    node = ast.Name(id="counts", ctx=ast.Load())
    assert _counter_whole_use(node, parent) == expected


def test_reader_site_nodes_and_reader_sites_agree_row_for_row():
    """Генератор узлов и список строк — ОДИН обход. Разойдясь, они отвечали бы
    на разные вопросы, а читатель не узнал бы, на какой."""
    tree = ast.parse(ONE_STEP_CONTROL_CLEAN)
    rows = _reader_sites("<scene>", tree)
    paired = [site for site, _t, _k, _s in
              _reader_site_nodes("<scene>", ast.parse(ONE_STEP_CONTROL_CLEAN))]
    assert [r["line"] for r in rows] == [p["line"] for p in paired]


# ---------------------------------------------------------------------------
# 7. ОТКАЗЫ ШАГА — ни один не есть ноль
# ---------------------------------------------------------------------------

def test_step_refuses_when_the_neighbour_did_not_measure():
    for harm in (None, {}, {"status": "UNMEASURED"}):
        doc = escaped_counter_one_step(REPO_ROOT, harm)
        assert doc["status"] == "UNMEASURED"
        assert doc["unmeasured_class"] == UNMEASURED_STEP_HARM


def test_step_refuses_when_the_neighbour_named_no_escape_count():
    doc = escaped_counter_one_step(
        REPO_ROOT, {"status": "MEASURED", "unmeasured_reader_reasons": {}})
    assert doc["unmeasured_class"] == UNMEASURED_STEP_HARM


def test_step_refuses_when_its_own_walk_disagrees_with_the_census(tmp_path):
    """Свой обход — ВТОРАЯ дорога к тому же населению. Разойдясь с первой, он
    отвечал бы на другой вопрос, и выбрать себе удобное число шаг не вправе."""
    (tmp_path / "spa_core" / "monitoring").mkdir(parents=True)
    (tmp_path / "scripts").mkdir()
    (tmp_path / "spa_core/monitoring/scene.py").write_text(
        "def tally(rows):\n" + COUNTER + "    return counts\n",
        encoding="utf-8")
    doc = escaped_counter_one_step(tmp_path, {
        "status": "MEASURED",
        "unmeasured_reader_reasons": {READER_GAP_ESCAPES: 99}})
    assert doc["status"] == "UNMEASURED"
    assert doc["unmeasured_class"] == UNMEASURED_STEP_POPULATION
    assert doc["walked"] == 1 and doc["census"] == 99


def test_step_refuses_when_its_own_control_fails(monkeypatch):
    """Число, полученное правилом, которое промахивается по известной форме,
    есть свойство ПРАВИЛА, а не населения."""
    monkeypatch.setattr(census, "ONE_STEP_CONTROL_SOURCE",
                        "def tally(rows):\n    return 1\n")
    doc = escaped_counter_one_step(
        REPO_ROOT, {"status": "MEASURED",
                    "unmeasured_reader_reasons": {READER_GAP_ESCAPES: 1}})
    assert doc["unmeasured_class"] == UNMEASURED_STEP_CONTROL


def test_missing_directory_is_named_not_silently_empty(tmp_path):
    doc = escaped_counter_one_step(tmp_path, {
        "status": "MEASURED",
        "unmeasured_reader_reasons": {READER_GAP_ESCAPES: 0}})
    assert doc["status"] == "MEASURED"
    assert [u["file"] for u in doc["files_unreadable"]] == list(
        census.OPEN_COUNTER_DIRS)


def test_unparsable_file_is_named_not_counted_as_clean(tmp_path):
    (tmp_path / "spa_core" / "monitoring").mkdir(parents=True)
    (tmp_path / "scripts").mkdir()
    (tmp_path / "scripts/broken.py").write_text("def (:\n", encoding="utf-8")
    doc = escaped_counter_one_step(tmp_path, {
        "status": "MEASURED",
        "unmeasured_reader_reasons": {READER_GAP_ESCAPES: 0}})
    assert any(u["file"] == "scripts/broken.py"
               for u in doc["files_unreadable"])


# ---------------------------------------------------------------------------
# 8. ФОРМА ОТВЕТА — три исхода различимы, шаг ничего не чинит
# ---------------------------------------------------------------------------

def test_every_declared_outcome_and_gap_has_a_distinct_machine_name():
    assert len(set(_ONE_STEP_OUTCOMES)) == len(_ONE_STEP_OUTCOMES)
    assert len(set(_STEP_GAPS)) == len(_STEP_GAPS)
    assert len(set(_ESCAPE_ROUTES)) == len(_ESCAPE_ROUTES)
    assert not set(_ONE_STEP_OUTCOMES) & set(_STEP_GAPS)


def test_zero_is_printed_for_every_named_reason(tmp_path):
    """Измеренный ноль и неизмеренное обязаны быть различимы: причина без
    строки в отчёте неотличима от причины, которой не бывает."""
    (tmp_path / "spa_core" / "monitoring").mkdir(parents=True)
    (tmp_path / "scripts").mkdir()
    doc = escaped_counter_one_step(tmp_path, {
        "status": "MEASURED",
        "unmeasured_reader_reasons": {READER_GAP_ESCAPES: 0}})
    assert set(doc["unresolved_reasons"]) == set(_STEP_GAPS)
    assert set(doc["routes"]) == set(_ESCAPE_ROUTES)


def test_step_is_advisory_and_repairs_nothing():
    doc = escaped_counter_one_step(REPO_ROOT, None)
    assert doc["applied"] is False
    assert doc["order"] == "G78.1"


def test_report_names_the_step_and_its_blindness():
    doc = {"escaped_counter_one_step": {
        "status": "MEASURED", "population": 66, "one_step_outcomes":
            {c: 0 for c in _ONE_STEP_OUTCOMES},
        "routes": {r: 0 for r in _ESCAPE_ROUTES},
        "unresolved_reasons": {g: 0 for g in _STEP_GAPS},
        "resolved_by_one_step": 0, "still_unmeasured": 66,
        "next_scope_reached": 4, "does_not_leave_the_scope_at_all": 6,
        "departing_population_net": 60, "control": {}, "blind": ["слепо"],
        "unresolved_sample": []}}
    lines = census.report(doc)
    assert any("[ОДИН ШАГ]" in line for line in lines)
    assert any("ПРОВОДКА ЖИВА" in line for line in lines)
    assert any("[СЛЕПОТА] слепо" in line for line in lines)


def test_report_says_not_measured_rather_than_silence():
    for doc in ({}, {"escaped_counter_one_step":
                     {"status": "UNMEASURED", "unmeasured_class": "x",
                      "reason": "y"}}):
        lines = census.report(doc)
        assert any("[ОДИН ШАГ] НЕ ИЗМЕРЕНО" in line for line in lines)


# ---------------------------------------------------------------------------
# 9. ЖИВОЕ ДЕРЕВО — проводка обязана СРАБАТЫВАТЬ, иначе ноль вакуумен
# ---------------------------------------------------------------------------

@pytest.mark.slow
def test_on_the_live_tree_the_step_reaches_a_next_scope():
    """Ноль разрешённых и ноль от непроведённого шага выглядят одинаково.
    Различает их ровно это число: сколько раз шаг ДОШЁЛ до следующей области
    и разобрал там читателя. Ноль здесь — красный тест, а не результат."""
    opened = census.open_class_counter_census(REPO_ROOT)
    harm = census.open_counter_reader_harm(REPO_ROOT, opened)
    doc = escaped_counter_one_step(REPO_ROOT, harm)
    assert doc["status"] == "MEASURED", doc.get("reason")
    assert doc["next_scope_reached"] > 0
    assert doc["population"] == (doc["one_step_outcomes"][ONE_STEP_SPLITS]
                                 + doc["one_step_outcomes"][ONE_STEP_WHOLESALE]
                                 + doc["one_step_outcomes"][ONE_STEP_UNRESOLVED])


# ---------------------------------------------------------------------------
# 10. КОНТРОЛЬ САМОГО КОНТРОЛЯ — половина, которая ничего не требует, есть
#     украшение, и её отсутствие обязано быть заметно
# ---------------------------------------------------------------------------

def test_control_refuses_when_only_one_form_of_escape_is_proven(monkeypatch):
    """Правило, доказавшее ОДНУ форму из двух, отвечает на половину вопроса
    заказа. Принять его значило бы выдать половину замера за полный."""
    monkeypatch.setattr(
        census, "ONE_STEP_CONTROL_SOURCE",
        "LIVE = 'live'\n"
        "def tally(rows):\n" + COUNTER +
        "    return counts\n"
        "def verdict(rows):\n"
        "    totals = tally(rows)\n"
        "    return totals[LIVE]\n"
        "def handed(rows):\n"
        "    seen = {}\n"
        "    for row in rows:\n"
        "        cls = str(row.get('outcome'))\n"
        "        seen[cls] = seen.get(cls, 0) + 1\n"
        "    got = second(seen)\n"
        "    return got\n"
        "def second(seen):\n"
        "    return seen[LIVE]\n")
    control = _one_step_control()
    assert control["passed"] is True
    monkeypatch.setattr(
        census, "ONE_STEP_CONTROL_SOURCE",
        "LIVE = 'live'\n"
        "def tally(rows):\n" + COUNTER +
        "    return counts\n"
        "def verdict(rows):\n"
        "    totals = tally(rows)\n"
        "    return totals[LIVE]\n"
        "def twin(rows):\n"
        "    seen = {}\n"
        "    for row in rows:\n"
        "        cls = str(row.get('outcome'))\n"
        "        seen[cls] = seen.get(cls, 0) + 1\n"
        "    return seen\n"
        "def other(rows):\n"
        "    got = twin(rows)\n"
        "    return got[LIVE]\n")
    control = _one_step_control()
    assert control["passed"] is False
    assert "маршрут" in control["reason"]


def _benign_counter(name: str) -> str:
    return (f"def {name}(rows):\n"
            f"    counts = {{}}\n"
            f"    for row in rows:\n"
            f"        cls = str(row.get('outcome'))\n"
            f"        counts[cls] = counts.get(cls, 0) + 1\n"
            f"    return listed(counts)\n")


def test_control_refuses_when_the_negative_half_stops_separating(monkeypatch):
    """Отрицательная половина обязана ТРЕБОВАТЬ четыре разных отказа. Сцена,
    в которой все пять счётчиков безвредны, не отличила бы правило от
    «объявляю разрешённым что угодно».

    Счётчиков здесь ровно ПЯТЬ намеренно: проверка их числа стои́т в контроле
    раньше проверки отказов, и сцена не того размера уронила бы контроль по
    ДРУГОЙ причине — тест зеленел бы, проверяя не то, что заявляет (ровно та
    слабость, которую мутационная батарея нашла в первом заходе).
    """
    monkeypatch.setattr(
        census, "ONE_STEP_CONTROL_CLEAN",
        "".join(_benign_counter(n) for n in
                ("one", "two", "three", "four", "five")) +
        "def listed(counted):\n"
        "    return sorted(counted.items())\n")
    control = _one_step_control()
    assert control["passed"] is False
    assert "ЧЕТЫРЕ разных отказа" in control["reason"], control["reason"]


def test_ceiling_of_the_neighbour_population_is_counted_and_subtracted(
        tmp_path):
    """Потолок соседа обязан быть ЧИСЛОМ и обязан вычитаться рядом с ним.

    Обнулить его молча — то же, что не заметить: читатель принял бы
    соседское население за замер уезжающих, а оно завышено сверху.
    """
    (tmp_path / "spa_core" / "monitoring").mkdir(parents=True)
    (tmp_path / "scripts").mkdir()
    (tmp_path / "scripts/scene.py").write_text(
        "def stays(rows):\n" + COUNTER +
        "    if not counts:\n        return None\n"
        "    return 1\n"
        "def leaves(rows):\n"
        "    seen = {}\n"
        "    for row in rows:\n"
        "        cls = str(row.get('outcome'))\n"
        "        seen[cls] = seen.get(cls, 0) + 1\n"
        "    return {'seen': seen}\n", encoding="utf-8")
    doc = escaped_counter_one_step(tmp_path, {
        "status": "MEASURED",
        "unmeasured_reader_reasons": {READER_GAP_ESCAPES: 2}})
    assert doc["status"] == "MEASURED", doc.get("reason")
    assert doc["population"] == 2
    assert doc["does_not_leave_the_scope_at_all"] == 1
    assert doc["departing_population_net"] == 1


def test_escape_sites_disagreeing_with_the_neighbour_is_a_third_outcome(
        monkeypatch):
    """Правило побега одно, но если два его читателя когда-нибудь разойдутся,
    счётчик обязан уйти третьим исходом с именем, а не пропасть."""
    monkeypatch.setattr(census, "_escape_sites", lambda scope, target: [])
    row = only("def tally(rows):\n" + COUNTER + "    return counts\n")
    assert row["one_step"] == ONE_STEP_UNRESOLVED
    assert row["step_gap"] == STEP_GAP_SITES_DISAGREE


def test_next_scope_reached_is_zero_when_nothing_departs(tmp_path):
    """Число «дошёл до следующей области» обязано БЫТЬ нулём там, где шаг
    никуда не ходил, — иначе оно не отличало бы живую проводку от мёртвой."""
    (tmp_path / "spa_core" / "monitoring").mkdir(parents=True)
    (tmp_path / "scripts").mkdir()
    (tmp_path / "scripts/scene.py").write_text(
        "def tally(rows):\n" + COUNTER + "    return {'tally': counts}\n",
        encoding="utf-8")
    doc = escaped_counter_one_step(tmp_path, {
        "status": "MEASURED",
        "unmeasured_reader_reasons": {READER_GAP_ESCAPES: 1}})
    assert doc["status"] == "MEASURED"
    assert doc["next_scope_reached"] == 0
    assert doc["does_not_leave_the_scope_at_all"] == 0
    assert doc["departing_population_net"] == 1
