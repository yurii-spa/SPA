"""Заказ G79 п. 1 — ОДИН шаг ПЕРЕНОСА ПОЛЕМ у счётчика, уехавшего контейнером.

ADR-462 ответил на заказ G78 нулём и назвал главным содержанием замера
НЕВЕРНУЮ премиссу: из 66 убежавших счётчиков возвратом уходит 7, аргументом 0,
а **53** уезжают сперва КОНТЕЙНЕРОМ (``return {'tally': counts}``). Восемьдесят
процентов населения путешествует ПОЛЕМ, а не вызовом. Заказ G79 п. 1 спросил
числом: сколько из 53 разрешает ОДИН шаг переноса полем и сколько остаётся
третьим исходом.

Каждый тест здесь — положительный контроль: он воспроизводит либо форму уже
случившегося дефекта (выдать НЕ ИЗМЕРЕНО за измеренный исход; объявить
разрешённым то, что уехало дальше; соврать в ИМЕНИ отказа), либо форму, которую
правило ОБЯЗАНО не спутать с другой.

**Три числа, которые набор держит РАЗДЕЛЬНО** — слить любые два значило бы
совершить ровно тот дефект, против которого написан весь ряд ADR-459…462:

* «шаг довёл до читателя, и читатель делит класс» — измеренный вред;
* «шаг довёл до читателя, и он безвреден» — измеренная безвредность;
* «шаг не довёл» — НЕ ИЗМЕРЕНО, и у каждой причины недохода СВОЁ имя.
"""

from __future__ import annotations

import ast
from pathlib import Path

from spa_core.monitoring import rule_second_copy_census as census
from spa_core.monitoring.rule_second_copy_census import (
    FIELD_FORM_BOUND,
    FIELD_FORM_DIRECT,
    FIELD_FORM_SUBSCRIPT,
    FIELD_GAP_AMBIGUOUS_FIELD,
    FIELD_GAP_CONTAINER_NOT_RETURNED,
    FIELD_GAP_FIELD_NEVER_READ,
    FIELD_GAP_NO_FIELD_NAME,
    FIELD_STEP_CONTROL_CLEAN,
    FIELD_STEP_CONTROL_SOURCE,
    ONE_STEP_SPLITS,
    ONE_STEP_UNRESOLVED,
    ONE_STEP_WHOLESALE,
    READER_GAP_ESCAPES,
    STEP_GAP_CONTAINER,
    STEP_GAP_ESCAPES_AGAIN,
    STEP_GAP_NO_CALLER,
    STEP_GAP_RESULT_UNBOUND,
    UNMEASURED_FIELD_CONTROL,
    UNMEASURED_FIELD_NEIGHBOUR,
    UNMEASURED_FIELD_POPULATION,
    _FIELD_FORMS,
    _FIELD_GAPS,
    _ONE_STEP_OUTCOMES,
    _callers_binding_the_result,
    _field_read_targets,
    _field_step_control,
    _field_step_sites,
    _one_step_sites,
    _reader_sites,
    _returned_container_fields,
    _returned_names,
    _subscript_field_carriers,
    container_counter_field_step,
)

REPO_ROOT = Path(__file__).resolve().parents[2]

#: Открытый счётчик ровно той формы, которую считает открытой сосед: ключ
#: приходит из артефакта и принадлежностью не сверен. Без этого мерить было бы
#: НЕ У ЧЕГО — сосед не признал бы счётчик открытым, и зелёный тест был бы
#: свойством сцены, а не правила.
COUNTER = (
    "    counts = {}\n"
    "    for row in rows:\n"
    "        cls = str(row.get('outcome'))\n"
    "        counts[cls] = counts.get(cls, 0) + 1\n"
)


def sites(source: str):
    return _field_step_sites("<scene>", ast.parse(source))


def only(source: str) -> dict:
    found = sites(source)
    assert len(found) == 1, [(s["file"], s["line"], s["counter"])
                             for s in found]
    return found[0]


def scope_of(source: str, name: str) -> ast.AST:
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    raise AssertionError(f"области {name} в сцене нет")


#: Сосед измерен и назвал население «уехал сперва полем» — минимальный вход,
#: при котором шаг вправе мерить.
def neighbour(container: int = 1) -> dict:
    return {"status": "MEASURED",
            "unresolved_reasons": {STEP_GAP_CONTAINER: container}}


# ---------------------------------------------------------------------------
# 1. КОНТРОЛЬ ПРАВИЛА — объявлен ДО замера и проверяется обеими половинами
# ---------------------------------------------------------------------------

def test_declared_rule_resolves_every_form_of_the_known_case():
    """Форм переноса ТРИ, и правило обязано довести до расколотого читателя
    всеми. Найдя одну, оно ответило бы на треть вопроса заказа, а число выдало
    бы за полный ответ."""
    control = _field_step_control()
    assert control["passed"], control
    assert control["known_case_resolved"] == len(_FIELD_FORMS)
    assert sorted(control["forms"]) == sorted(_FIELD_FORMS)


def test_control_scene_counters_are_open_and_escaping():
    """Предпосылка сцены ПРОВЕРЯЕТСЯ, а не предполагается: счётчик, которого
    сосед не считает убежавшим, мерить этим шагом нечего."""
    for source in (FIELD_STEP_CONTROL_SOURCE, FIELD_STEP_CONTROL_CLEAN):
        rows = _reader_sites("<scene>", ast.parse(source))
        escaping = [r for r in rows if r.get("gap") == READER_GAP_ESCAPES]
        assert escaping, source[:60]


def test_control_scene_counters_all_travel_by_a_container():
    """И вторая половина предпосылки: сцена обязана нести счётчики маршрута
    КОНТЕЙНЕР, иначе шаг переноса полем на ней не работает вовсе."""
    for source, want in ((FIELD_STEP_CONTROL_SOURCE, len(_FIELD_FORMS)),
                         (FIELD_STEP_CONTROL_CLEAN, 6)):
        rows = [r for r in _one_step_sites("<scene>", ast.parse(source))
                if r["step_gap"] == STEP_GAP_CONTAINER]
        assert len(rows) == want, [(r["owner"], r["step_gap"]) for r in rows]


def test_negative_half_separates_five_refusals_by_name():
    """Отрицательная половина обязана развести отказы РАЗНЫМИ именами: они
    чинятся разным, и одно имя на всех вернуло бы внутрь прибора тот самый
    класс, который прибор и ищет."""
    control = _field_step_control()
    assert control["clean_false_splits"] == 0
    assert sorted(control["clean_refusal_names"]) == sorted((
        FIELD_GAP_NO_FIELD_NAME, FIELD_GAP_AMBIGUOUS_FIELD,
        FIELD_GAP_CONTAINER_NOT_RETURNED, FIELD_GAP_FIELD_NEVER_READ,
        STEP_GAP_NO_CALLER))
    assert control["clean_benign"] == 1


def test_negative_half_keeps_exactly_one_benign_reader():
    """Безвредный читатель в отрицательной сцене ровно один: слей его с
    отказом — и «шаг разрешил N» стало бы неотличимо от «шаг объявляет
    разрешённым что угодно»."""
    clean = _field_step_sites("<clean>", ast.parse(FIELD_STEP_CONTROL_CLEAN))
    benign = [r for r in clean if r["field_step"] == ONE_STEP_WHOLESALE]
    assert len(benign) == 1, [(r["owner"], r["field_step"]) for r in clean]


def test_control_failure_refuses_the_whole_step(monkeypatch):
    """Правило, промахнувшееся по известной форме, даёт число — свойство
    ПРАВИЛА, а не населения. Такое число печатать нельзя вовсе."""
    monkeypatch.setattr(census, "_field_step_control",
                        lambda: {"passed": False, "reason": "сцена порвана"})
    out = container_counter_field_step(REPO_ROOT, neighbour())
    assert out["status"] == "UNMEASURED"
    assert out["unmeasured_class"] == UNMEASURED_FIELD_CONTROL


# ---------------------------------------------------------------------------
# 2. РАЗРЕШИМЫЕ ФОРМЫ — ради них заказ и поставлен
# ---------------------------------------------------------------------------

def test_dict_literal_returned_directly_reaches_a_splitting_reader():
    row = only(
        "LIVE = 'live'\n"
        "def tally(rows):\n" + COUNTER +
        "    return {'tally': counts}\n"
        "def verdict(rows):\n"
        "    got = tally(rows)\n"
        "    return got['tally'][LIVE]\n")
    assert row["field_step"] == ONE_STEP_SPLITS
    assert row["forms"] == [FIELD_FORM_DIRECT]
    assert row["fields"] == ["tally"]


def test_container_bound_to_a_name_and_returned_reaches_the_reader():
    row = only(
        "LIVE = 'live'\n"
        "def tally(rows):\n" + COUNTER +
        "    out = {'tally': counts}\n"
        "    return out\n"
        "def verdict(rows):\n"
        "    got = tally(rows)\n"
        "    return got['tally'][LIVE]\n")
    assert row["field_step"] == ONE_STEP_SPLITS
    assert row["forms"] == [FIELD_FORM_BOUND]


def test_counter_stored_by_subscript_into_a_returned_mapping_reaches_reader():
    """`doc['tally'] = counts` кладёт счётчик под ИМЕНЕМ ПОЛЯ ровно так же,
    как словарь-литерал. Приём соседа этой формы не знает, и отказать ей
    именем «контейнер без имени поля» значило бы соврать в самом имени."""
    row = only(
        "LIVE = 'live'\n"
        "def tally(rows):\n"
        "    doc = {}\n" + COUNTER +
        "    doc['tally'] = counts\n"
        "    return doc\n"
        "def verdict(rows):\n"
        "    got = tally(rows)\n"
        "    return got['tally'][LIVE]\n")
    assert row["field_step"] == ONE_STEP_SPLITS
    assert row["forms"] == [FIELD_FORM_SUBSCRIPT]


def test_caller_reading_the_field_by_get_is_the_same_reader():
    """`got.get('tally')` и `got['tally']` — одно чтение, записанное двумя
    формами. Знать одну значило бы объявить «поля никто не читает» там, где
    его читают."""
    row = only(
        "LIVE = 'live'\n"
        "def tally(rows):\n" + COUNTER +
        "    return {'tally': counts}\n"
        "def verdict(rows):\n"
        "    got = tally(rows)\n"
        "    return got.get('tally').get(LIVE, 0)\n")
    assert row["field_step"] == ONE_STEP_SPLITS


def test_caller_reading_the_field_by_get_with_a_default_is_the_same_reader():
    row = only(
        "LIVE = 'live'\n"
        "def tally(rows):\n" + COUNTER +
        "    return {'tally': counts}\n"
        "def verdict(rows):\n"
        "    got = tally(rows)\n"
        "    return got.get('tally', {})[LIVE]\n")
    assert row["field_step"] == ONE_STEP_SPLITS


def test_wholesale_reader_of_the_field_is_measured_benign():
    row = only(
        "def tally(rows):\n" + COUNTER +
        "    return {'tally': counts}\n"
        "def show(rows, report):\n"
        "    got = tally(rows)\n"
        "    for name, hits in sorted(got['tally'].items()):\n"
        "        report.append(f'{name}: {hits}')\n")
    assert row["field_step"] == ONE_STEP_WHOLESALE
    assert row["field_gap"] is None


def test_split_is_proven_by_a_module_constant_not_only_by_a_literal():
    """Класс, объявленный КОНСТАНТОЙ модуля, — то же объявление, что литерал.
    Не признать его значило бы занизить вред ровно на константах."""
    row = only(
        "LIVE = 'live'\n"
        "def tally(rows):\n" + COUNTER +
        "    return {'tally': counts}\n"
        "def verdict(rows):\n"
        "    got = tally(rows)\n"
        "    return got['tally'].get(LIVE, 0)\n")
    assert row["field_step"] == ONE_STEP_SPLITS


def test_two_callers_disagreeing_resolve_to_the_split():
    """Свидетель раскола ОДНОСТОРОННИЙ: доказал один читатель — доказано.
    Усреднить с безвредным значило бы потерять доказанный вред."""
    row = only(
        "LIVE = 'live'\n"
        "def tally(rows):\n" + COUNTER +
        "    return {'tally': counts}\n"
        "def show(rows, report):\n"
        "    got = tally(rows)\n"
        "    for name in got['tally']:\n"
        "        report.append(name)\n"
        "def verdict(rows):\n"
        "    got = tally(rows)\n"
        "    return got['tally'][LIVE]\n")
    assert row["field_step"] == ONE_STEP_SPLITS


def test_one_unmeasured_caller_makes_the_whole_escape_unmeasured():
    """А вот обратная сторона той же односторонности: раскол не доказан, но
    один читатель НЕ ИЗМЕРЕН ⇒ весь перенос не измерен. Объявить безвредным по
    измеренной половине и есть подмена третьего исхода."""
    row = only(
        "def tally(rows):\n" + COUNTER +
        "    return {'tally': counts}\n"
        "def show(rows, report):\n"
        "    got = tally(rows)\n"
        "    for name in got['tally']:\n"
        "        report.append(name)\n"
        "def carry(rows):\n"
        "    got = tally(rows)\n"
        "    kept = got['tally']\n"
        "    return kept\n")
    assert row["field_step"] == ONE_STEP_UNRESOLVED
    assert row["field_gap"] == STEP_GAP_ESCAPES_AGAIN


# ---------------------------------------------------------------------------
# 3. ТРЕТИЙ ИСХОД — и у каждой причины СВОЁ имя, потому что чинятся разным
# ---------------------------------------------------------------------------

def test_counter_returned_inside_a_tuple_has_no_field_name():
    """Кортеж несёт ПОЗИЦИЮ, а не имя: связывать по позиции — другое правило
    и другой разбор, а не поправка к этому."""
    row = only(
        "def tally(rows):\n" + COUNTER +
        "    return counts, len(rows)\n"
        "def verdict(rows):\n"
        "    got, total = tally(rows)\n"
        "    return total\n")
    assert row["field_step"] == ONE_STEP_UNRESOLVED
    assert row["field_gap"] == FIELD_GAP_NO_FIELD_NAME


def test_counter_returned_inside_a_list_has_no_field_name():
    row = only("def tally(rows):\n" + COUNTER + "    return [counts]\n")
    assert row["field_gap"] == FIELD_GAP_NO_FIELD_NAME


def test_ambiguous_field_name_refuses_and_is_not_a_finding():
    """Связь идёт по ИМЕНИ ПОЛЯ. На имени, несущем ещё и чужое значение, она
    приписала бы чужому сравнению наш класс — это ОТКАЗ, а не находка."""
    row = only(
        "LIVE = 'live'\n"
        "def tally(rows):\n" + COUNTER +
        "    other = {'tally': len(rows)}\n"
        "    return {'tally': counts, 'extra': other}\n"
        "def verdict(rows):\n"
        "    got = tally(rows)\n"
        "    return got['tally'][LIVE]\n")
    assert row["field_step"] == ONE_STEP_UNRESOLVED
    assert row["field_gap"] == FIELD_GAP_AMBIGUOUS_FIELD


def test_container_that_never_leaves_the_scope_refuses_by_its_own_name():
    """Контейнер, не покинувший область, читателя у зовущего НЕ ИМЕЕТ вовсе:
    выдумать его значило бы выдумать и вред."""
    row = only(
        "def tally(rows):\n" + COUNTER +
        "    bag = {'tally': counts}\n"
        "    publish(bag)\n")
    assert row["field_gap"] == FIELD_GAP_CONTAINER_NOT_RETURNED


def test_mapping_filled_by_subscript_but_not_returned_refuses_too():
    row = only(
        "def tally(rows):\n"
        "    doc = {}\n" + COUNTER +
        "    doc['tally'] = counts\n"
        "    publish(doc)\n")
    assert row["field_gap"] == FIELD_GAP_CONTAINER_NOT_RETURNED


def test_no_caller_in_this_file_is_a_third_outcome():
    row = only("def tally(rows):\n" + COUNTER + "    return {'tally': counts}\n")
    assert row["field_gap"] == STEP_GAP_NO_CALLER


def test_method_call_is_not_accepted_as_the_caller():
    """`obj.tally(...)` не разрешается: совпадение имени метода не доказывает,
    что зовут именно эту функцию. Строгость ошибается в сторону третьего
    исхода, а не выдуманного читателя."""
    row = only(
        "LIVE = 'live'\n"
        "def tally(rows):\n" + COUNTER +
        "    return {'tally': counts}\n"
        "def verdict(obj, rows):\n"
        "    got = obj.tally(rows)\n"
        "    return got['tally'][LIVE]\n")
    assert row["field_gap"] == STEP_GAP_NO_CALLER


def test_result_not_bound_to_a_name_is_a_third_outcome():
    row = only(
        "LIVE = 'live'\n"
        "def tally(rows):\n" + COUNTER +
        "    return {'tally': counts}\n"
        "def verdict(rows):\n"
        "    return tally(rows)['tally'][LIVE]\n")
    assert row["field_gap"] == STEP_GAP_RESULT_UNBOUND


def test_caller_reading_another_field_refuses_by_a_truthful_name():
    """Зовущий читает СОСЕДНЕЕ поле того же словаря. Сказать «не читает
    счётчик» значило бы соврать в имени отказа, а имя и есть то, чем отказ
    чинится."""
    row = only(
        "def tally(rows):\n" + COUNTER +
        "    return {'tally': counts, 'n': len(rows)}\n"
        "def verdict(rows):\n"
        "    got = tally(rows)\n"
        "    return got['n']\n")
    assert row["field_gap"] == FIELD_GAP_FIELD_NEVER_READ


def test_caller_that_returns_the_document_whole_never_reads_the_field():
    row = only(
        "def tally(rows):\n" + COUNTER +
        "    return {'tally': counts}\n"
        "def verdict(rows):\n"
        "    got = tally(rows)\n"
        "    return got\n")
    assert row["field_gap"] == FIELD_GAP_FIELD_NEVER_READ


def test_field_read_bound_to_a_name_escapes_again():
    """Поле прочитано, но связано именем и уехало дальше: это «нужен ещё
    шаг», а не «вреда нет»."""
    row = only(
        "def tally(rows):\n" + COUNTER +
        "    return {'tally': counts}\n"
        "def verdict(rows):\n"
        "    got = tally(rows)\n"
        "    kept = got['tally']\n"
        "    return kept\n")
    assert row["field_gap"] == STEP_GAP_ESCAPES_AGAIN


def test_caller_reading_the_field_by_a_dynamic_key_is_not_a_split():
    """Ключ, которого правило не разрешает, — НЕ доказанный раскол. Засчитать
    его значило бы объявить вред по неизмеренному ключу."""
    row = only(
        "def tally(rows):\n" + COUNTER +
        "    return {'tally': counts}\n"
        "def verdict(rows, want):\n"
        "    got = tally(rows)\n"
        "    return got['tally'][want]\n")
    assert row["field_step"] == ONE_STEP_UNRESOLVED
    assert row["field_gap"] not in (None, ONE_STEP_SPLITS)


# ---------------------------------------------------------------------------
# 4. ГРАНИЦА НАСЕЛЕНИЯ — шаг мерит ТОЛЬКО тех, кому сосед отказал контейнером
# ---------------------------------------------------------------------------

def test_counter_that_left_by_return_is_not_in_this_population():
    """Счётчик, уехавший ВЫЗОВОМ, — предмет соседа, и мерить его здесь значило
    бы отвечать на его вопрос вторым прибором."""
    assert sites(
        "LIVE = 'live'\n"
        "def tally(rows):\n" + COUNTER +
        "    return counts\n"
        "def verdict(rows):\n"
        "    got = tally(rows)\n"
        "    return got[LIVE]\n") == []


def test_counter_that_does_not_leave_at_all_is_not_in_this_population():
    assert sites("def tally(rows):\n" + COUNTER +
                 "    if not counts:\n"
                 "        return 'пусто'\n"
                 "    return 'есть'\n") == []


def test_population_equals_the_neighbour_number_or_the_step_refuses():
    """Свой обход есть ВТОРАЯ дорога к тому же населению. Разойдясь с первой,
    он отвечал бы на другой вопрос — и число печатать нельзя."""
    out = container_counter_field_step(REPO_ROOT, neighbour(container=999_999))
    assert out["status"] == "UNMEASURED"
    assert out["unmeasured_class"] == UNMEASURED_FIELD_POPULATION
    assert out["census"] == 999_999
    assert out["walked"] != 999_999


def test_population_cross_check_agrees_on_the_live_tree():
    """И положительная половина той же сверки: на живом дереве два обхода
    обязаны СОЙТИСЬ, иначе проверка выше зелена по недостижимости."""
    step = census.escaped_counter_one_step(
        REPO_ROOT,
        census.open_counter_reader_harm(
            REPO_ROOT, census.open_class_counter_census(REPO_ROOT)))
    assert step["status"] == "MEASURED"
    out = container_counter_field_step(REPO_ROOT, step)
    assert out["status"] == "MEASURED", out.get("reason")
    assert out["population"] == step["unresolved_reasons"][STEP_GAP_CONTAINER]


# ---------------------------------------------------------------------------
# 5. ОТКАЗЫ ШАГА — три, и ни один не есть ноль
# ---------------------------------------------------------------------------

def test_neighbour_unmeasured_refuses_and_says_it_is_not_a_zero():
    out = container_counter_field_step(REPO_ROOT, {"status": "UNMEASURED"})
    assert out["status"] == "UNMEASURED"
    assert out["unmeasured_class"] == UNMEASURED_FIELD_NEIGHBOUR
    assert "НЕ" in out["reason"]


def test_neighbour_absent_refuses_rather_than_reporting_zero():
    out = container_counter_field_step(REPO_ROOT, None)
    assert out["status"] == "UNMEASURED"
    assert out["unmeasured_class"] == UNMEASURED_FIELD_NEIGHBOUR


def test_neighbour_without_the_container_number_refuses():
    """Сосед измерен, но числа «уехал полем» не назвал — сверять не с чем, и
    это ОТКАЗ, а не свобода мерить своё население."""
    out = container_counter_field_step(REPO_ROOT,
                                       {"status": "MEASURED",
                                        "unresolved_reasons": {}})
    assert out["status"] == "UNMEASURED"
    assert out["unmeasured_class"] == UNMEASURED_FIELD_NEIGHBOUR


def test_refusal_carries_no_population_number_at_all():
    """Отказ, печатающий число населения рядом, читался бы как замер. Их и
    надо различать — ровно ради этого весь ряд ADR."""
    out = container_counter_field_step(REPO_ROOT, None)
    assert "population" not in out
    assert "field_step_outcomes" not in out


# ---------------------------------------------------------------------------
# 6. ПРАВИЛА ПО ОТДЕЛЬНОСТИ — каждое звено проверено своим контролем
# ---------------------------------------------------------------------------

def test_subscript_carriers_find_the_field_and_its_holder():
    scope = scope_of("def tally(rows):\n"
                     "    doc = {}\n" + COUNTER +
                     "    doc['tally'] = counts\n"
                     "    return doc\n", "tally")
    ours, ambiguous = _subscript_field_carriers(
        scope, ast.dump(ast.Name(id="counts", ctx=ast.Load())), {"counts"})
    assert ours == {("doc", "tally")}
    assert ambiguous == set()


def test_subscript_carriers_call_a_twice_filled_field_ambiguous():
    scope = scope_of("def tally(rows):\n"
                     "    doc = {}\n" + COUNTER +
                     "    doc['tally'] = counts\n"
                     "    doc['tally'] = len(rows)\n"
                     "    return doc\n", "tally")
    ours, ambiguous = _subscript_field_carriers(
        scope, ast.dump(ast.Name(id="counts", ctx=ast.Load())), {"counts"})
    assert ours == set()
    assert ambiguous == {"tally"}


def test_subscript_carriers_ignore_a_dynamic_field_name():
    """`doc[key] = counts` имени поля не даёт: зовущий не знает, что читать."""
    scope = scope_of("def tally(rows, key):\n" + COUNTER +
                     "    doc = {}\n"
                     "    doc[key] = counts\n"
                     "    return doc\n", "tally")
    ours, ambiguous = _subscript_field_carriers(
        scope, ast.dump(ast.Name(id="counts", ctx=ast.Load())), {"counts"})
    assert ours == set() and ambiguous == set()


def test_returned_container_fields_names_both_forms():
    scope = scope_of("def tally(rows):\n"
                     "    return {'a': 1}\n", "tally")
    assert _returned_container_fields(scope) == {"a": {FIELD_FORM_DIRECT}}
    scope = scope_of("def tally(rows):\n"
                     "    out = {'b': 1}\n"
                     "    return out\n", "tally")
    assert _returned_container_fields(scope) == {"b": {FIELD_FORM_BOUND}}


def test_name_bound_twice_is_not_resolved_to_a_container():
    """«Какое из двух» есть третий исход, а не выбор: имя, связанное в области
    не одним значением, контейнером не признаётся."""
    scope = scope_of("def tally(rows):\n"
                     "    out = {'b': 1}\n"
                     "    out = {'c': 2}\n"
                     "    return out\n", "tally")
    assert _returned_container_fields(scope) == {}


def test_returned_names_sees_only_a_bare_returned_name():
    scope = scope_of("def tally(rows):\n"
                     "    doc = {}\n"
                     "    return doc\n", "tally")
    assert _returned_names(scope) == {"doc"}
    scope = scope_of("def tally(rows):\n"
                     "    doc = {}\n"
                     "    return doc['x']\n", "tally")
    assert _returned_names(scope) == set()


def test_field_read_targets_find_both_forms_and_do_not_double_count():
    scope = scope_of("def verdict(rows):\n"
                     "    got = tally(rows)\n"
                     "    a = got['tally']\n"
                     "    b = got['tally']\n"
                     "    c = got.get('tally')\n", "verdict")
    found = _field_read_targets(scope, "got", "tally")
    assert len(found) == 2, [ast.unparse(n) for n in found]


def test_field_read_targets_do_not_match_by_substring():
    """Поле `tall` не есть поле `tally`: подстрочное совпадение объявило бы
    читателем чужое чтение (ADR-333)."""
    scope = scope_of("def verdict(rows):\n"
                     "    got = tally(rows)\n"
                     "    return got['tall']\n", "verdict")
    assert _field_read_targets(scope, "got", "tally") == []


def test_field_read_targets_do_not_match_a_key_that_CONTAINS_the_field():
    """У подстроки ДВА направления, и сосед выше проверяет только одно.

    `tall` короче `tally` — такое чтение не совпадёт ни при каком правиле.
    А `tally_total` ДЛИННЕЕ, и правило, сверяющее вхождение вместо равенства
    (`field in key`), объявило бы читателем чужое чтение. Мутация «чтение
    поля: совпадение по ПОДСТРОКЕ» ВЫЖИЛА у цикла #682 ровно на этом: тест,
    знающий одну сторону, честно зеленел и проверял не то, что заявляет.
    Обе формы чтения проверяются одной сценой — `.get` сверяет ключ своим
    сравнением, и односторонняя починка оставила бы вторую половину открытой.
    """
    scope = scope_of("def verdict(rows):\n"
                     "    got = tally(rows)\n"
                     "    a = got['tally_total']\n"
                     "    return got.get('tally_total')\n", "verdict")
    assert _field_read_targets(scope, "got", "tally") == []


def test_caller_reading_a_LONGER_key_is_not_a_reader_of_our_field():
    """То же самое ИСХОДОМ, а не устройством: зовущий читает `got['tally_n']`,
    и счётчик из поля `tally` не читает никто. Отказ обязан остаться
    «поля никто не читает» — иначе шаг доказывал бы вред СОВПАДЕНИЕМ ИМЁН,
    против чего написан сам заказ."""
    row = only(
        "def tally(rows):\n" + COUNTER +
        "    return {'tally': counts, 'tally_n': len(rows)}\n"
        "def verdict(rows):\n"
        "    got = tally(rows)\n"
        "    return got['tally_n']\n")
    assert row["field_gap"] == FIELD_GAP_FIELD_NEVER_READ


def test_field_read_targets_ignore_a_write_into_the_field():
    """Запись в поле читателем не является — иначе шаг мерил бы ПИСАТЕЛЯ под
    именем читателя, ровно как ловил себя сосед."""
    scope = scope_of("def fill(rows):\n"
                     "    got = {}\n"
                     "    got['tally'] = 1\n", "fill")
    assert _field_read_targets(scope, "got", "tally") == []


def test_callers_binding_the_result_names_its_two_refusals():
    tree = ast.parse("def tally(rows):\n    return 1\n")
    parents = census._parent_map(tree)
    owner_of = census._counter_owner_scopes(tree)
    scope = scope_of("def tally(rows):\n    return 1\n", "tally")
    out = _callers_binding_the_result(tree, parents, owner_of, scope)
    assert out["gap"] == STEP_GAP_NO_CALLER and out["sites"] == []

    src = ("def tally(rows):\n    return 1\n"
           "def use(rows):\n    return tally(rows)\n")
    tree = ast.parse(src)
    parents = census._parent_map(tree)
    owner_of = census._counter_owner_scopes(tree)
    out = _callers_binding_the_result(tree, parents, owner_of,
                                      scope_of(src, "tally"))
    assert out["gap"] == STEP_GAP_RESULT_UNBOUND


def test_callers_binding_the_result_is_the_only_copy_of_that_rule():
    """Извлечение из шага одного вызова обязано было СОХРАНИТЬ его вердикты:
    вторая копия правила внутри прибора, который ищет вторые копии, — дефект,
    случившийся в этом файле уже трижды."""
    src = ("LIVE = 'live'\n"
           "def tally(rows):\n" + COUNTER +
           "    return counts\n"
           "def verdict(rows):\n"
           "    got = tally(rows)\n"
           "    return got[LIVE]\n")
    row = [r for r in _one_step_sites("<scene>", ast.parse(src))][0]
    assert row["one_step"] == ONE_STEP_SPLITS


# ---------------------------------------------------------------------------
# 7. СЛОВАРЬ ИМЁН И ADVISORY
# ---------------------------------------------------------------------------

def test_every_refusal_name_is_declared_in_the_vocabulary():
    """Имя отказа, не объявленное в перечне, не посчиталось бы ни одним
    счётчиком отчёта — тот самый открытый счётчик, который прибор и ищет."""
    clean = _field_step_sites("<clean>", ast.parse(FIELD_STEP_CONTROL_CLEAN))
    for row in clean:
        if row["field_gap"] is not None:
            assert row["field_gap"] in _FIELD_GAPS, row["field_gap"]


def test_outcome_vocabulary_is_the_neighbour_one_not_a_second_copy():
    """Исходы у шага полем те же, что у шага вызова: заводить им вторые имена
    значило бы развести один класс по двум счётчикам."""
    source = _field_step_sites("<src>", ast.parse(FIELD_STEP_CONTROL_SOURCE))
    for row in source:
        assert row["field_step"] in _ONE_STEP_OUTCOMES


def test_forms_are_three_and_each_has_its_own_name():
    assert len(set(_FIELD_FORMS)) == 3
    assert FIELD_FORM_SUBSCRIPT in _FIELD_FORMS


def test_measured_result_is_advisory_and_repairs_nothing():
    out = container_counter_field_step(
        REPO_ROOT,
        census.escaped_counter_one_step(
            REPO_ROOT,
            census.open_counter_reader_harm(
                REPO_ROOT, census.open_class_counter_census(REPO_ROOT))))
    assert out["applied"] is False
    assert out["order"] == "G79.1"


def test_refusal_is_advisory_too():
    out = container_counter_field_step(REPO_ROOT, None)
    assert out["applied"] is False


def test_two_liveness_numbers_are_kept_apart():
    """«Дошёл до области зовущего» и «разобрал там ЧИТАТЕЛЯ» — разные
    достижения, и одно число на оба выдало бы половину проводки за целую."""
    out = container_counter_field_step(
        REPO_ROOT,
        census.escaped_counter_one_step(
            REPO_ROOT,
            census.open_counter_reader_harm(
                REPO_ROOT, census.open_class_counter_census(REPO_ROOT))))
    assert out["status"] == "MEASURED"
    assert out["reader_parsed_at_next_scope"] <= out["next_scope_reached"]
    assert out["reader_parsed_at_next_scope"] > 0


def test_blind_spots_are_named_in_the_result():
    out = container_counter_field_step(
        REPO_ROOT,
        census.escaped_counter_one_step(
            REPO_ROOT,
            census.open_counter_reader_harm(
                REPO_ROOT, census.open_class_counter_census(REPO_ROOT))))
    assert len(out["blind"]) >= 5


def measured() -> dict:
    return container_counter_field_step(
        REPO_ROOT,
        census.escaped_counter_one_step(
            REPO_ROOT,
            census.open_counter_reader_harm(
                REPO_ROOT, census.open_class_counter_census(REPO_ROOT))))


def test_resolved_counts_only_the_two_measured_outcomes():
    """«Разрешено» есть раскол ПЛЮС безвредность и ничего больше: зачислить
    туда третий исход значило бы выдать НЕ ИЗМЕРЕНО за измеренное — ровно та
    подмена, против которой весь ряд ADR-459…462."""
    out = measured()
    outcomes = out["field_step_outcomes"]
    assert out["resolved_by_field_step"] == (outcomes[ONE_STEP_SPLITS]
                                             + outcomes[ONE_STEP_WHOLESALE])
    assert out["still_unmeasured"] == outcomes[ONE_STEP_UNRESOLVED]
    assert sum(outcomes.values()) == out["population"]


def test_every_unresolved_row_carries_a_named_reason():
    """Третий исход без имени причины — это «не измерено», выданное за
    остаток: чинятся причины разным, и безымянную чинить нечем."""
    out = measured()
    named = sum(out["unresolved_reasons"].values())
    assert named == out["still_unmeasured"], out["unresolved_reasons"]


# ---------------------------------------------------------------------------
# 9. ДВА ЧИСЛА ЖИВОСТИ И КОНТРОЛЬ ПРАВИЛА — добавлено циклом #684
#
# Обе проверки ниже написаны по ИЗМЕРЕННЫМ выжившим мутациям, а не «на всякий
# случай»: полный прогон батареи (26 мутаций, впервые доведённый до конца)
# дал 23 убитых и 3 выживших, и все три сидели на свойствах, которые ADR-463
# объявляет главными, а батарея не защищала ни одним тестом.
# ---------------------------------------------------------------------------

def _scene_root(tmp_path, source: str) -> Path:
    """Корень-однодневка с ОДНИМ счётчиком в сканируемом каталоге.

    Числа живости считает только :func:`container_counter_field_step` целиком,
    поэтому сцена подаётся ему так же, как живое дерево: через файл в
    ``spa_core/monitoring``. Разбирать сцену в обход прибора значило бы
    проверять не тот путь, которым идёт замер.
    """
    scanned = tmp_path / census.OPEN_COUNTER_DIRS[0]
    scanned.mkdir(parents=True)
    (scanned / "scene.py").write_text(source, encoding="utf-8")
    return tmp_path


def test_reached_and_parsed_are_TWO_numbers_and_the_gap_between_them_is_real(
        tmp_path):
    """«Дошёл до зовущего» и «разобрал там ЧИТАТЕЛЯ» — разные достижения.

    ADR-463 держит их врозь (`next_scope_reached` 20 против
    `reader_parsed_at_next_scope` 4) и прямо говорит, что одно число на оба
    выдало бы ПОЛОВИНУ проводки за целую. Свойство было объявлено в тексте и
    не защищено ничем: мутация «два числа живости слиты в одно»
    (``parsed = reached``) ВЫЖИЛА у полной батареи цикла #684, потому что
    соседний тест требовал лишь ``parsed <= reached`` и ``parsed > 0`` — под
    слиянием верно и то, и другое.

    Сцена: счётчик уезжает полем `tally`, доходит до зовущего, а зовущий
    читает ДРУГОЕ поле. Это ровно класс `next_scope_never_reads_that_field` —
    единственный, которым два числа и различаются (20 = 4 + 16).
    """
    root = _scene_root(tmp_path,
                       "def tally(rows):\n" + COUNTER +
                       "    return {'tally': counts, 'tally_n': len(rows)}\n"
                       "def verdict(rows):\n"
                       "    got = tally(rows)\n"
                       "    return got['tally_n']\n")
    out = container_counter_field_step(root, neighbour())
    assert out["status"] == "MEASURED", out
    assert out["unresolved_reasons"][FIELD_GAP_FIELD_NEVER_READ] == 1
    assert out["next_scope_reached"] == 1
    assert out["reader_parsed_at_next_scope"] == 0, (
        "счётчик дошёл до области зовущего, но читателя там не разобрали — "
        "слить это с «разобрал» значит объявить проводку целой по половине")


def test_reached_and_parsed_agree_when_the_reader_IS_parsed(tmp_path):
    """Вторая половина того же контроля: там, где читатель РАЗОБРАН, числа
    обязаны совпасть. Без этой половины тест выше проходил бы и у правила,
    которое `parsed` всегда обнуляет, — то есть доказывал бы не разность
    двух чисел, а сломанность второго."""
    root = _scene_root(tmp_path,
                       "def tally(rows):\n" + COUNTER +
                       "    return {'tally': counts}\n"
                       "def verdict(rows):\n"
                       "    got = tally(rows)\n"
                       "    return got['tally'].get('COVERED', 0)\n")
    out = container_counter_field_step(root, neighbour())
    assert out["status"] == "MEASURED", out
    assert out["next_scope_reached"] == 1
    assert out["reader_parsed_at_next_scope"] == 1


def test_control_REFUSES_when_only_two_of_three_forms_reach_a_split_reader(
        monkeypatch):
    """Контроль обязан требовать ВСЕ три формы переноса, а не «хотя бы две».

    Мутация «контроль: довольно ДВУХ форм из трёх»
    (``len(split) != len(_FIELD_FORMS)`` → ``len(split) < 2``) ВЫЖИЛА у полной
    батареи #684. Вердикт `passed` она не меняет — следующее звено ловит
    недостачу по формам, — но меняет ИМЯ отказа, а весь ряд ADR-459…463 стои́т
    на том, что отказы обязаны называться разным: контроль, промахнувшийся по
    форме, обязан сказать «довёл до расколотого читателя 2 из 3», а не
    «раскол доказан формами». Починка своего имени — разная, и безымянную
    чинить нечем.

    Сцена — положительный контроль прибора, у которого ТРЕТЬЯ форма
    (подписка) перестаёт доходить до читателя: счётчиков по-прежнему три,
    расколов два.
    """
    two_of_three = FIELD_STEP_CONTROL_SOURCE.replace(
        '    made = filed(rows)\n    return made["kept"][REACH_LIVE] > 0\n',
        '    made = filed(rows)\n    return made["filed_n"]\n')
    assert two_of_three != FIELD_STEP_CONTROL_SOURCE, (
        "замена не применилась — сцена контроля изменилась, и тест проверял "
        "бы НЕ ТО (третий исход, а не отрицательный контроль)")
    monkeypatch.setattr(census, "FIELD_STEP_CONTROL_SOURCE", two_of_three)
    verdict = census._field_step_control()
    assert verdict["passed"] is False
    assert "довёл до расколотого читателя 2 из 3" in verdict["reason"], verdict
