"""Заказ G81 п. 1 — ОДИН шаг по СВЯЗАННОМУ ИМЕНИ в той же области.

ADR-465 ответил на заказ G80 числом ТРИ и назвал ГЛАВНЫМ остатком 16: читатель
НАШЁЛ поле документа — подпиской, ``.get`` или объявленным читателем
``observed`` — и СВЯЗАЛ прочитанное именем
(``origins = observed(opened, "key_origin_counts", kind=dict)``), после чего
счётчик убежал СНОВА. Заказ G81 п. 1 спросил числом: сколько из 16 разрешает
ОДИН шаг по связанному имени В ТОЙ ЖЕ области, и сколько остаётся третьим
исходом; «связал и прочитал здесь» обязано отличаться от «связал и отдал
дальше» ИМЕНАМИ, а не одним отказом.

Каждый тест здесь — положительный контроль: он воспроизводит либо форму уже
случившегося дефекта (выдать НЕ ИЗМЕРЕНО за измеренный исход; доказать вред
СОВПАДЕНИЕМ ИМЁН; разрешить счётчик по ИЗМЕРЕННОЙ половине; соврать в имени
отказа), либо форму, которую правило ОБЯЗАНО не спутать с другой.

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
    BOUND_NAME_CONTROL_CLEAN,
    BOUND_NAME_CONTROL_SOURCE,
    DOC_READ_GET,
    DOC_READ_OBSERVED,
    DOC_READ_SUBSCRIPT,
    ONE_STEP_SPLITS,
    ONE_STEP_UNRESOLVED,
    ONE_STEP_WHOLESALE,
    READER_GAP_DYNAMIC,
    STEP_GAP_ESCAPES_AGAIN,
    STEP_GAP_NO_READ,
    UNMEASURED_BOUND_CONTROL,
    UNMEASURED_BOUND_NEIGHBOUR,
    UNMEASURED_BOUND_POPULATION,
    _BOUND_GAPS,
    _DOC_READ_FORMS,
    _binding_of_read,
    _bound_name_control,
    _bound_name_sites,
    _name_binding_sources,
    bound_name_read_in_this_scope,
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
EXTRA_UNBOUND_COUNTER = """

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
    c = doc["yy"]
    return c[REACH_LIVE] > 0
"""


def _rows(src: str) -> list:
    return _bound_name_sites("<t>", ast.parse(src))


def _one(src: str) -> dict:
    rows = _rows(src)
    assert len(rows) == 1, [
        (r["owner"], r["bound_step"], r["bound_gap"]) for r in rows]
    return rows[0]


def _neighbour(n: int) -> dict:
    return {"status": "MEASURED",
            "unresolved_reasons": {STEP_GAP_ESCAPES_AGAIN: n}}


def _tree(tmp_path: Path, *scenes: str) -> Path:
    root = tmp_path / "tree"
    (root / "spa_core" / "monitoring").mkdir(parents=True)
    (root / "scripts").mkdir(parents=True)
    for idx, src in enumerate(scenes):
        (root / "spa_core" / "monitoring" / f"scene{idx}.py").write_text(
            src, encoding="utf-8")
    return root


# --- ЗВЕНО 1: прочитанное СВЯЗАНО именем ------------------------------------


def test_subscript_read_bound_and_split_is_resolved():
    """Живая форма заказа: `c = doc["X"]` → `c[CLASS]`. Без неё шаг пуст."""
    row = _one(_scene("alpha", '''
def reader(doc):
    c = doc["alpha"]
    return c[REACH_LIVE] > 0
'''))
    assert row["bound_step"] == ONE_STEP_SPLITS
    assert row["bound_gap"] is None
    assert row["bound_names"] == ["c"]
    assert row["read_forms"] == [DOC_READ_SUBSCRIPT]


def test_get_read_bound_and_split_is_resolved():
    """Вторая форма чтения поля. Правило, знающее одну, занизило бы ответ."""
    row = _one(_scene("beta", '''
def reader(doc):
    c = doc.get("beta")
    return c.get(REACH_LIVE, 0) > 0
'''))
    assert row["bound_step"] == ONE_STEP_SPLITS
    assert row["read_forms"] == [DOC_READ_GET]


def test_observed_read_bound_and_split_is_resolved():
    """Главная форма дерева (инв. #17) — и главная форма населения этого шага."""
    row = _one(_scene("gamma", '''
def reader(doc):
    c = observed(doc, "gamma", kind=dict)
    return c[REACH_LIVE] > 0
'''))
    assert row["bound_step"] == ONE_STEP_SPLITS
    assert row["read_forms"] == [DOC_READ_OBSERVED]


def test_annotated_binding_is_a_binding_too():
    """`c: dict = doc["X"]` связывает имя ровно так же — иначе шаг занизит."""
    row = _one(_scene("delta", '''
def reader(doc):
    c: dict = doc["delta"]
    return c[REACH_LIVE] > 0
'''))
    assert row["bound_step"] == ONE_STEP_SPLITS
    assert row["bound_names"] == ["c"]


def test_read_handed_into_a_call_is_refused_by_its_own_name():
    """Прочитанное отдано в вызов: имени нет, шагать не по чему.

    Это НЕ «вреда нет» — раскол стои́т у зовущего, и чинится он ДРУГИМ
    (межпроцедурным разбором), а не ещё одним шагом в этой области.
    """
    row = _one(_scene("eps", '''
def reader(doc):
    return audit(doc["eps"])
'''))
    assert row["bound_step"] == ONE_STEP_UNRESOLVED
    assert row["bound_gap"] == BOUND_GAP_UNBOUND
    assert row["bound_names"] == []


def test_read_returned_directly_is_refused_as_unbound():
    row = _one(_scene("zeta", '''
def reader(doc):
    return doc["zeta"]
'''))
    assert row["bound_gap"] == BOUND_GAP_UNBOUND


def test_read_placed_into_a_container_is_refused_as_unbound():
    row = _one(_scene("eta", '''
def reader(doc):
    return {"kept": doc["eta"]}
'''))
    assert row["bound_gap"] == BOUND_GAP_UNBOUND


def test_defensive_or_tail_gets_its_own_name_not_the_unbound_one():
    """НАЙДЕНО ЗАПУСКОМ и это главное содержание замера.

    ``c = observed(doc, "X", kind=dict) or {}`` — честная форма инварианта
    #17 с защитным хвостом. Значение имя ПОЛУЧАЕТ, просто на узел позже.
    Назвать это «отдано без имени» значило бы послать чинить межпроцедурный
    разбор там, где не хватает одного звена в этой же области: имя отказа —
    то, чем отказ чинится (урок ADR-465).
    """
    row = _one(_scene("tl", '''
def reader(doc):
    c = observed(doc, "tl", kind=dict) or {}
    return c[REACH_LIVE] > 0
'''))
    assert row["bound_step"] == ONE_STEP_UNRESOLVED
    assert row["bound_gap"] == BOUND_GAP_OR_TAIL
    assert row["bound_gap"] != BOUND_GAP_UNBOUND


def test_or_tail_without_a_name_after_it_is_plain_unbound():
    """Хвост сам по себе имени не даёт: `return doc["X"] or {}` читают выше."""
    row = _one(_scene("tm", '''
def reader(doc):
    return doc["tm"] or {}
'''))
    assert row["bound_gap"] == BOUND_GAP_UNBOUND


def test_read_on_the_right_of_or_is_not_a_defensive_tail():
    """`fallback() or doc["X"]` — имя могло получить ДРУГОЕ значение.

    Хвост односторонен по построению: защитным он является только тогда,
    когда наше чтение стои́т ПЕРВЫМ. Считать хвостом и правую сторону значило
    бы приписать нашему счётчику имя, в котором его может не быть вовсе.
    """
    row = _one(_scene("rt", '''
def reader(doc, fallback):
    c = fallback or doc["rt"]
    return c[REACH_LIVE] > 0
'''))
    assert row["bound_gap"] == BOUND_GAP_UNBOUND


def test_value_printed_whole_into_a_string_gets_its_own_name():
    """ЧУЖОЙ потолок, названный ещё ADR-462, и назван он ОТДЕЛЬНО.

    ``f"{doc['counts']}"`` не уезжает никуда — счётчик печатают целиком, —
    но правило побега соседа перечисляет пробег поимённо и всё прочее зовёт
    побегом. Прибор соседа здесь не правится (чужая батарея, п. 2 правила
    приёмки); читателю важно не искать вреда там, где его нет.
    """
    row = _one(_scene("pw", '''
def reader(doc):
    return f"{doc['pw']}"
'''))
    assert row["bound_gap"] == BOUND_GAP_PRINTED_WHOLE


def test_the_dearest_limit_is_named_first_when_shapes_mix():
    """Порядок имён НЕ произволен: первым называется то, что дороже чинить.

    Отдано в чужой вызов ⇒ нужен межпроцедурный разбор; защитный хвост ⇒
    хватит одного звена здесь. Счётчик, у которого есть и то и другое, чинится
    ОБОИМИ, и назвать его дешёвым именем значило бы обещать дешёвую починку.
    """
    row = _one(_scene("mx", '''
def reader(doc):
    c = doc["mx"] or {}
    audit(doc["mx"])
    return c[REACH_LIVE] > 0
'''))
    assert row["bound_gap"] == BOUND_GAP_UNBOUND


def test_printed_is_named_before_the_or_tail_when_both_occur():
    """Чужой потолок дороже своего звена — и называется раньше него."""
    row = _one(_scene("px", '''
def reader(doc):
    c = doc["px"] or {}
    print(f"{doc['px']}")
    return c[REACH_LIVE] > 0
'''))
    assert row["bound_gap"] == BOUND_GAP_PRINTED_WHOLE


def test_two_names_for_one_read_are_refused_not_chosen():
    """ГОТОВЫЙ раскол у ОБОИХ имён, и правило обязано его НЕ засчитать.

    «Какое из двух» есть третий исход, а не выбор: молчаливый выбор первого
    дал бы читателя, которого на этом пути может не быть вовсе.
    """
    row = _one(_scene("theta", '''
def reader(doc):
    a = doc["theta"]
    b = doc["theta"]
    return a[REACH_LIVE] + b[REACH_LIVE]
'''))
    assert row["bound_step"] == ONE_STEP_UNRESOLVED
    assert row["bound_gap"] == BOUND_GAP_MANY_NAMES


def test_partly_bound_read_is_not_resolved_by_its_measured_half():
    """Одно чтение связано и расколото, другое отдано в вызов — ОТКАЗ.

    Разрешить счётчик по измеренной половине значило бы объявить измеренным
    исход, у которого вторая половина не измерена: ровно та подмена, против
    которой весь ряд G78…G81 и написан.
    """
    row = _one(_scene("iota", '''
def reader(doc):
    c = doc["iota"]
    audit(doc["iota"])
    return c[REACH_LIVE] > 0
'''))
    assert row["bound_step"] == ONE_STEP_UNRESOLVED
    assert row["bound_gap"] == BOUND_GAP_UNBOUND


def test_unbound_and_escapes_again_are_two_different_names():
    """Требование заказа дословно: развести ИМЕНАМИ, а не одним отказом."""
    unbound = _one(_scene("kap", '''
def reader(doc):
    return audit(doc["kap"])
'''))
    again = _one(_scene("kap", '''
def reader(doc):
    c = doc["kap"]
    return c
'''))
    assert unbound["bound_gap"] == BOUND_GAP_UNBOUND
    assert again["bound_gap"] == STEP_GAP_ESCAPES_AGAIN
    assert unbound["bound_gap"] != again["bound_gap"]


def test_binding_of_read_names_the_escape_count_it_saw():
    """Число побегов — наблюдение, а не «вроде связано»: его печатает шаг."""
    tree = ast.parse(_scene("lam", '''
def reader(doc):
    c = doc["lam"]
    return c[REACH_LIVE] > 0
'''))
    scope = next(n for n in ast.walk(tree)
                 if isinstance(n, ast.FunctionDef) and n.name == "reader")
    read = next(n for n in ast.walk(scope)
                if isinstance(n, ast.Subscript)
                and isinstance(n.slice, ast.Constant)
                and n.slice.value == "lam")
    found = _binding_of_read(scope, read)
    assert found == {"gap": None, "name": "c", "escapes": 1, "bound": 1,
                     "or_tail": 0, "printed": 0}


def test_read_that_does_not_escape_at_all_is_named_unbound_not_escaped():
    """Вызванный вне своего пути, помощник обязан отвечать ЧЕСТНО.

    Через шаг сюда не приходит ничего: населением он берёт ровно те чтения,
    которым сосед отказал побегом, поэтому побегов там ≥ 1 по построению.
    Имя отказа всё равно обязано быть СВОИМ: «побегов нет» и «побег есть, но
    имени не получил» — разные вещи, и назвать первое вторым значило бы
    послать чинить несуществующий следующий шаг.
    """
    tree = ast.parse(_scene("vv", '''
def reader(doc):
    return len(doc["vv"])
'''))
    scope = next(n for n in ast.walk(tree)
                 if isinstance(n, ast.FunctionDef) and n.name == "reader")
    read = next(n for n in ast.walk(scope)
                if isinstance(n, ast.Subscript)
                and isinstance(n.slice, ast.Constant)
                and n.slice.value == "vv")
    found = _binding_of_read(scope, read)
    assert found["gap"] == BOUND_GAP_UNBOUND
    assert found["escapes"] == 0


# --- ЗВЕНО 2: односторонность — у имени ОДИН источник -----------------------


def test_name_reassigned_from_another_source_is_refused_though_split_is_ready():
    """ГЛАВНОЕ ограничение односторонности, и оно ЗВЕНО, а не оговорка.

    `c = doc["X"]` … `c = other` … `c[CLASS]`: к моменту чтения имя могло
    держать ЧУЖОЕ значение. Засчитать раскол нашим значило бы доказывать вред
    совпадением ИМЁН — тот же дефект, что ADR-465 запретил уровнем выше.
    """
    row = _one(_scene("mu", '''
def reader(doc, other):
    c = doc["mu"]
    if other:
        c = other
    return c[REACH_LIVE] > 0
'''))
    assert row["bound_step"] == ONE_STEP_UNRESOLVED
    assert row["bound_gap"] == BOUND_GAP_REBOUND


def test_single_source_scene_differing_only_by_that_line_does_find_the_split():
    """Отрицательная половина звена 2 доказана ПАРОЙ, а не утверждением."""
    row = _one(_scene("mu", '''
def reader(doc, other):
    c = doc["mu"]
    return c[REACH_LIVE] > 0
'''))
    assert row["bound_step"] == ONE_STEP_SPLITS


def test_parameter_of_the_same_name_is_a_second_source():
    """`def reader(doc, c)` — до присваивания имя держало чужое значение."""
    row = _one(_scene("nu", '''
def reader(doc, c):
    c = doc["nu"]
    return c[REACH_LIVE] > 0
'''))
    assert row["bound_gap"] == BOUND_GAP_REBOUND


def test_loop_target_of_the_same_name_is_a_second_source():
    row = _one(_scene("xi", '''
def reader(doc, rows):
    c = doc["xi"]
    for c in rows:
        pass
    return c[REACH_LIVE] > 0
'''))
    assert row["bound_gap"] == BOUND_GAP_REBOUND


def test_name_binding_sources_counts_zero_when_the_name_comes_from_outside():
    """Ноль единицей НЕ выдаётся: `!= 1` есть третий исход, а не «один»."""
    tree = ast.parse("def reader(doc):\n    return q[0]\n")
    scope = tree.body[0]
    assert _name_binding_sources(scope, "q") == 0


# --- ЗВЕНО 3: читатель связанного имени — правило соседа --------------------


def test_bound_name_escaping_again_is_refused_by_the_neighbour_name():
    """«Нужен ещё шаг», а не «вреда нет» — и имя у него СОСЕДСКОЕ."""
    row = _one(_scene("omi", '''
def reader(doc):
    c = doc["omi"]
    return c
'''))
    assert row["bound_gap"] == STEP_GAP_ESCAPES_AGAIN


def test_bound_name_read_by_a_dynamic_key_is_refused():
    row = _one(_scene("pi", '''
def reader(doc, key):
    c = doc["pi"]
    return c[key] > 0
'''))
    assert row["bound_gap"] == READER_GAP_DYNAMIC


def test_bound_name_never_read_is_refused():
    row = _one(_scene("rho", '''
def reader(doc):
    c = doc["rho"]
    return 0
'''))
    assert row["bound_gap"] == STEP_GAP_NO_READ


def test_bound_name_used_wholesale_is_benign_not_a_split():
    """«Дошёл и безвреден» — ТРЕТЬЕ число, и слить его с отказом нельзя."""
    row = _one(_scene("sig", '''
def reader(doc):
    c = doc["sig"]
    return sorted(c)
'''))
    assert row["bound_step"] == ONE_STEP_WHOLESALE
    assert row["bound_gap"] is None


def test_literal_string_class_is_a_split_too():
    row = _one(_scene("tau", '''
def reader(doc):
    c = doc["tau"]
    return c["live"] > 0
'''))
    assert row["bound_step"] == ONE_STEP_SPLITS


def test_uppercase_name_is_a_declared_class_even_when_imported():
    row = _one(_scene("ups", '''
def reader(doc):
    c = doc["ups"]
    return c[OUTER_CLASS] > 0
'''))
    assert row["bound_step"] == ONE_STEP_SPLITS


def test_writing_into_the_bound_name_is_not_a_read():
    """Иначе шаг мерил бы ПИСАТЕЛЯ под именем читателя — ловушка соседа."""
    row = _one(_scene("phi", '''
def reader(doc):
    c = doc["phi"]
    c[REACH_LIVE] = c.get(REACH_LIVE, 0) + 1
    return len(c)
'''))
    assert row["bound_step"] == ONE_STEP_WHOLESALE


# --- СВОД по нескольким чтениям (правило соседа) ----------------------------


def test_split_at_one_reader_proves_the_counter_though_another_refuses():
    """Свидетель односторонний: раскол доказан хотя бы одним ⇒ доказан."""
    row = _one(_scene("chi", '''
def reader_a(doc):
    c = doc["chi"]
    return c[REACH_LIVE] > 0
''', extra='''
def reader_b(doc):
    return audit(doc["chi"])
'''))
    assert row["bound_step"] == ONE_STEP_SPLITS


def test_refusal_at_any_reader_keeps_the_counter_unmeasured_without_a_split():
    """Объявить безвредным по измеренной половине — та самая подмена."""
    row = _one(_scene("psi", '''
def reader_a(doc):
    return audit(doc["psi"])
''', extra='''
def reader_b(doc, key):
    c = doc["psi"]
    return c[key] > 0
'''))
    assert row["bound_step"] == ONE_STEP_UNRESOLVED
    assert row["bound_gap"] in _BOUND_GAPS


# --- НАСЕЛЕНИЕ: только отказ соседа «прочитано и убежало СНОВА» -------------


def test_counter_resolved_by_the_document_step_is_not_in_the_population():
    """Разрешённое соседом не наше: мерили бы чужое правило."""
    assert _rows(_scene("aa", '''
def reader(doc):
    return doc["aa"][REACH_LIVE] > 0
''')) == []


def test_counter_whose_field_is_read_at_the_caller_is_not_in_the_population():
    src = '''
REACH_LIVE = "live"


def writer(rows):
    counts = {}
    for row in rows:
        cls = str(row.get("reach"))
        counts[cls] = counts.get(cls, 0) + 1
    return {"bb": counts}


def caller(rows):
    doc = writer(rows)
    return doc["bb"][REACH_LIVE] > 0
'''
    assert _rows(src) == []


def test_counter_with_no_reader_of_the_field_is_not_in_the_population():
    assert _rows(_scene("cc", "")) == []


def test_counter_read_wholesale_by_the_neighbour_is_not_in_the_population():
    """Сосед разрешил его безвредным — у нас ему делать нечего."""
    assert _rows(_scene("dd", '''
def reader(doc):
    return len(doc["dd"])
''')) == []


# --- КОНТРОЛЬ объявленного правила -----------------------------------------


def test_control_passes_on_the_declared_scenes():
    out = _bound_name_control()
    assert out["passed"] is True, out.get("reason")
    assert out["known_case_resolved"] == len(_DOC_READ_FORMS)


def test_positive_scene_proves_all_three_read_forms():
    """Слепота к форме чтения — ровно та ошибка, что стоила ADR-465 11 имён."""
    rows = _bound_name_sites("<s>", ast.parse(BOUND_NAME_CONTROL_SOURCE))
    forms = sorted({f for r in rows for f in r["read_forms"]})
    assert forms == sorted(_DOC_READ_FORMS)
    assert all(r["bound_step"] == ONE_STEP_SPLITS for r in rows)


def test_negative_scene_yields_every_refusal_name_and_one_benign():
    rows = _bound_name_sites("<c>", ast.parse(BOUND_NAME_CONTROL_CLEAN))
    assert len(rows) == len(_BOUND_GAPS) + 1
    assert sorted({r["bound_gap"] for r in rows if r["bound_gap"]}) == sorted(
        _BOUND_GAPS)
    assert sum(1 for r in rows if r["bound_step"] == ONE_STEP_WHOLESALE) == 1
    assert not [r for r in rows if r["bound_step"] == ONE_STEP_SPLITS]


def test_negative_scene_carries_two_ready_splits_the_rule_must_not_count():
    """Отрицательная сила звеньев 1–2 доказана КОНТРОЛЕМ, а не населением.

    На живом дереве оба отказа могут не сработать ни разу; сцена несёт их
    с ГОТОВЫМ расколом, поэтому снятие звена красит набор здесь, а не «когда
    попадётся».
    """
    rows = _bound_name_sites("<c>", ast.parse(BOUND_NAME_CONTROL_CLEAN))
    ready = [r for r in rows
             if r["bound_gap"] in (BOUND_GAP_MANY_NAMES, BOUND_GAP_REBOUND)]
    assert len(ready) == 2
    assert all(r["bound_step"] == ONE_STEP_UNRESOLVED for r in ready)


def test_control_liveness_numbers_differ_on_the_negative_scene():
    """Ноль от живой проводки и ноль от непроведённого шага одинаковы на вид.

    На живом дереве числа звеньев 1 и 2 совпадают, поэтому подмена одного
    другим ловится ТОЛЬКО сценой, где они разные.
    """
    out = _bound_name_control()
    assert out["clean_bound_named"] == 5
    assert out["clean_stepped"] == 4
    assert out["clean_bound_named"] != out["clean_stepped"]


def test_control_fails_when_a_read_form_is_missing(monkeypatch):
    scene = BOUND_NAME_CONTROL_SOURCE.replace(
        'c = observed(doc, "gamma", kind=dict)', 'c = doc["gamma"]')
    monkeypatch.setattr(census, "BOUND_NAME_CONTROL_SOURCE", scene)
    out = _bound_name_control()
    assert out["passed"] is False
    assert "форм" in out["reason"] or "форма" in out["reason"]


def test_control_fails_when_the_positive_scene_stops_splitting(monkeypatch):
    scene = BOUND_NAME_CONTROL_SOURCE.replace(
        "return c[REACH_LIVE] > 0", "return sorted(c)")
    monkeypatch.setattr(census, "BOUND_NAME_CONTROL_SOURCE", scene)
    out = _bound_name_control()
    assert out["passed"] is False


def test_control_fails_when_the_negative_scene_loses_a_refusal_name(monkeypatch):
    scene = BOUND_NAME_CONTROL_CLEAN.replace('''def dyn_reader(doc, key):
    c = doc["dyn"]
    return c[key] > 0''', '''def dyn_reader(doc):
    c = doc["dyn"]
    return c
''')
    monkeypatch.setattr(census, "BOUND_NAME_CONTROL_CLEAN", scene)
    out = _bound_name_control()
    assert out["passed"] is False


def test_control_fails_when_the_negative_scene_starts_splitting(monkeypatch):
    scene = BOUND_NAME_CONTROL_CLEAN.replace('''def reb_reader(doc, other):
    c = doc["reb"]
    if other:
        c = other
    return c[REACH_LIVE] > 0''', '''def reb_reader(doc, other):
    c = doc["reb"]
    return c[REACH_LIVE] > 0''')
    monkeypatch.setattr(census, "BOUND_NAME_CONTROL_CLEAN", scene)
    out = _bound_name_control()
    assert out["passed"] is False
    assert "раскол" in out["reason"] or "ожидались" in out["reason"]


# --- КОНТРОЛЬ НА КОНТРОЛЬ: каждая проверка сцены обязана иметь зубы -------


def test_control_refuses_when_the_negative_scene_changes_size(monkeypatch):
    """Размер сцены — отдельная проверка, и снятая она молчит.

    Сцена, потерявшая счётчик, но сохранившая ВСЕ имена отказов, проходит
    все прочие проверки: без счёта строк «разбор разрешил N» считалось бы по
    сцене, которой автор уже не тот, что объявлен.
    """
    monkeypatch.setattr(census, "BOUND_NAME_CONTROL_CLEAN",
                        BOUND_NAME_CONTROL_CLEAN + EXTRA_UNBOUND_COUNTER)
    out = _bound_name_control()
    assert out["passed"] is False
    assert "счётчик" in out["reason"]


def test_control_refuses_when_the_positive_scene_changes_size(monkeypatch):
    """Тот же вопрос с положительной стороны: форм три, счётчиков тоже три."""
    doubled = BOUND_NAME_CONTROL_SOURCE + EXTRA_SPLIT_COUNTER
    monkeypatch.setattr(census, "BOUND_NAME_CONTROL_SOURCE", doubled)
    out = _bound_name_control()
    assert out["passed"] is False
    assert "положительной сцене" in out["reason"]


def test_control_refuses_when_the_benign_reader_disappears(monkeypatch):
    """«Дошёл и безвреден» — ТРЕТИЙ исход, и сцена обязана нести ровно один.

    Без счёта безвредных сцена, где безвредный читатель стал отказом, прошла
    бы: имена отказов те же, ложных расколов нет, а исход, который шаг обязан
    уметь отличать от отказа, в сцене больше не встречается.
    """
    scene = BOUND_NAME_CONTROL_CLEAN.replace("    return sorted(c)",
                                             "    return c")
    monkeypatch.setattr(census, "BOUND_NAME_CONTROL_CLEAN", scene)
    out = _bound_name_control()
    assert out["passed"] is False


def test_control_refuses_when_the_two_liveness_numbers_collapse(monkeypatch):
    """Проверка чисел живости — сама себе контроль, и снятая она молчит.

    Ноль от живой проводки и ноль от непроведённого шага выглядят одинаково
    (урок ADR-462): на живом дереве оба числа совпадают, поэтому подмену
    одного другим ловит ТОЛЬКО сцена, где они разные, — а значит, за самой
    этой разницей обязан следить отдельный отказ.
    """
    real = census._bound_name_sites

    def fake(rel, tree):
        rows = real(rel, tree)
        if rel == "<control-clean>":
            for row in rows:
                row["stepped"] = 1
        return rows

    monkeypatch.setattr(census, "_bound_name_sites", fake)
    out = _bound_name_control()
    assert out["passed"] is False
    assert "живости" in out["reason"]


def test_unparsable_control_scene_is_a_named_refusal(monkeypatch):
    monkeypatch.setattr(census, "BOUND_NAME_CONTROL_SOURCE", "def (:\n")
    out = _bound_name_control()
    assert out["passed"] is False
    assert "не разобрана" in out["reason"]


# --- ОДНО ПРАВИЛО — ОДНА КОПИЯ ---------------------------------------------


def test_escape_rule_is_the_neighbours_not_a_second_copy(monkeypatch):
    """Четвёртая копия правила побега была бы тем самым искомым дефектом."""
    called = []
    original = census._escape_sites

    def spy(scope, target):
        called.append(1)
        return original(scope, target)

    monkeypatch.setattr(census, "_escape_sites", spy)
    _rows(_scene("ee", '''
def reader(doc):
    c = doc["ee"]
    return c[REACH_LIVE] > 0
'''))
    assert called


def test_reader_rule_is_the_neighbours_not_a_second_copy(monkeypatch):
    """Читателя разбирает сосед: своего правила «что есть раскол» тут нет."""
    seen = []
    original = census._one_step_reader

    def spy(scope, target, declared):
        seen.append(getattr(target, "id", None))
        return original(scope, target, declared)

    monkeypatch.setattr(census, "_one_step_reader", spy)
    _rows(_scene("ff", '''
def reader(doc):
    c = doc["ff"]
    return c[REACH_LIVE] > 0
'''))
    assert "c" in seen


def test_reads_are_taken_from_the_neighbour_not_re_found(monkeypatch):
    called = []
    original = census._document_field_reads

    def spy(tree, owner_of, field, writer):
        called.append(field)
        return original(tree, owner_of, field, writer)

    monkeypatch.setattr(census, "_document_field_reads", spy)
    _rows(_scene("gg", '''
def reader(doc):
    c = doc["gg"]
    return c[REACH_LIVE] > 0
'''))
    assert "gg" in called


# --- ПЕРЕПИСЬ: третий исход отдельным значением -----------------------------


def test_absent_neighbour_is_unmeasured_not_zero(tmp_path):
    out = bound_name_read_in_this_scope(_tree(tmp_path), None)
    assert out["status"] == "UNMEASURED"
    assert out["unmeasured_class"] == UNMEASURED_BOUND_NEIGHBOUR
    assert "population" not in out


def test_unmeasured_neighbour_is_unmeasured(tmp_path):
    out = bound_name_read_in_this_scope(
        _tree(tmp_path), {"status": "UNMEASURED"})
    assert out["unmeasured_class"] == UNMEASURED_BOUND_NEIGHBOUR


def test_neighbour_without_the_escapes_again_key_is_unmeasured(tmp_path):
    out = bound_name_read_in_this_scope(
        _tree(tmp_path), {"status": "MEASURED", "unresolved_reasons": {}})
    assert out["unmeasured_class"] == UNMEASURED_BOUND_NEIGHBOUR


def test_population_mismatch_is_unmeasured_not_a_number(tmp_path):
    """Своё население разошлось с соседским ⇒ шаг отвечал бы на другой вопрос."""
    root = _tree(tmp_path, _scene("hh", '''
def reader(doc):
    c = doc["hh"]
    return c[REACH_LIVE] > 0
'''))
    out = bound_name_read_in_this_scope(root, _neighbour(7))
    assert out["status"] == "UNMEASURED"
    assert out["unmeasured_class"] == UNMEASURED_BOUND_POPULATION
    assert out["walked"] == 1
    assert out["census"] == 7


def test_failed_control_makes_the_whole_step_unmeasured(tmp_path, monkeypatch):
    monkeypatch.setattr(census, "BOUND_NAME_CONTROL_SOURCE", "def (:\n")
    out = bound_name_read_in_this_scope(_tree(tmp_path), _neighbour(0))
    assert out["status"] == "UNMEASURED"
    assert out["unmeasured_class"] == UNMEASURED_BOUND_CONTROL


def test_missing_directory_is_named_not_silently_skipped(tmp_path):
    root = tmp_path / "bare"
    (root / "spa_core" / "monitoring").mkdir(parents=True)
    out = bound_name_read_in_this_scope(root, _neighbour(0))
    assert out["status"] == "MEASURED"
    assert [u["file"] for u in out["files_unreadable"]] == ["scripts"]


def test_unparsable_file_is_named_not_silently_skipped(tmp_path):
    root = _tree(tmp_path)
    (root / "spa_core" / "monitoring" / "broken.py").write_text(
        "def (:\n", encoding="utf-8")
    out = bound_name_read_in_this_scope(root, _neighbour(0))
    assert out["status"] == "MEASURED"
    assert any("broken.py" in u["file"] for u in out["files_unreadable"])


def test_measured_step_counts_both_outcomes_and_every_refusal_name(tmp_path):
    root = _tree(
        tmp_path,
        _scene("ii", '''
def reader(doc):
    c = doc["ii"]
    return c[REACH_LIVE] > 0
'''),
        _scene("jj", '''
def reader(doc):
    return audit(doc["jj"])
'''))
    out = bound_name_read_in_this_scope(root, _neighbour(2))
    assert out["status"] == "MEASURED"
    assert out["population"] == 2
    assert out["bound_step_outcomes"][ONE_STEP_SPLITS] == 1
    assert out["still_unmeasured"] == 1
    assert out["unresolved_reasons"][BOUND_GAP_UNBOUND] == 1
    assert sorted(out["unresolved_reasons"]) == sorted(_BOUND_GAPS)
    # «связано именем» считает СВЯЗАННЫЕ, а не все строки: у отданного в
    # вызов имени нет, и выдать его связанным значило бы объявить проводку
    # живой там, где звено 1 не отработало.
    assert out["read_value_bound_to_a_name"] == 1


def test_resolved_counts_the_benign_reader_too(tmp_path):
    """«Разрешено» есть раскол ПЛЮС безвредный: это два исхода, а не один."""
    root = _tree(tmp_path, _scene("qq", '''
def reader(doc):
    c = doc["qq"]
    return sorted(c)
'''))
    out = bound_name_read_in_this_scope(root, _neighbour(1))
    assert out["bound_step_outcomes"][ONE_STEP_WHOLESALE] == 1
    assert out["resolved_by_bound_name_step"] == 1


def test_counter_whose_caller_does_not_bind_the_result_is_in_the_population():
    """Второе имя отказа соседа — «результат никуда не связан».

    Забыть его значило бы потерять ЧАСТЬ населения молча: строки просто не
    появились бы, и число вышло бы меньше соседского без единого слова.
    """
    src = '''
REACH_LIVE = "live"


def writer(rows):
    counts = {}
    for row in rows:
        cls = str(row.get("reach"))
        counts[cls] = counts.get(cls, 0) + 1
    return {"rr": counts}


def caller(rows):
    return len(writer(rows))


def reader(doc):
    c = doc["rr"]
    return c[REACH_LIVE] > 0
'''
    row = _one(src)
    assert row["bound_step"] == ONE_STEP_SPLITS


def test_neighbour_verdict_passes_through_for_reads_we_do_not_own():
    """Наш шаг вступает ТОЛЬКО там, где сосед отказал побегом.

    Применить его ко всякому чтению значило бы переписать вердикт соседа
    своим — вторая копия правила читателя внутри прибора, который ищет
    вторые копии правил.
    """
    row = _one(_scene("ss", '''
def reader_a(doc):
    return len(doc["ss"])
''', extra='''
def reader_b(doc):
    c = doc["ss"]
    return sorted(c)
'''))
    assert row["bound_step"] == ONE_STEP_WHOLESALE


def test_two_liveness_numbers_are_kept_apart(tmp_path):
    """Связано именем ДВА, а до звена 3 дошёл ОДИН — складывать нельзя."""
    root = _tree(
        tmp_path,
        _scene("kk", '''
def reader(doc):
    c = doc["kk"]
    return c[REACH_LIVE] > 0
'''),
        _scene("ll", '''
def reader(doc, other):
    c = doc["ll"]
    if other:
        c = other
    return c[REACH_LIVE] > 0
'''))
    out = bound_name_read_in_this_scope(root, _neighbour(2))
    assert out["read_value_bound_to_a_name"] == 2
    assert out["bound_name_single_source"] == 1


def test_harm_sample_names_file_line_counter_field_and_bound_name(tmp_path):
    root = _tree(tmp_path, _scene("mm", '''
def reader(doc):
    c = doc["mm"]
    return c[REACH_LIVE] > 0
'''))
    out = bound_name_read_in_this_scope(root, _neighbour(1))
    sample = out["harm_sample"][0]
    assert sample["field"] == "mm"
    assert sample["bound"] == "c"
    assert sample["counter"] == "counts"
    assert sample["split"]


def test_unresolved_sample_names_the_refusal(tmp_path):
    root = _tree(tmp_path, _scene("nn", '''
def reader(doc):
    return audit(doc["nn"])
'''))
    out = bound_name_read_in_this_scope(root, _neighbour(1))
    assert out["unresolved_sample"][0]["gap"] == BOUND_GAP_UNBOUND


def test_step_is_advisory_and_says_so(tmp_path):
    out = bound_name_read_in_this_scope(_tree(tmp_path), _neighbour(0))
    assert out["applied"] is False
    assert out["order"] == "G81.1"


def test_blind_spots_are_named_not_implied(tmp_path):
    out = bound_name_read_in_this_scope(_tree(tmp_path), _neighbour(0))
    text = " ".join(out["blind"])
    assert BOUND_GAP_REBOUND in text
    assert BOUND_GAP_UNBOUND in text
    assert STEP_GAP_ESCAPES_AGAIN in text


# --- ОТЧЁТ -----------------------------------------------------------------


def test_report_says_unmeasured_when_the_step_is_absent():
    lines = census.report({"renamed_copy_surface": []})
    assert any("[ПО СВЯЗАННОМУ ИМЕНИ] НЕ ИЗМЕРЕНО" in ln for ln in lines)


def test_report_names_unmeasured_class_of_the_step():
    lines = census.report({
        "bound_name_read_in_this_scope": {
            "status": "UNMEASURED",
            "unmeasured_class": UNMEASURED_BOUND_POPULATION,
            "reason": "разошлось"},
        "renamed_copy_surface": []})
    assert any(UNMEASURED_BOUND_POPULATION in ln for ln in lines)


def test_report_separates_unbound_from_escapes_again(tmp_path):
    root = _tree(tmp_path, _scene("oo", '''
def reader(doc):
    return audit(doc["oo"])
'''))
    step = bound_name_read_in_this_scope(root, _neighbour(1))
    lines = census.report({"bound_name_read_in_this_scope": step,
                           "renamed_copy_surface": []})
    text = " ".join(lines)
    assert "отдано в вызов БЕЗ имени 1" in text
    assert "имя убежало СНОВА 0" in text


def test_report_prints_both_liveness_numbers_in_the_declared_order(tmp_path):
    """Числа разные, и перепутать их местами отчёт не вправе.

    Совпавшие числа читаются одинаково при любом порядке — поэтому сцена
    отчёта взята такая, где связано ДВА имени, а до звена 3 дошло ОДНО.
    """
    root = _tree(
        tmp_path,
        _scene("pp", '''
def reader(doc):
    c = doc["pp"]
    return c[REACH_LIVE] > 0
'''),
        _scene("pq", '''
def reader(doc, other):
    c = doc["pq"]
    if other:
        c = other
    return c[REACH_LIVE] > 0
'''))
    step = bound_name_read_in_this_scope(root, _neighbour(2))
    lines = census.report({"bound_name_read_in_this_scope": step,
                           "renamed_copy_surface": []})
    live = [ln for ln in lines if "ПРОВОДКА ЖИВА" in ln]
    assert len(live) == 1
    assert "РОВНО одним именем у 2" in live[0]
    assert "у 1 это имя связывает РОВНО ОДИН источник" in live[0]


def test_measure_wires_the_step_under_its_own_key():
    """Отдельным ключом, а не поправкой к соседу: вопросы разные."""
    import inspect
    src = inspect.getsource(census.measure)
    assert "bound_name_read_in_this_scope(root, doc_step)" in src
    assert '"bound_name_read_in_this_scope": bound_step,' in src


@pytest.mark.parametrize("gap", _BOUND_GAPS)
def test_every_declared_refusal_name_is_reachable(gap):
    """Имя отказа, которого не даёт ни одна сцена, есть украшение."""
    rows = _bound_name_sites("<c>", ast.parse(BOUND_NAME_CONTROL_CLEAN))
    assert gap in {r["bound_gap"] for r in rows}
