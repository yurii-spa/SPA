"""Заказ G82 п. 1 — шаг, признающий ЗАЩИТНЫЙ ХВОСТ ``or {}`` частью связывания.

ADR-466 ответил на заказ G81 числом СЕМЬ из 16 и назвал главным содержанием
замера не число, а ИМЯ: восемь отказов из девяти были свалены в «отдано без
имени», и это имя оказалось ложным у всех восьми. Самый дешёвый из разведённых
классов — защитный хвост ``ext = observed(doc, "by_extension", kind=dict)
or {}``: значение имя ПОЛУЧАЕТ, просто на узел позже. Заказ G82 п. 1 спросил
числом, сколько из пяти таких разрешает шаг, признающий хвост частью
связывания; потребовал назвать односторонность ЗАРАНЕЕ и ограничить её ЗВЕНОМ
(хвост защитен только слева от ``or``); и потребовал, чтобы девятый живой
случай — хвост, результат которого пробегают целиком, — получил СВОЁ имя, а не
попал в чужое.

Каждый тест здесь положительный контроль: он воспроизводит либо форму уже
случившегося дефекта (выдать НЕ ИЗМЕРЕНО за измеренный исход · доказать вред
совпадением имён · разрешить счётчик по ИЗМЕРЕННОЙ половине · соврать в имени
отказа · объявить имя, которого шаг выдать не может), либо форму, которую
правило ОБЯЗАНО не спутать с другой.

**Три числа, которые набор держит РАЗДЕЛЬНО:** «дошёл до читателя, и читатель
делит класс» · «дошёл, и он безвреден» · «не дошёл» — и у каждой причины
недохода СВОЁ машинное имя, потому что чинятся они разным.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from spa_core.monitoring import rule_second_copy_census as census
from spa_core.monitoring.rule_second_copy_census import (
    BOUND_GAP_MANY_NAMES,
    BOUND_GAP_OR_TAIL,
    BOUND_GAP_PRINTED_WHOLE,
    BOUND_GAP_REBOUND,
    BOUND_GAP_UNBOUND,
    DOC_READ_GET,
    DOC_READ_OBSERVED,
    DOC_READ_SUBSCRIPT,
    ONE_STEP_SPLITS,
    ONE_STEP_UNRESOLVED,
    ONE_STEP_WHOLESALE,
    READER_GAP_DYNAMIC,
    STEP_GAP_ESCAPES_AGAIN,
    STEP_GAP_NO_READ,
    TAIL_CONTROL_CLEAN,
    TAIL_CONTROL_SOURCE,
    TAIL_GAP_RESULT_UNBOUND,
    TAIL_GAP_RIGHT_OPERAND,
    UNMEASURED_TAIL_CONTROL,
    UNMEASURED_TAIL_NEIGHBOUR,
    UNMEASURED_TAIL_POPULATION,
    _DOC_READ_FORMS,
    _TAIL_GAPS,
    _defensive_tail_binding,
    _defensive_tail_control,
    _defensive_tail_sites,
    _tail_name_of_escape,
    defensive_tail_binding,
)

# --- материал ---------------------------------------------------------------


def _scene(field: str, reader: str, *, head: str = "", extra: str = "") -> str:
    """Сцена, попадающая в население шага.

    Зовущий обязан быть и обязан НЕ читать поле — иначе счётчик разрешил бы
    сосед (шаг переноса полем), и сцена мерила бы чужое правило. Читатель
    стои́т в ТРЕТЬЕЙ области, до которой от писателя нет ни одного вызова:
    ровно так выглядит живой случай.
    """
    return f'''
REACH_LIVE = "live"
{head}

def writer(rows):
    counts = {{}}
    for row in rows:
        cls = str(row.get("reach"))
        counts[cls] = counts.get(cls, 0) + 1
    return {{"{field}": counts}}


def caller(rows):
    doc = writer(rows)
    return len(doc)


{reader}
{extra}
'''


#: Лишний счётчик отрицательной сцены: имя отказа у него НЕ новое, поэтому
#: проверку имён он пройдёт — его ловит только счёт строк.
EXTRA_REFUSED_COUNTER = """

def zz_writer(rows):
    counts = {}
    for row in rows:
        cls = str(row.get("reach"))
        counts[cls] = counts.get(cls, 0) + 1
    return {"zz": counts}


def zz_caller(rows):
    doc = zz_writer(rows)
    return len(doc)


def zz_reader(doc):
    return audit(doc["zz"])
"""

#: Лишний счётчик положительной сцены: форма чтения у него НЕ новая, поэтому
#: проверку форм он пройдёт — его ловит только счёт строк.
EXTRA_SPLIT_COUNTER = """

def yy_writer(rows):
    counts = {}
    for row in rows:
        cls = str(row.get("reach"))
        counts[cls] = counts.get(cls, 0) + 1
    return {"yy": counts}


def yy_caller(rows):
    doc = yy_writer(rows)
    return len(doc)


def yy_reader(doc):
    c = doc["yy"] or {}
    return c[REACH_LIVE] > 0
"""


def _rows(src: str) -> list:
    return _defensive_tail_sites("<t>", ast.parse(src))


def _one(src: str) -> dict:
    rows = _rows(src)
    assert len(rows) == 1, [
        (r["owner"], r["tail_step"], r["tail_gap"]) for r in rows]
    return rows[0]


def _neighbour(behind_tail: int, unnamed: int = 0) -> dict:
    return {"status": "MEASURED",
            "unresolved_reasons": {BOUND_GAP_OR_TAIL: behind_tail,
                                   BOUND_GAP_UNBOUND: unnamed}}


def _tree(tmp_path: Path, *scenes: str) -> Path:
    root = tmp_path / "tree"
    (root / "spa_core" / "monitoring").mkdir(parents=True)
    (root / "scripts").mkdir(parents=True)
    for idx, src in enumerate(scenes):
        (root / "spa_core" / "monitoring" / f"scene{idx}.py").write_text(
            src, encoding="utf-8")
    return root


# --- ЗВЕНО 1: хвост признан частью связывания -------------------------------


def test_subscript_read_behind_a_tail_is_resolved():
    row = _one(_scene("f", '''
def reader(doc):
    c = doc["f"] or {}
    return c[REACH_LIVE] > 0
'''))
    assert row["tail_step"] == ONE_STEP_SPLITS
    assert row["tail_names"] == ["c"]
    assert row["bound_gap"] == BOUND_GAP_OR_TAIL


def test_get_read_behind_a_tail_is_resolved():
    row = _one(_scene("f", '''
def reader(doc):
    c = doc.get("f") or {}
    return c.get(REACH_LIVE, 0) > 0
'''))
    assert row["tail_step"] == ONE_STEP_SPLITS
    assert DOC_READ_GET in row["read_forms"]


def test_observed_read_behind_a_tail_is_resolved():
    row = _one(_scene("f", '''
def reader(doc):
    c = observed(doc, "f", kind=dict) or {}
    return c[REACH_LIVE] > 0
'''))
    assert row["tail_step"] == ONE_STEP_SPLITS
    assert DOC_READ_OBSERVED in row["read_forms"]


def test_annotated_binding_behind_a_tail_is_a_binding_too():
    row = _one(_scene("f", '''
def reader(doc):
    c: dict = doc["f"] or {}
    return c[REACH_LIVE] > 0
'''))
    assert row["tail_step"] == ONE_STEP_SPLITS


def test_a_longer_or_chain_still_binds_when_we_are_first():
    """``doc["f"] or other or {}`` — наше чтение по-прежнему ПЕРВЫЙ операнд."""
    row = _one(_scene("f", '''
def reader(doc, other):
    c = doc["f"] or other or {}
    return c[REACH_LIVE] > 0
'''))
    assert row["tail_step"] == ONE_STEP_SPLITS
    assert row["tail_names"] == ["c"]


# --- ОДНОСТОРОННОСТЬ: хвост защитен ТОЛЬКО слева ----------------------------


def test_read_on_the_right_of_or_is_refused_though_the_split_is_ready():
    """Главное ограничение шага, объявленное ЗАРАНЕЕ.

    ``c = other or doc["f"]`` при истинном ``other`` оставляет в ``c`` ЧУЖОЕ
    значение. Раскол внизу ГОТОВ, и засчитать его значило бы доказать вред
    СОВПАДЕНИЕМ ИМЁН — ровно тот дефект, против которого ADR-465 и ADR-466
    завели свои звенья.
    """
    row = _one(_scene("f", '''
def reader(doc, other):
    c = other or doc["f"]
    return c[REACH_LIVE] > 0
'''))
    assert row["tail_step"] == ONE_STEP_UNRESOLVED
    assert row["tail_gap"] == TAIL_GAP_RIGHT_OPERAND


def test_the_mirror_scene_differing_only_by_the_side_does_find_the_split():
    """Отрицательная половина без этой сцены доказывала бы не то.

    Сцены отличаются РОВНО стороной операнда; разный исход и есть
    доказательство, что звено меряет сторону, а не что-то другое.
    """
    row = _one(_scene("f", '''
def reader(doc, other):
    c = doc["f"] or other
    return c[REACH_LIVE] > 0
'''))
    assert row["tail_step"] == ONE_STEP_SPLITS


def test_right_operand_is_named_before_the_tail_when_both_occur():
    """Смешанная форма зовётся САМЫМ ДОРОГИМ пределом, а не первым попавшимся."""
    row = _one(_scene("f", '''
def reader(doc, other):
    a = doc["f"] or {}
    b = other or doc["f"]
    return a[REACH_LIVE] + b[REACH_LIVE]
'''))
    assert row["tail_gap"] == TAIL_GAP_RIGHT_OPERAND


def test_and_is_not_an_or_tail():
    """``doc["f"] and {}`` защитным хвостом НЕ является: значение другое."""
    row = _one(_scene("f", '''
def reader(doc):
    c = doc["f"] and {}
    return c[REACH_LIVE] > 0
'''))
    assert row["tail_step"] == ONE_STEP_UNRESOLVED
    assert row["tail_gap"] == BOUND_GAP_UNBOUND


# --- ДЕВЯТЫЙ ЖИВОЙ СЛУЧАЙ: хвост без имени ----------------------------------


def test_tail_walked_whole_gets_its_own_name_not_the_unbound_one():
    """Ровно живой случай ``(ax.get("transitions") or {}).items()``.

    До этого шага такая строка попадала в ЧУЖОЕ имя «отдано без имени», то
    есть посылала строить МЕЖПРОЦЕДУРНЫЙ разбор там, где значение вообще не
    покидает выражения. Имя отказа и есть указание, что чинить.
    """
    row = _one(_scene("f", '''
def reader(doc):
    for key, n in (doc["f"] or {}).items():
        report(key, n)
'''))
    assert row["tail_step"] == ONE_STEP_UNRESOLVED
    assert row["tail_gap"] == TAIL_GAP_RESULT_UNBOUND
    assert row["tail_gap"] != BOUND_GAP_UNBOUND


def test_tail_handed_into_a_call_is_also_the_tail_name_not_unbound():
    row = _one(_scene("f", '''
def reader(doc):
    return audit(doc["f"] or {})
'''))
    assert row["tail_gap"] == TAIL_GAP_RESULT_UNBOUND


def test_read_handed_into_a_call_without_any_tail_stays_unbound():
    """Сосед назвал это «отдано без имени», и имя ВЕРНО — оно проходит насквозь."""
    row = _one(_scene("f", '''
def reader(doc):
    return audit(doc["f"])
'''))
    assert row["tail_step"] == ONE_STEP_UNRESOLVED
    assert row["tail_gap"] == BOUND_GAP_UNBOUND
    assert row["bound_gap"] == BOUND_GAP_UNBOUND


def test_the_two_unbound_shapes_are_told_apart_by_name():
    """«Хвост без имени» и «отдано в вызов» чинятся РАЗНЫМ — значит имена разные."""
    tail = _one(_scene("f", '''
def reader(doc):
    return audit(doc["f"] or {})
'''))
    plain = _one(_scene("f", '''
def reader(doc):
    return audit(doc["f"])
'''))
    assert tail["tail_gap"] != plain["tail_gap"]


# --- ЗВЕНО 2: у имени ровно один источник -----------------------------------


def test_name_reassigned_from_another_source_is_refused_though_split_is_ready():
    row = _one(_scene("f", '''
def reader(doc, other):
    c = doc["f"] or {}
    if other:
        c = other
    return c[REACH_LIVE] > 0
'''))
    assert row["tail_step"] == ONE_STEP_UNRESOLVED
    assert row["tail_gap"] == BOUND_GAP_REBOUND


def test_single_source_scene_differing_only_by_that_line_does_find_the_split():
    row = _one(_scene("f", '''
def reader(doc, other):
    c = doc["f"] or {}
    return c[REACH_LIVE] > 0
'''))
    assert row["tail_step"] == ONE_STEP_SPLITS


def test_parameter_of_the_same_name_is_a_second_source_behind_a_tail():
    row = _one(_scene("f", '''
def reader(doc, c):
    c = doc["f"] or {}
    return c[REACH_LIVE] > 0
'''))
    assert row["tail_gap"] == BOUND_GAP_REBOUND


def test_two_tails_bound_to_two_names_are_refused_not_chosen():
    row = _one(_scene("f", '''
def reader(doc):
    a = doc["f"] or {}
    b = doc["f"] or {}
    return a[REACH_LIVE] + b[REACH_LIVE]
'''))
    assert row["tail_gap"] == BOUND_GAP_MANY_NAMES


def test_partly_bound_read_is_not_resolved_by_its_measured_half():
    """Половина уехала в вызов, половина связана хвостом — разрешить нельзя."""
    row = _one(_scene("f", '''
def reader(doc):
    c = doc["f"] or {}
    audit(doc["f"])
    return c[REACH_LIVE] > 0
'''))
    assert row["tail_step"] == ONE_STEP_UNRESOLVED
    assert row["tail_gap"] == BOUND_GAP_UNBOUND


# --- ЗВЕНО 3: читатель имени — правило СОСЕДСКОЕ ----------------------------


def test_tail_name_escaping_again_is_refused_by_the_neighbour_name():
    row = _one(_scene("f", '''
def reader(doc):
    c = doc["f"] or {}
    return c
'''))
    assert row["tail_gap"] == STEP_GAP_ESCAPES_AGAIN


def test_tail_name_read_by_a_dynamic_key_is_refused():
    row = _one(_scene("f", '''
def reader(doc, key):
    c = doc["f"] or {}
    return c[key] > 0
'''))
    assert row["tail_gap"] == READER_GAP_DYNAMIC


def test_tail_name_never_read_is_refused():
    row = _one(_scene("f", '''
def reader(doc):
    c = doc["f"] or {}
    return len(doc)
'''))
    assert row["tail_gap"] == STEP_GAP_NO_READ


def test_tail_name_used_wholesale_is_benign_not_a_split():
    """Третий исход отделён от отказа: безвредный читатель ИЗМЕРЕН."""
    row = _one(_scene("f", '''
def reader(doc):
    c = doc["f"] or {}
    return sum(c.values())
'''))
    assert row["tail_step"] == ONE_STEP_WHOLESALE
    assert row["tail_gap"] is None


def test_split_at_one_reader_proves_the_counter_though_another_refuses():
    row = _one(_scene("f", '''
def reader(doc):
    c = doc["f"] or {}
    return c[REACH_LIVE] > 0
''', extra='''

def second_reader(doc, key):
    c = doc["f"] or {}
    return c[key]
'''))
    assert row["tail_step"] == ONE_STEP_SPLITS


def test_refusal_at_any_reader_keeps_the_counter_unmeasured_without_a_split():
    row = _one(_scene("f", '''
def reader(doc):
    c = doc["f"] or {}
    return sum(c.values())
''', extra='''

def second_reader(doc, key):
    c = doc["f"] or {}
    return c[key]
'''))
    assert row["tail_step"] == ONE_STEP_UNRESOLVED


# --- ГРАНИЦА НАСЕЛЕНИЯ ------------------------------------------------------


def test_counter_printed_whole_is_not_in_the_population_at_all():
    """ЧУЖОЙ потолок (ADR-462): прибор соседа здесь не чинится его населением."""
    assert _rows(_scene("f", '''
def reader(doc):
    return f"{doc['f']}"
''')) == []


def test_counter_the_neighbour_already_resolved_is_not_in_the_population():
    assert _rows(_scene("f", '''
def reader(doc):
    c = doc["f"]
    return c[REACH_LIVE] > 0
''')) == []


def test_counter_bound_to_two_plain_names_stays_with_the_neighbour():
    """Сосед отказал ИМЕНАМИ, а не хвостом — это не наше население."""
    assert _rows(_scene("f", '''
def reader(doc):
    a = doc["f"]
    b = doc["f"]
    return a[REACH_LIVE] + b[REACH_LIVE]
''')) == []


def test_counter_with_no_reader_of_the_field_is_not_in_the_population():
    assert _rows(_scene("f", '''
def reader(doc):
    return len(doc)
''')) == []


# --- помощник классификации, в том числе НЕДОСТИЖИМАЯ через шаг ветка -------


def _escape_and_parents(src: str):
    tree = ast.parse(src)
    parents = census._parent_map(tree)
    node = next(n for n in ast.walk(tree)
                if isinstance(n, ast.Subscript)
                and isinstance(n.value, ast.Name) and n.value.id == "doc")
    return node, parents


def test_tail_name_of_escape_names_the_printed_branch_when_reached_directly():
    """Ветка ВЕРНА, но через шаг недостижима — проверяется ПРЯМЫМ вызовом.

    Ровно тем порядком ADR-466 закрыл свою недостижимую ветку: имя, которое
    шаг выдать не может, объявлять в перечне нельзя, но и оставлять его
    непроверенным — значит держать в приборе строку, не видевшую ни одного
    контроля.
    """
    node, parents = _escape_and_parents('v = f"{doc[\'f\']}"')
    assert _tail_name_of_escape(node, parents) == (None,
                                                   BOUND_GAP_PRINTED_WHOLE)


def test_tail_name_of_escape_names_a_plain_assignment():
    node, parents = _escape_and_parents('c = doc["f"]')
    assert _tail_name_of_escape(node, parents) == ("c", None)


def test_tail_name_of_escape_names_the_tail_target():
    node, parents = _escape_and_parents('c = doc["f"] or {}')
    assert _tail_name_of_escape(node, parents) == ("c", None)


def test_tail_name_of_escape_refuses_the_right_operand():
    node, parents = _escape_and_parents('c = other or doc["f"]')
    assert _tail_name_of_escape(node, parents) == (None,
                                                   TAIL_GAP_RIGHT_OPERAND)


def test_tail_name_of_escape_refuses_an_unbound_tail():
    node, parents = _escape_and_parents('audit((doc["f"] or {}).items())')
    assert _tail_name_of_escape(node, parents) == (None,
                                                   TAIL_GAP_RESULT_UNBOUND)


def test_printed_whole_is_not_among_the_declared_names():
    """Объявленное имя есть ОБЕЩАНИЕ разбора; недостижимому здесь не место."""
    assert BOUND_GAP_PRINTED_WHOLE not in _TAIL_GAPS


# --- правило соседа НЕ переписано -------------------------------------------


def test_neighbour_verdict_passes_through_untouched(monkeypatch):
    """Вердикт, которому сосед НЕ отказывал хвостом, наш шаг не переписывает."""
    seen = []
    original = census._binding_of_read

    def spy(scope, read):
        out = original(scope, read)
        seen.append(out["gap"])
        return out

    monkeypatch.setattr(census, "_binding_of_read", spy)
    _defensive_tail_binding(ast.parse("c = doc['f']"),
                            next(n for n in ast.walk(ast.parse("c = doc['f']"))
                                 if isinstance(n, ast.Subscript)))
    assert seen, "вердикт соседа не спрошен — правило связывания скопировано"


def test_escape_rule_is_the_neighbours_not_a_second_copy(monkeypatch):
    called = []
    original = census._escape_sites
    monkeypatch.setattr(census, "_escape_sites",
                        lambda s, t: called.append(1) or original(s, t))
    _rows(_scene("f", '''
def reader(doc):
    c = doc["f"] or {}
    return c[REACH_LIVE] > 0
'''))
    assert called, "правило побега не спрошено у соседа — это вторая копия"


def test_reader_rule_is_the_neighbours_not_a_second_copy(monkeypatch):
    called = []
    original = census._one_step_reader
    monkeypatch.setattr(census, "_one_step_reader",
                        lambda s, t, d: called.append(1) or original(s, t, d))
    _rows(_scene("f", '''
def reader(doc):
    c = doc["f"] or {}
    return c[REACH_LIVE] > 0
'''))
    assert called, "правило читателя не спрошено у соседа — это вторая копия"


def test_source_count_rule_is_the_neighbours_not_a_second_copy(monkeypatch):
    called = []
    original = census._name_binding_sources
    monkeypatch.setattr(census, "_name_binding_sources",
                        lambda s, n: called.append(1) or original(s, n))
    _rows(_scene("f", '''
def reader(doc):
    c = doc["f"] or {}
    return c[REACH_LIVE] > 0
'''))
    assert called, "счёт источников имени не спрошен у соседа"


# --- КОНТРОЛЬ обеими половинами ---------------------------------------------


def test_control_passes_on_the_declared_scenes():
    assert _defensive_tail_control()["passed"] is True


def test_positive_scene_proves_all_three_read_forms_behind_a_tail():
    rows = _defensive_tail_sites("<c>", ast.parse(TAIL_CONTROL_SOURCE))
    forms = sorted({f for r in rows for f in r["read_forms"]})
    assert forms == sorted(_DOC_READ_FORMS)
    assert all(r["tail_step"] == ONE_STEP_SPLITS for r in rows)


def test_negative_scene_yields_every_declared_name_and_one_benign():
    rows = _defensive_tail_sites("<c>", ast.parse(TAIL_CONTROL_CLEAN))
    refused = [r for r in rows if r["tail_step"] == ONE_STEP_UNRESOLVED]
    assert sorted({r["tail_gap"] for r in refused}) == sorted(_TAIL_GAPS)
    assert [r for r in rows if r["tail_step"] == ONE_STEP_WHOLESALE]


def test_negative_scene_carries_two_ready_splits_the_rule_must_not_count():
    rows = _defensive_tail_sites("<c>", ast.parse(TAIL_CONTROL_CLEAN))
    ready = {r["tail_gap"] for r in rows
             if r["tail_gap"] in (TAIL_GAP_RIGHT_OPERAND, BOUND_GAP_REBOUND)}
    assert ready == {TAIL_GAP_RIGHT_OPERAND, BOUND_GAP_REBOUND}


def test_negative_scene_excludes_the_printed_counter_from_the_population():
    rows = _defensive_tail_sites("<c>", ast.parse(TAIL_CONTROL_CLEAN))
    assert "prn" not in {r.get("field") for r in rows}


def test_control_fails_when_the_positive_scene_loses_a_read_form(monkeypatch):
    shrunk = TAIL_CONTROL_SOURCE.replace(
        'c = observed(doc, "gamma", kind=dict) or {}',
        'c = doc["gamma"] or {}')
    monkeypatch.setattr(census, "TAIL_CONTROL_SOURCE", shrunk)
    out = _defensive_tail_control()
    assert out["passed"] is False
    assert "форм" in out["reason"] or "формы" in out["reason"]


def test_control_fails_when_a_refusal_name_disappears(monkeypatch):
    shrunk = TAIL_CONTROL_CLEAN.replace(
        "    c = other or doc[\"right\"]\n",
        "    c = doc[\"right\"] or {}\n")
    monkeypatch.setattr(census, "TAIL_CONTROL_CLEAN", shrunk)
    assert _defensive_tail_control()["passed"] is False


def test_control_fails_when_the_benign_reader_disappears(monkeypatch):
    shrunk = TAIL_CONTROL_CLEAN.replace(
        "    return sum(c.values())", "    return c[REACH_LIVE] > 0")
    monkeypatch.setattr(census, "TAIL_CONTROL_CLEAN", shrunk)
    out = _defensive_tail_control()
    assert out["passed"] is False


def test_control_fails_when_a_printed_counter_enters_the_population(monkeypatch):
    """Граница населения проверяется ОТДЕЛЬНО от перечня имён.

    Перечень имён молчит и тогда, когда чужой счётчик взят, но назван чужим
    именем, — поэтому граница обязана иметь свой отказ.
    """
    widened = TAIL_CONTROL_CLEAN.replace(
        '    return f"{doc[\'prn\']}"',
        '    c = doc["prn"] or {}\n    return c[REACH_LIVE] > 0')
    monkeypatch.setattr(census, "TAIL_CONTROL_CLEAN", widened)
    out = _defensive_tail_control()
    assert out["passed"] is False
    assert "потолок" in out["reason"]


def test_unparsable_control_scene_is_a_refusal_not_a_pass(monkeypatch):
    monkeypatch.setattr(census, "TAIL_CONTROL_SOURCE", "def (:")
    out = _defensive_tail_control()
    assert out["passed"] is False
    assert "не разобрана" in out["reason"]


# --- ТРЕТИЙ ИСХОД у самого шага ---------------------------------------------


def test_absent_neighbour_is_unmeasured_not_zero(tmp_path):
    out = defensive_tail_binding(_tree(tmp_path), None)
    assert out["status"] == "UNMEASURED"
    assert out["unmeasured_class"] == UNMEASURED_TAIL_NEIGHBOUR


def test_unmeasured_neighbour_is_unmeasured(tmp_path):
    out = defensive_tail_binding(_tree(tmp_path), {"status": "UNMEASURED"})
    assert out["status"] == "UNMEASURED"
    assert out["unmeasured_class"] == UNMEASURED_TAIL_NEIGHBOUR


def test_neighbour_without_the_tail_key_is_unmeasured(tmp_path):
    out = defensive_tail_binding(
        _tree(tmp_path),
        {"status": "MEASURED",
         "unresolved_reasons": {BOUND_GAP_UNBOUND: 0}})
    assert out["unmeasured_class"] == UNMEASURED_TAIL_NEIGHBOUR


def test_neighbour_without_the_unbound_key_is_unmeasured(tmp_path):
    """Оба ключа обязательны: население шага есть СУММА двух отказов."""
    out = defensive_tail_binding(
        _tree(tmp_path),
        {"status": "MEASURED",
         "unresolved_reasons": {BOUND_GAP_OR_TAIL: 1}})
    assert out["unmeasured_class"] == UNMEASURED_TAIL_NEIGHBOUR


def test_population_mismatch_is_unmeasured_not_a_number(tmp_path):
    root = _tree(tmp_path, _scene("f", '''
def reader(doc):
    c = doc["f"] or {}
    return c[REACH_LIVE] > 0
'''))
    out = defensive_tail_binding(root, _neighbour(9))
    assert out["status"] == "UNMEASURED"
    assert out["unmeasured_class"] == UNMEASURED_TAIL_POPULATION
    assert out["population"] == 1 and out["declared_population"] == 9


def test_failed_control_makes_the_whole_step_unmeasured(tmp_path, monkeypatch):
    monkeypatch.setattr(census, "TAIL_CONTROL_SOURCE", "def (:")
    out = defensive_tail_binding(_tree(tmp_path), _neighbour(0))
    assert out["unmeasured_class"] == UNMEASURED_TAIL_CONTROL


def test_missing_directory_is_named_not_silently_skipped(tmp_path):
    root = tmp_path / "bare"
    root.mkdir()
    out = defensive_tail_binding(root, _neighbour(0))
    assert out["status"] == "UNMEASURED"
    assert out["unmeasured_class"] == UNMEASURED_TAIL_POPULATION


def test_unparsable_file_is_named_not_silently_skipped(tmp_path):
    root = _tree(tmp_path)
    (root / "spa_core" / "monitoring" / "broken.py").write_text(
        "def (:", encoding="utf-8")
    out = defensive_tail_binding(root, _neighbour(0))
    assert out["status"] == "UNMEASURED"
    assert out["files_unreadable"]


# --- ИЗМЕРЕННЫЙ шаг ---------------------------------------------------------


def _measured(tmp_path: Path, *scenes: str, behind: int, unnamed: int = 0):
    return defensive_tail_binding(_tree(tmp_path, *scenes),
                                  _neighbour(behind, unnamed))


def test_measured_step_counts_both_outcomes_and_every_refusal_name(tmp_path):
    out = _measured(
        tmp_path,
        _scene("a", '''
def reader(doc):
    c = doc["a"] or {}
    return c[REACH_LIVE] > 0
'''),
        _scene("b", '''
def reader(doc):
    c = doc["b"] or {}
    return sum(c.values())
'''),
        _scene("c", '''
def reader(doc, other):
    c = other or doc["c"]
    return c[REACH_LIVE] > 0
'''),
        behind=3)
    assert out["status"] == "MEASURED"
    assert out["tail_step_outcomes"][ONE_STEP_SPLITS] == 1
    assert out["tail_step_outcomes"][ONE_STEP_WHOLESALE] == 1
    assert out["tail_step_outcomes"][ONE_STEP_UNRESOLVED] == 1
    assert out["unresolved_reasons"][TAIL_GAP_RIGHT_OPERAND] == 1
    assert out["resolved_by_defensive_tail_step"] == 2


def test_population_is_the_sum_of_two_neighbour_refusals(tmp_path):
    """Без ВТОРОГО ключа девятый живой случай остался бы под чужим именем."""
    out = _measured(
        tmp_path,
        _scene("a", '''
def reader(doc):
    c = doc["a"] or {}
    return c[REACH_LIVE] > 0
'''),
        _scene("b", '''
def reader(doc):
    return audit(doc["b"])
'''),
        behind=1, unnamed=1)
    assert out["status"] == "MEASURED"
    assert out["population"] == 2
    assert out["population_behind_a_tail"] == 1
    assert out["population_unnamed_by_the_neighbour"] == 1


def test_two_liveness_numbers_are_kept_apart(tmp_path):
    """Сцена, где числа РАЗНЫЕ: подмену одного другим ловит только она."""
    out = _measured(
        tmp_path,
        _scene("a", '''
def reader(doc):
    c = doc["a"] or {}
    return c[REACH_LIVE] > 0
'''),
        _scene("b", '''
def reader(doc, other):
    c = doc["b"] or {}
    if other:
        c = other
    return c[REACH_LIVE] > 0
'''),
        behind=2)
    assert out["read_value_bound_behind_a_tail"] == 2
    assert out["tail_name_single_source"] == 1


def test_harm_sample_names_file_line_counter_field_and_bound_name(tmp_path):
    out = _measured(tmp_path, _scene("a", '''
def reader(doc):
    c = doc["a"] or {}
    return c[REACH_LIVE] > 0
'''), behind=1)
    item = out["harm_sample"][0]
    assert item["field"] == "a" and item["bound"] == "c"
    assert item["line"] and item["file"].endswith(".py")
    assert "REACH_LIVE" in item["split"]


def test_unresolved_sample_names_the_refusal(tmp_path):
    out = _measured(tmp_path, _scene("a", '''
def reader(doc):
    for key, n in (doc["a"] or {}).items():
        report(key, n)
'''), behind=1)
    assert out["unresolved_sample"][0]["gap"] == TAIL_GAP_RESULT_UNBOUND


def test_step_is_advisory_and_says_so(tmp_path):
    out = _measured(tmp_path, behind=0)
    assert out["applied"] is False
    assert out["order"] == "G82.1"


def test_blind_spots_are_named_not_implied(tmp_path):
    out = _measured(tmp_path, behind=0)
    blind = " ".join(out["blind"])
    assert TAIL_GAP_RIGHT_OPERAND in blind
    assert TAIL_GAP_RESULT_UNBOUND in blind


# --- отрисовка --------------------------------------------------------------


def test_report_says_unmeasured_when_the_step_is_absent():
    lines = census.report({"status": "CLEAN"})
    assert any("[ЗА ЗАЩИТНЫМ ХВОСТОМ] НЕ ИЗМЕРЕНО" in ln for ln in lines)


def test_report_names_unmeasured_class_of_the_step():
    lines = census.report({"status": "CLEAN", "defensive_tail_binding": {
        "status": "UNMEASURED", "unmeasured_class": UNMEASURED_TAIL_POPULATION,
        "reason": "две дороги разошлись"}})
    assert any(UNMEASURED_TAIL_POPULATION in ln for ln in lines)


def test_report_prints_both_liveness_numbers_and_the_split(tmp_path):
    out = _measured(tmp_path, _scene("a", '''
def reader(doc):
    c = doc["a"] or {}
    return c[REACH_LIVE] > 0
'''), behind=1)
    lines = census.report({"status": "CLEAN", "defensive_tail_binding": out})
    text = "\n".join(lines)
    assert "ПРОВОДКА ЖИВА" in text
    assert "РАСКОЛ" in text
    assert "КОНТРОЛЬ" in text


def test_report_separates_the_tail_names_in_the_why_line(tmp_path):
    out = _measured(tmp_path, _scene("a", '''
def reader(doc):
    for key, n in (doc["a"] or {}).items():
        report(key, n)
'''), behind=1)
    lines = census.report({"status": "CLEAN", "defensive_tail_binding": out})
    text = "\n".join(lines)
    assert "ПОЧЕМУ НЕ ДОШЁЛ" in text
    assert "ПРАВЫЙ" in text


def test_measure_wires_the_step_under_its_own_key():
    import inspect
    src = inspect.getsource(census.measure)
    assert "defensive_tail_binding(root, bound_step)" in src
    assert '"defensive_tail_binding": tail_step' in src


@pytest.mark.parametrize("gap", _TAIL_GAPS)
def test_every_declared_refusal_name_is_reachable(gap):
    """Имя, которого шаг выдать не может, есть обещание разбора, которого нет."""
    rows = _defensive_tail_sites("<c>", ast.parse(TAIL_CONTROL_CLEAN))
    assert gap in {r["tail_gap"] for r in rows}


# --- контроли НА КОНТРОЛЬ: закрыты мутациями, пережившими первый прогон -----


def test_dearest_limit_is_named_first_when_call_and_tail_mix():
    """Порядок имён — УТВЕРЖДЕНИЕ, а не косметика.

    Мутация, переставившая «хвост без имени» вперёд «отдано в вызов»,
    пережила первый прогон: ни одна сцена не несла ДВУХ отказов сразу.
    Дороже здесь вызов — он требует межпроцедурного разбора, а хвост
    чинится разбором потребителя на месте.
    """
    row = _one(_scene("f", '''
def reader(doc):
    audit(doc["f"])
    for key, n in (doc["f"] or {}).items():
        report(key, n)
'''))
    assert row["tail_gap"] == BOUND_GAP_UNBOUND


def test_right_operand_is_named_before_the_unbound_tail():
    row = _one(_scene("f", '''
def reader(doc, other):
    a = other or doc["f"]
    for key, n in (doc["f"] or {}).items():
        report(key, n)
'''))
    assert row["tail_gap"] == TAIL_GAP_RIGHT_OPERAND


def test_control_checks_the_NAMES_not_only_how_many_refusals(monkeypatch):
    """Счёт отказов молчит, когда имён стало меньше, а отказов столько же.

    Мутация, снявшая сверку ИМЁН отрицательной сцены, пережила первый
    прогон именно поэтому: все прежние сцены меняли и число. Здесь правый
    операнд подменён вторым «отдано в вызов» — отказов по-прежнему восемь,
    а РАЗНЫХ имён семь, и поймать это может только сверка имён.
    """
    swapped = TAIL_CONTROL_CLEAN.replace(
        '    c = other or doc["right"]\n    return c[REACH_LIVE] > 0',
        '    return audit(doc["right"])')
    assert swapped != TAIL_CONTROL_CLEAN
    monkeypatch.setattr(census, "TAIL_CONTROL_CLEAN", swapped)
    out = _defensive_tail_control()
    assert out["passed"] is False
    assert "именами" in out["reason"]


def test_step_owns_only_the_reads_the_neighbour_refused_by_a_tail():
    """Вердикт соседа спрашивается ПО КАЖДОМУ чтению, а не подменяется оптом.

    Мутация, заменившая вердикт соседа константой, пережила первый прогон:
    на исход она не влияла, но раздувала ПРОВОДКУ — число чтений, которые
    шаг считает своими. У счётчика два чтения, и МОЁ здесь ровно одно.
    """
    # Сцена устроена НЕ произвольно, и это свойство прибора, а не вкус.
    # Чтения в своде идут порядком `ast.walk` (вширь), а защитный хвост по
    # ПОСТРОЕНИЮ лежит на узел ГЛУБЖЕ обычного чтения: `c = doc["f"] or {}`
    # это Assign → BoolOp → Subscript, а `d = doc["f"]` — Assign → Subscript.
    # Поэтому обычное чтение ВСЕГДА обогнало бы хвост, первым неразрешённым
    # оказался бы чужой отказ, и счётчик ушёл бы к соседу, а сцена измерила
    # бы чужое правило. Соседнее чтение здесь вложено в `if` — ровно чтобы
    # глубины сравнялись.
    row = _one(_scene("f", '''
def aa_reader(doc):
    c = doc["f"] or {}
    return c[REACH_LIVE] > 0
''', extra='''

def zz_reader(doc, other):
    if other:
        d = doc["f"]
        if other:
            d = other
        return d[REACH_LIVE] > 0
'''))
    assert row["bound_gap"] == BOUND_GAP_OR_TAIL
    assert row["behind_a_tail"] == 1
    assert row["tail_names"] == ["c"]


def test_skipped_directory_is_not_walked(tmp_path):
    """Обход обязан быть ДОСЛОВНО соседским, иначе сверка мерит не то.

    Две дороги к одному населению, разойдясь правилом ОБХОДА, дают
    расхождение, не имеющее отношения к правилу шага.
    """
    root = _tree(tmp_path)
    archive = root / "scripts" / "archive"
    archive.mkdir(parents=True)
    (archive / "old.py").write_text(_scene("f", '''
def reader(doc):
    c = doc["f"] or {}
    return c[REACH_LIVE] > 0
'''), encoding="utf-8")
    out = defensive_tail_binding(root, _neighbour(0))
    assert out["status"] == "MEASURED"
    assert out["population"] == 0
