"""Заказ G80 п. 1 — разбор ПО ИМЕНИ ПОЛЯ ЧЕРЕЗ ГРАНИЦУ ФУНКЦИИ.

ADR-463 ответил на заказ G79 нулём и назвал ГЛАВНЫМ числом 26 из 53: два имени
отказа — ``next_scope_never_reads_that_field`` (16) и
``returned_value_is_not_bound_to_a_name`` (10) — суть ОДИН класс, названный с
двух сторон. Счётчик кладут в ДОКУМЕНТ, документ возвращают, а поле его читают
не у зовущего, а много позже и другой точкой входа. Заказ G80 п. 1 спросил
числом: сколько из 26 разрешает разбор по имени поля во всём файле и сколько
остаётся третьим исходом; односторонность («нашли читателя ключа ``X``» не есть
«это НАШ счётчик») обязана быть НАЗВАНА и ОГРАНИЧЕНА.

Каждый тест здесь — положительный контроль: он воспроизводит либо форму уже
случившегося дефекта (выдать НЕ ИЗМЕРЕНО за измеренный исход; доказать вред
СОВПАДЕНИЕМ ИМЁН; соврать в имени отказа; знать одну форму чтения из трёх),
либо форму, которую правило ОБЯЗАНО не спутать с другой.

**Три числа, которые набор держит РАЗДЕЛЬНО:** «дошёл до читателя, и читатель
делит класс» · «дошёл, и он безвреден» · «не дошёл» — и у каждой причины
недохода СВОЁ машинное имя, потому что чинятся они разным.
"""

from __future__ import annotations

import ast
from pathlib import Path

from spa_core.monitoring import rule_second_copy_census as census
from spa_core.monitoring.rule_second_copy_census import (
    DOC_GAP_FIELD_WRITTEN_TWICE,
    DOC_GAP_MANY_FIELDS,
    DOC_GAP_NO_READER_IN_FILE,
    DOC_READ_GET,
    DOC_READ_HELPER,
    DOC_READ_OBSERVED,
    DOC_READ_SUBSCRIPT,
    DOC_READER_CONTROL_CLEAN,
    DOC_READER_CONTROL_SOURCE,
    FIELD_GAP_FIELD_NEVER_READ,
    ONE_STEP_SPLITS,
    ONE_STEP_UNRESOLVED,
    ONE_STEP_WHOLESALE,
    READER_GAP_DYNAMIC,
    STEP_GAP_ESCAPES_AGAIN,
    STEP_GAP_RESULT_UNBOUND,
    UNMEASURED_DOC_CONTROL,
    UNMEASURED_DOC_NEIGHBOUR,
    UNMEASURED_DOC_POPULATION,
    _DOC_GAPS,
    _DOC_READ_FORMS,
    _document_field_reads,
    _document_reader_control,
    _document_reader_sites,
    _field_write_scopes,
    _is_declared_reader,
    document_field_reader_in_file,
)

# --- материал ---------------------------------------------------------------


def _rows(src: str) -> list:
    return _document_reader_sites("<t>", ast.parse(src))


def _scene(field: str, extra: str = "", *, head: str = "") -> str:
    """Сцена, попадающая в население: счётчик уезжает полем, зовущий не читает.

    Зовущий обязан быть и обязан НЕ читать поле — иначе счётчик разрешил бы
    сосед (шаг переноса полем), и сцена мерила бы чужое правило.
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

{extra}
'''


def _neighbour(never_read: int = 1, unbound: int = 0) -> dict:
    return {"status": "MEASURED",
            "unresolved_reasons": {FIELD_GAP_FIELD_NEVER_READ: never_read,
                                   STEP_GAP_RESULT_UNBOUND: unbound}}


# --- половины контроля ------------------------------------------------------


def test_positive_control_resolves_every_counter_of_the_scene():
    """Не разрешив СВОЮ известную сцену, правило не вправе говорить о дереве."""
    out = _document_reader_control()
    assert out["passed"] is True, out.get("reason")
    assert out["known_case_resolved"] == len(_DOC_READ_FORMS) + 1


def test_positive_control_proves_all_three_read_forms():
    """Одна форма чтения — половина ответа, выданная за целый."""
    out = _document_reader_control()
    assert out["read_forms"] == sorted(_DOC_READ_FORMS)


def test_positive_scene_actually_carries_all_three_read_forms():
    """Сцена обязана НЕСТИ то, чего требует от правила: иначе контроль вакуумен."""
    rows = _rows(DOC_READER_CONTROL_SOURCE)
    forms = sorted({f for r in rows for f in r["read_forms"]})
    assert forms == sorted(_DOC_READ_FORMS)


def test_negative_control_gives_no_false_splits():
    out = _document_reader_control()
    assert out["clean_false_splits"] == 0


def test_negative_control_separates_four_refusal_names():
    """Отказ, слитый с другим отказом, и есть подмена третьего исхода."""
    out = _document_reader_control()
    assert sorted(out["clean_refusal_names"]) == sorted((
        DOC_GAP_FIELD_WRITTEN_TWICE, DOC_GAP_NO_READER_IN_FILE,
        STEP_GAP_ESCAPES_AGAIN, READER_GAP_DYNAMIC))


def test_negative_control_keeps_exactly_one_benign():
    """«Безвредно» и «не измерено» — разные исходы, и слить их нельзя."""
    out = _document_reader_control()
    assert out["clean_benign"] == 1


def test_negative_scene_population_is_five():
    assert len(_rows(DOC_READER_CONTROL_CLEAN)) == 5


def test_control_failure_makes_the_whole_step_unmeasured(monkeypatch):
    """Число, полученное промахивающимся правилом, есть свойство ПРАВИЛА."""
    monkeypatch.setattr(census, "_document_reader_control",
                        lambda: {"passed": False, "reason": "сцена"})
    out = document_field_reader_in_file(Path("."), _neighbour())
    assert out["status"] == "UNMEASURED"
    assert out["unmeasured_class"] == UNMEASURED_DOC_CONTROL
    assert "doc_step_outcomes" not in out


# --- звено 1: имя поля ------------------------------------------------------


def test_two_field_names_are_a_refusal_not_a_choice():
    src = '''
REACH_LIVE = "live"


def writer(rows):
    counts = {}
    for row in rows:
        cls = str(row.get("reach"))
        counts[cls] = counts.get(cls, 0) + 1
    return {"one": counts, "two": counts}


def caller(rows):
    doc = writer(rows)
    return len(doc)


def reader(doc):
    return doc["one"][REACH_LIVE] > 0
'''
    rows = _rows(src)
    assert len(rows) == 1
    assert rows[0]["doc_step"] == ONE_STEP_UNRESOLVED
    assert rows[0]["doc_gap"] == DOC_GAP_MANY_FIELDS


# --- звено 2: ОДНОСТОРОННОСТЬ, названная и ограниченная ---------------------


def test_field_written_by_two_scopes_is_refused_even_with_a_ready_reader():
    """Главный контроль шага: имя — не адрес.

    Читатель ключа здесь ЕСТЬ и класс он делит. Засчитать его нашим значило бы
    доказать вред СОВПАДЕНИЕМ ИМЁН — ровно тем, чего заказ требовал не делать.
    """
    rows = _rows(DOC_READER_CONTROL_CLEAN)
    dup = [r for r in rows if r["field"] == "dup"]
    assert len(dup) == 1
    assert dup[0]["doc_step"] == ONE_STEP_UNRESOLVED
    assert dup[0]["doc_gap"] == DOC_GAP_FIELD_WRITTEN_TWICE
    assert dup[0]["writers"] == 2


def test_the_same_scene_with_one_writer_does_split():
    """Отрицательная половина без положительной ничего не доказывает.

    Сцена отличается от предыдущей ровно вторым писателем ключа: раскол в ней
    находится, значит отказ выше — свойство звена, а не бессилие правила.
    """
    src = _scene("dup", '''
def reader(doc):
    return doc["dup"][REACH_LIVE] > 0
''')
    rows = _rows(src)
    assert len(rows) == 1
    assert rows[0]["doc_step"] == ONE_STEP_SPLITS
    assert rows[0]["writers"] == 1


def test_two_writes_of_one_key_inside_one_scope_are_one_writer():
    """Отказывать себе на ДВУХ записях одной области значило бы занизить замер."""
    src = '''
REACH_LIVE = "live"


def writer(rows):
    doc = {}
    counts = {}
    for row in rows:
        cls = str(row.get("reach"))
        counts[cls] = counts.get(cls, 0) + 1
    doc["kept"] = counts
    doc["kept"] = counts
    return doc


def caller(rows):
    made = writer(rows)
    return len(made)


def reader(made):
    return made["kept"][REACH_LIVE] > 0
'''
    rows = _rows(src)
    assert len(rows) == 1
    assert rows[0]["writers"] == 1
    assert rows[0]["doc_step"] == ONE_STEP_SPLITS


def test_field_write_scopes_sees_both_write_forms():
    tree = ast.parse('''
def a():
    return {"x": 1}


def b():
    doc = {}
    doc["x"] = 2
    return doc
''')
    owner = census._counter_owner_scopes(tree)
    assert len(_field_write_scopes(tree, owner, "x")) == 2


# --- звено 3: читатель ключа во всём файле ----------------------------------


def test_no_reader_in_this_file_is_the_instrument_limit_not_absence_of_harm():
    rows = _rows(_scene("lost"))
    assert len(rows) == 1
    assert rows[0]["doc_step"] == ONE_STEP_UNRESOLVED
    assert rows[0]["doc_gap"] == DOC_GAP_NO_READER_IN_FILE
    assert rows[0]["readers"] == 0


def test_reader_inside_the_writer_scope_is_not_a_reader_elsewhere():
    """Писатель, читающий собственное поле, читателем документа не является."""
    src = '''
REACH_LIVE = "live"


def writer(rows):
    counts = {}
    for row in rows:
        cls = str(row.get("reach"))
        counts[cls] = counts.get(cls, 0) + 1
    doc = {"solo": counts}
    if doc["solo"][REACH_LIVE]:
        pass
    return doc


def caller(rows):
    made = writer(rows)
    return len(made)
'''
    rows = _rows(src)
    assert len(rows) == 1
    assert rows[0]["doc_gap"] == DOC_GAP_NO_READER_IN_FILE


def test_subscript_form_is_found():
    rows = _rows(_scene("sub", '''
def reader(doc):
    return doc["sub"][REACH_LIVE] > 0
'''))
    assert rows[0]["read_forms"] == [DOC_READ_SUBSCRIPT]
    assert rows[0]["doc_step"] == ONE_STEP_SPLITS


def test_get_form_is_found():
    rows = _rows(_scene("got", '''
def reader(doc):
    return doc.get("got", {})[REACH_LIVE] > 0
'''))
    assert rows[0]["read_forms"] == [DOC_READ_GET]
    assert rows[0]["doc_step"] == ONE_STEP_SPLITS


def test_declared_observation_helper_is_the_third_form():
    """Форма, найденная ЗАПУСКОМ: без неё 17 из 26 получили бы ложный отказ."""
    rows = _rows(_scene("seen", '''
def reader(doc):
    return observed(doc, "seen", kind=dict)[REACH_LIVE] > 0
'''))
    assert rows[0]["read_forms"] == [DOC_READ_OBSERVED]
    assert rows[0]["doc_step"] == ONE_STEP_SPLITS


def test_a_foreign_call_carrying_the_same_string_is_not_a_read():
    """«Вызов, среди аргументов которого есть наша строка» — не правило чтения."""
    rows = _rows(_scene("noisy", '''
def reader(doc):
    log.info(doc, "noisy", kind=dict)
'''))
    assert rows[0]["doc_gap"] == DOC_GAP_NO_READER_IN_FILE


def test_declared_reader_is_recognised_by_name_only():
    assert _is_declared_reader(ast.Name(id=DOC_READ_HELPER)) is True
    assert _is_declared_reader(ast.parse("m.observed(d, 'x')").body[0]
                               .value.func) is True
    assert _is_declared_reader(ast.Name(id="peeked")) is False


def test_helper_call_with_one_argument_is_not_a_field_read():
    """У объявленного читателя поле стои́т ВТОРЫМ аргументом, и это часть формы."""
    rows = _rows(_scene("solo", '''
def reader(doc):
    return observed("solo")
'''))
    assert rows[0]["doc_gap"] == DOC_GAP_NO_READER_IN_FILE


def test_reads_are_deduplicated_per_scope_and_form():
    tree = ast.parse('''
def w():
    return {"x": 1}


def r(doc):
    a = doc["x"]
    b = doc["x"]
    return a, b
''')
    owner = census._counter_owner_scopes(tree)
    writer = tree.body[0]
    assert len(_document_field_reads(tree, owner, "x", writer)) == 1


# --- звено 4: читатель, и его исходы ----------------------------------------


def test_wholesale_reader_is_benign_and_counted_as_resolved():
    rows = _rows(_scene("bulk", '''
def reader(doc):
    return sorted(doc["bulk"])
'''))
    assert rows[0]["doc_step"] == ONE_STEP_WHOLESALE
    assert rows[0]["doc_gap"] is None


def test_reader_binding_the_field_escapes_again_and_is_not_benign():
    """«Нужен ещё шаг» — не «вреда нет», и это разные исходы."""
    rows = _rows(_scene("again", '''
def reader(doc):
    c = doc["again"]
    return c.get(REACH_LIVE, 0)
'''))
    assert rows[0]["doc_step"] == ONE_STEP_UNRESOLVED
    assert rows[0]["doc_gap"] == STEP_GAP_ESCAPES_AGAIN


def test_unresolvable_key_is_named_and_not_a_split():
    rows = _rows(_scene("dyn", '''
def reader(doc, key):
    return doc["dyn"][key] > 0
'''))
    assert rows[0]["doc_step"] == ONE_STEP_UNRESOLVED
    assert rows[0]["doc_gap"] == READER_GAP_DYNAMIC


def test_a_split_by_one_reader_is_enough_though_another_is_silent():
    """Свидетель раскола односторонний: доказанный раскол не отменяется молчанием."""
    rows = _rows(_scene("many", '''
def quiet(doc):
    return sorted(doc["many"])


def loud(doc):
    return doc["many"][REACH_LIVE] > 0
'''))
    assert rows[0]["doc_step"] == ONE_STEP_SPLITS
    assert rows[0]["readers"] == 2


def test_one_unmeasured_reader_sinks_the_whole_counter():
    """Объявить безвредным по измеренной половине и есть та самая подмена."""
    rows = _rows(_scene("mix", '''
def bulk(doc):
    return sorted(doc["mix"])


def rebound(doc):
    c = doc["mix"]
    return c
'''))
    assert rows[0]["doc_step"] == ONE_STEP_UNRESOLVED
    assert rows[0]["doc_gap"] == STEP_GAP_ESCAPES_AGAIN


def test_a_write_by_the_reader_is_not_a_read():
    """Правило читателя соседское, и запись оно читателем не считает."""
    rows = _rows(_scene("wr", '''
def reader(doc):
    doc["wr"][REACH_LIVE] = doc["wr"].get(REACH_LIVE, 0) + 1
'''))
    assert rows[0]["doc_step"] != ONE_STEP_SPLITS


# --- население и отказы шага ------------------------------------------------


def test_population_is_the_neighbour_sum_of_two_gap_names():
    out = document_field_reader_in_file(Path("."), _neighbour(999, 999))
    assert out["status"] == "UNMEASURED"
    assert out["unmeasured_class"] == UNMEASURED_DOC_POPULATION
    assert out["census"] == 1998


def test_unmeasured_neighbour_is_not_an_empty_population():
    out = document_field_reader_in_file(Path("."), {"status": "UNMEASURED"})
    assert out["unmeasured_class"] == UNMEASURED_DOC_NEIGHBOUR
    assert "population" not in out


def test_neighbour_without_the_two_reason_keys_is_unmeasured():
    out = document_field_reader_in_file(Path("."),
                                        {"status": "MEASURED",
                                         "unresolved_reasons": {}})
    assert out["unmeasured_class"] == UNMEASURED_DOC_NEIGHBOUR


def test_neighbour_of_the_wrong_type_is_unmeasured():
    assert document_field_reader_in_file(
        Path("."), None)["unmeasured_class"] == UNMEASURED_DOC_NEIGHBOUR


def test_missing_directory_is_named_not_silently_skipped(tmp_path):
    out = document_field_reader_in_file(tmp_path, _neighbour(0, 0))
    assert out["status"] == "MEASURED"
    assert [u["file"] for u in out["files_unreadable"]] == list(
        census.OPEN_COUNTER_DIRS)


def test_unparsable_file_is_named_not_counted_clean(tmp_path):
    base = tmp_path / "spa_core" / "monitoring"
    base.mkdir(parents=True)
    (base / "broken.py").write_text("def (", encoding="utf-8")
    out = document_field_reader_in_file(tmp_path, _neighbour(0, 0))
    assert any(u["file"].endswith("broken.py")
               for u in out["files_unreadable"])


def test_every_gap_name_is_declared_in_the_roster():
    src_rows = _rows(DOC_READER_CONTROL_SOURCE) + _rows(DOC_READER_CONTROL_CLEAN)
    for row in src_rows:
        if row["doc_gap"] is not None:
            assert row["doc_gap"] in _DOC_GAPS


def test_gap_names_are_distinct():
    assert len(set(_DOC_GAPS)) == len(_DOC_GAPS)


# --- живой замер ------------------------------------------------------------


def test_live_measurement_reports_both_liveness_numbers():
    """Ноль от живой проводки и ноль от непроведённого шага выглядят одинаково."""
    root = Path(__file__).resolve().parents[2]
    out = document_field_reader_in_file(root, _neighbour(16, 10))
    assert out["status"] == "MEASURED", out.get("reason")
    assert out["population"] == 26
    assert out["field_name_unique_in_file"] == 26
    assert out["reader_of_that_field_found"] == 20


def test_live_measurement_answers_with_a_pair_of_numbers():
    root = Path(__file__).resolve().parents[2]
    out = document_field_reader_in_file(root, _neighbour(16, 10))
    assert out["resolved_by_document_step"] == 3
    assert out["still_unmeasured"] == 23
    assert (out["resolved_by_document_step"] + out["still_unmeasured"]
            == out["population"])


def test_the_named_case_of_adr_463_is_read_in_its_own_module():
    """`key_origin_counts` читают в том же модуле — и правило двух форм врало.

    ADR-463 назвал этот случай поимённо: поле пишет
    ``open_class_counter_census`` и читает ``report`` ТОГО ЖЕ файла. Правило,
    знающее подписку и ``.get``, объявило бы «поля не читает никто» — то есть
    противоречило бы уже опубликованному замеру соседа.
    """
    root = Path(__file__).resolve().parents[2]
    path = root / "spa_core" / "monitoring" / "rule_second_copy_census.py"
    rows = _document_reader_sites("x", ast.parse(path.read_text(
        encoding="utf-8")))
    named = [r for r in rows if r["field"] == "key_origin_counts"]
    assert len(named) == 1
    assert named[0]["readers"] == 1
    assert named[0]["read_forms"] == [DOC_READ_OBSERVED]
    assert named[0]["doc_gap"] == STEP_GAP_ESCAPES_AGAIN


def test_the_step_is_advisory():
    root = Path(__file__).resolve().parents[2]
    out = document_field_reader_in_file(root, _neighbour(16, 10))
    assert out["applied"] is False


def test_blind_spots_name_the_one_sidedness_aloud():
    root = Path(__file__).resolve().parents[2]
    out = document_field_reader_in_file(root, _neighbour(16, 10))
    assert any(DOC_GAP_FIELD_WRITTEN_TWICE in b for b in out["blind"])
    assert any(DOC_GAP_NO_READER_IN_FILE in b for b in out["blind"])


def test_report_prints_the_pair_and_the_refusal_names():
    root = Path(__file__).resolve().parents[2]
    out = document_field_reader_in_file(root, _neighbour(16, 10))
    lines = census.report({"document_field_reader_in_file": out})
    body = "\n".join(lines)
    assert "[ПО ИМЕНИ ПОЛЯ]" in body
    assert DOC_GAP_NO_READER_IN_FILE in body or "не читает в файле никто" in body
    assert "[ПО ИМЕНИ ПОЛЯ · КОНТРОЛЬ]" in body


def test_report_says_not_measured_when_the_step_is_absent():
    lines = census.report({})
    assert any("[ПО ИМЕНИ ПОЛЯ] НЕ ИЗМЕРЕНО" in line for line in lines)


def test_report_never_prints_a_clean_pass_for_an_unmeasured_step():
    lines = census.report({"document_field_reader_in_file":
                           {"status": "UNMEASURED",
                            "unmeasured_class": UNMEASURED_DOC_CONTROL,
                            "reason": "сцена"}})
    body = "\n".join(lines)
    assert "НЕ ИЗМЕРЕНО" in body
    assert "доводит до расколотого читателя" not in body


def test_whole_step_on_a_controlled_tree_reports_each_number_separately():
    """Сквозная проба на дереве, где числа РАЗНЫЕ — иначе слитые не отличить.

    На живом дереве имя поля однозначно у всех 26, и мутация, подменившая это
    число населением, осталась бы незамеченной. Здесь отрицательная сцена даёт
    4 из 5 однозначных и 3 из 5 с найденным читателем — три разных числа.
    """
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp) / "spa_core" / "monitoring"
        base.mkdir(parents=True)
        (base / "scene.py").write_text(DOC_READER_CONTROL_CLEAN,
                                       encoding="utf-8")
        out = document_field_reader_in_file(Path(tmp), _neighbour(5, 0))
    assert out["status"] == "MEASURED", out.get("reason")
    assert out["population"] == 5
    assert out["field_name_unique_in_file"] == 4
    assert out["reader_of_that_field_found"] == 3
    assert out["resolved_by_document_step"] == 1
    assert out["still_unmeasured"] == 4


def test_unresolved_sample_names_the_writer_count_of_the_ambiguous_case():
    """Образец обязан нести то, чем отказ чинится, а не одно имя класса."""
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp) / "spa_core" / "monitoring"
        base.mkdir(parents=True)
        (base / "scene.py").write_text(DOC_READER_CONTROL_CLEAN,
                                       encoding="utf-8")
        out = document_field_reader_in_file(Path(tmp), _neighbour(5, 0))
    dup = [s for s in out["unresolved_sample"]
           if s["gap"] == DOC_GAP_FIELD_WRITTEN_TWICE]
    assert dup and dup[0]["writers"] == 2


def test_control_refuses_when_the_positive_scene_misses_a_read_form(monkeypatch):
    """Контроль обязан краснеть от НЕполной сцены, иначе он украшение.

    Мутация «требование ВСЕХ форм чтения снято» ВЫЖИЛА на первом прогоне
    (#687): проверка формы стои́т ради сцены, которая формы НЕ несёт, а такой
    сцены в наборе не было — свойство проверялось только там, где оно и так
    выполняется. Здесь сцена лишена третьей формы намеренно.
    """
    lean = DOC_READER_CONTROL_SOURCE.replace(
        'return observed(doc, "noted", kind=dict)[REACH_LIVE] > 0',
        'return doc["noted"][REACH_LIVE] > 0')
    monkeypatch.setattr(census, "DOC_READER_CONTROL_SOURCE", lean)
    out = _document_reader_control()
    assert out["passed"] is False
    assert "форм" in out["reason"]


def test_control_refuses_when_the_negative_scene_produces_a_false_split(monkeypatch):
    """Вторая половина контроля обязана краснеть от ложного раскола.

    Сцена отличается от настоящей ровно снятым ВТОРЫМ писателем ключа `dup`:
    счётчик перестаёт быть неоднозначным, читатель засчитывается, и контроль
    обязан назвать это ложным расколом, а не пропустить.
    """
    start = DOC_READER_CONTROL_CLEAN.index("def dup_two(")
    end = DOC_READER_CONTROL_CLEAN.index("def dup_reader(")
    loose = DOC_READER_CONTROL_CLEAN[:start] + DOC_READER_CONTROL_CLEAN[end:]
    monkeypatch.setattr(census, "DOC_READER_CONTROL_CLEAN", loose)
    out = _document_reader_control()
    assert out["passed"] is False
    assert "ложных расколов" in out["reason"] or "расколов" in out["reason"]
