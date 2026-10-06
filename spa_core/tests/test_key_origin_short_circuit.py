"""Батарея шага «течь правила ключа, измеренная целиком» (заказ G100 п. 1, ADR-574).

Шаг G99 п. 1 нашёл ОДИН ложный член знаменателя ряда и назвал его причину:
соседский ``_reads_data`` отвечает ``True`` на ЛЮБУЮ подписку РАНЬШЕ, чем идёт
обход связываний. Заказ G100 п. 1 просит дословно:

    Спросить тем же порядком у ВСЕХ 171: сколько ключей «из артефакта»
    разрешились бы обходом связываний, если спросить его ДО короткого
    замыкания, а не после. Односторонность назвать заранее: правка правила
    соседа сдвигает знаменатель тринадцати решений разом, и применять её
    замером нельзя — только отдельным решением.

Батарея устроена по ЗВЕНЬЯМ: зелёный контур целиком, красное на КАЖДОМ
порванном звене с НАЗВАННЫМ звеном, и отказ там, где предпосылка не
обеспечена. Отдельный разряд — на ЧЕСТНОСТЬ РАЗНОСТИ: шаг мерит два прогона
ОДНОГО тела, и поэтому обязан доказывать, что при обоих выключенных
переключателях это тело есть соседское правило, а не его пересказ.

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

STEP = "key_origin_before_the_short_circuit"


# --------------------------------------------------------------- вход сцены

def _hit(budget=C.RELOC_BUDGET_NODES):
    rows, _shifts, _peer = C._reloc_sites(
        "<scene>", ast.parse(C.RELOC_CONTROL_SOURCE), budget_nodes=budget)
    return rows


def _clean():
    rows, _shifts, _peer = C._reloc_sites(
        "<scene-clean>", ast.parse(C.RELOC_CONTROL_CLEAN))
    return rows


def _by_owner(rows):
    return {r["owner"]: r for r in rows}


def _neighbour(population):
    """Сосед, ответивший как на живом дереве."""
    return {"status": "MEASURED", "open_to_an_unnamed_class": population}


def _tree(tmp_path: Path, **modules: str) -> Path:
    """Одноразовое дерево с ОБОИМИ объявленными каталогами."""
    for sub in C.OPEN_COUNTER_DIRS:
        (tmp_path / sub).mkdir(parents=True, exist_ok=True)
    for name, body in modules.items():
        (tmp_path / C.OPEN_COUNTER_DIRS[0] / f"{name}.py").write_text(
            body, encoding="utf-8")
    return tmp_path


# ------------------------------------------- строгий свидетель против соседа

@pytest.mark.parametrize("source", ["[]", "()", "{}", "set()"])
def test_the_strict_witness_refuses_an_empty_literal(source):
    """Пустой литерал класса НЕ объявляет — на этом и держится вся разность."""
    expr = ast.parse(source, mode="eval").body
    assert not C._nonempty_literal_enumeration(expr)


@pytest.mark.parametrize("source", ['("a", "b")', '["a"]', '{"a": 1}'])
def test_the_strict_witness_accepts_a_non_empty_literal(source):
    expr = ast.parse(source, mode="eval").body
    assert C._nonempty_literal_enumeration(expr)
    assert C._literal_enumeration(expr)


def test_the_two_witnesses_differ_exactly_on_the_empty_literal():
    """РАЗНИЦА свидетелей обязана быть ровно одна — иначе разность прогонов
    мерила бы не дыру, а два разных правила."""
    for source in ("[]", "()", "{}"):
        expr = ast.parse(source, mode="eval").body
        assert C._literal_enumeration(expr)
        assert not C._nonempty_literal_enumeration(expr)
    for source in ('("a",)', '{"k": 0}', '"a"', "name", "f(x)"):
        expr = ast.parse(source, mode="eval").body
        assert (C._literal_enumeration(expr)
                == C._nonempty_literal_enumeration(expr))


# ------------------------------------------------------- тождество тела

def test_both_switches_off_reproduce_the_neighbour_rule_on_the_scenes():
    """Пока это не доказано, любая разность мерила бы описку во второй копии."""
    for source in (C.RELOC_CONTROL_SOURCE, C.RELOC_CONTROL_CLEAN):
        _rows, shifts, _peer = C._reloc_sites("<scene>", ast.parse(source))
        assert [s for s in shifts if s["identity"] != s["neighbour"]] == []


def test_both_switches_off_reproduce_the_neighbour_rule_on_the_producer():
    """Сцена мала; тождество обязано держаться и на НАСТОЯЩЕМ файле."""
    tree = ast.parse(Path(C.__file__).read_text(encoding="utf-8"))
    _rows, shifts, _peer = C._reloc_sites(C.PRODUCER, tree)
    broken = [s for s in shifts if s["identity"] != s["neighbour"]]
    assert broken == [], broken[:3]


def test_a_broken_identity_refuses_the_whole_step(tmp_path, monkeypatch):
    """Положительный контроль на отказ: тело разошлось ⇒ шаг НЕ мерит.

    Расхождение подаётся только на НАСТОЯЩИХ файлах (имена сцен начинаются
    с ``<``), и это не удобство: сломай его и на сцене — первым откажет
    КОНТРОЛЬ, а не тождество. Тот порядок проверяется соседним тестом.
    """
    root = _tree(tmp_path, m=C.RELOC_CONTROL_CLEAN)
    real = C._reloc_sites

    def forging(rel, tree, **kw):
        rows, shifts, peer = real(rel, tree, **kw)
        if not rel.startswith("<"):
            shifts = shifts + [{"file": rel, "line": 1, "key": "k",
                                "neighbour": C.KEY_ARTIFACT,
                                "identity": C.KEY_LITERAL,
                                "strict_same_order": C.KEY_ARTIFACT}]
        return rows, shifts, peer

    monkeypatch.setattr(C, "_reloc_sites", forging)
    out = C.key_origin_before_the_short_circuit(root, _neighbour(2))
    assert out["status"] == "UNMEASURED"
    assert out["unmeasured_class"] == C.UNMEASURED_RELOC_IDENTITY
    assert out["identity_broken"] >= 1


def test_a_body_that_lies_everywhere_is_caught_by_the_control_first(
        tmp_path, monkeypatch):
    """Порядок отказов — не случайность: контроль идёт ДО замера, поэтому
    тело, соврав и на сцене, не доходит до сверки тождества вовсе."""
    root = _tree(tmp_path, m=C.RELOC_CONTROL_CLEAN)
    real = C._key_origin_variant

    def lying(expr, binds, mb, params, seen, budget, *, relocate, strict):
        if not relocate and not strict:
            return C.KEY_LITERAL                      # заведомо не соседское
        return real(expr, binds, mb, params, seen, budget,
                    relocate=relocate, strict=strict)

    monkeypatch.setattr(C, "_key_origin_variant", lying)
    out = C.key_origin_before_the_short_circuit(root, _neighbour(2))
    assert out["status"] == "UNMEASURED"
    assert out["unmeasured_class"] == C.UNMEASURED_RELOC_CONTROL


# ------------------------------------------------- две двери и их различие

def test_the_relocation_refutes_the_key_whose_every_free_name_is_declared():
    row = _by_owner(_hit())["refuted_by_a_non_empty_enumeration"]
    assert row["relocated"] == C.RELOC_DECLARED
    assert row["witness"] == C.RELOC_SURVIVES_STRICT


def test_the_known_false_member_is_seen_by_the_container_and_not_by_the_relocation():
    """`ENUM[cut]` — форма ADR-566. Индекс не разрешается ничем, и «часть
    ключа объявлена» вердиктом перестановки не является."""
    row = _by_owner(_hit())["the_known_false_member"]
    assert row["relocated"] == C.RELOC_STILL_ARTIFACT
    assert row["witness"] == C.RELOC_RESTS_ON_NOTHING
    assert row["container"] == C.RELOC_CONTAINER_SEQUENCE


def test_the_empty_literal_refutation_does_not_survive_the_strict_witness():
    """Главная находка шага: опровержение, стоящее на `rows = []`."""
    row = _by_owner(_hit())["refuted_only_by_an_empty_literal"]
    assert row["relocated"] == C.RELOC_DECLARED
    assert row["relocated_strict"] == C.RELOC_STILL_ARTIFACT
    assert row["witness"] == C.RELOC_RESTS_ON_EMPTY


def test_a_key_that_really_comes_from_data_is_left_alone():
    row = _by_owner(_hit())["still_an_artifact"]
    assert row["relocated"] == C.RELOC_STILL_ARTIFACT
    assert row["witness"] == C.RELOC_RESTS_ON_NOTHING


def test_the_relocation_has_its_own_third_outcome():
    """`UNRESOLVED` не есть опровержение и не есть артефакт."""
    row = _by_owner(_hit())["unresolved_under_the_relocation"]
    assert row["relocated"] == C.RELOC_UNRESOLVED
    assert row["relocated"] not in C._RELOC_REFUTING
    assert row["witness"] == C.RELOC_RESTS_ON_NOTHING


def test_the_literal_outcome_has_a_live_case():
    row = _by_owner(_hit())["refuted_to_a_plain_literal"]
    assert row["relocated"] == C.RELOC_LITERAL
    assert row["relocated"] in C._RELOC_REFUTING


@pytest.mark.parametrize("owner", [
    "refuted_by_a_non_empty_enumeration", "the_known_false_member",
    "the_known_false_member_again", "refuted_only_by_an_empty_literal",
    "still_an_artifact", "refuted_to_a_plain_literal",
    "unresolved_under_the_relocation"])
def test_every_scene_site_is_in_the_open_population(owner):
    """Сцена обязана попадать в население СОСЕДА, иначе она мимо предмета."""
    assert owner in _by_owner(_hit())


def test_the_negative_half_refutes_nothing(tmp_path):
    rows = _clean()
    assert rows, "отрицательная половина пуста — «опровергнуто 0» ничего не значит"
    assert [r for r in rows if r["relocated"] in C._RELOC_REFUTING] == []
    assert [r for r in rows
            if r["container"] in C._RELOC_CONTAINER_DECLARING] == []


def test_a_literal_key_never_enters_the_population():
    owners = {r["owner"] for r in _clean()}
    assert "a_literal_key_is_not_in_the_population" not in owners


# ------------------------------------------------- дверь контейнера, точно

def _container(source: str, scope_src: str = "") -> str:
    tree = ast.parse(scope_src + "\nVALUE = " + source + "\n")
    binds = C._scope_bindings(tree)
    expr = ast.parse(source, mode="eval").body
    return C._subscript_container_kind(expr, binds, binds, set(), set(),
                                       [C.RELOC_BUDGET_NODES])


def test_a_mapping_with_constant_keys_is_not_a_declaring_container():
    """`D[k]` отдаёт ЗНАЧЕНИЕ: объявленность КЛЮЧЕЙ о классе не говорит
    ничего. Соседский свидетель перечня проверяет у словаря именно ключи."""
    assert _container('{"a": compute()}') == C.RELOC_CONTAINER_UNDECLARED


def test_a_mapping_with_constant_values_is_a_declaring_container():
    assert _container('{"a": "alpha"}') == C.RELOC_CONTAINER_MAPPING_VALUES


def test_an_empty_container_is_not_declaring():
    assert _container("[]") == C.RELOC_CONTAINER_UNDECLARED
    assert _container("{}") == C.RELOC_CONTAINER_UNDECLARED


def test_a_parameter_container_does_not_resolve():
    expr = ast.parse("rows", mode="eval").body
    assert C._subscript_container_kind(expr, {}, {}, {"rows"}, set(),
                                       [C.RELOC_BUDGET_NODES]
                                       ) == C.RELOC_CONTAINER_UNRESOLVED


def test_disagreeing_bindings_do_not_declare_the_container():
    scope = 'ENUM = ("a", "b")\n' + "if flag:\n    ENUM = load()\n"
    tree = ast.parse(scope)
    binds = C._scope_bindings(tree)
    expr = ast.parse("ENUM", mode="eval").body
    assert C._subscript_container_kind(expr, binds, binds, set(), set(),
                                       [C.RELOC_BUDGET_NODES]
                                       ) == C.RELOC_CONTAINER_UNDECLARED


# ------------------------------------------------------------------ бюджет

def test_a_starved_budget_gives_a_third_outcome_and_never_a_refutation():
    """Обрыв обхода обязан отвечать «не измерено», а не чинить знаменатель."""
    outcomes = {r["relocated"] for r in _hit(budget=1)}
    assert C.RELOC_BUDGET_SPENT in outcomes
    assert not (outcomes & set(C._RELOC_REFUTING))


def test_the_budget_is_spent_per_key_and_not_per_file():
    """Общий бюджет на файл сделал бы вердикт зависящим от ПОРЯДКА ключей."""
    rows = _hit()
    assert {r["relocated"] for r in rows} != {C.RELOC_BUDGET_SPENT}
    assert len(rows) > 1


def test_the_budget_outcome_is_outside_the_refuting_set():
    assert C.RELOC_BUDGET_SPENT not in C._RELOC_REFUTING
    assert C.RELOC_UNRESOLVED not in C._RELOC_REFUTING


# ------------------------------------------------------------------ контроль

def test_the_control_passes_as_written():
    control = C._reloc_control()
    assert control["passed"], control.get("reason")
    assert control["clean_false_positives"] == 0
    assert control["refuted_only_by_the_container"] == 2
    assert control["refuted_by_both_doors_on_the_scene"] == 1
    assert control["starved_refutations_outside_the_full_run"] == 0


def test_the_control_refuses_when_an_outcome_has_no_live_case(monkeypatch):
    """Положительный контроль на отказ №2: исход без живого случая."""
    head, rest = C.RELOC_CONTROL_SOURCE.split(
        "def refuted_to_a_plain_literal", 1)
    short = head + rest.split("def moved_by_the_strict_witness", 1)[1].join(
        ["def moved_by_the_strict_witness", ""])
    monkeypatch.setattr(C, "RELOC_CONTROL_SOURCE", short)
    control = C._reloc_control()
    assert not control["passed"]
    assert "украшение" in control["reason"]


def test_the_control_refuses_when_the_empty_literal_is_not_separated(monkeypatch):
    """Положительный контроль на отказ №3: опоры опровержения слиты."""
    without = C.RELOC_CONTROL_SOURCE.replace(
        '    rows = []\n', '    rows = load()\n', 1)
    monkeypatch.setattr(C, "RELOC_CONTROL_SOURCE", without)
    control = C._reloc_control()
    assert not control["passed"]
    assert C.RELOC_RESTS_ON_EMPTY in control["reason"] or "опора" in control["reason"]


def test_the_control_refuses_on_a_false_positive_in_the_clean_half(monkeypatch):
    """Положительный контроль на отказ №4: поправка завышена."""
    dirty = C.RELOC_CONTROL_CLEAN + '''

def a_false_positive(doc):
    acc = {}
    rows = []
    for row in rows:
        acc[row["cls"]] = acc.get(row["cls"], 0) + 1
    return acc
'''
    monkeypatch.setattr(C, "RELOC_CONTROL_CLEAN", dirty)
    control = C._reloc_control()
    assert not control["passed"]
    assert "ЗАВЫШЕНА" in control["reason"]


def test_the_control_refuses_when_the_scene_does_not_parse(monkeypatch):
    monkeypatch.setattr(C, "RELOC_CONTROL_SOURCE", "def broken(:\n")
    control = C._reloc_control()
    assert not control["passed"]
    assert "не разобрана" in control["reason"]


def test_a_failed_control_refuses_the_measurement(tmp_path, monkeypatch):
    monkeypatch.setattr(C, "RELOC_CONTROL_SOURCE", "def broken(:\n")
    out = C.key_origin_before_the_short_circuit(_tree(tmp_path),
                                                _neighbour(0))
    assert out["status"] == "UNMEASURED"
    assert out["unmeasured_class"] == C.UNMEASURED_RELOC_CONTROL


# ------------------------------------------------------- отказы самого шага

@pytest.mark.parametrize("neighbour", [
    None, {}, {"status": "UNMEASURED"},
    {"status": "MEASURED"}])
def test_an_unmeasured_neighbour_refuses_the_step(tmp_path, neighbour):
    """Знаменателя нет ⇒ течь не «равна нулю», а НЕ ИЗМЕРЕНА."""
    out = C.key_origin_before_the_short_circuit(_tree(tmp_path), neighbour)
    assert out["status"] == "UNMEASURED"
    assert out["unmeasured_class"] == C.UNMEASURED_RELOC_NEIGHBOUR


def test_a_missing_directory_is_unmeasured_not_empty(tmp_path):
    (tmp_path / C.OPEN_COUNTER_DIRS[0]).mkdir(parents=True)
    out = C.key_origin_before_the_short_circuit(tmp_path, _neighbour(0))
    assert out["status"] == "UNMEASURED"
    assert out["unmeasured_class"] == C.UNMEASURED_RELOC_UNREADABLE


def test_an_unparsable_file_is_unmeasured_not_skipped(tmp_path):
    root = _tree(tmp_path)
    (root / C.OPEN_COUNTER_DIRS[0] / "broken.py").write_text(
        "def broken(:\n", encoding="utf-8")
    out = C.key_origin_before_the_short_circuit(root, _neighbour(0))
    assert out["status"] == "UNMEASURED"
    assert out["unmeasured_class"] == C.UNMEASURED_RELOC_UNREADABLE


def test_a_population_disagreement_refuses_the_step(tmp_path):
    root = _tree(tmp_path, m=C.RELOC_CONTROL_SOURCE)
    out = C.key_origin_before_the_short_circuit(root, _neighbour(999))
    assert out["status"] == "UNMEASURED"
    assert out["unmeasured_class"] == C.UNMEASURED_RELOC_POPULATION
    assert out["declared_population"] == 999


def test_a_coordinate_disagreement_refuses_even_when_the_numbers_agree(
        tmp_path, monkeypatch):
    """Потеря узла и удвоение другого население не меняют, а раскладку — да."""
    root = _tree(tmp_path, m=C.RELOC_CONTROL_SOURCE)
    real = C._reloc_sites

    def shifted(rel, tree, **kw):
        rows, shifts, peer = real(rel, tree, **kw)
        if peer:
            peer = [(f, (line or 0) + 1000, c, k) for f, line, c, k in peer]
        return rows, shifts, peer

    monkeypatch.setattr(C, "_reloc_sites", shifted)
    population = len(real("m.py", ast.parse(C.RELOC_CONTROL_SOURCE))[0])
    out = C.key_origin_before_the_short_circuit(root, _neighbour(population))
    assert out["status"] == "UNMEASURED"
    assert out["unmeasured_class"] == C.UNMEASURED_RELOC_COORDINATES


# ------------------------------------------------------------------ вердикт

def _measured(tmp_path):
    """Сцена кладётся по пути ПРОИЗВОДИТЕЛЯ намеренно: иначе `own_sites`
    пусто, и его числа не проверены ничем."""
    root = _tree(tmp_path)
    (root / C.PRODUCER).write_text(C.RELOC_CONTROL_SOURCE, encoding="utf-8")
    rows, _s, _p = C._reloc_sites(C.PRODUCER,
                                  ast.parse(C.RELOC_CONTROL_SOURCE))
    return C.key_origin_before_the_short_circuit(root, _neighbour(len(rows)))


def test_the_outcomes_sum_to_the_population(tmp_path):
    """Инв. #17: сумма исходов равна населению, а ноль объявлен."""
    out = _measured(tmp_path)
    assert out["status"] == "MEASURED"
    assert sum(out["relocated_outcomes"].values()) == out["population"]
    assert out["relocated_outcomes_outside_the_closed_list"] == 0
    assert set(out["relocated_outcomes"]) == set(C._RELOC_OUTCOMES)


def test_the_witness_axis_also_sums_to_the_population(tmp_path):
    out = _measured(tmp_path)
    assert sum(out["refutation_rests_on"].values()) == out["population"]
    assert set(out["refutation_rests_on"]) == set(C._RELOC_WITNESSES)


def test_the_container_axis_also_sums_to_the_population(tmp_path):
    out = _measured(tmp_path)
    assert sum(out["subscript_container_kinds"].values()) == out["population"]
    assert set(out["subscript_container_kinds"]) == set(C._RELOC_CONTAINERS)


def test_the_answer_separates_the_literal_reading_from_the_honest_one(tmp_path):
    """Сцена несёт ОДНО опровержение на пустом литерале — и два знаменателя
    обязаны разойтись ровно на него."""
    out = _measured(tmp_path)
    answer = out["answer"]
    rests = out["refutation_rests_on"]
    assert rests[C.RELOC_RESTS_ON_EMPTY] == 1
    assert (answer["denominator_under_the_honest_reading"]
            - answer["denominator_under_the_literal_reading"]) == 1
    assert (answer["refuted_by_the_relocation"]
            > answer["refuted_by_the_relocation_on_a_real_enumeration"])


def test_the_two_doors_are_counted_separately_and_their_overlap_measured(
        tmp_path):
    out = _measured(tmp_path)
    answer = out["answer"]
    assert answer["refuted_by_the_container_form"] >= 1
    assert answer["refuted_by_either_door"] == (
        answer["refuted_by_the_relocation"]
        + answer["refuted_by_the_container_form"]
        - answer["refuted_by_both_doors"])


def test_the_step_changes_nothing_it_measures(tmp_path):
    """ADVISORY: поправка НАЗВАНА и НЕ применена."""
    out = _measured(tmp_path)
    assert out["applied"] is False
    assert any("не пересчитаны" in s for s in out["what_it_does_not_prove"])


def test_the_producer_declares_its_own_sites(tmp_path):
    out = _measured(tmp_path)
    assert out["own_sites"]["producer"] == C.PRODUCER
    assert "in_the_population" in out["own_sites"]


def test_the_strict_witness_axis_is_reported_even_when_it_is_zero(tmp_path):
    """Ноль здесь — утверждение («дыра закрыта замыканием»), а не молчание."""
    out = _measured(tmp_path)
    assert "neighbour_verdicts_moved_by_the_strict_witness" in out
    assert isinstance(out["neighbour_verdicts_moved_by_the_strict_witness"],
                      int)


# ------------------------------------------------------------------ отчёт

def test_the_step_is_wired_into_the_census_under_its_own_key():
    """Шаг, которого нет в отчёте, не читает никто."""
    src = Path(C.__file__).read_text(encoding="utf-8")
    assert ("short_circuit_step = key_origin_before_the_short_circuit("
            in src)
    assert f'"{STEP}": short_circuit_step,' in src


def test_a_missing_step_is_printed_as_unmeasured_not_as_silence():
    text = "\n".join(C.report({}))
    assert "[ТЕЧЬ ПРАВИЛА КЛЮЧА] НЕ ИЗМЕРЕНО" in text


def test_an_unmeasured_step_prints_its_named_reason():
    text = "\n".join(C.report({STEP: {
        "status": "UNMEASURED",
        "unmeasured_class": C.UNMEASURED_RELOC_IDENTITY,
        "reason": "тело разошлось"}}))
    assert C.UNMEASURED_RELOC_IDENTITY in text


def test_the_verdict_names_both_readings_out_loud(tmp_path):
    """Число, лежащее в поле и не произнесённое, читателю не достаётся."""
    text = "\n".join(C.report({STEP: _measured(tmp_path)}))
    assert "[ТЕЧЬ ПРАВИЛА КЛЮЧА]" in text
    assert "[ТЕЧЬ · ОТВЕТ ЗАКАЗА]" in text
    assert "ПУСТОЙ литерал" in text
    assert "[ТЕЧЬ · ЧЕМ ДЕРЖИТСЯ ЗАМЫКАНИЕ]" in text
    assert "[ТЕЧЬ · ТОЖДЕСТВО ТЕЛА]" in text


def test_the_report_prints_the_budget_as_a_choice(tmp_path):
    text = "\n".join(C.report({STEP: _measured(tmp_path)}))
    assert str(C.RELOC_BUDGET_NODES) in text
    assert any("ВЫБОР, а не свойство дерева" in line
               for line in C.report({STEP: _measured(tmp_path)}))


@pytest.mark.parametrize("name", list(C._RELOC_OUTCOMES)
                         + list(C._RELOC_WITNESSES)
                         + list(C._RELOC_CONTAINERS))
def test_every_declared_name_is_distinct_and_non_empty(name):
    assert isinstance(name, str) and name
    assert len({*C._RELOC_OUTCOMES, *C._RELOC_WITNESSES,
                *C._RELOC_CONTAINERS}) == (len(C._RELOC_OUTCOMES)
                                           + len(C._RELOC_WITNESSES)
                                           + len(C._RELOC_CONTAINERS))


def test_the_refusal_classes_are_distinct():
    classes = (C.UNMEASURED_RELOC_NEIGHBOUR, C.UNMEASURED_RELOC_CONTROL,
               C.UNMEASURED_RELOC_POPULATION, C.UNMEASURED_RELOC_COORDINATES,
               C.UNMEASURED_RELOC_IDENTITY, C.UNMEASURED_RELOC_UNREADABLE)
    assert len(set(classes)) == len(classes)


# ===========================================================================
# ЗАКРЫТИЕ ДЫР СЦЕНЫ, найденных мутационным стендом (33 выживших из 129).
# Каждый тест ниже написан ПО КОНКРЕТНОМУ мутанту: сцена шести счётчиков не
# доводила до его ветки, и «убит» было неотличимо от «не наблюдаем».
# ===========================================================================

def _variant(source: str, *, relocate: bool, strict: bool,
             budget: int = C.RELOC_BUDGET_NODES, scope: str = "",
             params=()) -> str:
    """Вердикт варианта у ОДНОГО выражения, без сцены со счётчиками."""
    tree = ast.parse(scope) if scope else ast.parse("")
    binds = C._scope_bindings(tree)
    expr = ast.parse(source, mode="eval").body
    return C._key_origin_variant(expr, binds, binds, set(params), set(),
                                 [budget], relocate=relocate, strict=strict)


# ---- бюджет: ПОРОГ, а не наличие ветки (мутанты `budget -= 1`, `<= 0`)

def _threshold(source: str, scope: str, *, relocate=True) -> int:
    """Наименьший бюджет, при котором вердикт перестаёт быть «исчерпан»."""
    for budget in range(1, 60):
        if _variant(source, relocate=relocate, strict=False, budget=budget,
                    scope=scope) != C.RELOC_BUDGET_SPENT:
            return budget
    raise AssertionError("порог не найден в разумных пределах")


def test_the_budget_is_spent_exactly_one_node_per_visit():
    """`budget -= 2` и `<= 1` сдвинули бы ПОРОГ, не тронув наличие ветки."""
    scope = 'KINDS = ("a", "b")\nmid = KINDS[0]\ntag = mid\n'
    # Три посещения узла: `tag` → `mid` → `KINDS[0]`; на четвёртом шаге
    # свидетель перечня отвечает без рекурсии. `budget -= 2` удвоил бы порог,
    # `budget[0] <= 1` сдвинул бы его на единицу.
    assert _threshold("tag", scope) == 3


def test_the_container_budget_is_spent_one_node_per_visit():
    scope = 'KINDS = ("a", "b")\nalias = KINDS\n'
    for budget in (1, 2):
        assert C._subscript_container_kind(
            ast.parse("alias", mode="eval").body,
            C._scope_bindings(ast.parse(scope)),
            C._scope_bindings(ast.parse(scope)), set(), set(),
            [budget]) == C.RELOC_CONTAINER_BUDGET
    assert C._subscript_container_kind(
        ast.parse("alias", mode="eval").body,
        C._scope_bindings(ast.parse(scope)),
        C._scope_bindings(ast.parse(scope)), set(), set(),
        [3]) == C.RELOC_CONTAINER_SEQUENCE


# ---- переключатель `relocate` у выражения БЕЗ свободных имён

def test_a_nameless_subscript_is_an_artifact_under_both_switches():
    """Мутант `if relocate and not names` вернул бы здесь «не разрешилось»:
    у выражения имён нет, а подписка есть."""
    assert _variant('"abc"[0]', relocate=True, strict=False) == C.KEY_ARTIFACT
    assert _variant('"abc"[0]', relocate=False, strict=False) == C.KEY_ARTIFACT


def test_a_nameless_expression_without_a_read_is_unresolved():
    assert _variant("1 + 2", relocate=True, strict=False) == C.KEY_UNRESOLVED


# ---- примесь вердиктов: «часть ключа объявлена» вердиктом не является

def test_a_mixture_of_declared_and_literal_is_declared_not_a_fallthrough():
    """Мутант `verdicts < {...}` (строгое подмножество) провалил бы ровно
    этот случай: оба класса присутствуют, и подмножество перестаёт быть
    собственным."""
    scope = 'ENUM = ("a", "b")\nlit = "z"\nmix = ENUM[0] if lit else lit\n'
    assert _variant("mix", relocate=True, strict=False,
                    scope=scope) == C.KEY_DECLARED


def test_a_mixture_with_an_artifact_is_not_refuted():
    scope = 'ENUM = ("a", "b")\nmix = ENUM[0]\n'
    assert _variant("mix + doc['x']", relocate=True, strict=False,
                    scope=scope, params=("doc",)) == C.KEY_ARTIFACT


# ---- контейнер: `seen` и `params` — РАЗНЫЕ двери (мутант `or` → `and`)

def test_a_container_already_seen_does_not_resolve():
    scope = "alias = alias\n"
    binds = C._scope_bindings(ast.parse(scope))
    expr = ast.parse("alias", mode="eval").body
    assert C._subscript_container_kind(expr, binds, binds, set(), {"alias"},
                                       [C.RELOC_BUDGET_NODES]
                                       ) == C.RELOC_CONTAINER_UNRESOLVED


def test_a_container_that_is_only_a_parameter_does_not_resolve():
    scope = 'alias = ("a", "b")\n'
    binds = C._scope_bindings(ast.parse(scope))
    expr = ast.parse("alias", mode="eval").body
    assert C._subscript_container_kind(expr, binds, binds, {"alias"}, set(),
                                       [C.RELOC_BUDGET_NODES]
                                       ) == C.RELOC_CONTAINER_UNRESOLVED


# ---- усечение имён в строке: ширина объявлена, а не случайна

def test_the_counter_and_the_key_are_truncated_to_sixty_characters():
    long_name = "k" * 90
    src = (f'def wide(doc):\n'
           f'    {long_name} = {{}}\n'
           f'    {long_name}[doc["{"c" * 90}"]] = '
           f'{long_name}.get(doc["{"c" * 90}"], 0) + 1\n')
    rows, _s, _p = C._reloc_sites("<wide>", ast.parse(src))
    assert len(rows) == 1
    assert len(rows[0]["counter"]) == 60
    assert len(rows[0]["key"]) == 60


# ---- защитная ветка сортировки обоснована ЗАМЕРОМ, а не надеждой

def test_every_row_carries_an_integer_line():
    """`item["line"] or 0` в ключе сортировки недостижим: `lineno` у узлов,
    из которых строятся строки, задан всегда. Утверждение — здесь."""
    rows, shifts, _p = C._reloc_sites("<scene>",
                                      ast.parse(C.RELOC_CONTROL_SOURCE))
    for row in list(rows) + list(shifts):
        assert isinstance(row["line"], int)


# ---- контракт отображения исходов: почему третий счётчик сегодня ноль

def test_the_outcome_mapping_covers_the_closed_list_exactly():
    """Пока это равенство держится, `*_outside_the_closed_list` недостижим —
    и это ОБЪЯВЛЕНО, а не случайно."""
    assert set(C._RELOC_BY_ORIGIN.values()) == set(C._RELOC_OUTCOMES)
    assert set(C._RELOC_BY_ORIGIN) == {C.KEY_ARTIFACT, C.KEY_DECLARED,
                                       C.KEY_LITERAL, C.KEY_UNRESOLVED,
                                       C.RELOC_BUDGET_SPENT}


# ---- ось «строгий свидетель двигает соседа» умеет отвечать ДА

def test_the_strict_witness_axis_can_answer_yes_on_the_scene():
    """Ноль на живом дереве есть утверждение лишь тогда, когда ось вообще
    способна ответить иначе."""
    _rows, shifts, _p = C._reloc_sites("<scene>",
                                       ast.parse(C.RELOC_CONTROL_SOURCE))
    moved = [s for s in shifts
             if s["strict_same_order"] != s["neighbour"]]
    assert len(moved) == 1
    assert moved[0]["owner"] == "moved_by_the_strict_witness"
    assert moved[0]["neighbour"] == C.KEY_DECLARED
    assert moved[0]["strict_same_order"] != C.KEY_DECLARED


def test_the_control_refuses_when_the_scene_cannot_move_the_strict_witness(
        monkeypatch):
    without = C.RELOC_CONTROL_SOURCE.split(
        "def moved_by_the_strict_witness")[0] + C.RELOC_CONTROL_SOURCE.split(
        "def unresolved_under_the_relocation")[1].join(
        ["def unresolved_under_the_relocation", ""])
    monkeypatch.setattr(C, "RELOC_CONTROL_SOURCE", without)
    control = C._reloc_control()
    assert not control["passed"]
    assert "неспособность ответить" in control["reason"]


# ---- оставшиеся ветви отказа контроля: каждая с живым случаем

def test_the_control_refuses_when_the_two_roads_disagree(monkeypatch):
    real = C._reloc_sites

    def losing_peer(rel, tree, **kw):
        rows, shifts, peer = real(rel, tree, **kw)
        if rel == "<control-clean>":
            peer = peer[:-1]
        return rows, shifts, peer

    monkeypatch.setattr(C, "_reloc_sites", losing_peer)
    control = C._reloc_control()
    assert not control["passed"]
    assert "две дороги" in control["reason"]


def test_the_control_refuses_when_the_budget_outcome_never_appears(
        monkeypatch):
    real = C._reloc_sites

    def never_starved(rel, tree, **kw):
        return real(rel, tree)          # бюджет не передаётся — голода нет

    monkeypatch.setattr(C, "_reloc_sites", never_starved)
    control = C._reloc_control()
    assert not control["passed"]
    assert "не предъявился ни разу" in control["reason"]


def test_the_control_refuses_when_a_starved_traversal_refutes(monkeypatch):
    real = C._reloc_sites

    def starving_refutes(rel, tree, **kw):
        rows, shifts, peer = real(rel, tree, **kw)
        if kw.get("budget_nodes") == 1:
            rows = [dict(r) for r in rows]
            # опровержение подаётся там, где ПОЛНЫЙ обход его не даёт —
            # иначе голод ничего не создал, а лишь повторил полный ответ
            victim = next(i for i, r in enumerate(rows)
                          if r["relocated"] == C.RELOC_STILL_ARTIFACT)
            rows[victim]["relocated"] = C.RELOC_DECLARED
            other = next(i for i in range(len(rows)) if i != victim)
            rows[other]["relocated"] = C.RELOC_BUDGET_SPENT
        return rows, shifts, peer

    monkeypatch.setattr(C, "_reloc_sites", starving_refutes)
    control = C._reloc_control()
    assert not control["passed"]
    assert "ПРОИЗВЁЛ опровержение" in control["reason"]


def test_the_control_refuses_when_the_two_doors_are_not_separated(monkeypatch):
    """`ENUM[cut]` обязан опровергаться ТОЛЬКО контейнером; слить двери —
    значит сделать ответ заказу неразложимым."""
    merged = C.RELOC_CONTROL_SOURCE.replace(
        "def the_known_false_member(cut):\n    acc = {}\n"
        "    acc[KINDS[cut]] = acc.get(KINDS[cut], 0) + 1\n",
        "def the_known_false_member():\n    acc = {}\n"
        "    acc[KINDS[0]] = acc.get(KINDS[0], 0) + 1\n", 1)
    monkeypatch.setattr(C, "RELOC_CONTROL_SOURCE", merged)
    control = C._reloc_control()
    assert not control["passed"]
    assert "неразложим" in control["reason"]


def test_the_control_refuses_when_the_clean_half_declares_a_container(
        monkeypatch):
    dirty = C.RELOC_CONTROL_CLEAN + '''

ENUM = ("a", "b")


def a_declared_container_in_the_clean_half(cut):
    acc = {}
    acc[ENUM[cut]] = acc.get(ENUM[cut], 0) + 1
    return acc
'''
    monkeypatch.setattr(C, "RELOC_CONTROL_CLEAN", dirty)
    control = C._reloc_control()
    assert not control["passed"]
    assert "контейнер назван объявленным" in control["reason"]


# ---- вердикт: ЧИСЛА, а не присутствие полей

def test_the_answer_numbers_are_exact_on_the_scene(tmp_path):
    answer = _measured(tmp_path)["answer"]
    assert answer == {
        "refuted_by_the_relocation": 3,
        "refuted_by_the_relocation_on_a_real_enumeration": 2,
        "refuted_by_the_container_form": 3,
        "refuted_by_both_doors": 1,
        "refuted_by_either_door": 5,
        "denominator_now": 7,
        "denominator_under_the_literal_reading": 2,
        "denominator_under_the_honest_reading": 3,
    }


def test_the_witness_counts_are_exact_on_the_scene(tmp_path):
    assert _measured(tmp_path)["refutation_rests_on"] == {
        C.RELOC_RESTS_ON_EMPTY: 1,
        C.RELOC_SURVIVES_STRICT: 2,
        C.RELOC_RESTS_ON_NOTHING: 4,
    }


def test_the_producer_counts_its_own_sites_and_not_the_others(tmp_path):
    """Сцена лежит по пути производителя, поэтому числа ненулевые и
    проверяемы: подмена `==` на `!=` их переворачивает."""
    own = _measured(tmp_path)["own_sites"]
    assert own == {"producer": C.PRODUCER, "in_the_population": 7,
                   "refuted_by_either_door": 5}


def test_the_number_of_files_scanned_is_reported_and_true(tmp_path):
    assert _measured(tmp_path)["files_scanned"] == 1


def test_the_two_parity_flags_are_true_and_not_decoration(tmp_path):
    out = _measured(tmp_path)
    assert out["coordinates_agree_with_the_neighbour"] is True
    assert out["variant_reproduces_the_neighbour"] is True


def test_the_strict_witness_axis_counts_the_scene_case(tmp_path):
    assert _measured(tmp_path)[
        "neighbour_verdicts_moved_by_the_strict_witness"] == 1


def test_the_refuted_sample_holds_refuted_sites_only(tmp_path):
    out = _measured(tmp_path)
    assert {item["owner"] for item in out["refuted_sample"]} <= {
        "refuted_by_a_non_empty_enumeration", "the_known_false_member",
        "refuted_only_by_an_empty_literal", "refuted_to_a_plain_literal",
        "the_known_false_member_again"}
    assert out["refuted_sample"]


def test_the_budget_sample_is_empty_when_no_budget_was_spent(tmp_path):
    out = _measured(tmp_path)
    assert out["relocated_outcomes"][C.RELOC_BUDGET_SPENT] == 0
    assert out["budget_spent_sample"] == []


# ---- вторая волна: мутанты, пережившие первое закрытие дыр сцены

def test_an_artifact_reached_only_through_a_binding_stays_an_artifact():
    """Мутант `if not not names` вернул бы здесь «не разрешилось»: замыкание
    на ВЕРХУ ключа молчит, а артефакт пришёл шагом ниже, по связыванию."""
    scope = 'tag = doc["x"]\n'
    assert _variant("tag", relocate=True, strict=False, scope=scope,
                    params=("doc",)) == C.KEY_ARTIFACT
    assert _variant("tag", relocate=False, strict=False, scope=scope,
                    params=("doc",)) == C.KEY_ARTIFACT


def test_the_scene_separates_both_doors_from_the_container_alone():
    """Два числа и они РАЗНЫЕ: при равенстве подмена «не опровергается
    перестановкой» на «опровергается» переставила бы их незаметно."""
    rows = _hit()
    only_container = [r for r in rows
                      if r["container"] in C._RELOC_CONTAINER_DECLARING
                      and r["relocated"] not in C._RELOC_REFUTING]
    both = [r for r in rows
            if r["container"] in C._RELOC_CONTAINER_DECLARING
            and r["relocated"] in C._RELOC_REFUTING]
    assert len(only_container) == 2
    assert len(both) == 1
    assert {r["owner"] for r in only_container} == {
        "the_known_false_member", "the_known_false_member_again"}


def test_the_control_reports_a_measured_zero_not_a_printed_one():
    """Поле «голод опроверг лишнего» есть ЗАМЕР разности, а не литерал 0."""
    control = C._reloc_control()
    assert control["starved_refutations_outside_the_full_run"] == 0
    full = {r["line"] for r in _hit() if r["relocated"] in C._RELOC_REFUTING}
    starved = {r["line"] for r in _hit(budget=1)
               if r["relocated"] in C._RELOC_REFUTING}
    assert starved - full == set()


def test_the_outside_counter_is_a_difference_not_a_tally(tmp_path):
    """Третий счётчик недостижим, пока отображение полно, — и считается он
    разностью, чтобы недостижимость не прятала ещё и подмену счёта."""
    out = _measured(tmp_path)
    assert (out["relocated_outcomes_outside_the_closed_list"]
            == out["population"] - sum(out["relocated_outcomes"].values()))
    assert out["relocated_outcomes_outside_the_closed_list"] == 0


def test_the_control_refuses_when_only_one_of_the_two_counts_breaks(
        monkeypatch):
    """Третья волна мутации: при сцене, где ломается РОВНО ОДНО из двух
    чисел, подмена `or` на `and` и подмена `in` на `not in` в отборе
    «только контейнер» проходили бы контроль незамеченными."""
    head, rest = C.RELOC_CONTROL_SOURCE.split(
        "def the_known_false_member_again", 1)
    one_less = head + rest.split("def refuted_only_by_an_empty_literal", 1)[
        1].join(["def refuted_only_by_an_empty_literal", ""])
    monkeypatch.setattr(C, "RELOC_CONTROL_SOURCE", one_less)
    control = C._reloc_control()
    assert not control["passed"]
    assert control["only_container"] == 1
    assert control["both_doors"] == 1
    assert "неразложим" in control["reason"]
