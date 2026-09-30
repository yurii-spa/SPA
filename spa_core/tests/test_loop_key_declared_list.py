"""Батарея шага «КЛЮЧ ИЗ ЦИКЛА» (заказ G85 п. 4, ADR-519).

ADR-467 назвал остаток шага за защитный хвост ИМЕНАМИ, и одно из них —
«счётчик прочитан ключом, которого правило не разрешает»:

    " · ".join(f"{k} {ext.get(k, 0)}" for k in EXTENSIONS)

Ключ тут не литерал и не объявленная константа: он пробегает ОБЪЯВЛЕННЫЙ
перечень, то есть класс всё-таки назван — просто не в точке чтения. Заказ
G83 п. 1 → G84 п. 3 → G85 п. 4 просит дословно:

    Сколько чтений неразрешимым ключом разрешает шаг, признающий пробег по
    объявленному перечню ОБЪЯВЛЕНИЕМ класса, и сколько остаётся третьим
    исходом. Односторонность назвать заранее и ограничить звеном: перечень
    обязан быть КОНСТАНТОЙ модуля (не параметром, не результатом вызова) —
    иначе «объявленность» держалась бы на имени, а не на значении. Население
    этого шага — ОДИН счётчик, и это обязано быть сказано вслух: правило,
    выведенное на населении в одну строку, есть подгонка прибора под данные,
    поэтому сила правила доказывается КОНТРОЛЕМ, а не числом.

Последнее требование и определяет форму батареи: почти всё здесь — КОНТРОЛЬ.
Зелёный контур целиком, красное на КАЖДОМ порванном звене с НАЗВАННЫМ звеном,
и отказ шага там, где предпосылка не обеспечена. Отдельный разряд — контроли
НА КОНТРОЛЬ: каждую клаузу `_loop_key_control` обязан ловить отдельный тест,
иначе снять любую поодиночке можно было бы молча (урок ADR-517).

Ни одного литерала даты и ни одного литерала pid здесь нет вовсе — предмет
шага не зависит ни от календаря, ни от того, какой номер сегодня занят.
"""
from __future__ import annotations

import ast
import sys
from pathlib import Path

import pytest

if __package__ in (None, ""):                      # прямой запуск без conftest
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from spa_core.monitoring import rule_second_copy_census as C

STEP = "loop_key_over_a_declared_list"


# --------------------------------------------------------------- вход сцены

def _positive():
    return C._loop_key_sites("<scene>", ast.parse(C.LOOP_KEY_CONTROL_SOURCE))


def _negative():
    return C._loop_key_sites("<scene-clean>",
                             ast.parse(C.LOOP_KEY_CONTROL_CLEAN))


def _tail(dynamic=1):
    """Сосед, ответивший как на живом дереве: N отказов «неразрешимый ключ»."""
    return {"status": "MEASURED",
            "unresolved_reasons": {
                C.TAIL_GAP_RIGHT_OPERAND: 0,
                C.TAIL_GAP_RESULT_UNBOUND: 1,
                C.READER_GAP_DYNAMIC: dynamic,
                C.STEP_GAP_ESCAPES_AGAIN: 1}}


def _scene_tree(extra: str = "") -> ast.Module:
    return ast.parse(C.LOOP_KEY_CONTROL_SOURCE + extra)


# =========================================================== ЗЕЛЁНЫЙ КОНТУР

def test_positive_scene_is_resolved_whole():
    """Оба счётчика положительной сцены обязаны РАЗРЕШИТЬСЯ."""
    rows = _positive()
    assert len(rows) == 3, [r["field"] for r in rows]
    assert {r["loop_step"] for r in rows} == {C.ONE_STEP_SPLITS}
    assert [r["loop_gap"] for r in rows] == [None, None, None]


def test_both_proof_forms_are_exercised_by_the_positive_scene():
    """Перечень МОДУЛЯ и перечень НА МЕСТЕ — две формы, и обе предъявлены."""
    proved = {p for r in _positive() for p in r["loop_proofs"]}
    assert proved == set(C._LOOP_PROOFS)


def test_the_resolved_split_names_the_reading_that_proves_it():
    """Раскол обязан назвать ЧТЕНИЕ, а не только вердикт."""
    for row in _positive():
        assert row["loop_splits"], row["counter"]
        assert any("get(" in (s.get("how") or "")
                   or "[" in (s.get("how") or "")
                   for s in row["loop_splits"])


def test_the_resolved_row_names_the_key():
    """Ключ назван ИМЕНЕМ: без него «разрешено» нечем поверить."""
    for row in _positive():
        assert row["loop_keys"], row["counter"]


def test_control_passes_on_the_declared_scenes():
    assert C._loop_key_control()["passed"] is True


def test_control_reports_both_halves_by_number():
    control = C._loop_key_control()
    assert control["positive"] == 3
    assert control["negative"] == len(C._LOOP_GAPS)
    assert sorted(control["gaps"]) == sorted(C._LOOP_GAPS)


# =================================================== КАЖДОЕ ИМЯ ОТКАЗА ЖИВОЕ

def test_negative_scene_refuses_every_counter():
    rows = _negative()
    assert rows, "отрицательная сцена не дала ни одного счётчика"
    assert {r["loop_step"] for r in rows} == {C.ONE_STEP_UNRESOLVED}


def test_negative_scene_uses_every_declared_gap_name_exactly_once():
    """Семь имён отказа — семь счётчиков. Два класса под одним именем есть
    потеря указания на починку."""
    gaps = [r["loop_gap"] for r in _negative()]
    assert sorted(gaps) == sorted(C._LOOP_GAPS)
    assert len(gaps) == len(set(gaps))


@pytest.mark.parametrize("counter,gap", [
    ("gamma", C.LOOP_GAP_NOT_A_LOOP_VARIABLE),
    ("delta", C.LOOP_GAP_TUPLE_TARGET),
    ("epsilon", C.LOOP_GAP_BOUND_OUTSIDE),
    ("zeta", C.LOOP_GAP_ITER_NOT_A_MODULE_NAME),
    ("eta", C.LOOP_GAP_ITER_NOT_AN_ENUMERATION),
    ("theta", C.LOOP_GAP_ITER_REBOUND),
    ("iota", C.LOOP_GAP_LOOPS_DISAGREE),
])
def test_each_negative_counter_gets_its_own_name(counter, gap):
    """Имя отказа привязано к КОНКРЕТНОМУ счётчику, а не к набору имён.

    Счётчики сцены зовутся одинаково (`counts`) намеренно — имя не есть адрес
    (ADR-465), — поэтому строка ищется по ПОЛЮ документа.
    """
    rows = {r["field"]: r for r in _negative()}
    assert counter in rows, sorted(rows)
    assert rows[counter]["loop_gap"] == gap


# ================================================= ЗВЕНО: ПЕРЕЧЕНЬ ПО ЗНАЧЕНИЮ

def test_empty_enumeration_declares_no_class():
    """Пустой перечень перечнем не считается: он не объявляет ни одного
    класса, и зачесть его значило бы доказать объявленность отсутствием."""
    tree = ast.parse("EMPTY = ()\nFULL = ('a',)\n")
    declared = C._declared_constant_names(tree)
    assert C._declared_enumeration_display(
        ast.parse("()", mode="eval").body, declared) is False
    once, _rebound = C._module_declared_enumerations(tree, declared)
    assert "EMPTY" not in once
    assert "FULL" in once


def test_enumeration_of_module_constants_counts_by_value_not_by_name():
    """Перечень ИМЁН-констант — перечень объявленных классов; перечень
    вычисляемых выражений — нет, хотя имя у него такое же ЗАГЛАВНОЕ."""
    tree = ast.parse("A = 'a'\nB = 'b'\nGOOD = (A, B)\nBAD = (len('x'),)\n")
    declared = C._declared_constant_names(tree)
    once, _rebound = C._module_declared_enumerations(tree, declared)
    assert "GOOD" in once
    assert "BAD" not in once


def test_rebound_enumeration_is_named_apart_from_never_an_enumeration():
    """Переприсвоенное имя чинится ИНАЧЕ, чем имя, которое перечнем не было."""
    tree = ast.parse("X = ('a',)\nX = ('b',)\nY = 'plain'\n")
    declared = C._declared_constant_names(tree)
    once, rebound = C._module_declared_enumerations(tree, declared)
    assert once == set()
    assert rebound == {"X"}


def test_a_dict_display_of_literal_keys_declares_its_classes():
    """Пробег по словарю-литералу отдаёт его КЛЮЧИ, и они объявлены."""
    declared = set()
    node = ast.parse("{'a': 1, 'b': 2}", mode="eval").body
    assert C._declared_enumeration_display(node, declared) is False


# =============================================== ЗВЕНО: КЛЮЧ ИЗ ЦИКЛА, ПРЯМО

def _scope(source: str, name: str) -> ast.AST:
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return tree, node
    raise AssertionError(name)


def test_loop_targets_of_sees_comprehensions_not_only_for():
    """Живой случай заказа есть ВКЛЮЧЕНИЕ; знать только `for` значило бы
    сказать «ключ не переменная цикла» там, где он ею является."""
    tree, fn = _scope("E = ('a',)\n\n\ndef f(c):\n"
                      "    return [c.get(k, 0) for k in E]\n", "f")
    found = C._loop_targets_of(fn, "k")
    assert len(found) == 1
    assert found[0][1] is True


def test_loop_targets_of_marks_a_tuple_target_as_not_bare():
    tree, fn = _scope("P = (('a', 1),)\n\n\ndef f(c):\n"
                      "    return [c.get(k, 0) for k, _n in P]\n", "f")
    found = C._loop_targets_of(fn, "k")
    assert len(found) == 1
    assert found[0][1] is False


def test_proof_refuses_a_locally_shadowed_enumeration():
    """Перечень обязан быть константой МОДУЛЯ: локально переприсвоенное имя
    держит чужое значение, и объявленность держалась бы на имени."""
    source = ("E = ('a',)\n\n\ndef f(c, rows):\n"
              "    E = sorted(rows)\n"
              "    return [c.get(k, 0) for k in E]\n")
    tree, fn = _scope(source, "f")
    declared = C._declared_constant_names(tree)
    once, rebound = C._module_declared_enumerations(tree, declared)
    module_names = set(C.toplevel_constants(tree)) | once | rebound
    out = C._loop_key_proof(fn, "k", declared, once, rebound, module_names)
    assert out == {"gap": C.LOOP_GAP_ITER_NOT_A_MODULE_NAME}


def test_proof_refuses_a_parameter_as_the_enumeration():
    source = ("def f(c, names):\n"
              "    return [c.get(k, 0) for k in names]\n")
    tree, fn = _scope(source, "f")
    declared = C._declared_constant_names(tree)
    once, rebound = C._module_declared_enumerations(tree, declared)
    module_names = set(C.toplevel_constants(tree)) | once | rebound
    out = C._loop_key_proof(fn, "k", declared, once, rebound, module_names)
    assert out == {"gap": C.LOOP_GAP_ITER_NOT_A_MODULE_NAME}


def test_proof_refuses_when_the_key_is_also_bound_outside_a_loop():
    """«Все циклы согласны» НЕ означает «все связывания суть циклы» — ровно
    та подмена, которой черновик этого шага насчитал три ложных находки."""
    source = ("E = ('a',)\n\n\ndef f(c, row):\n"
              "    k = row['cls']\n"
              "    out = [c.get(k, 0)]\n"
              "    for k in E:\n"
              "        out.append(c.get(k, 0))\n"
              "    return out\n")
    tree, fn = _scope(source, "f")
    declared = C._declared_constant_names(tree)
    once, rebound = C._module_declared_enumerations(tree, declared)
    module_names = set(C.toplevel_constants(tree)) | once | rebound
    out = C._loop_key_proof(fn, "k", declared, once, rebound, module_names)
    assert out == {"gap": C.LOOP_GAP_BOUND_OUTSIDE}


def test_proof_calls_two_disagreeing_loops_an_absence_of_an_answer():
    """Спор есть ОТСУТСТВИЕ ответа, а не первый из ответов."""
    source = ("E = ('a',)\n\n\ndef f(c):\n"
              "    out = []\n"
              "    for k in E:\n"
              "        out.append(c.get(k, 0))\n"
              "    for k in sorted(c):\n"
              "        out.append(c.get(k, 0))\n"
              "    return out\n")
    tree, fn = _scope(source, "f")
    declared = C._declared_constant_names(tree)
    once, rebound = C._module_declared_enumerations(tree, declared)
    module_names = set(C.toplevel_constants(tree)) | once | rebound
    out = C._loop_key_proof(fn, "k", declared, once, rebound, module_names)
    assert out == {"gap": C.LOOP_GAP_LOOPS_DISAGREE}


def test_proof_names_the_form_when_the_enumeration_is_written_in_place():
    source = ("def f(c):\n"
              "    return [c.get(k, 0) for k in ('p', 'q')]\n")
    tree, fn = _scope(source, "f")
    declared = C._declared_constant_names(tree)
    once, rebound = C._module_declared_enumerations(tree, declared)
    module_names = set(C.toplevel_constants(tree)) | once | rebound
    out = C._loop_key_proof(fn, "k", declared, once, rebound, module_names)
    assert out == {"proofs": [C.LOOP_BY_ENUM_IN_PLACE]}


def test_proof_says_not_a_loop_variable_when_no_loop_binds_the_name():
    source = ("def f(c, row):\n"
              "    return c.get(row['cls'], 0)\n")
    tree, fn = _scope(source, "f")
    declared = C._declared_constant_names(tree)
    out = C._loop_key_proof(fn, "cls", declared, set(), set(), set())
    assert out == {"gap": C.LOOP_GAP_NOT_A_LOOP_VARIABLE}


# ============================== ПРАВИЛО ЧИТАТЕЛЯ НЕ ПЕРЕПИСАНО, А РАСШИРЕНО

def test_the_key_is_identified_by_outcome_not_by_a_second_parse():
    """Ключом признаётся имя, от которого вердикт СОСЕДА меняется. Имя, не
    участвующее в чтении, ключом не становится, сколько бы циклов ни было."""
    source = ("E = ('a',)\n"
              "OTHER = ('z',)\n\n\n"
              "def f(c):\n"
              "    out = []\n"
              "    for spare in OTHER:\n"
              "        out.append(spare)\n"
              "    for k in E:\n"
              "        out.append(c.get(k, 0))\n"
              "    return out\n")
    tree, fn = _scope(source, "f")
    declared = C._declared_constant_names(tree)
    once, rebound = C._module_declared_enumerations(tree, declared)
    module_names = set(C.toplevel_constants(tree)) | once | rebound
    out = C._loop_key_reader(fn, "c", declared, once, rebound, module_names)
    assert out["verdict"] == C.ONE_STEP_SPLITS
    assert out["keys"] == ["k"]


def test_the_reader_step_refuses_when_the_neighbour_verdict_is_not_dynamic():
    """Ветка НЕДОСТИЖИМА через шаг (вердикт пересчитывается тем же вызовом) и
    поэтому проверяется ПРЯМЫМ вызовом помощника — порядком ADR-466/467."""
    source = ("def f(c):\n"
              "    return c.items()\n")
    tree, fn = _scope(source, "f")
    out = C._loop_key_reader(fn, "c", set(), set(), set(), set())
    assert out["gap"] == C.LOOP_GAP_NEIGHBOUR_VERDICT
    assert out["verdict"] == C.ONE_STEP_UNRESOLVED


def test_the_unreachable_gap_is_not_declared_among_the_step_gaps():
    """Объявить имя, которого шаг выдать не может, значило бы обещать разбор,
    которого нет (урок ADR-467 о недостижимой ветке)."""
    assert C.LOOP_GAP_NEIGHBOUR_VERDICT not in C._LOOP_GAPS


def test_one_resolved_key_is_enough_for_the_neighbour():
    """У соседа `splits` смотрится первым, и одного расколотого чтения ему
    достаточно; требовать ВСЕХ ключей значило бы завести своё правило."""
    source = ("E = ('a',)\n\n\ndef f(c, row):\n"
              "    out = [c.get(row['cls'], 0)]\n"
              "    for k in E:\n"
              "        out.append(c.get(k, 0))\n"
              "    return out\n")
    tree, fn = _scope(source, "f")
    declared = C._declared_constant_names(tree)
    once, rebound = C._module_declared_enumerations(tree, declared)
    module_names = set(C.toplevel_constants(tree)) | once | rebound
    out = C._loop_key_reader(fn, "c", declared, once, rebound, module_names)
    assert out["verdict"] == C.ONE_STEP_SPLITS
    assert "k" in out["proofs"]


# ================================================== ОТКАЗЫ САМОГО ШАГА — ТРИ

def test_step_refuses_when_the_neighbour_is_absent():
    out = C.loop_key_over_a_declared_list(Path("."), None)
    assert out["status"] == "UNMEASURED"
    assert out["unmeasured_class"] == C.UNMEASURED_LOOP_NEIGHBOUR


def test_step_refuses_when_the_neighbour_is_unmeasured():
    out = C.loop_key_over_a_declared_list(Path("."),
                                          {"status": "UNMEASURED"})
    assert out["status"] == "UNMEASURED"
    assert out["unmeasured_class"] == C.UNMEASURED_LOOP_NEIGHBOUR


def test_step_refuses_when_the_neighbour_never_named_the_number():
    out = C.loop_key_over_a_declared_list(
        Path("."), {"status": "MEASURED", "unresolved_reasons": {}})
    assert out["status"] == "UNMEASURED"
    assert out["unmeasured_class"] == C.UNMEASURED_LOOP_NEIGHBOUR


def test_step_refuses_when_the_directory_is_absent(tmp_path):
    out = C.loop_key_over_a_declared_list(tmp_path, _tail())
    assert out["status"] == "UNMEASURED"
    assert out["unmeasured_class"] == C.UNMEASURED_LOOP_POPULATION
    assert out["files_unreadable"]


def test_step_refuses_when_an_unparsable_file_lies_in_the_walk(tmp_path):
    for sub in C.OPEN_COUNTER_DIRS:
        (tmp_path / sub).mkdir(parents=True, exist_ok=True)
    (tmp_path / C.OPEN_COUNTER_DIRS[0] / "broken.py").write_text(
        "def (:\n", encoding="utf-8")
    out = C.loop_key_over_a_declared_list(tmp_path, _tail())
    assert out["status"] == "UNMEASURED"
    assert out["unmeasured_class"] == C.UNMEASURED_LOOP_POPULATION


def test_step_refuses_when_the_two_walks_disagree(tmp_path):
    for sub in C.OPEN_COUNTER_DIRS:
        (tmp_path / sub).mkdir(parents=True, exist_ok=True)
    out = C.loop_key_over_a_declared_list(tmp_path, _tail(dynamic=3))
    assert out["status"] == "UNMEASURED"
    assert out["unmeasured_class"] == C.UNMEASURED_LOOP_POPULATION
    assert out["population"] == 0
    assert out["declared_population"] == 3


def test_step_refuses_when_its_own_control_fails(monkeypatch, tmp_path):
    for sub in C.OPEN_COUNTER_DIRS:
        (tmp_path / sub).mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(C, "_loop_key_control",
                        lambda: {"passed": False, "reason": "сцена порвана"})
    out = C.loop_key_over_a_declared_list(tmp_path, _tail(dynamic=0))
    assert out["status"] == "UNMEASURED"
    assert out["unmeasured_class"] == C.UNMEASURED_LOOP_CONTROL
    assert "сцена порвана" in out["reason"]


def test_a_refusal_is_never_a_zero():
    """НЕ ИЗМЕРЕНО обязано быть отличимо от «разрешено ноль»."""
    out = C.loop_key_over_a_declared_list(Path("."), None)
    assert "loop_step_outcomes" not in out
    assert out.get("resolved_by_the_loop_key_step") is None


# ================================================= КОНТРОЛИ НА КОНТРОЛЬ

def test_control_fails_if_the_positive_scene_resolves_nothing(monkeypatch):
    monkeypatch.setattr(C, "LOOP_KEY_CONTROL_SOURCE", "X = 1\n")
    control = C._loop_key_control()
    assert control["passed"] is False
    assert "положительной сцене" in control["reason"]


def test_control_fails_if_a_positive_counter_is_left_unresolved(monkeypatch):
    """Сцена из двух счётчиков, один из которых правило разрешить не может."""
    broken = C.LOOP_KEY_CONTROL_SOURCE.replace(
        'for k in ("p", "q"):', "for k in sorted(c):")  # только у `beta`
    monkeypatch.setattr(C, "LOOP_KEY_CONTROL_SOURCE", broken)
    control = C._loop_key_control()
    assert control["passed"] is False
    assert "положительной сцены" in control["reason"]


def test_control_fails_if_only_one_proof_form_is_exercised(monkeypatch):
    """Сцена, доказавшая одну форму из двух, силы правила не доказывает."""
    single = (C.LOOP_KEY_CONTROL_SOURCE
              .replace('for k in ("p", "q"):', "for k in EXTS:")
              .replace('for j in ("r", "s"):', "for j in EXTS:"))
    monkeypatch.setattr(C, "LOOP_KEY_CONTROL_SOURCE", single)
    control = C._loop_key_control()
    assert control["passed"] is False
    assert "формами" in control["reason"]


def test_control_fails_if_the_negative_scene_resolves_a_counter(monkeypatch):
    """Правило, которому всё годится, звена не имеет."""
    loose = C.LOOP_KEY_CONTROL_CLEAN.replace("for k in sorted(c):",
                                             "for k in GOOD:")
    monkeypatch.setattr(C, "LOOP_KEY_CONTROL_CLEAN", loose)
    control = C._loop_key_control()
    assert control["passed"] is False
    assert "разрешил" in control["reason"]


def test_control_fails_if_a_declared_gap_name_is_never_produced(monkeypatch):
    """Имя, которое сцена не предъявила, есть обещание разбора без разбора."""
    monkeypatch.setattr(C, "_LOOP_GAPS",
                        tuple(C._LOOP_GAPS) + ("a_name_no_scene_produces",))
    control = C._loop_key_control()
    assert control["passed"] is False
    assert "объявлено" in control["reason"]


def test_control_fails_when_the_scene_does_not_parse(monkeypatch):
    monkeypatch.setattr(C, "LOOP_KEY_CONTROL_SOURCE", "def (:\n")
    control = C._loop_key_control()
    assert control["passed"] is False
    assert "не разобрана" in control["reason"]


# ============================== ФОРМА ОТВЕТА: ЗАКРЫТА, СУММА РАВНА НАСЕЛЕНИЮ

def test_outcome_form_is_closed_and_two_because_wholesale_is_unreachable():
    assert C._LOOP_KEY_OUTCOMES == (C.ONE_STEP_SPLITS, C.ONE_STEP_UNRESOLVED)
    assert C.ONE_STEP_WHOLESALE not in C._LOOP_KEY_OUTCOMES


def test_measured_answer_sums_to_the_population(tmp_path):
    for sub in C.OPEN_COUNTER_DIRS:
        (tmp_path / sub).mkdir(parents=True, exist_ok=True)
    (tmp_path / C.OPEN_COUNTER_DIRS[0] / "scene.py").write_text(
        C.LOOP_KEY_CONTROL_SOURCE, encoding="utf-8")
    out = C.loop_key_over_a_declared_list(tmp_path, _tail(dynamic=3))
    assert out["status"] == "MEASURED"
    assert out["population"] == 3
    assert sum(out["loop_step_outcomes"].values()) == out["population"]
    assert sum(out["unresolved_reasons"].values()) == out["still_unmeasured"]


def test_every_zero_is_declared_not_omitted(tmp_path):
    """Инв. #17: ноль ОБЪЯВЛЕН, а не пропущен."""
    for sub in C.OPEN_COUNTER_DIRS:
        (tmp_path / sub).mkdir(parents=True, exist_ok=True)
    (tmp_path / C.OPEN_COUNTER_DIRS[0] / "scene.py").write_text(
        C.LOOP_KEY_CONTROL_SOURCE, encoding="utf-8")
    out = C.loop_key_over_a_declared_list(tmp_path, _tail(dynamic=3))
    assert sorted(out["unresolved_reasons"]) == sorted(C._LOOP_GAPS)
    assert sorted(out["resolved_by"]) == sorted(C._LOOP_PROOFS)
    assert set(out["loop_step_outcomes"]) == set(C._LOOP_KEY_OUTCOMES)


def test_the_step_says_its_population_out_loud(tmp_path):
    """Заказ требует сказать население вслух — не примечанием, а полем."""
    for sub in C.OPEN_COUNTER_DIRS:
        (tmp_path / sub).mkdir(parents=True, exist_ok=True)
    (tmp_path / C.OPEN_COUNTER_DIRS[0] / "scene.py").write_text(
        C.LOOP_KEY_CONTROL_SOURCE, encoding="utf-8")
    out = C.loop_key_over_a_declared_list(tmp_path, _tail(dynamic=3))
    assert out["population_is_one_counter"] is False
    assert any("НАСЕЛЕНИЕ ШАГА" in line for line in out["blind"])


def test_the_step_is_advisory_and_changes_nothing(tmp_path):
    for sub in C.OPEN_COUNTER_DIRS:
        (tmp_path / sub).mkdir(parents=True, exist_ok=True)
    out = C.loop_key_over_a_declared_list(tmp_path, _tail(dynamic=0))
    assert out["applied"] is False
    assert out["order"] == "G85.4"


# ================================== ПОПРАВКА К ЗНАМЕНАТЕЛЮ — НАЗВАНА, НЕ ВНЕСЕНА

def test_the_false_member_census_finds_the_index_of_an_enumeration():
    """`EXTENSIONS[cut - 1]` — индекс в объявленный перечень: класс объявлен
    не хуже, чем у литерала, и счётчик незнакомому классу НЕ открыт."""
    source = ("A = 'a'\nB = 'b'\nEXTS = (A, B)\n\n\n"
              "def measure(rows):\n"
              "    by_ext = {e: 0 for e in EXTS}\n"
              "    for cut in range(1, len(EXTS) + 1):\n"
              "        by_ext[EXTS[cut - 1]] += 1\n"
              "    return {'by_ext': by_ext}\n")
    out = C._written_key_from_an_enumeration("<scene>", ast.parse(source))
    assert out["population"] == 1
    assert out["forms"][C.FALSE_BY_INDEX] == 1
    assert out["forms"][C.FALSE_NOT_PROVED] == 0
    assert out["sample"][0]["counter"] == "by_ext"


def test_a_loop_bound_key_never_reaches_this_population():
    """ПОЛОЖИТЕЛЬНЫЙ контроль на то, ПОЧЕМУ формы «переменная цикла» в
    поправке нет вовсе: соседский `_key_origin` идёт по связываниям до
    неподвижной точки и такой ключ разрешает САМ — в население «открытых
    счётчиков» он не попадает. Течь одна, и она названа: короткое замыкание
    `_reads_data` на любой подписке.
    """
    source = ("A = 'a'\nEXTS = (A,)\n\n\n"
              "def measure(rows):\n"
              "    tally = {e: 0 for e in EXTS}\n"
              "    for k in EXTS:\n"
              "        tally[k] = tally.get(k, 0) + 1\n"
              "    return {'tally': tally}\n")
    tree = ast.parse(source)
    origins = {s["key_origin"] for s in C._open_counter_sites("<scene>", tree)}
    assert C.KEY_ARTIFACT not in origins, origins
    out = C._written_key_from_an_enumeration("<scene>", tree)
    assert out["population"] == 0
    assert C.FALSE_BY_INDEX in C._FALSE_MEMBER_FORMS


def test_the_false_member_census_does_not_claim_a_key_from_data():
    """Ключ из данных ложным членом НЕ объявляется: свидетель односторонний."""
    source = ("def measure(rows):\n"
              "    tally = {}\n"
              "    for row in rows:\n"
              "        tally[row['cls']] = tally.get(row['cls'], 0) + 1\n"
              "    return {'tally': tally}\n")
    out = C._written_key_from_an_enumeration("<scene>", ast.parse(source))
    assert out["population"] == 1
    assert out["forms"][C.FALSE_NOT_PROVED] == 1
    assert out["forms"][C.FALSE_BY_INDEX] == 0
    assert out["sample"] == []


def test_the_false_member_form_is_closed_and_has_a_third_outcome():
    assert C.FALSE_KEY_NODE_ABSENT in C._FALSE_MEMBER_FORMS
    assert len(set(C._FALSE_MEMBER_FORMS)) == len(C._FALSE_MEMBER_FORMS)


def test_the_correction_is_reported_but_not_applied(tmp_path):
    """Поправка к знаменателю НАЗВАНА числом и НЕ применена: население соседа
    остаётся как есть, числа прошлых решений не пересчитываются."""
    for sub in C.OPEN_COUNTER_DIRS:
        (tmp_path / sub).mkdir(parents=True, exist_ok=True)
    (tmp_path / C.OPEN_COUNTER_DIRS[0] / "scene.py").write_text(
        C.LOOP_KEY_CONTROL_SOURCE, encoding="utf-8")
    out = C.loop_key_over_a_declared_list(tmp_path, _tail(dynamic=3))
    false = out["false_members_of_the_neighbour_population"]
    assert sum(false["forms"].values()) == false["population"]
    assert any("НЕ применена" in line for line in out["blind"])


def test_the_step_does_not_add_an_open_counter_of_its_own():
    """Прибор, добавляющий себя в измеряемый класс, мерит уже не дерево:
    первая редакция этого шага подняла население соседа 171 → 172 строкой
    `false_forms[form] += count`."""
    src = Path(C.__file__).read_text(encoding="utf-8")
    block = src.split("КЛЮЧ ИЗ ЦИКЛА — заказ G85 п. 4", 1)[1]
    block = block.split("def registry_ambiguity_scope", 1)[0]
    # Нарезанный текст модулем не является, поэтому спрашивается ФОРМА, а не
    # разбор: открытый счётчик у этого шага был бы `d[k] += n` по ключу из
    # данных, и именно эта строка стояла в черновике.
    assert "false_forms[form] += count" not in block
    assert "false_by_file.append" in block


# ======================================================== ПРОВОДКА В ПЕРЕПИСЬ

def test_the_step_is_wired_into_the_measure():
    src = Path(C.__file__).read_text(encoding="utf-8")
    assert "loop_key_step = loop_key_over_a_declared_list(root, tail_step)" in src
    assert f'"{STEP}": loop_key_step,' in src


def test_the_report_names_the_step_and_its_refusal():
    unmeasured = {STEP: {"status": "UNMEASURED",
                         "unmeasured_class": C.UNMEASURED_LOOP_NEIGHBOUR,
                         "reason": "соседа нет"}}
    lines = C.report(unmeasured)
    assert any("[КЛЮЧ ИЗ ЦИКЛА] НЕ ИЗМЕРЕНО" in line for line in lines)


def test_the_report_says_not_measured_when_the_step_is_missing():
    lines = C.report({})
    assert any("[КЛЮЧ ИЗ ЦИКЛА] НЕ ИЗМЕРЕНО — перепись собрана без" in line
               for line in lines)


def test_the_report_prints_the_measured_answer(tmp_path):
    for sub in C.OPEN_COUNTER_DIRS:
        (tmp_path / sub).mkdir(parents=True, exist_ok=True)
    (tmp_path / C.OPEN_COUNTER_DIRS[0] / "scene.py").write_text(
        C.LOOP_KEY_CONTROL_SOURCE, encoding="utf-8")
    step = C.loop_key_over_a_declared_list(tmp_path, _tail(dynamic=3))
    lines = C.report({STEP: step})
    assert any("[КЛЮЧ · ЧЕМ ДОКАЗАН]" in line for line in lines)
    assert any("[КЛЮЧ · ПОЧЕМУ НЕ ДОКАЗАН]" in line for line in lines)
    assert any("[КЛЮЧ · НАСЕЛЕНИЕ]" in line for line in lines)
    assert any("[КЛЮЧ · ПОПРАВКА К ЗНАМЕНАТЕЛЮ]" in line for line in lines)


def test_the_step_declares_what_it_does_not_prove(tmp_path):
    for sub in C.OPEN_COUNTER_DIRS:
        (tmp_path / sub).mkdir(parents=True, exist_ok=True)
    out = C.loop_key_over_a_declared_list(tmp_path, _tail(dynamic=0))
    assert out["what_it_does_not_prove"]
    assert any("ДОРОГА" in line for line in out["what_it_does_not_prove"])


# ================================== СОСЕДСКОЕ ПРАВИЛО НЕ ПЕРЕПИСАНО (ОДНА КОПИЯ)

def test_the_step_owns_no_rule_about_what_a_split_is():
    """Раскол считает сосед; вторая копия правила и есть предмет переписи."""
    src = Path(C.__file__).read_text(encoding="utf-8")
    block = src.split("КЛЮЧ ИЗ ЦИКЛА — заказ G85 п. 4", 1)[1]
    block = block.split("def registry_ambiguity_scope", 1)[0]
    assert "_one_step_reader(" in block
    assert "SPLIT_AT_COUNTER" not in block
    assert "READER_WHOLE_ATTRS" not in block


def test_the_step_owns_no_rule_about_what_a_declared_class_is():
    src = Path(C.__file__).read_text(encoding="utf-8")
    block = src.split("КЛЮЧ ИЗ ЦИКЛА — заказ G85 п. 4", 1)[1]
    block = block.split("def registry_ambiguity_scope", 1)[0]
    assert "_is_declared_class(" in block
    assert "isupper()" not in block


def test_the_reads_walk_has_one_copy_and_two_readers():
    """Область читателя добывается соседским обходом, а не вторым."""
    src = Path(C.__file__).read_text(encoding="utf-8")
    assert src.count("def _defensive_tail_reads(") == 1
    assert src.count("_defensive_tail_reads(") == 3


# ===================== ДОБОР ПО ВЫЖИВШИМ МУТАНТАМ (разбор, а не зачёт)

def _prep(source: str, fn_name: str):
    tree, fn = _scope(source, fn_name)
    declared = C._declared_constant_names(tree)
    once, rebound = C._module_declared_enumerations(tree, declared)
    module_names = set(C.toplevel_constants(tree)) | once | rebound
    return tree, fn, declared, once, rebound, module_names


def test_a_mixed_display_declares_nothing():
    """`all`, а не `any`: перечень, где объявлен ЛИШЬ ЧАСТЬ элементов, класса
    своей переменной цикла не объявляет — иначе объявленность доказывалась бы
    одним удачным элементом из пяти."""
    tree = ast.parse("A = 'a'\nMIXED = (A, len('x'))\nGOOD = (A,)\n")
    declared = C._declared_constant_names(tree)
    once, _rebound = C._module_declared_enumerations(tree, declared)
    assert "GOOD" in once
    assert "MIXED" not in once
    mixed = ast.parse("(A, len('x'))", mode="eval").body
    assert C._declared_enumeration_display(mixed, {"A"}) is False


def test_one_tuple_target_is_enough_to_refuse():
    """`any`, а не `all`: достаточно ОДНОГО цикла с кортежной целью — про этот
    ключ уже не известно, что он пробегает перечень."""
    source = ("E = ('a',)\nP = (('a', 1),)\n\n\ndef f(c):\n"
              "    out = []\n"
              "    for k in E:\n"
              "        out.append(c.get(k, 0))\n"
              "    for k, _n in P:\n"
              "        out.append(c.get(k, 0))\n"
              "    return out\n")
    _tree, fn, declared, once, rebound, names = _prep(source, "f")
    out = C._loop_key_proof(fn, "k", declared, once, rebound, names)
    assert out == {"gap": C.LOOP_GAP_TUPLE_TARGET}


def test_the_gap_order_is_a_permutation_of_the_declared_gaps():
    """Порядок ПОЛОН: имя вне него ронял бы `.index` громко, а запасная ветка
    «первый попавшийся» выдала бы тихое не то."""
    assert sorted(C._LOOP_GAP_ORDER) == sorted(C._LOOP_GAPS)


def test_the_most_expensive_reason_is_named_first():
    """Два цикла и стороннее связывание разом ⇒ назван СПОР, а не дешёвое
    «итерируемое не имя модуля»: имя отказа есть указание, что чинить."""
    source = ("E = ('a',)\n\n\ndef f(c, row):\n"
              "    out = []\n"
              "    for k in E:\n"
              "        out.append(c.get(k, 0))\n"
              "    for k in sorted(c):\n"
              "        out.append(c.get(k, 0))\n"
              "    return out\n")
    _tree, fn, declared, once, rebound, names = _prep(source, "f")
    out = C._loop_key_reader(fn, "c", declared, once, rebound, names)
    assert out["gap"] == C.LOOP_GAP_LOOPS_DISAGREE


def test_a_read_the_tail_step_never_reached_is_marked_false():
    """Флаг `behind` честен: чтение, до которого шаг за хвост НЕ дошёл, не
    объявляется своим — иначе ЧУЖОЙ предел считался бы нашим.

    Сцена несёт оба случая под одним полем: `late_reader` связывает
    прочитанное за защитным хвостом (шаг доходит), `early_reader` пробегает
    прочитанное ЦЕЛИКОМ и связывания не имеет вовсе (шаг не доходит).
    """
    source = ("E = ('a',)\n\n\ndef writer(rows):\n"
              "    counts = {}\n"
              "    for row in rows:\n"
              "        counts[row['cls']] = counts.get(row['cls'], 0) + 1\n"
              "    return {'z': counts}\n\n\n"
              "def early_reader(doc):\n"
              "    return len(doc['z'])\n\n\n"
              "def late_reader(doc):\n"
              "    c = doc['z'] or {}\n"
              "    return [c.get(k, 0) for k in E]\n")
    tree = ast.parse(source)
    owner_of = C._counter_owner_scopes(tree)
    declared = C._declared_constant_names(tree)
    writer = [n for n in ast.walk(tree)
              if isinstance(n, ast.FunctionDef) and n.name == "writer"][0]
    reads = list(C._defensive_tail_reads(tree, owner_of, declared, writer, "z"))
    flags = sorted(behind for *_rest, behind in reads)
    assert flags == [False, True], reads
    # и шаг за ключ берёт РОВНО одно из двух — то, до которого сосед дошёл
    out = C._loop_key_step(tree, owner_of, declared, writer, "z",
                           {"E"}, set(), {"E"})
    assert out["reads_by_a_loop_key"] == 1
    assert out["verdict"] == C.ONE_STEP_SPLITS


def test_a_counter_that_never_travels_stays_out_of_the_population():
    """ГРАНИЦА НАСЕЛЕНИЯ — отдельное требование, а не следствие имён: счётчик,
    прочитанный на месте, к этому шагу не относится вовсе."""
    fields = {r["field"] for r in _negative()}
    assert "kappa" not in fields
    assert len(_negative()) == len(C._LOOP_GAPS)


def test_control_fails_when_two_counters_share_one_gap_name(monkeypatch):
    """Клауза «два класса под одним именем»: имена все семь, а отказов восемь."""
    duplicate = C.LOOP_KEY_CONTROL_CLEAN + '''

def lambda_writer(rows):
    counts = {}
    for row in rows:
        counts[row["cls"]] = counts.get(row["cls"], 0) + 1
    return {"lam": counts}


def lambda_caller(rows):
    doc = lambda_writer(rows)
    return len(doc)


def lambda_reader(doc):
    c = doc["lam"] or {}
    out = []
    for k in sorted(c):
        out.append(c.get(k, 0))
    return out
'''
    monkeypatch.setattr(C, "LOOP_KEY_CONTROL_CLEAN", duplicate)
    control = C._loop_key_control()
    assert control["passed"] is False
    assert "объявленных имён" in control["reason"]


def test_the_false_member_lookup_survives_a_key_longer_than_the_truncation():
    """Обрезка ключа обязана совпадать с соседской: разойдись она на один
    символ — узел записи «не найден» у всякого длинного ключа."""
    long_name = "a_very_long_enumeration_name_that_surely_exceeds_sixty_chars"
    source = (f"A = 'a'\n{long_name} = (A,)\n\n\n"
              "def measure(rows):\n"
              f"    by_ext = {{e: 0 for e in {long_name}}}\n"
              f"    for cut in range(1, len({long_name}) + 1):\n"
              f"        by_ext[{long_name}[cut - 1]] += 1\n"
              "    return {'by_ext': by_ext}\n")
    tree = ast.parse(source)
    key = [s["key"] for s in C._open_counter_sites("<scene>", tree)][0]
    assert len(key) == 60, len(key)
    out = C._written_key_from_an_enumeration("<scene>", tree)
    assert out["forms"][C.FALSE_KEY_NODE_ABSENT] == 0
    assert out["forms"][C.FALSE_BY_INDEX] == 1


def test_the_false_member_census_has_a_live_third_outcome(monkeypatch):
    """Ветка «узел записи не найден» НЕДОСТИЖИМА через сам шаг (обе стороны
    ищут узел одним помощником и одной обрезкой), поэтому проверяется ПРЯМЫМ
    подставлением населения — порядком ADR-466/467."""
    source = ("def measure(rows):\n"
              "    tally = {}\n"
              "    for row in rows:\n"
              "        tally[row['cls']] = tally.get(row['cls'], 0) + 1\n"
              "    return {'tally': tally}\n")
    tree = ast.parse(source)
    real = C._open_counter_sites

    def _moved(rel, parsed):
        return [{**s, "line": (s["line"] or 0) + 1000}
                for s in real(rel, parsed)]

    monkeypatch.setattr(C, "_open_counter_sites", _moved)
    out = C._written_key_from_an_enumeration("<scene>", tree)
    assert out["population"] == 1
    assert out["forms"][C.FALSE_KEY_NODE_ABSENT] == 1
    assert out["forms"][C.FALSE_NOT_PROVED] == 0


def _measured(tmp_path, source, dynamic):
    for sub in C.OPEN_COUNTER_DIRS:
        (tmp_path / sub).mkdir(parents=True, exist_ok=True)
    (tmp_path / C.OPEN_COUNTER_DIRS[0] / "scene.py").write_text(
        source, encoding="utf-8")
    return C.loop_key_over_a_declared_list(tmp_path, _tail(dynamic=dynamic))


def test_each_gap_is_counted_once_on_the_negative_scene(tmp_path):
    """Счёт отказов ИМЕНАМИ: сумма равна населению, и каждое имя ровно один
    раз. Двойной инкремент или перевёрнутое сравнение видны здесь, а не в
    сцене, где все отказы нулевые."""
    out = _measured(tmp_path, C.LOOP_KEY_CONTROL_CLEAN, len(C._LOOP_GAPS))
    assert out["status"] == "MEASURED", out.get("reason")
    assert out["population"] == len(C._LOOP_GAPS)
    assert out["still_unmeasured"] == len(C._LOOP_GAPS)
    assert out["resolved_by_the_loop_key_step"] == 0
    assert out["unresolved_reasons"] == {gap: 1 for gap in C._LOOP_GAPS}
    assert sum(out["unresolved_reasons"].values()) == out["population"]


def test_each_proof_form_is_counted_once_on_the_positive_scene(tmp_path):
    out = _measured(tmp_path, C.LOOP_KEY_CONTROL_SOURCE, 3)
    assert out["status"] == "MEASURED", out.get("reason")
    # Счётчиков три, а форм две — и третий несёт ОБЕ разом: на симметричной
    # сцене (по счётчику на форму) перевёрнутое `in` дало бы те же числа.
    assert out["resolved_by"] == {C.LOOP_BY_MODULE_ENUM: 2,
                                 C.LOOP_BY_ENUM_IN_PLACE: 2}
    assert out["resolved_by_the_loop_key_step"] == 3
    assert out["still_unmeasured"] == 0


def test_the_harm_sample_carries_the_reading_that_proves_the_split(tmp_path):
    """Пример обязан называть ЧТЕНИЕ. Пустой `split` есть отчёт без улики."""
    out = _measured(tmp_path, C.LOOP_KEY_CONTROL_SOURCE, 3)
    assert len(out["harm_sample"]) == 3
    assert all(item["split"] for item in out["harm_sample"]), out["harm_sample"]
    assert all("get(" in item["split"] for item in out["harm_sample"])
    assert out["unresolved_sample"] == []


def test_the_unresolved_sample_carries_only_refused_rows(tmp_path):
    out = _measured(tmp_path, C.LOOP_KEY_CONTROL_CLEAN, len(C._LOOP_GAPS))
    assert out["harm_sample"] == []
    assert out["unresolved_sample"]
    assert all(item["gap"] in C._LOOP_GAPS
               for item in out["unresolved_sample"])


def test_the_step_counts_the_files_it_walked(tmp_path):
    """`files_scanned` есть ЗАМЕР обхода, а не украшение отчёта."""
    out = _measured(tmp_path, C.LOOP_KEY_CONTROL_SOURCE, 3)
    assert out["files_scanned"] == 1
    (tmp_path / C.OPEN_COUNTER_DIRS[0] / "second.py").write_text(
        "X = 1\n", encoding="utf-8")
    again = C.loop_key_over_a_declared_list(tmp_path, _tail(dynamic=3))
    assert again["files_scanned"] == 2


def test_the_skip_rule_is_the_neighbour_one_and_is_exercised(tmp_path):
    """Правило пропуска дословно соседское; перечень односоставный, поэтому
    `any` и `all` на нём совпадают — сказано вслух, а не зачтено молча."""
    assert C.OPEN_COUNTER_SKIP == ("scripts/archive",)
    skipped = tmp_path / "scripts" / "archive"
    skipped.mkdir(parents=True, exist_ok=True)
    (skipped / "old.py").write_text(C.LOOP_KEY_CONTROL_SOURCE,
                                    encoding="utf-8")
    (tmp_path / "spa_core" / "monitoring").mkdir(parents=True, exist_ok=True)
    out = C.loop_key_over_a_declared_list(tmp_path, _tail(dynamic=0))
    assert out["status"] == "MEASURED", out.get("reason")
    assert out["population"] == 0


def test_a_site_without_a_counter_node_is_skipped_not_crashed(monkeypatch):
    """Вторая половина охраны населения: узла счётчика нет ⇒ шагать некуда.
    Разобранное дерево такого узла не даёт, поэтому население ПОДСТАВЛЯЕТСЯ —
    порядком ADR-466/467. Слей охрану в «и», и `_field_step` упал бы на `None`.
    """
    tree = ast.parse(C.LOOP_KEY_CONTROL_SOURCE)
    real = C._one_step_site_nodes

    def _with_a_nodeless_site(rel, parsed):
        rows = list(real(rel, parsed))
        first = dict(rows[0][0]) if rows else {"step_gap": C.STEP_GAP_CONTAINER}
        first["step_gap"] = C.STEP_GAP_CONTAINER
        return [(first, None, parsed)] + rows

    monkeypatch.setattr(C, "_one_step_site_nodes", _with_a_nodeless_site)
    rows = C._loop_key_sites("<scene>", tree)
    assert len(rows) == 3, [r["field"] for r in rows]


def test_a_row_can_carry_both_proof_forms_at_once():
    """Строка с ДВУМЯ ключами разом — не редкость сцены, а её содержание:
    на симметричной сцене счёт форм нельзя отличить от перевёрнутого."""
    both = [r for r in _positive() if len(r["loop_proofs"]) == 2]
    assert len(both) == 1, [(r["field"], r["loop_proofs"]) for r in _positive()]
    assert sorted(both[0]["loop_keys"]) == ["j", "k"]


def test_the_population_flag_is_true_only_for_a_single_counter(tmp_path):
    """Заказ требует сказать население ВСЛУХ, и на живом дереве оно РАВНО
    ОДНОМУ. Признак обязан быть верен в обе стороны: на сцене из одного
    счётчика — истина, на сцене из трёх — ложь.
    """
    one = ("E = ('a',)\n\n\ndef writer(rows):\n"
           "    counts = {}\n"
           "    for row in rows:\n"
           "        counts[row['cls']] = counts.get(row['cls'], 0) + 1\n"
           "    return {'z': counts}\n\n\n"
           "def caller(rows):\n"
           "    doc = writer(rows)\n"
           "    return len(doc)\n\n\n"
           "def reader(doc):\n"
           "    c = doc['z'] or {}\n"
           "    return [c.get(k, 0) for k in E]\n")
    single = _measured(tmp_path, one, 1)
    assert single["status"] == "MEASURED", single.get("reason")
    assert single["population"] == 1
    assert single["population_is_one_counter"] is True
    many = _measured(tmp_path, C.LOOP_KEY_CONTROL_SOURCE, 3)
    assert many["population"] == 3
    assert many["population_is_one_counter"] is False
