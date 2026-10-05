"""Батарея шага «род накопителя у СВЯЗЫВАНИЯ» (заказ G85 п. 2, ADR-518).

ADR-469 померил форму вреда у писателя и у части населения ответил ТРЕТЬИМ
исходом: род накопителя не измерен. Заказ G85 п. 2 просит разобрать остаток и
просит дословно:

    Шестнадцать неизмеренных родов. Восемь связаны вне области записи, восемь
    пришли непрозрачным вызовом. Первые чинятся межобластным разбором, вторые —
    расширением перечня конструкторов; односторонность назвать заранее и
    ограничить звеном (перечень обязан оставаться ЗАКРЫТЫМ).

Батарея устроена по ЗВЕНЬЯМ: зелёный контур целиком, красное на КАЖДОМ
порванном звене с НАЗВАННЫМ звеном, и отказ там, где предпосылка не обеспечена.
Отдельный разряд тестов — на ЧЕСТНОСТЬ ИМЕНИ: шаг обязан ловить вердикт,
утверждающий о накопителе то, чего о нём не спрашивали, и обязан не повторять
этой ошибки сам (`the_caller_argument_is_outside_the_closed_list` существует
именно поэтому).

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

STEP = "accumulator_kind_at_the_binding"


# --------------------------------------------------------------- вход сцены

def _hit():
    return [s for s in C._binding_kind_sites(
        "<scene>", ast.parse(C.KIND_BINDING_CONTROL_SOURCE))
        if s["writer"] == C.WRITER_UNRESOLVED]


def _clean():
    return [s for s in C._binding_kind_sites(
        "<scene-clean>", ast.parse(C.KIND_BINDING_CONTROL_CLEAN))
        if s["writer"] == C.WRITER_UNRESOLVED]


def _writer(unresolved=17):
    """Сосед, ответивший как на живом дереве: N третьих исходов."""
    return {"status": "MEASURED",
            "unresolved_reasons": {
                C.WRITER_GAP_NO_BINDING: 8,
                C.WRITER_GAP_OPAQUE: unresolved - 8,
                C.WRITER_GAP_MANY_KINDS: 0}}


def _scene(tmp_path: Path, *, source: str) -> Path:
    """Одноразовое дерево с ОДНИМ файлом в каталоге, который обходит шаг."""
    base = tmp_path / C.OPEN_COUNTER_DIRS[0]
    base.mkdir(parents=True, exist_ok=True)
    (base / "scene.py").write_text(source, encoding="utf-8")
    for extra in C.OPEN_COUNTER_DIRS[1:]:
        (tmp_path / extra).mkdir(parents=True, exist_ok=True)
    return tmp_path


# ------------------------------------------------- ЗЕЛЁНЫЙ КОНТУР ЦЕЛИКОМ

def test_control_passes_on_the_declared_rule():
    """Объявленное правило проходит ОБЕИМИ половинами своей сцены."""
    control = C._binding_kind_control()
    assert control["passed"], control.get("reason")


def test_positive_half_proves_the_kind_by_all_three_named_repairs():
    """Ремонт без живого случая есть украшение, а не правило."""
    control = C._binding_kind_control()
    by_repair = control["by_repair"]
    assert set(by_repair) == set(C._KIND_REPAIRS)
    assert all(by_repair[r] for r in C._KIND_REPAIRS), by_repair


def test_tuple_repair_tells_a_strict_accumulator_from_a_forgiving_one():
    """Иначе род оказался бы свойством ФОРМЫ связывания, а не накопителя.

    Это ядро ремонта: `_scope_bindings` отдаёт ОБОИМ именам кортежной цели
    одну правую часть, поэтому разбор обязан взять СВОЙ элемент по положению —
    возьми он кортеж целиком, оба счётчика получили бы один род.
    """
    control = C._binding_kind_control()
    assert control["by_repair"][C.REPAIR_TUPLE_POSITION] == ["forgiving",
                                                             "strict"]


def test_sequence_is_its_own_outcome_not_a_third_one():
    """Находка о НАСЕЛЕНИИ не имеет права утонуть в «род не измерен»."""
    seqs = [s for s in _hit()
            if s["kind_outcome"] == C.KIND_NOT_A_MAPPING]
    assert len(seqs) == 1, [s["counter"] for s in seqs]
    assert seqs[0]["kind_gap"] is None


def test_negative_half_answers_nothing_about_the_kind():
    """«Ремонт доказал род у N» ≠ «ремонт объявляет род у чего угодно»."""
    assert all(s["kind_outcome"] == C.KIND_STILL_UNMEASURED
               for s in _clean()), [s["counter"] for s in _clean()]


def test_negative_half_splits_its_refusals_by_all_four_names():
    """Отказ без своей причины посылает чинить не то."""
    assert {s["kind_gap"] for s in _clean()} == set(C._KIND_GAPS)


# --------------------------------------- КАЖДОЕ ЗВЕНО ПОРВАНО ПООДИНОЧКЕ

def test_control_refuses_when_the_tuple_repair_stops_splitting_by_position(
        monkeypatch):
    """Порвано звено «свой элемент по положению» — контроль обязан покраснеть."""
    monkeypatch.setattr(C, "_tuple_position_kind",
                        lambda name, expr, scope: None)
    control = C._binding_kind_control()
    assert not control["passed"]
    assert "ремонт" in control["reason"] or "род" in control["reason"]


def test_control_refuses_when_the_element_default_repair_is_blinded(
        monkeypatch):
    """Порвано звено «умолчание `setdefault`»."""
    monkeypatch.setattr(C, "_literal_default_of_setdefault", lambda expr: None)
    control = C._binding_kind_control()
    assert not control["passed"]
    assert control["by_repair"][C.REPAIR_ELEMENT_DEFAULT] == []


def test_control_refuses_when_the_caller_repair_is_blinded(monkeypatch):
    """Порвано звено «аргумент зовущего»: межобластной разбор не работает.

    Оба ремонта этого звена гаснут разом, и так и должно быть: ВТОРОЕ звено
    (ADR-573) стоит на том же обходе зовущих, и доказать род без него не может
    ни первое, ни оно само.
    """
    monkeypatch.setattr(C, "_caller_argument_kinds",
                        lambda name, scope, tree: [])
    control = C._binding_kind_control()
    assert not control["passed"]
    assert control["by_repair"][C.REPAIR_CALLER_ARGUMENT] == []
    assert control["by_repair"][C.REPAIR_SECOND_LINK] == []


def test_control_refuses_when_a_sequence_is_read_as_a_mapping(monkeypatch):
    """Порвано звено «это не отображение» — поправка к населению исчезает."""
    monkeypatch.setattr(C, "_sequence_binding", lambda expr: False)
    control = C._binding_kind_control()
    assert not control["passed"]
    assert "последовательност" in control["reason"]


def test_control_refuses_when_disagreeing_callers_are_read_as_one_kind(
        monkeypatch):
    """САМОЕ ОСТРОЕ звено: правило, берущее ПЕРВОГО зовущего.

    Оно ответило бы уверенным родом на вопрос, ответа на который нет, — и
    вердикт был бы не измерением, а порядком обхода файла.
    """
    real = C._caller_argument_kinds

    def _first_only(name, scope, tree):
        return real(name, scope, tree)[:1]

    monkeypatch.setattr(C, "_caller_argument_kinds", _first_only)
    control = C._binding_kind_control()
    assert not control["passed"]


def test_control_refuses_when_my_own_closed_list_admits_an_unknown_form(
        monkeypatch):
    """Перечень ФОРМ СВЯЗЫВАНИЯ обязан остаться ЗАКРЫТЫМ.

    Ослаблено ровно МОЁ звено, а не соседское: разбор кортежа начинает
    отвечать родом на ЛЮБУЮ правую часть — в том числе на `build_pair()`,
    распаковку непрозрачного вызова с отрицательной половины сцены. Тогда
    правило объявляет род там, где формы связывания не знает, и это обязано
    краснеть ЛОЖНЫМ ПОЛОЖИТЕЛЬНЫМ, а не проходить.
    """
    real = C._tuple_position_kind

    def _guesses(name, expr, scope):
        # Ослабление ХИРУРГИЧЕСКОЕ: там, где форма известна, ответ остаётся
        # прежним, и положительная половина сцены не трогается. Догадка
        # появляется РОВНО там, где перечень форм сказал бы «не знаю».
        found = real(name, expr, scope)
        return found if found is not None else ast.Dict(keys=[], values=[])

    monkeypatch.setattr(C, "_tuple_position_kind", _guesses)
    control = C._binding_kind_control()
    assert not control["passed"]
    assert control.get("clean_false_positives"), control.get("reason")


def test_the_closed_list_of_binding_forms_is_exactly_what_is_declared():
    """Перечень сверяется с ОБЪЯВЛЕННЫМ, иначе «закрыт» есть только слово."""
    assert C._KIND_REPAIRS == (C.REPAIR_TUPLE_POSITION,
                               C.REPAIR_ELEMENT_DEFAULT,
                               C.REPAIR_CALLER_ARGUMENT,
                               C.REPAIR_SECOND_LINK)
    # Порядок называния причин ВТОРОГО звена — ОБЪЯВЛЕН, и сверяется он с
    # объявлением, а не с порядком обхода файла (ADR-573).
    assert C._ARG_GAP_ORDER == (
        (C._ARG_NOT_A_NAME, C.KIND_GAP_CALLER_ARGUMENT),
        (C._ARG_SECOND_LINK_IS_A_PARAMETER, C.KIND_GAP_THIRD_LINK),
        (C._ARG_SECOND_LINK_OPAQUE, C.KIND_GAP_SECOND_LINK_OPAQUE),
        (C._ARG_SECOND_LINK_DISAGREES, C.KIND_GAP_SECOND_LINK_DISAGREES))
    assert C._PROVEN_KINDS == ("strict", "forgiving", "sequence")
    # Род накопителя шаг НЕ переопределяет: перечень конструкторов остаётся
    # соседским, и своей копии у него нет ни одной строки.
    assert C._FORGIVING_CTORS == ("Counter", "defaultdict")
    assert C._STRICT_CTORS == ("dict", "OrderedDict", "fromkeys")


# ---------------------------------------------- ЧЕСТНОСТЬ ИМЕНИ У СОСЕДА

def test_a_non_name_target_is_flagged_as_a_misnamed_scope_verdict(tmp_path):
    """«Связан не в этой области» при цели, которая ИМЕНЕМ не является.

    Вопрос об области к такой цели не задавался ВООБЩЕ: накопитель здесь —
    элемент чужого контейнера. Это живая форма дерева
    (`leg_provenance_split.measure`, `shadow_blockade_attribution.attribute`).
    """
    root = _scene(tmp_path, source='''
def measure(rows, by_leg):
    for row in rows:
        by_leg[row["leg"]][str(row.get("verdict"))] += 1
''')
    out = C.accumulator_kind_at_the_binding(root, _writer(unresolved=1))
    assert out["status"] == "MEASURED", out.get("reason")
    assert out["misnamed_gaps"][C.MISNAMED_SCOPE] == 1
    assert out["misnamed_total"] == 1


def test_a_tuple_binding_is_flagged_as_a_misnamed_opaque_call(tmp_path):
    """«Пришёл вызовом неизвестного рода» при связывании, которое НЕ вызов.

    Живая форма дерева (`cartographer/owner_decisions`, `tracker_counts`):
    `_scope_bindings` отдаёт всему кортежу одну правую часть, и кортеж назван
    вызовом. Тот же класс, что ADR-469 нашёл однажды внутри себя.
    """
    root = _scene(tmp_path, source='''
def measure(rows):
    spare, counts = [], {"clean": 0}
    for row in rows:
        counts[str(row.get("verdict"))] += 1
    return counts
''')
    out = C.accumulator_kind_at_the_binding(root, _writer(unresolved=1))
    assert out["status"] == "MEASURED", out.get("reason")
    assert out["misnamed_gaps"][C.MISNAMED_OPAQUE] == 1
    assert out["kind_outcomes"][C.KIND_RESOLVED] == 1
    assert out["resolved_kinds"]["strict"] == 1


def test_the_step_does_not_repeat_the_sin_it_charges_the_neighbour_with(
        tmp_path):
    """Зовущий НАЙДЕН, а передаёт имя — это не «форма вне перечня».

    Общее имя послало бы расширять перечень форм связывания вместо второго
    звена разбора, то есть чинить не то. С ADR-573 у этой формы имя СВОЁ и
    ещё точнее: имя, которое и в области зовущего есть параметр, ждёт
    ТРЕТЬЕГО звена, и оно объявлено НЕ разбираемым заранее. Проверяется здесь
    именно то, ради чего ADR-518 завёл отдельный исход: «форма связывания вне
    перечня» на этой сцене обязана остаться НУЛЁМ.
    """
    root = _scene(tmp_path, source='''
def callee(rows, given):
    for row in rows:
        given[str(row.get("verdict"))] += 1


def caller(rows, upstream):
    return callee(rows, upstream)
''')
    out = C.accumulator_kind_at_the_binding(root, _writer(unresolved=1))
    assert out["status"] == "MEASURED", out.get("reason")
    gaps = out["unresolved_reasons"]
    assert gaps[C.KIND_GAP_THIRD_LINK] == 1
    assert gaps[C.KIND_GAP_OPAQUE] == 0
    assert gaps[C.KIND_GAP_CALLER_ARGUMENT] == 0


def test_a_parameter_with_no_caller_in_this_file_is_its_own_refusal(tmp_path):
    """Односторонность объявлена ЗАРАНЕЕ: звено — ЭТОТ файл.

    «Зовущего в этом файле нет» НЕ означает «зовущих нет»: зовущий из другого
    модуля не искался вовсе, и сказать это обязано ИМЯ отказа.
    """
    root = _scene(tmp_path, source='''
def callee(rows, given):
    for row in rows:
        given[str(row.get("verdict"))] += 1
''')
    out = C.accumulator_kind_at_the_binding(root, _writer(unresolved=1))
    assert out["status"] == "MEASURED", out.get("reason")
    assert out["unresolved_reasons"][C.KIND_GAP_NO_CALLER] == 1
    assert out["kind_outcomes"][C.KIND_STILL_UNMEASURED] == 1


def test_disagreeing_callers_are_an_absence_of_an_answer(tmp_path):
    """Два зовущих с ПРОТИВОПОЛОЖНЫМИ накопителями — не первый из них."""
    root = _scene(tmp_path, source='''
from collections import Counter


def callee(rows, given):
    for row in rows:
        given[str(row.get("verdict"))] += 1


def one_way(rows):
    return callee(rows, {})


def other_way(rows):
    return callee(rows, Counter())
''')
    out = C.accumulator_kind_at_the_binding(root, _writer(unresolved=1))
    assert out["status"] == "MEASURED", out.get("reason")
    assert out["unresolved_reasons"][C.KIND_GAP_CALLERS_DISAGREE] == 1


def test_a_caller_that_passes_a_declared_ctor_resolves_the_kind(tmp_path):
    """Обратная сторона того же звена: межобластной разбор РАБОТАЕТ.

    Без этого теста «зовущий не помог» было бы неотличимо от «зовущего не
    спросили».
    """
    root = _scene(tmp_path, source='''
def callee(rows, given):
    for row in rows:
        given[str(row.get("verdict"))] += 1


def caller(rows):
    return callee(rows, {"clean": 0})
''')
    out = C.accumulator_kind_at_the_binding(root, _writer(unresolved=1))
    assert out["status"] == "MEASURED", out.get("reason")
    assert out["resolved_by"][C.REPAIR_CALLER_ARGUMENT] == 1
    assert out["resolved_kinds"]["strict"] == 1


# ----------------------------------------- НАСЕЛЕНИЕ: ПОПРАВКА К ЗНАМЕНАТЕЛЮ

def test_a_sequence_accumulator_is_not_a_class_counter_at_all(tmp_path):
    """`[0] * 7` — индекс есть ПОЛОЖЕНИЕ, а не класс.

    Отсутствующего ключа у такого накопителя не бывает вовсе: промах даёт
    `IndexError`, и `KeyError` недостижим по построению. Это ЛОЖНЫЙ член
    населения «открытый счётчик класса», а не «род не измерен» — то есть
    поправка к знаменателю чисел ряда. Живая форма —
    `edge_weekday_loss_gate.tail_share_by_wd`.
    """
    root = _scene(tmp_path, source='''
def measure(rows):
    slots = [0] * 7
    for row in rows:
        slots[int(row.get("slot"))] += 1
    return slots
''')
    out = C.accumulator_kind_at_the_binding(root, _writer(unresolved=1))
    assert out["status"] == "MEASURED", out.get("reason")
    assert out["kind_outcomes"][C.KIND_NOT_A_MAPPING] == 1
    assert out["kind_outcomes"][C.KIND_STILL_UNMEASURED] == 0
    assert out["kind_outcomes"][C.KIND_RESOLVED] == 0


def test_the_form_of_outcomes_is_closed_and_zero_is_declared(tmp_path):
    """Инв. #17: ноль ОБЪЯВЛЕН, а не пропущен."""
    root = _scene(tmp_path, source='''
def measure(rows):
    slots = [0] * 7
    for row in rows:
        slots[int(row.get("slot"))] += 1
    return slots
''')
    out = C.accumulator_kind_at_the_binding(root, _writer(unresolved=1))
    assert set(out["kind_outcomes"]) == set(C._KIND_OUTCOMES)
    assert set(out["resolved_by"]) == set(C._KIND_REPAIRS)
    assert set(out["unresolved_reasons"]) == set(C._KIND_GAPS)
    assert set(out["misnamed_gaps"]) == set(C._MISNAMED)
    assert sum(out["kind_outcomes"].values()) == out["population"]


# --------------------------------------------- ТРЕТИЙ ИСХОД САМОГО ШАГА

def test_absent_neighbour_is_unmeasured_not_all_kinds_known(tmp_path):
    """Соседа нет ⇒ населения «род не измерен» НЕ СУЩЕСТВУЕТ."""
    out = C.accumulator_kind_at_the_binding(tmp_path, None)
    assert out["status"] == "UNMEASURED"
    assert out["unmeasured_class"] == C.UNMEASURED_KIND_NEIGHBOUR


def test_unmeasured_neighbour_is_not_read_as_a_clean_answer(tmp_path):
    """Сосед отказал ⇒ шаг отказывает тоже, а не досчитывает своё."""
    out = C.accumulator_kind_at_the_binding(tmp_path,
                                            {"status": "UNMEASURED"})
    assert out["status"] == "UNMEASURED"
    assert out["unmeasured_class"] == C.UNMEASURED_KIND_NEIGHBOUR


def test_a_neighbour_without_its_reason_breakdown_is_unmeasured(tmp_path):
    """Сосед не назвал причин ⇒ сверять население не с чем."""
    out = C.accumulator_kind_at_the_binding(tmp_path, {"status": "MEASURED"})
    assert out["status"] == "UNMEASURED"
    assert out["unmeasured_class"] == C.UNMEASURED_KIND_NEIGHBOUR


def test_two_roads_to_one_population_must_agree(tmp_path):
    """Разойдясь, два обхода отвечают на РАЗНЫЕ вопросы — отказ целиком."""
    root = _scene(tmp_path, source='''
def measure(rows):
    slots = [0] * 7
    for row in rows:
        slots[int(row.get("slot"))] += 1
    return slots
''')
    out = C.accumulator_kind_at_the_binding(root, _writer(unresolved=9))
    assert out["status"] == "UNMEASURED"
    assert out["unmeasured_class"] == C.UNMEASURED_KIND_POPULATION
    assert out["population"] == 1
    assert out["declared_population"] == 9


def test_a_failing_control_refuses_the_whole_step(tmp_path, monkeypatch):
    """Правило, не прошедшее контроль, не имеет права мерить дерево."""
    monkeypatch.setattr(C, "_sequence_binding", lambda expr: False)
    out = C.accumulator_kind_at_the_binding(tmp_path, _writer())
    assert out["status"] == "UNMEASURED"
    assert out["unmeasured_class"] == C.UNMEASURED_KIND_CONTROL


def test_an_unreadable_directory_is_unmeasured_not_empty(tmp_path):
    """Каталога нет ⇒ население неполно, а неполное не есть измеренное."""
    out = C.accumulator_kind_at_the_binding(tmp_path, _writer())
    assert out["status"] == "UNMEASURED"
    assert out["unmeasured_class"] == C.UNMEASURED_KIND_POPULATION


def test_a_syntax_error_in_the_tree_is_unmeasured_not_skipped(tmp_path):
    """Файл не разобран ⇒ отказ поимённо, а не молчаливый пропуск."""
    root = _scene(tmp_path, source="def broken(:\n")
    out = C.accumulator_kind_at_the_binding(root, _writer())
    assert out["status"] == "UNMEASURED"
    assert out["unmeasured_class"] == C.UNMEASURED_KIND_POPULATION
    assert out["files_unreadable"]


# ------------------------------------------------------ ADVISORY и проводка

def test_the_step_changes_nothing():
    """Прибор только ЧИТАЕТ: `applied` ложно во всех исходах."""
    assert C.accumulator_kind_at_the_binding(
        Path("/nonexistent"), None)["applied"] is False


def test_the_step_never_copies_the_kind_rule():
    """Второй копии правила рода нет — она и есть предмет этой переписи.

    Род считает ТОЛЬКО `_accumulator_kind` соседа; ослепи его — и ни один
    ремонт не назовёт рода, даже разбор кортежа, у которого свой элемент
    найден верно.
    """
    seen = {}
    real = C._accumulator_kind

    def _blind(expr):
        seen["called"] = True
        return None

    try:
        C._accumulator_kind = _blind
        control = C._binding_kind_control()
    finally:
        C._accumulator_kind = real
    assert seen.get("called"), "правило рода у соседа не спрошено вовсе"
    assert not control["passed"]


def test_the_step_is_wired_into_the_census_under_its_own_key():
    """Шаг, которого нет в отчёте, не читает никто."""
    src = Path(C.__file__).read_text(encoding="utf-8")
    assert ("kind_step = accumulator_kind_at_the_binding(root, writer_step)"
            in src)
    assert f'"{STEP}": kind_step,' in src


def test_the_verdict_names_the_population_correction_out_loud():
    """Поправка к знаменателю обязана быть НАЗВАНА, а не лежать в поле."""
    doc = {STEP: {
        "status": "MEASURED", "population": 17, "still_unmeasured": 8,
        "misnamed_total": 11,
        "kind_outcomes": {C.KIND_RESOLVED: 4, C.KIND_NOT_A_MAPPING: 5,
                          C.KIND_STILL_UNMEASURED: 8},
        "resolved_by": {r: 0 for r in C._KIND_REPAIRS},
        "resolved_kinds": {"strict": 3, "forgiving": 1},
        "unresolved_reasons": {g: 0 for g in C._KIND_GAPS},
        "misnamed_gaps": {m: 0 for m in C._MISNAMED},
        "control": {"resolved": 4, "by_repair": {}, "sequences": 1,
                    "clean_gaps": list(C._KIND_GAPS),
                    "disagreeing_callers_seen": 2},
        "not_a_mapping_sample": [], "blind": []}}
    text = "\n".join(C.report(doc))
    assert "[РОД У СВЯЗЫВАНИЯ]" in text
    assert "ПОСЛЕДОВАТЕЛЬНОСТЬ" in text
    assert "[РОД · ЧЕСТНОСТЬ ИМЕНИ У СОСЕДА]" in text


def test_a_missing_step_is_printed_as_unmeasured_not_as_silence():
    """Перепись без шага ⇒ «НЕ ИЗМЕРЕНО», а не «род измерен у всех»."""
    text = "\n".join(C.report({}))
    assert "[РОД У СВЯЗЫВАНИЯ] НЕ ИЗМЕРЕНО" in text


def test_an_unmeasured_step_prints_its_named_reason():
    """Отказ печатается ИМЕНЕМ класса, иначе чинить посылают не туда."""
    text = "\n".join(C.report({STEP: {
        "status": "UNMEASURED",
        "unmeasured_class": C.UNMEASURED_KIND_NEIGHBOUR,
        "reason": "сосед не измерен"}}))
    assert C.UNMEASURED_KIND_NEIGHBOUR in text


@pytest.mark.parametrize("name", list(C._KIND_REPAIRS) + list(C._KIND_GAPS)
                         + list(C._MISNAMED) + list(C._KIND_OUTCOMES))
def test_every_declared_name_is_distinct_and_spoken(name):
    """Имя, не встречающееся в вердикте, читателю не достаётся."""
    assert isinstance(name, str) and name
    assert len({*C._KIND_REPAIRS, *C._KIND_GAPS, *C._MISNAMED,
                *C._KIND_OUTCOMES}) == (len(C._KIND_REPAIRS)
                                        + len(C._KIND_GAPS)
                                        + len(C._MISNAMED)
                                        + len(C._KIND_OUTCOMES))


# =========================================================================
# КОНТРОЛИ НА КОНТРОЛЬ — урок ADR-517 (цикл #733), применённый здесь
# =========================================================================
# Первый прогон мутаций по региону дал ПЯТНАДЦАТЬ выживших, и большинство —
# КЛАУЗЫ самого контроля: батарея проверяла их только сводным `passed` и
# полями замера, поэтому снять любую поодиночке можно было МОЛЧА. Ровно эту
# слабость ADR-517 назвал у себя и закрыл контролями на контроль (37 → 41).
# Ниже каждая клауза трогается ОТДЕЛЬНО — так, чтобы сработала только она.

def _clean_scene(monkeypatch, source: str) -> dict:
    """Контроль на ПОДМЕНЁННОЙ отрицательной половине сцены."""
    monkeypatch.setattr(C, "KIND_BINDING_CONTROL_CLEAN", source)
    return C._binding_kind_control()


def test_the_tuple_clause_fires_on_its_own(monkeypatch):
    """Клауза «кортеж развёл строгий от снисходительного» — поодиночке.

    Снисходительный конструктор читается строгим: все три ремонта
    по-прежнему дают род (клауза 1 молчит), но разбор кортежа перестаёт
    различать накопители — и это обязана поймать ИМЕННО эта клауза.
    """
    real = C._accumulator_kind
    monkeypatch.setattr(C, "_accumulator_kind",
                        lambda expr: ("strict" if real(expr) == "forgiving"
                                      else real(expr)))
    control = C._binding_kind_control()
    assert not control["passed"]
    assert control.get("tuple_kinds") == ["strict", "strict"], control
    assert "ФОРМЫ связывания" in control["reason"]


def test_the_gap_name_clause_fires_on_its_own(monkeypatch):
    """Клауза «отказы разведены ВСЕМИ именами» — поодиночке.

    Объявлено пятое имя отказа, которого сцена не производит. Замер не
    тронут ничем: ремонты дают род, ложных положительных нет, — и покраснеть
    обязана ровно клауза полноты имён.
    """
    monkeypatch.setattr(C, "_KIND_GAPS",
                        C._KIND_GAPS + ("a_gap_no_scene_produces",))
    control = C._binding_kind_control()
    assert not control["passed"]
    assert "a_gap_no_scene_produces" not in (control.get("clean_gaps") or [])
    assert "именами" in control["reason"]


def test_the_relayed_clause_fires_on_its_own(monkeypatch):
    """Клауза «аргумент, который не ИМЯ, отделён» — поодиночке.

    Отрицательная половина получает ВТОРОЙ такой случай. Все имена отказа на
    месте, ложных положительных нет — покраснеть обязана ровно клауза,
    считающая зовущих у этой причины.
    """
    control = _clean_scene(monkeypatch, C.KIND_BINDING_CONTROL_CLEAN + '''

def given_a_call_twice(rows, given):
    for row in rows:
        given[str(row.get("verdict"))] += 1


def passes_a_call_twice(rows):
    return given_a_call_twice(rows, build_cell())
''')
    assert not control["passed"]
    assert control.get("relayed") == [1, 1], control
    assert "АРГУМЕНТЕ" in control["reason"]


def test_the_disagreement_clause_fires_on_its_own(monkeypatch):
    """Клауза «спор измерен ЧИСЛОМ зовущих» — поодиночке.

    У спорящего случая появляется ТРЕТИЙ зовущий. Имя отказа то же, число
    зовущих другое — и клауза обязана мерить именно число, иначе «спор
    найден» ничего не говорит о том, скольких спросили.
    """
    control = _clean_scene(monkeypatch, C.KIND_BINDING_CONTROL_CLEAN + '''

def third_way(rows):
    return disagree(rows, dict())
''')
    assert not control["passed"]
    assert control.get("disagreeing") == [3], control


# ======================= ГРАНИЦА ПРИМЕНИМОСТИ ШАГА =======================

def test_a_kind_the_neighbour_already_proved_is_not_re_judged():
    """Шаг молчит там, где ADR-469 ответил: второй копии правила рода нет.

    Переспросить уже доказанный род значило бы завести вторую копию правила —
    ровно тот предмет, который вся перепись ищет. Молчание здесь есть
    ПРОВОДКА, а не оттенок, и проверяется оно полем `kind_outcome`.
    """
    sites = C._binding_kind_sites("<scene>", ast.parse('''
def measure(rows):
    plain = {}
    for row in rows:
        plain[str(row.get("verdict"))] += 1
    return plain
'''))
    assert len(sites) == 1
    assert sites[0]["writer"] == C.WRITER_LOUD
    assert sites[0]["kind_outcome"] is None
    assert sites[0]["misnamed"] is None


def test_the_population_holds_only_the_neighbours_third_outcomes(tmp_path):
    """Население — ОСТАТОК соседа, а не все счётчики файла.

    Возьми шаг всех — и два обхода к одному населению разошлись бы, то есть
    ответили бы на разные вопросы. Сцена несёт ОДИН третий исход соседа и
    ОДИН уже доказанный им род.
    """
    root = _scene(tmp_path, source='''
def measure(rows):
    plain = {}
    spare, counts = [], {"clean": 0}
    for row in rows:
        plain[str(row.get("verdict"))] += 1
        counts[str(row.get("verdict"))] += 1
    return plain, counts
''')
    out = C.accumulator_kind_at_the_binding(root, _writer(unresolved=1))
    assert out["status"] == "MEASURED", out.get("reason")
    assert out["population"] == 1
    assert out["kind_outcomes"][C.KIND_RESOLVED] == 1


# ================== ЗАКРЫТОСТЬ ПЕРЕЧНЯ: ОТРИЦАТЕЛЬНЫЕ СЛУЧАИ ==================

def test_a_two_arg_attribute_call_that_is_not_setdefault_proves_nothing(
        tmp_path):
    """Ремонт умолчания судит `setdefault`, а не «вызов с двумя аргументами».

    `pop(k, D)` умолчание НЕ ЗАПИСЫВАЕТ: накопителем станет что угодно, и
    объявить род по второму аргументу значило бы прочесть чужую форму как
    свою.
    """
    root = _scene(tmp_path, source='''
def measure(rows, tally):
    for row in rows:
        cell = tally.pop("side", {"fired": 0})
        cell[str(row.get("verdict"))] += 1
''')
    out = C.accumulator_kind_at_the_binding(root, _writer(unresolved=1))
    assert out["status"] == "MEASURED", out.get("reason")
    assert out["kind_outcomes"][C.KIND_RESOLVED] == 0
    assert out["resolved_by"][C.REPAIR_ELEMENT_DEFAULT] == 0


def test_setdefault_with_one_argument_proves_nothing(tmp_path):
    """`setdefault(k)` умолчания не несёт — умолчание там `None`."""
    root = _scene(tmp_path, source='''
def measure(rows, tally):
    for row in rows:
        cell = tally.setdefault("side")
        cell[str(row.get("verdict"))] += 1
''')
    out = C.accumulator_kind_at_the_binding(root, _writer(unresolved=1))
    assert out["status"] == "MEASURED", out.get("reason")
    assert out["resolved_by"][C.REPAIR_ELEMENT_DEFAULT] == 0


def test_a_caller_passing_a_sequence_is_named_not_a_mapping(tmp_path):
    """Зовущий передаёт СПИСОК — класса нет, и это не «род не измерен».

    Ветка последовательности обязана работать и на аргументе зовущего, иначе
    поправка к населению зависела бы от того, где накопитель связан.
    """
    root = _scene(tmp_path, source='''
def callee(rows, given):
    for row in rows:
        given[int(row.get("slot"))] += 1


def caller(rows, axis):
    return callee(rows, [0] * len(axis))
''')
    out = C.accumulator_kind_at_the_binding(root, _writer(unresolved=1))
    assert out["status"] == "MEASURED", out.get("reason")
    assert out["kind_outcomes"][C.KIND_NOT_A_MAPPING] == 1
    # «Чем доказан РОД» и «чем доказано, что накопитель не отображение» —
    # РАЗНЫЕ утверждения, и в одном числе им не место: первое здесь ноль.
    assert out["resolved_by"][C.REPAIR_CALLER_ARGUMENT] == 0
    assert out["sequence_proved_by"][C.REPAIR_CALLER_ARGUMENT] == 1


def test_a_caller_that_omits_the_argument_is_not_read_as_passing_it(tmp_path):
    """Зовущий, не передавший аргумент, о роде не говорит НИЧЕГО.

    Смещение на единицу в отборе позиционных аргументов прочло бы соседний
    аргумент как накопитель — то есть объявило бы род по чужому выражению.
    """
    root = _scene(tmp_path, source='''
def callee(rows, given=None):
    for row in rows:
        given[str(row.get("verdict"))] += 1


def caller(rows):
    return callee(rows)
''')
    out = C.accumulator_kind_at_the_binding(root, _writer(unresolved=1))
    assert out["status"] == "MEASURED", out.get("reason")
    assert out["unresolved_reasons"][C.KIND_GAP_NO_CALLER] == 1
    assert out["resolved_by"][C.REPAIR_CALLER_ARGUMENT] == 0


def test_a_name_bound_with_two_different_kinds_is_unmeasured(tmp_path):
    """Имя, связанное РАЗНЫМИ родами, есть отсутствие ответа.

    Взять первое связывание значило бы сделать вердикт свойством порядка
    обхода файла. Сосед держит для этого своё имя
    (`accumulator_is_bound_with_more_than_one_kind`) и на этом случае
    отвечает сам; шаг обязан не досчитать род и здесь.
    """
    root = _scene(tmp_path, source='''
from collections import Counter


def measure(rows, flag):
    spare, counts = [], {"clean": 0}
    if flag:
        spare, counts = [], Counter()
    for row in rows:
        counts[str(row.get("verdict"))] += 1
    return counts
''')
    out = C.accumulator_kind_at_the_binding(root, _writer(unresolved=1))
    assert out["status"] == "MEASURED", out.get("reason")
    assert out["kind_outcomes"][C.KIND_RESOLVED] == 0
    assert out["kind_outcomes"][C.KIND_STILL_UNMEASURED] == 1


def test_an_unmeasured_neighbour_carrying_its_reasons_is_still_refused(
        tmp_path):
    """Отказ соседа читается по СТАТУСУ, а не по наличию полей.

    Сосед, отказавший и всё же напечатавший разбор причин, — не измеренный
    сосед. Судить по наличию поля значило бы прочесть его отказ как ответ:
    тот же дефект, что «читать ключ, а не значение» у plist
    (`.claude/rules/deployment.md`).
    """
    out = C.accumulator_kind_at_the_binding(
        tmp_path, {**_writer(), "status": "UNMEASURED"})
    assert out["status"] == "UNMEASURED"
    assert out["unmeasured_class"] == C.UNMEASURED_KIND_NEIGHBOUR


def test_what_proved_the_kind_is_never_mixed_with_what_proved_a_sequence(
        tmp_path):
    """Число, чьё имя не описывает того, что оно считает — предмет всего ряда.

    Сцена несёт ОБА исхода одним и тем же ремонтом (умолчание `setdefault`):
    у одного накопителя умолчание — отображение, у другого — список. Сложи их
    в одно поле, и «чем доказан РОД» считало бы строку, где рода не доказано
    вовсе. Тест — прямой контроль на ту правку, которую поймал отрицательный
    тест выше, а не чтение глазами.
    """
    root = _scene(tmp_path, source='''
def measure(rows, tally):
    for row in rows:
        cell = tally.setdefault("side", {"fired": 0})
        cell[str(row.get("verdict"))] += 1
        slots = tally.setdefault("slots", [0] * 7)
        slots[int(row.get("slot"))] += 1
''')
    out = C.accumulator_kind_at_the_binding(root, _writer(unresolved=2))
    assert out["status"] == "MEASURED", out.get("reason")
    assert out["resolved_by"][C.REPAIR_ELEMENT_DEFAULT] == 1
    assert out["sequence_proved_by"][C.REPAIR_ELEMENT_DEFAULT] == 1
    assert out["kind_outcomes"][C.KIND_RESOLVED] == 1
    assert out["kind_outcomes"][C.KIND_NOT_A_MAPPING] == 1
    # Сумма по ремонтам НЕ равна населению: остаток доказан не ремонтом.
    assert (sum(out["resolved_by"].values())
            + sum(out["sequence_proved_by"].values())
            == out["population"] - out["still_unmeasured"])


# =========================================================================
# ВТОРОЙ ПРОХОД МУТАЦИЙ — 7 выживших из 38, каждый РАЗОБРАН
# =========================================================================
# Шесть были дырами в батарее, и они закрыты ниже. Седьмой —
# ЭКВИВАЛЕНТНЫЙ мутант: снятие клаузы `kind_outcome == KIND_RESOLVED` в счёте
# `resolved_kinds` числа изменить не может, потому что поле `accumulator`
# ставится ТОЛЬКО на возвратах `KIND_RESOLVED` (три места в шаге, проверено
# перечислением). Клауза оставлена намеренно — она держит ЧЕСТНОСТЬ ИМЕНИ поля
# на случай четвёртого возврата, и «мутация выжила» здесь не есть слабость
# проверки. Сказано вслух, а не зачтено молча.

def test_the_population_filter_is_load_bearing_not_decorative():
    """Отбор по третьему исходу соседа НЕСЁТ вес, а не украшает.

    Положительная половина сцены содержит счётчик, род которого сосед УЖЕ
    доказал (`plain = {}` — строгий). Сними отбор, и он войдёт в население
    шага: тогда «шаг померил N» означало бы другое N, а два обхода к одному
    населению разошлись бы.
    """
    control = C._binding_kind_control()
    assert control["passed"], control.get("reason")
    assert control["sites"] == 6, control
    all_sites = C._binding_kind_sites(
        "<scene>", ast.parse(C.KIND_BINDING_CONTROL_SOURCE))
    assert len(all_sites) == 7, [s["counter"] for s in all_sites]
    proved = [s for s in all_sites if s["writer"] != C.WRITER_UNRESOLVED]
    assert len(proved) == 1 and proved[0]["kind_outcome"] is None


def test_a_bare_list_literal_accumulator_is_a_sequence_too(tmp_path):
    """Перечень форм последовательности несёт ТРИ вида, не один.

    Живые случаи дерева — `[0.0] * len(axis)` и `[0] * 7`, то есть `BinOp`;
    список-литерал и списковое включение в перечне объявлены, а замером не
    предъявлены ни разу. Форма, объявленная и не проверенная, есть украшение.
    """
    for source, what in (
            ('slots = [0, 0, 0]', "список-литерал"),
            ('slots = [0 for _ in range(7)]', "списковое включение")):
        root = _scene(tmp_path, source=f'''
def measure(rows):
    {source}
    for row in rows:
        slots[int(row.get("slot"))] += 1
    return slots
''')
        out = C.accumulator_kind_at_the_binding(root, _writer(unresolved=1))
        assert out["status"] == "MEASURED", (what, out.get("reason"))
        assert out["kind_outcomes"][C.KIND_NOT_A_MAPPING] == 1, what


def test_a_tuple_of_a_different_length_proves_nothing(tmp_path):
    """Длины цели и правой части обязаны СОВПАДАТЬ.

    Иначе элемент берётся по индексу из набора другой длины — то есть род
    объявляется по ЧУЖОМУ выражению, и вердикт становится свойством порядка
    элементов, а не накопителя.
    """
    root = _scene(tmp_path, source='''
from collections import Counter


def measure(rows):
    spare, counts = [], Counter(), {}
    for row in rows:
        counts[str(row.get("verdict"))] += 1
    return counts
''')
    out = C.accumulator_kind_at_the_binding(root, _writer(unresolved=1))
    assert out["status"] == "MEASURED", out.get("reason")
    assert out["kind_outcomes"][C.KIND_RESOLVED] == 0
    assert out["unresolved_reasons"][C.KIND_GAP_OPAQUE] == 1


def test_a_starred_target_proves_nothing(tmp_path):
    """Звёздочка СДВИГАЕТ положения — по индексу их считать нельзя.

    `*spare, counts = {}, {}, Counter()`: по индексу имени `counts`
    соответствовал бы нулевой элемент (строгий), а на деле последний
    (снисходительный). Ровно противоположный род — и правило, считающее
    индексы наивно, ответило бы уверенно и НЕВЕРНО.
    """
    root = _scene(tmp_path, source='''
from collections import Counter


def measure(rows):
    *spare, counts = {}, {}, Counter()
    for row in rows:
        counts[str(row.get("verdict"))] += 1
    return counts
''')
    out = C.accumulator_kind_at_the_binding(root, _writer(unresolved=1))
    assert out["status"] == "MEASURED", out.get("reason")
    assert out["kind_outcomes"][C.KIND_RESOLVED] == 0
    assert out["unresolved_reasons"][C.KIND_GAP_OPAQUE] == 1


def test_the_element_is_taken_from_the_assignment_that_bound_this_name(
        tmp_path):
    """Положение читается у ТОГО присваивания, чьё выражение и разбирается.

    Имя связано ДВАЖДЫ, и в двух присваиваниях стоит на РАЗНЫХ положениях —
    но накопитель у обоих снисходительный, так что честный ответ один и тот
    же. Разорви пару «цель ↔ выражение», и положение возьмётся у первого
    встреченного присваивания, а элемент — у разбираемого: `counts` прочтётся
    по нулевому положению второго кортежа, где стоит СТРОГИЙ словарь. Два
    связывания разойдутся в роде, и уверенный ответ станет отказом — вердикт
    окажется свойством порядка обхода файла, а не накопителя.
    """
    root = _scene(tmp_path, source='''
from collections import Counter


def measure(rows, flag):
    counts, spare = Counter(), {}
    if flag:
        spare, counts = {}, Counter()
    for row in rows:
        counts[str(row.get("verdict"))] += 1
    return counts
''')
    out = C.accumulator_kind_at_the_binding(root, _writer(unresolved=1))
    assert out["status"] == "MEASURED", out.get("reason")
    assert out["kind_outcomes"][C.KIND_RESOLVED] == 1
    assert out["resolved_kinds"]["forgiving"] == 1
    assert out["resolved_kinds"]["strict"] == 0


def test_bindings_that_disagree_about_the_very_outcome_are_unmeasured(
        tmp_path):
    """Связывания, спорящие не о РОДЕ, а об ИСХОДЕ, — отсутствие ответа.

    Одно связывание даёт последовательность, другое — отображение. Это спор
    не о том, строг накопитель или снисходителен, а о том, есть ли у него
    класс вообще; выбрать из двух исходов один значило бы решить монетой.
    """
    root = _scene(tmp_path, source='''
def measure(rows, flag):
    spare, counts = [], [0] * 7
    if flag:
        spare, counts = [], {"clean": 0}
    for row in rows:
        counts[str(row.get("verdict"))] += 1
    return counts
''')
    out = C.accumulator_kind_at_the_binding(root, _writer(unresolved=1))
    assert out["status"] == "MEASURED", out.get("reason")
    assert out["kind_outcomes"][C.KIND_STILL_UNMEASURED] == 1
    assert out["kind_outcomes"][C.KIND_NOT_A_MAPPING] == 0
    assert out["kind_outcomes"][C.KIND_RESOLVED] == 0


# =========================================================================
# ВТОРОЕ ЗВЕНО — заказ G99 п. 3 (ADR-573)
# =========================================================================
# Заказ дословно: «Пять аргументов зовущего требуют ВТОРОГО звена, и звено
# объявлено отсутствующим. `the_caller_argument_is_outside_the_closed_list`
# = 5: зовущий передаёт имя, чей род лежит на шаг выше. Разобрать второе звено
# (и назвать заранее, что третье не разбирается), либо доказать замером, что
# второе звено ничего не добавляет.»
#
# Замер на живом дереве ответил: звено понадобилось у пяти и ответило у
# ЧЕТЫРЁХ. Пятый ждёт ТРЕТЬЕГО звена, и оно объявлено не разбираемым заранее.
# Ниже — зелёный контур и красное на КАЖДОМ порванном звене.

def _hit_scene(monkeypatch, source: str) -> dict:
    """Контроль на ПОДМЕНЁННОЙ положительной половине сцены."""
    monkeypatch.setattr(C, "KIND_BINDING_CONTROL_SOURCE", source)
    return C._binding_kind_control()


#: ЖИВАЯ форма четырёх счётчиков остатка: зовущий передаёт ИМЯ, и в его
#: области имя связано словарным включением. Род доказывается ровно одним
#: шагом вверх — и именно это ADR-518 объявил «не доказуемым одним звеном»,
#: приняв за параметр зовущего то, что параметром не было.
_SECOND_LINK_LIVE_FORM = '''
def callee(rows, given):
    for row in rows:
        given[str(row.get("verdict"))] += 1


def caller(rows, live):
    upstream = {b: 0 for b in live}
    return callee(rows, upstream)
'''


def test_the_second_link_proves_the_kind_in_the_callers_scope(tmp_path):
    """Род доказан СВЯЗЫВАНИЕМ переданного имени в области ЗОВУЩЕГО."""
    out = C.accumulator_kind_at_the_binding(
        _scene(tmp_path, source=_SECOND_LINK_LIVE_FORM), _writer(unresolved=1))
    assert out["status"] == "MEASURED", out.get("reason")
    assert out["kind_outcomes"][C.KIND_RESOLVED] == 1
    assert out["resolved_by"][C.REPAIR_SECOND_LINK] == 1
    # Первое звено на этой сцене не отвечало ВОВСЕ, и присвоить ему ответ
    # второго значило бы снова назвать число не тем, что оно считает.
    assert out["resolved_by"][C.REPAIR_CALLER_ARGUMENT] == 0
    assert out["resolved_kinds"]["strict"] == 1


def test_the_answer_of_the_order_is_a_number_not_prose(tmp_path):
    """«Понадобилось · ответило · осталось» — три числа, а не оговорка.

    Знаменатель здесь НУЖДА, а не успех: мерить долю от доказанных значило бы
    спрятать остаток, ради которого заказ и поставлен.
    """
    out = C.accumulator_kind_at_the_binding(
        _scene(tmp_path, source=_SECOND_LINK_LIVE_FORM), _writer(unresolved=1))
    assert out["second_link"] == {"needed": 1, "kind_proved": 1,
                                  "not_a_mapping": 0, "still_unmeasured": 0,
                                  "third_link_declared_not_walked": 0}


def test_the_third_link_is_declared_not_walked_and_counted(tmp_path):
    """Имя, которое и у зовущего есть ПАРАМЕТР, остаётся неизмеренным."""
    out = C.accumulator_kind_at_the_binding(_scene(tmp_path, source='''
def callee(rows, given):
    for row in rows:
        given[str(row.get("verdict"))] += 1


def caller(rows, upstream):
    return callee(rows, upstream)
'''), _writer(unresolved=1))
    assert out["status"] == "MEASURED", out.get("reason")
    assert out["unresolved_reasons"][C.KIND_GAP_THIRD_LINK] == 1
    assert out["second_link"]["third_link_declared_not_walked"] == 1
    assert out["second_link"]["needed"] == 1
    assert out["second_link"]["still_unmeasured"] == 1


def test_one_proven_caller_does_not_answer_for_the_one_left_a_link_short(
        tmp_path):
    """ЖИВАЯ форма `_trim` из `edge_overlay_domain_admissibility`.

    Один зовущий доказал род вторым звеном, другой передал СВОЙ параметр.
    Взять доказавшего и объявить род значило бы ответить порядком обхода
    файла: второй зовущий может передать накопитель противоположного рода, и
    об этом по дереву НЕ ВИДНО.
    """
    out = C.accumulator_kind_at_the_binding(_scene(tmp_path, source='''
def callee(rows, given):
    for row in rows:
        given[str(row.get("verdict"))] += 1


def caller(rows, live):
    upstream = {b: 0 for b in live}
    return callee(rows, upstream)


def relay(rows, upstream):
    return callee(rows, upstream)
'''), _writer(unresolved=1))
    assert out["status"] == "MEASURED", out.get("reason")
    assert out["kind_outcomes"][C.KIND_STILL_UNMEASURED] == 1
    assert out["unresolved_reasons"][C.KIND_GAP_THIRD_LINK] == 1
    assert out["resolved_by"][C.REPAIR_SECOND_LINK] == 0


def test_a_second_link_binding_outside_the_closed_list_is_its_own_refusal(
        tmp_path):
    """Имя связано, и форма связывания вне перечня — чинится ПЕРЕЧНЕМ.

    Своё имя, а не общее с третьим звеном: там ход упёрся в параметр и чинится
    ЗВЕНОМ, здесь — в неизвестную форму, и чинится она перечнем форм. Одно имя
    на два ремонта послало бы чинить не то.
    """
    out = C.accumulator_kind_at_the_binding(_scene(tmp_path, source='''
def callee(rows, given):
    for row in rows:
        given[str(row.get("verdict"))] += 1


def caller(rows):
    upstream = make_tally()
    return callee(rows, upstream)
'''), _writer(unresolved=1))
    assert out["status"] == "MEASURED", out.get("reason")
    assert out["unresolved_reasons"][C.KIND_GAP_SECOND_LINK_OPAQUE] == 1
    assert out["unresolved_reasons"][C.KIND_GAP_THIRD_LINK] == 0
    assert out["unresolved_reasons"][C.KIND_GAP_CALLER_ARGUMENT] == 0


def test_second_link_bindings_that_prove_two_kinds_are_an_absence_of_an_answer(
        tmp_path):
    """Имя связано ДВАЖДЫ и разным родом — спор, а не первый из ответов."""
    out = C.accumulator_kind_at_the_binding(_scene(tmp_path, source='''
from collections import Counter


def callee(rows, given):
    for row in rows:
        given[str(row.get("verdict"))] += 1


def caller(rows, flag):
    upstream = {}
    if flag:
        upstream = Counter()
    return callee(rows, upstream)
'''), _writer(unresolved=1))
    assert out["status"] == "MEASURED", out.get("reason")
    assert out["unresolved_reasons"][C.KIND_GAP_SECOND_LINK_DISAGREES] == 1
    assert out["kind_outcomes"][C.KIND_RESOLVED] == 0


def test_one_proven_binding_beside_an_unknown_one_proves_nothing(tmp_path):
    """Одно связывание доказало род, другое — нет: род НЕ доказан.

    И назван он не спором: спорить не о чем, когда второй ответ есть «не
    знаю». Правило, берущее доказавшее связывание, ответило бы порядком
    обхода области.
    """
    out = C.accumulator_kind_at_the_binding(_scene(tmp_path, source='''
def callee(rows, given):
    for row in rows:
        given[str(row.get("verdict"))] += 1


def caller(rows, flag):
    upstream = {}
    if flag:
        upstream = make_tally()
    return callee(rows, upstream)
'''), _writer(unresolved=1))
    assert out["status"] == "MEASURED", out.get("reason")
    assert out["unresolved_reasons"][C.KIND_GAP_SECOND_LINK_OPAQUE] == 1
    assert out["unresolved_reasons"][C.KIND_GAP_SECOND_LINK_DISAGREES] == 0
    assert out["kind_outcomes"][C.KIND_RESOLVED] == 0


_TWO_REASONS_ONE_NAME = '''
def callee(rows, given):
    for row in rows:
        given[str(row.get("verdict"))] += 1


def by_call(rows):
    return callee(rows, make_tally())


def by_param(rows, upstream):
    return callee(rows, upstream)
'''

_TWO_REASONS_SWAPPED = '''
def callee(rows, given):
    for row in rows:
        given[str(row.get("verdict"))] += 1


def by_param(rows, upstream):
    return callee(rows, upstream)


def by_call(rows):
    return callee(rows, make_tally())
'''


@pytest.mark.parametrize("source", [_TWO_REASONS_ONE_NAME,
                                    _TWO_REASONS_SWAPPED])
def test_the_name_of_the_refusal_follows_the_declared_order_not_the_file(
        tmp_path, source):
    """Причин у зовущих две, имя отказа ОДНО — и берётся оно по объявлению.

    Порядок обхода файла не есть измерение: поменяй зовущих местами, и вердикт
    обязан остаться тем же. Первым называется тот, на котором ход остановился
    РАНЬШЕ, — здесь «аргумент вообще не имя», потому что за ним второго звена
    не наступает вовсе.
    """
    out = C.accumulator_kind_at_the_binding(_scene(tmp_path, source=source),
                                            _writer(unresolved=1))
    assert out["status"] == "MEASURED", out.get("reason")
    assert out["unresolved_reasons"][C.KIND_GAP_CALLER_ARGUMENT] == 1
    assert out["unresolved_reasons"][C.KIND_GAP_THIRD_LINK] == 0


def test_the_second_link_stays_inside_one_file(tmp_path):
    """Односторонность ОБЪЯВЛЕНА: звено — ЭТОТ файл, и соседний не читается.

    Зовущий из другого файла связывает имя так, что род доказался бы сразу.
    Шаг обязан этого НЕ увидеть и сказать «зовущего в этом файле нет» —
    иначе ответ зависел бы от того, как далеко прибор решил заглянуть.
    """
    root = _scene(tmp_path, source='''
def callee(rows, given):
    for row in rows:
        given[str(row.get("verdict"))] += 1
''')
    (root / C.OPEN_COUNTER_DIRS[0] / "neighbour.py").write_text('''
from scene import callee


def caller(rows, live):
    upstream = {b: 0 for b in live}
    return callee(rows, upstream)
''', encoding="utf-8")
    out = C.accumulator_kind_at_the_binding(root, _writer(unresolved=1))
    assert out["status"] == "MEASURED", out.get("reason")
    assert out["unresolved_reasons"][C.KIND_GAP_NO_CALLER] == 1
    assert out["second_link"]["needed"] == 0


def test_the_mark_of_the_second_link_has_three_values_not_two():
    """«Не спрашивали» · «спросили, не понадобилось» · «понадобилось».

    Три исхода у наблюдения обязаны быть различимы (инв. #17): слей первые
    два в `False`, и «сколько раз звено понадобилось» начало бы считать сам
    факт вопроса.
    """
    rows = C._binding_kind_sites("<scene>", ast.parse('''
from collections import Counter


def proved_by_the_neighbour(rows):
    plain = {}
    for row in rows:
        plain[str(row.get("verdict"))] += 1
    return plain


def first_link(rows, given):
    for row in rows:
        given[str(row.get("verdict"))] += 1


def passes_a_ctor(rows):
    return first_link(rows, Counter())


def needs_the_second(rows, given):
    for row in rows:
        given[str(row.get("verdict"))] += 1


def passes_a_name(rows, live):
    upstream = {b: 0 for b in live}
    return needs_the_second(rows, upstream)
'''))
    mark = {r["owner"]: r["second_link"] for r in rows}
    assert mark["proved_by_the_neighbour"] is None
    assert mark["first_link"] is False
    assert mark["needs_the_second"] is True


def test_the_second_link_asks_the_closed_list_through_its_own_one_place(
        monkeypatch):
    """У ВТОРОГО звена применение перечня одно — и оно `_closed_list_kind`.

    Утверждение сознательно УЗКОЕ: шаг применяет перечень и в блоках (1)/(3)
    `_binding_kind_site`, составы там другие, и расхождения двух применений
    никто не мерил (названный остаток, заказ G134 п. 1). Проверяется ровно то,
    что звено не держит СВОЕЙ копии: ослепи это место — и второе звено не
    докажет рода ни у одного случая.
    """
    seen = {}
    real = C._closed_list_kind

    def _watched(name, expr, scope):
        seen["called"] = True
        return C._ARG_SECOND_LINK_OPAQUE

    monkeypatch.setattr(C, "_closed_list_kind", _watched)
    control = C._binding_kind_control()
    assert seen.get("called"), "перечень форм у второго звена не спрошен вовсе"
    assert not control["passed"]
    assert control["by_repair"][C.REPAIR_SECOND_LINK] == []
    assert real is not _watched


# -------------------- КОНТРОЛИ НА КОНТРОЛЬ ВТОРОГО ЗВЕНА --------------------

@pytest.mark.parametrize("gap,extra", [
    (C.KIND_GAP_THIRD_LINK, '''

def relayed_twice(rows, given):
    for row in rows:
        given[str(row.get("verdict"))] += 1


def relay_twice(rows, upstream):
    return relayed_twice(rows, upstream)
'''),
    (C.KIND_GAP_SECOND_LINK_OPAQUE, '''

def given_an_opaque_name_twice(rows, given):
    for row in rows:
        given[str(row.get("verdict"))] += 1


def passes_an_opaque_name_twice(rows):
    upstream = build_cell()
    return given_an_opaque_name_twice(rows, upstream)
'''),
    (C.KIND_GAP_SECOND_LINK_DISAGREES, '''

def given_a_disputed_name_twice(rows, given):
    for row in rows:
        given[str(row.get("verdict"))] += 1


def passes_a_disputed_name_twice(rows, flag):
    upstream = {}
    if flag:
        upstream = Counter()
    return given_a_disputed_name_twice(rows, upstream)
'''),
])
def test_each_second_link_clause_fires_on_its_own(monkeypatch, gap, extra):
    """Каждая причина ВТОРОГО звена обязана иметь РОВНО один случай.

    Две причины на одно имя неотличимы друг от друга, и сливают они разные
    ремонты. Трогается по одной клаузе за раз: имена все на месте, ложных
    положительных нет, замер не тронут — краснеть обязана ровно та, у которой
    случаев стало два.
    """
    control = _clean_scene(monkeypatch, C.KIND_BINDING_CONTROL_CLEAN + extra)
    assert not control["passed"]
    assert control.get("gap") == gap, control
    assert control.get("hits") == 2, control


def test_the_walked_clause_fires_on_its_own(monkeypatch):
    """Клауза «звено ПРОЙДЕНО, а не объявлено» — поодиночке.

    Положительная половина получает ВТОРОЙ случай второго звена. Ремонты все
    дают род, кортеж по-прежнему разводит накопители, отрицательная половина
    не тронута — покраснеть обязана ровно клауза, считающая пройденное.
    """
    control = _hit_scene(monkeypatch, C.KIND_BINDING_CONTROL_SOURCE + '''

def second_link_callee_twice(rows, given):
    for row in rows:
        given[str(row.get("verdict"))] += 1


def second_link_caller_twice(rows):
    upstream = Counter()
    return second_link_callee_twice(rows, upstream)
''')
    assert not control["passed"]
    assert "пройденный" in control["reason"], control
    assert len(control.get("walked") or []) == 2, control


def test_the_mark_clause_fires_on_its_own(monkeypatch):
    """Клауза «отметка не стои́т там, где зовущего не спрашивали».

    Отметка ставится ремонтам, у которых зовущего нет вовсе. Всё остальное на
    месте — и покраснеть обязана ровно клауза, различающая «понадобилось» от
    «спросили».
    """
    real = C._binding_kind_sites

    def _stamped(rel, tree):
        rows = real(rel, tree)
        for row in rows:
            if row["resolved_by"] == C.REPAIR_TUPLE_POSITION:
                row["second_link"] = True
        return rows

    monkeypatch.setattr(C, "_binding_kind_sites", _stamped)
    control = C._binding_kind_control()
    assert not control["passed"]
    assert "не спрашивали" in control["reason"], control


def test_the_second_link_is_spoken_in_the_verdict():
    """Звено, о котором вердикт молчит, читателю не достаётся."""
    text = "\n".join(C.report({STEP: {
        "status": "MEASURED", "population": 17, "still_unmeasured": 4,
        "misnamed_total": 11,
        "kind_outcomes": {C.KIND_RESOLVED: 8, C.KIND_NOT_A_MAPPING: 5,
                          C.KIND_STILL_UNMEASURED: 4},
        "resolved_by": {C.REPAIR_SECOND_LINK: 4},
        "resolved_kinds": {"strict": 8, "forgiving": 0},
        "unresolved_reasons": {C.KIND_GAP_THIRD_LINK: 1},
        "misnamed_gaps": {},
        "second_link": {"needed": 5, "kind_proved": 4, "not_a_mapping": 0,
                        "still_unmeasured": 1,
                        "third_link_declared_not_walked": 1},
        "control": {"passed": True}}}))
    assert "[РОД · ВТОРОЕ ЗВЕНО] понадобилось у 5" in text
    assert "род доказан у 4" in text
    assert "ТРЕТЬЕГО" in text


# -------------------- ДЫРЫ СЦЕНЫ, НАЙДЕННЫЕ МУТАЦИЕЙ (цикл #782) --------------------
# Первый прогон мутаций по региону дал 74 убитых и 18 выживших, и ни один не зачтён:
# все восемнадцать оказались дырами ЭТОЙ батареи, а не силой правила. Каждый тест ниже
# назван по своему мутанту — так, чтобы снять его молча было нельзя.

def test_the_second_link_proves_a_sequence_and_it_is_not_a_class_counter(
        tmp_path):
    """Мутанты «L14889 if → False», «L14890 return → None», «L15456 sum(1→2)».

    Второе звено обязано уметь ответить и находкой о НАСЕЛЕНИИ: накопитель,
    пришедший от зовущего, бывает последовательностью, и тогда класса у него
    нет вовсе. Без этой сцены ветка последовательности во втором звене не
    исполнялась ни разу, а поле `not_a_mapping` было нулём при любом множителе.
    """
    out = C.accumulator_kind_at_the_binding(_scene(tmp_path, source='''
def callee(rows, given):
    for row in rows:
        given[int(row.get("slot"))] += 1


def caller(rows, axis):
    upstream = [0] * len(axis)
    return callee(rows, upstream)
'''), _writer(unresolved=1))
    assert out["status"] == "MEASURED", out.get("reason")
    assert out["kind_outcomes"][C.KIND_NOT_A_MAPPING] == 1
    assert out["sequence_proved_by"][C.REPAIR_SECOND_LINK] == 1
    assert out["second_link"] == {"needed": 1, "kind_proved": 0,
                                  "not_a_mapping": 1, "still_unmeasured": 0,
                                  "third_link_declared_not_walked": 0}


def test_the_second_link_reads_the_default_of_setdefault(tmp_path):
    """Мутанты «L14896 is→is not», «L14901 is not→is», «L14901 return→None».

    Имя у зовущего связано ЭЛЕМЕНТОМ чужого контейнера, взятым с умолчанием.
    Форма перечню известна, и второе звено обязано её спросить — иначе род
    остался бы неизмеренным там, где он прямо написан.
    """
    out = C.accumulator_kind_at_the_binding(_scene(tmp_path, source='''
def callee(rows, given):
    for row in rows:
        given[str(row.get("verdict"))] += 1


def caller(rows, tally):
    upstream = tally.setdefault("side", {"fired": 0})
    return callee(rows, upstream)
'''), _writer(unresolved=1))
    assert out["status"] == "MEASURED", out.get("reason")
    assert out["kind_outcomes"][C.KIND_RESOLVED] == 1
    assert out["resolved_by"][C.REPAIR_SECOND_LINK] == 1
    assert out["resolved_kinds"]["strict"] == 1


def test_the_second_link_takes_its_own_element_of_a_tuple_binding(tmp_path):
    """Мутант «L14896 if → always False» — и он тонкий.

    У кортежного связывания умолчания `setdefault` НЕТ, то есть первый
    спрошенный вид формы отдаёт `None`. Правило, перестающее пропускать
    `None`, разберёт пустоту вместо кортежа и объявит род неизмеренным —
    при том что элемент по положению найден верно.
    """
    out = C.accumulator_kind_at_the_binding(_scene(tmp_path, source='''
from collections import Counter


def callee(rows, given):
    for row in rows:
        given[str(row.get("verdict"))] += 1


def caller(rows):
    spare, upstream = [], Counter()
    return callee(rows, upstream)
'''), _writer(unresolved=1))
    assert out["status"] == "MEASURED", out.get("reason")
    assert out["resolved_by"][C.REPAIR_SECOND_LINK] == 1
    assert out["resolved_kinds"]["forgiving"] == 1


def test_the_second_link_names_a_sequence_found_inside_a_tuple_binding(
        tmp_path):
    """Мутанты «L14898 if → False», «L14899 return → None».

    Элемент кортежа может оказаться последовательностью, и тогда ответ —
    находка о НАСЕЛЕНИИ, а не «род не измерен». Разные исходы обязаны
    остаться разными и на втором звене.
    """
    out = C.accumulator_kind_at_the_binding(_scene(tmp_path, source='''
def callee(rows, given):
    for row in rows:
        given[int(row.get("slot"))] += 1


def caller(rows, axis):
    spare, upstream = {}, [0] * len(axis)
    return callee(rows, upstream)
'''), _writer(unresolved=1))
    assert out["status"] == "MEASURED", out.get("reason")
    assert out["kind_outcomes"][C.KIND_NOT_A_MAPPING] == 1
    assert out["sequence_proved_by"][C.REPAIR_SECOND_LINK] == 1


@pytest.mark.parametrize("signature,what", [
    ("def caller(rows, *upstream):", "звёздный параметр"),
    ("def caller(rows, **upstream):", "двузвёздный параметр"),
])
def test_a_starred_parameter_of_the_caller_is_a_parameter_too(
        tmp_path, signature, what):
    """Мутанты «L14859 if a.vararg → False», «L14861 if a.kwarg → False».

    Имя, собранное `*args`/`**kwargs`, параметром быть не перестаёт, и ответ
    о нём лежит ТРЕТЬИМ звеном. Пропусти эти два вида — и то же самое
    положение дел получило бы имя «связывание вне перечня», то есть послало
    бы расширять перечень форм вместо звена.
    """
    out = C.accumulator_kind_at_the_binding(_scene(tmp_path, source=f'''
def callee(rows, given):
    for row in rows:
        given[str(row.get("verdict"))] += 1


{signature}
    return callee(rows, upstream)
'''), _writer(unresolved=1))
    assert out["status"] == "MEASURED", out.get("reason")
    assert out["unresolved_reasons"][C.KIND_GAP_THIRD_LINK] == 1, what
    assert out["unresolved_reasons"][C.KIND_GAP_SECOND_LINK_OPAQUE] == 0


def test_an_argument_that_is_not_a_name_never_marks_the_second_link(tmp_path):
    """Мутант «L14992 link 1→2».

    Второму звену не за что взяться, когда аргумент — не имя: звено НЕ
    пройдено, и отметка обязана остаться ложной. Поставь её здесь, и число
    «сколько раз звено понадобилось» начнёт считать случаи, которых оно не
    касалось.
    """
    out = C.accumulator_kind_at_the_binding(_scene(tmp_path, source='''
def callee(rows, given):
    for row in rows:
        given[str(row.get("verdict"))] += 1


def caller(rows):
    return callee(rows, make_tally())
'''), _writer(unresolved=1))
    assert out["status"] == "MEASURED", out.get("reason")
    assert out["unresolved_reasons"][C.KIND_GAP_CALLER_ARGUMENT] == 1
    assert out["second_link"]["needed"] == 0
    assert out["unresolved_sample"][0]["second_link"] is False


def test_no_caller_is_reported_as_zero_callers_not_as_one(tmp_path):
    """Мутант «L15069 callers_seen 0→1».

    «Зовущих не нашлось» и «нашёлся один» — разные наблюдения, и число рядом
    с отказом обязано говорить второе только тогда, когда оно верно.
    """
    out = C.accumulator_kind_at_the_binding(_scene(tmp_path, source='''
def callee(rows, given):
    for row in rows:
        given[str(row.get("verdict"))] += 1
'''), _writer(unresolved=1))
    assert out["status"] == "MEASURED", out.get("reason")
    assert out["unresolved_reasons"][C.KIND_GAP_NO_CALLER] == 1
    assert out["unresolved_sample"][0]["callers_seen"] == 0
    assert out["unresolved_sample"][0]["second_link"] is False


# --- КОНТРАКТ САМИХ ЗВЕНЬЕВ: ветки fail-CLOSED, через шаг НЕ наблюдаемые ---
# Три мутанта ниже через публичный шаг не видны по построению, и это сказано
# вслух, а не обойдено: защитная ветка «область не функция» из `_binding_kind_site`
# недостижима (там область обязана иметь параметры), а имя `_ARG_SECOND_LINK_OPAQUE`
# в последней строке `_closed_list_kind` неотличимо от любого другого
# НЕдоказанного ответа — `_second_link_kind` всё равно назовёт его отказом.
# Поэтому они проверяются у КОНТРАКТА функции, а не через вердикт: мутант,
# наблюдаемый только у контракта, обязан быть убит у контракта, иначе он не убит.

def test_params_of_a_scope_that_is_not_a_function_is_an_empty_set():
    """Мутанты «L14854 if → False», «L14855 return → None».

    Пустое МНОЖЕСТВО, а не `None` и не падение: ответ идёт в проверку
    вхождения, и `None` обрушил бы её, а падение превратило бы отказ правила
    в отказ прибора.
    """
    assert C._params_of(ast.parse("x = 1")) == set()
    assert C._params_of(ast.parse("x = 1").body[0]) == set()


def test_the_caller_walk_refuses_a_scope_that_is_not_a_function():
    """Мутанты «L14957 if → False», «L14958 return → None».

    У модуля параметров нет, спрашивать зовущих не о чем — и ответ обязан
    быть ПУСТЫМ СПИСКОМ: `None` прочитался бы как «зовущих нет» через
    `len(...)` только случайно, а падение стёрло бы весь вердикт шага.
    """
    tree = ast.parse('''
def callee(rows, given):
    for row in rows:
        given[str(row.get("verdict"))] += 1
''')
    assert C._caller_argument_kinds("given", tree, tree) == []


def test_an_unknown_binding_form_is_named_by_the_closed_list_vocabulary():
    """Мутант «L14902 return → None».

    Через вердикт шага он не виден: `None` и названная причина равно не
    доказывают рода. Но словарь ответов этой функции ЗАКРЫТ, и имя из него —
    часть её контракта: вернув `None`, она отдала бы наружу значение, которого
    в словаре нет, и следующий читатель о причине не узнал бы ничего.
    """
    unknown = ast.parse("tally = make_it()").body[0].value
    assert C._closed_list_kind(
        "tally", unknown, ast.parse("tally = make_it()")) == (
        C._ARG_SECOND_LINK_OPAQUE)
