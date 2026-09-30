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
    """Порвано звено «аргумент зовущего»: межобластной разбор не работает."""
    monkeypatch.setattr(C, "_caller_argument_kinds",
                        lambda name, scope, tree: (set(), 0))
    control = C._binding_kind_control()
    assert not control["passed"]
    assert control["by_repair"][C.REPAIR_CALLER_ARGUMENT] == []


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
        kinds, seen = real(name, scope, tree)
        return ({sorted(map(str, kinds))[0]} if kinds else kinds), seen

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
                               C.REPAIR_CALLER_ARGUMENT)
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
    звена разбора, то есть чинить не то. Живая форма дерева —
    `edge_trim_proceeds_destination.redistribute(w, …)`, где `w` сам параметр
    зовущего; на ней пять счётчиков из живого остатка.
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
    assert gaps[C.KIND_GAP_CALLER_ARGUMENT] == 1
    assert gaps[C.KIND_GAP_OPAQUE] == 0


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
    """Клауза «зовущий с ИМЕНЕМ отделён» — поодиночке.

    Отрицательная половина получает ВТОРОЙ такой случай. Все четыре имени
    отказа на месте, ложных положительных нет — покраснеть обязана ровно
    клауза, считающая переданные имена.
    """
    control = _clean_scene(monkeypatch, C.KIND_BINDING_CONTROL_CLEAN + '''

def relayed_twice(rows, given):
    for row in rows:
        given[str(row.get("verdict"))] += 1


def relay_twice(rows, upstream):
    return relayed_twice(rows, upstream)
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
    assert control["sites"] == 5, control
    all_sites = C._binding_kind_sites(
        "<scene>", ast.parse(C.KIND_BINDING_CONTROL_SOURCE))
    assert len(all_sites) == 6, [s["counter"] for s in all_sites]
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
