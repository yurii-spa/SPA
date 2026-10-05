"""Батарея шага «знаменатель ряда» (заказ G99 п. 1, ADR-568).

Шаг ADR-518 назвал ложные члены населения ряда — счётчики, у которых КЛАССА
НЕТ ВОВСЕ, потому что накопитель у них последовательность, а индекс есть
положение. Но спрашивал он их только у ОСТАТКА «род не измерен»: семнадцати
счётчиков из двух сотен. Заказ G99 п. 1 просит дословно:

    Пять ложных членов населения — это поправка к ЗНАМЕНАТЕЛЮ, и её никто не
    применил. Шаг НАЗВАЛ их, но числа ряда G78…G98 по-прежнему делятся на 171.
    Спросить прямо: сколько из 171 открытых счётчиков соседа —
    последовательности, а не отображения, и каким становится население ряда
    после вычитания. Это вопрос к СОСЕДУ, а не к его остатку: здесь измерены
    только 17 из 171.

Батарея устроена по ЗВЕНЬЯМ: зелёный контур целиком, красное на КАЖДОМ
порванном звене с НАЗВАННЫМ звеном, и громкий отказ там, где предпосылка не
обеспечена. Отдельный разряд — ПОЛОЖИТЕЛЬНЫЕ КОНТРОЛИ на два дефекта, которые
этот цикл совершил в своём же черновике и поймал замером: «список стои́т рядом»
и «два связывания спорят, берём первое». Оба воспроизводятся сценой и обязаны
краснеть, если правило вернётся к догадке.

Ни одного литерала даты и ни одного литерала pid здесь нет вовсе: предмет шага
не зависит ни от календаря, ни от того, какой номер процесса сегодня занят.
"""
from __future__ import annotations

import ast
import sys
from pathlib import Path

import pytest

if __package__ in (None, ""):                      # прямой запуск без conftest
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from spa_core.monitoring import rule_second_copy_census as C

STEP = "sequence_members_of_the_whole_population"

#: Имена функций, добавленных ЭТИМ решением в производителя. Перечень нужен
#: статическому контролю ниже: прибор стои́т в населении, которое мерит, и
#: открытый счётчик внутри него сдвинул бы знаменатель ряда самим фактом
#: доставки (ADR-566).
OWN_FUNCTIONS = ("_door_labels", "_member_site", "_member_sites",
                 "_member_control", STEP)


# --------------------------------------------------------------- вход сцены

def _hit():
    rows, _peer = C._member_sites("<scene>", ast.parse(C.MEMBER_CONTROL_SOURCE))
    return rows


def _clean():
    rows, _peer = C._member_sites("<scene-clean>",
                                  ast.parse(C.MEMBER_CONTROL_CLEAN))
    return rows


def _rows(source: str):
    rows, _peer = C._member_sites("<ad-hoc>", ast.parse(source))
    return rows


def _scene(tmp_path: Path, *, source: str) -> Path:
    """Одноразовое дерево с ОДНИМ файлом в каталоге, который обходит шаг."""
    base = tmp_path / C.OPEN_COUNTER_DIRS[0]
    base.mkdir(parents=True, exist_ok=True)
    (base / "scene.py").write_text(source, encoding="utf-8")
    for extra in C.OPEN_COUNTER_DIRS[1:]:
        (tmp_path / extra).mkdir(parents=True, exist_ok=True)
    return tmp_path


def _measure(root: Path):
    """Шаг на одноразовом дереве — с ЖИВЫМ соседом того же дерева."""
    neighbour = C.open_class_counter_census(root)
    return C.sequence_members_of_the_whole_population(root, neighbour)


ONE_SEQUENCE = '''
def alpha(rows):
    extra = [0.0] * 3
    for row in rows:
        extra[row["slot"]] += 1
    return extra
'''

ONE_MAPPING = '''
def beta(rows):
    tally = {}
    for row in rows:
        tally[row["cls"]] += 1
    return tally
'''


# ------------------------------------------------- ЗЕЛЁНЫЙ КОНТУР ЦЕЛИКОМ

def test_control_passes_on_the_declared_rule():
    """Объявленное правило проходит ОБЕИМИ половинами своей сцены."""
    control = C._member_control()
    assert control["passed"], control


def test_the_step_is_measured_on_a_live_tree(tmp_path):
    """Контур целиком: сцена из одного счётчика даёт ИЗМЕРЕННЫЙ вердикт."""
    out = _measure(_scene(tmp_path, source=ONE_SEQUENCE))
    assert out["status"] == "MEASURED", out
    assert out["population"] == 1
    assert out["member_outcomes"][C.MEMBER_FALSE] == 1


def test_the_step_is_advisory():
    """`applied` ложно: шаг только ЧИТАЕТ и ничего не чинит."""
    assert C.sequence_members_of_the_whole_population(
        Path("/nonexistent"), None)["applied"] is False


# ----------------------------------------- ПРЕДМЕТ: КЛАСС ЕСТЬ ИЛИ ЕГО НЕТ

def test_a_sequence_accumulator_is_a_false_member():
    """Накопитель-последовательность: класса нет вовсе, не «род не измерен»."""
    rows = _rows(ONE_SEQUENCE)
    assert len(rows) == 1
    assert rows[0]["member"] == C.MEMBER_FALSE
    assert rows[0]["doors"] == []


def test_a_bare_dict_accumulator_is_refuted_by_the_writer_door():
    """Род доказал сосед ADR-469 — последовательностью это место не бывает."""
    rows = _rows(ONE_MAPPING)
    assert len(rows) == 1
    assert rows[0]["member"] == C.MEMBER_REFUTED
    assert rows[0]["doors"] == [C.DOOR_WRITER_KIND]


def test_the_write_form_door_refutes_without_looking_at_the_binding():
    """`.get(k, D)` — у списка такого метода нет; накопитель тут ПАРАМЕТР."""
    rows = _rows('''
def gamma(rows, witness):
    for row in rows:
        witness[row["cls"]] = witness.get(row["cls"], 0) + 1
    return witness
''')
    assert len(rows) == 1
    assert rows[0]["member"] == C.MEMBER_REFUTED
    assert rows[0]["doors"] == [C.DOOR_WRITE_FORM]


def test_the_binding_door_refutes_an_element_of_a_foreign_container():
    """Род доказало СВЯЗЫВАНИЕ: умолчание `setdefault` есть род элемента."""
    rows = _rows('''
import collections


def delta(rows, witness):
    for row in rows:
        cell = witness.setdefault(row["cls"], collections.Counter())
        cell[row["kind"]] += 1
    return witness
''')
    cells = [r for r in rows if r["counter"] == "cell"]
    assert len(cells) == 1, rows
    assert cells[0]["member"] == C.MEMBER_REFUTED
    assert cells[0]["doors"] == [C.DOOR_BINDING]


def test_an_opaque_call_is_the_third_outcome_not_a_mapping():
    """Мутный накопитель НЕ выдаётся за «не последовательность» (инв. #17)."""
    rows = _rows('''
def omega(rows, make):
    cell = make()
    for row in rows:
        cell[row["cls"]] += 1
    return cell
''')
    assert len(rows) == 1
    assert rows[0]["member"] == C.MEMBER_UNMEASURED
    assert rows[0]["member_gap"] == C.MEMBER_GAP_NEITHER_DOOR


# ------------------- ПОЛОЖИТЕЛЬНЫЕ КОНТРОЛИ НА ДЕФЕКТЫ ЭТОГО ЖЕ ЧЕРНОВИКА

def test_a_list_standing_next_to_the_accumulator_is_not_the_accumulator():
    """Дефект черновика №1: «в области есть список ⇒ накопитель список».

    Воспроизводит форму, на которой первый прототип этого цикла напечатал
    выдуманную находку: список и словарь связаны в ОДНОЙ области, и счётчик
    пишется в словарь.
    """
    rows = _rows('''
def alpha(rows):
    order = [0.0] * 3
    tally = {}
    for row in rows:
        tally[row["cls"]] += 1
    return order, tally
''')
    assert len(rows) == 1
    assert rows[0]["counter"] == "tally"
    assert rows[0]["member"] == C.MEMBER_REFUTED


def test_two_bindings_of_one_name_that_disagree_give_no_answer():
    """Дефект черновика №2: «два связывания — берём первое».

    ОДНО имя связано в одной области и списком, и словарём, а форма записи
    (`+=`) отвечает за оба рода — то есть спасти ответ может ТОЛЬКО правило о
    споре связываний. Правило, берущее первое, объявило бы ложным членом
    настоящий словарь.
    """
    rows = _rows('''
def alpha(rows, part):
    causes = [0, 0, 0]
    for row in part:
        causes[row["slot"]] += 1
    causes = {}
    for row in rows:
        causes[row["cls"]] += 1
    return causes
''')
    assert len(rows) == 2, rows
    assert [r["member"] for r in rows] == [C.MEMBER_UNMEASURED] * 2, rows
    assert {r["member_gap"] for r in rows} == {C.MEMBER_GAP_NEITHER_DOOR}


def test_the_live_case_of_disagreeing_bindings_is_saved_by_the_form_door():
    """Живой случай (`slo_keepability.py`) — и НАЗВАНА дверь, которая спасла.

    Там форма записи `X[k] = X.get(k, 0) + 1`, то есть опровергает сама
    форма, а спор связываний до вердикта не доходит. Это и есть причина, по
    которой живой замер даёт ПЯТЬ ложных членов, а не шесть: первый прототип
    этого цикла напечатал шестым ровно это место.
    """
    rows = _rows('''
def alpha(rows, part):
    causes: list = []
    for row in part:
        causes.append(row)
    causes: dict = {}
    for row in rows:
        causes[row["cls"]] = causes.get(row["cls"], 0) + 1
    return causes
''')
    assert len(rows) == 1
    assert rows[0]["member"] == C.MEMBER_REFUTED
    assert rows[0]["doors"] == [C.DOOR_WRITE_FORM]


def test_the_gate_of_the_neighbour_step_is_really_open():
    """Отличие от ADR-518: вердикт выносится и там, где писатель ОТВЕТИЛ.

    Шаг ADR-518 молчит о таких счётчиках по построению (`writer != unresolved`
    ⇒ пустой вердикт). Если гейт вернётся, этот тест краснеет — и ответ о
    двух сотнях снова станет ответом о семнадцати.
    """
    rows = _rows(ONE_MAPPING)
    assert rows[0]["writer"] != C.WRITER_UNRESOLVED
    assert rows[0]["member"] in (C.MEMBER_REFUTED, C.MEMBER_FALSE)
    gated = C._binding_kind_site(
        ast.parse(ONE_MAPPING).body[0], ast.parse(ONE_MAPPING),
        ast.parse("tally").body[0].value,
        {"writer": C.WRITER_SILENT, "writer_gap": None})
    assert gated["kind_outcome"] is None, gated


def test_the_doors_may_contradict_and_the_contradiction_has_its_own_name():
    """`.get` у списка падает `AttributeError` — одна из дверей врёт."""
    rows = _rows('''
def epsilon(rows):
    cell = [0, 0, 0]
    for row in rows:
        cell[row["cls"]] = cell.get(row["cls"], 0) + 1
    return cell
''')
    assert len(rows) == 1
    assert rows[0]["member"] == C.MEMBER_UNMEASURED
    assert rows[0]["member_gap"] == C.MEMBER_GAP_DOORS_CONTRADICT
    assert rows[0]["doors"] == [C.DOOR_WRITE_FORM]


# ------------------------------------------------ КОНТРОЛЬ САМОГО КОНТРОЛЯ

def test_the_positive_half_names_exactly_one_false_member():
    """Иначе находка о НАСЕЛЕНИИ слилась бы с «род не измерен»."""
    assert sum(1 for s in _hit() if s["member"] == C.MEMBER_FALSE) == 1


def test_the_positive_half_exercises_every_declared_door():
    """Дверь без живого случая есть украшение, а не проба."""
    assert {d for s in _hit() for d in s["doors"]} == set(C._MEMBER_DOORS)


def test_the_positive_half_separates_both_named_gaps():
    """Спор дверей и молчание обеих чинятся РАЗНЫМ, значит и зовутся разным."""
    assert ({s["member_gap"] for s in _hit() if s["member_gap"]}
            == set(C._MEMBER_GAPS))


def test_the_negative_half_names_no_false_member():
    """Завысить поправку к знаменателю — тот же дефект, что занизить."""
    assert [s for s in _clean() if s["member"] == C.MEMBER_FALSE] == []


def test_the_negative_half_keeps_a_third_outcome():
    """Мутный накопитель на чистой сцене обязан остаться НЕ ИЗМЕРЕННЫМ."""
    assert any(s["member"] == C.MEMBER_UNMEASURED for s in _clean())


def test_the_control_refuses_when_the_positive_scene_loses_its_sequence(
        monkeypatch):
    """Порванное звено: в положительной сцене не осталось ложного члена."""
    monkeypatch.setattr(C, "MEMBER_CONTROL_SOURCE", C.MEMBER_CONTROL_CLEAN)
    control = C._member_control()
    assert control["passed"] is False
    assert "ложным членом" in control["reason"]


def test_the_control_refuses_when_the_clean_scene_gains_a_sequence(
        monkeypatch):
    """Порванное звено: на отрицательной половине появился ложный член."""
    monkeypatch.setattr(C, "MEMBER_CONTROL_CLEAN", C.MEMBER_CONTROL_SOURCE)
    control = C._member_control()
    assert control["passed"] is False
    assert control["clean_false_positives"], control


def test_the_control_refuses_on_an_unparsable_scene(monkeypatch):
    """Сцена, которую не разобрать, — отказ с причиной, а не ноль."""
    monkeypatch.setattr(C, "MEMBER_CONTROL_SOURCE", "def (")
    control = C._member_control()
    assert control["passed"] is False
    assert "не разобрана" in control["reason"]


# --------------------------------------------- ОТКАЗЫ ШАГА: НИ ОДИН НЕ НОЛЬ

def test_an_unmeasured_neighbour_is_not_zero_false_members():
    """Соседа нет ⇒ знаменателя не существует, а не «поправка равна нулю»."""
    out = C.sequence_members_of_the_whole_population(Path("."), None)
    assert out["status"] == "UNMEASURED"
    assert out["unmeasured_class"] == C.UNMEASURED_MEMBER_NEIGHBOUR
    assert "population" not in out


def test_a_neighbour_without_the_population_field_is_unmeasured():
    """Поле населения отсутствует — отказ, а не подстановка нуля."""
    out = C.sequence_members_of_the_whole_population(
        Path("."), {"status": "MEASURED"})
    assert out["unmeasured_class"] == C.UNMEASURED_MEMBER_NEIGHBOUR


def test_a_neighbour_in_unmeasured_status_is_unmeasured_here(tmp_path):
    """Вердикт соседа `UNMEASURED` наследуется, а не игнорируется."""
    out = C.sequence_members_of_the_whole_population(
        tmp_path, {"status": "UNMEASURED", "open_to_an_unnamed_class": 1})
    assert out["unmeasured_class"] == C.UNMEASURED_MEMBER_NEIGHBOUR


def test_a_failing_control_stops_the_measurement(monkeypatch, tmp_path):
    """Правило не прошло пробу ⇒ замера нет вовсе."""
    monkeypatch.setattr(C, "MEMBER_CONTROL_SOURCE", C.MEMBER_CONTROL_CLEAN)
    out = C.sequence_members_of_the_whole_population(
        tmp_path, {"status": "MEASURED", "open_to_an_unnamed_class": 0})
    assert out["unmeasured_class"] == C.UNMEASURED_MEMBER_CONTROL


def test_a_missing_directory_is_unmeasured_not_an_empty_population(tmp_path):
    """Каталога нет ⇒ «не измерено» с причиной, а не ноль счётчиков."""
    out = C.sequence_members_of_the_whole_population(
        tmp_path, {"status": "MEASURED", "open_to_an_unnamed_class": 0})
    assert out["status"] == "UNMEASURED"
    assert out["unmeasured_class"] == C.UNMEASURED_MEMBER_POPULATION
    assert out["files_unreadable"]


def test_an_unreadable_file_is_unmeasured(tmp_path):
    """Файл не разобран ⇒ население неполно, а неполное не есть измеренное."""
    root = _scene(tmp_path, source=ONE_SEQUENCE)
    (root / C.OPEN_COUNTER_DIRS[0] / "broken.py").write_text(
        "def (", encoding="utf-8")
    out = C.sequence_members_of_the_whole_population(
        root, {"status": "MEASURED", "open_to_an_unnamed_class": 1})
    assert out["unmeasured_class"] == C.UNMEASURED_MEMBER_POPULATION


def test_a_population_disagreement_refuses(tmp_path):
    """Две дороги к одному населению разошлись ЧИСЛОМ ⇒ отказ."""
    root = _scene(tmp_path, source=ONE_SEQUENCE)
    out = C.sequence_members_of_the_whole_population(
        root, {"status": "MEASURED", "open_to_an_unnamed_class": 2})
    assert out["unmeasured_class"] == C.UNMEASURED_MEMBER_POPULATION
    assert out["population"] == 1
    assert out["declared_population"] == 2


def test_equal_counts_with_shifted_coordinates_refuse(monkeypatch, tmp_path):
    """Стык, потерявший узел и удвоивший другой: ЧИСЛО то же, раскладка нет.

    Сверка одних чисел населения этого не видит — ровно тот приём, без
    которого стык заказа G98 п. 2 был бы тих.
    """
    root = _scene(tmp_path, source=ONE_SEQUENCE)
    real = C._open_counter_sites

    def _shifted(rel, tree):
        found = real(rel, tree)
        for site in found:
            if site["key_origin"] == C.KEY_ARTIFACT:
                site["line"] = (site["line"] or 0) + 1000
        return found

    monkeypatch.setattr(C, "_open_counter_sites", _shifted)
    out = C.sequence_members_of_the_whole_population(
        root, {"status": "MEASURED", "open_to_an_unnamed_class": 1})
    assert out["unmeasured_class"] == C.UNMEASURED_MEMBER_COORDINATES
    assert out["population"] == out["declared_population"] == 1
    assert out["coordinates_only_at_the_neighbour"]
    assert out["coordinates_only_here"]


# ------------------------------------------------- ФОРМА ОТВЕТА И АРИФМЕТИКА

def test_the_outcomes_sum_to_the_population(tmp_path):
    """Перечень исходов ЗАКРЫТ: сумма обязана равняться населению."""
    out = _measure(_scene(tmp_path, source=ONE_SEQUENCE + ONE_MAPPING))
    assert sum(out["member_outcomes"].values()) == out["population"]


def test_the_corrected_population_is_the_population_minus_the_union(tmp_path):
    """Знаменатель после вычитания — арифметика, а не отдельное утверждение."""
    out = _measure(_scene(tmp_path, source=ONE_SEQUENCE + ONE_MAPPING))
    assert (out["series_population_corrected"]
            == out["population"] - out["false_members_union"])


def test_the_correction_is_an_interval_with_the_third_outcome_on_top(tmp_path):
    """Нижняя граница доказана, верхняя добавляет НЕ ИЗМЕРЕННОЕ."""
    out = _measure(_scene(tmp_path, source='''
def alpha(rows):
    extra = [0.0] * 3
    for row in rows:
        extra[row["slot"]] += 1
    return extra


def omega(rows, make):
    cell = make()
    for row in rows:
        cell[row["cls"]] += 1
    return cell
'''))
    assert out["correction_at_least"] == out["false_members_union"] == 1
    assert out["correction_at_most"] == (
        out["false_members_union"]
        + out["member_outcomes"][C.MEMBER_UNMEASURED]) == 2


def test_the_two_causes_are_one_field_with_a_measured_overlap(tmp_path):
    """Две причины ложного членства и ИЗМЕРЕННОЕ пересечение, не объявленное.

    Сцена несёт обе причины на РАЗНЫХ счётчиках: пересечение равно нулю
    ЗАМЕРОМ, и это не то же, что «пересечения не бывает».
    """
    out = _measure(_scene(tmp_path, source='''
EXTENSIONS = ("py", "md")


def alpha(rows):
    extra = [0.0] * 3
    for row in rows:
        extra[row["slot"]] += 1
    return extra


def beta(rows, cut):
    by_extension = {ext: 0 for ext in EXTENSIONS}
    for _row in rows:
        by_extension[EXTENSIONS[cut - 1]] = by_extension.get(
            EXTENSIONS[cut - 1], 0) + 1
    return by_extension
'''))
    causes = out["false_members_by_cause"]
    assert causes[C.CAUSE_SEQUENCE] == 1
    assert causes[C.CAUSE_ENUMERATION_INDEX] == 1
    assert out["false_members_overlap"] == 0
    assert out["false_members_union"] == 2
    assert out["series_population_corrected"] == out["population"] - 2


def test_one_counter_may_carry_both_causes_and_the_overlap_counts_it_once(
        tmp_path):
    """Пересечение ИЗМЕРЕНО: один счётчик обеих причин вычитается ОДИН раз.

    Без этой сцены правило «пересечение = 0» было бы неотличимо от замера, и
    поправка к знаменателю считалась бы с двойным вычетом.
    """
    out = _measure(_scene(tmp_path, source='''
EXTENSIONS = ("py", "md")


def alpha(rows, cut):
    extra = [0.0] * 3
    for _row in rows:
        extra[EXTENSIONS[cut - 1]] += 1
    return extra
'''))
    causes = out["false_members_by_cause"]
    assert causes[C.CAUSE_SEQUENCE] == 1
    assert causes[C.CAUSE_ENUMERATION_INDEX] == 1
    assert out["false_members_overlap"] == 1
    assert out["false_members_union"] == 1
    assert out["series_population_corrected"] == out["population"] - 1


def test_the_door_count_is_declared_not_to_sum_to_the_population(tmp_path):
    """У одного места дверей бывает две, и это СКАЗАНО, а не скрыто."""
    out = _measure(_scene(tmp_path, source='''
import collections


def delta(rows, witness):
    for row in rows:
        cell = witness.setdefault(row["cls"], collections.Counter())
        cell[row["kind"]] = cell.get(row["kind"], 0) + 1
    return witness
'''))
    both = C.DOOR_WRITE_FORM + "+" + C.DOOR_BINDING
    assert out["refuted_by_exactly_these_doors"][both] == 1
    assert sum(out["refuted_by_door"].values()) == 2
    assert out["member_outcomes"][C.MEMBER_REFUTED] == 1


CONTRADICTION = '''
def epsilon(rows):
    cell = [0, 0, 0]
    for row in rows:
        cell[row["cls"]] = cell.get(row["cls"], 0) + 1
    return cell
'''


def test_the_outside_cell_carries_its_own_third_outcome(tmp_path):
    """«Ноль вне остатка» есть утверждение лишь при нуле НЕ ИЗМЕРЕННЫХ там."""
    out = _measure(_scene(tmp_path, source=ONE_SEQUENCE + ONE_MAPPING))
    outside = out["outside_the_writer_remainder"]
    assert set(outside) == {"population", "false_members", "unmeasured",
                            "the_only_route_past_refutation"}
    assert outside["population"] == 1
    assert outside["false_members"] == 0
    assert outside["unmeasured"] == 0


def test_outside_the_remainder_only_a_contradiction_escapes_refutation(
        tmp_path):
    """ПОЧЕМУ вне остатка ноль — это ПОСТРОЕНИЕ, и дорога мимо него ОДНА.

    Сцена ставит рядом счётчик, чей род доказал писатель, и счётчик, где
    форма записи спорит со связыванием. Первый опровергнут, второй выходит
    из опровержения — и ЕДИНСТВЕННЫМ названным путём. Без этой сцены клетка
    «вне остатка не измерено» была бы нулём по построению, а её ноль читался
    бы как заслуга замера.
    """
    out = _measure(_scene(tmp_path, source=ONE_MAPPING + CONTRADICTION))
    outside = out["outside_the_writer_remainder"]
    assert outside["population"] == 2
    assert outside["false_members"] == 0
    assert outside["unmeasured"] == 1
    assert out["doors_contradicting"] == 1
    assert (out["unmeasured_reasons"][C.MEMBER_GAP_DOORS_CONTRADICT]
            == outside["unmeasured"])


def test_a_sequence_outside_the_remainder_is_a_contradiction_not_a_member(
        tmp_path):
    """Последовательность, прикрытая формой `.get`, НЕ объявляется ложным
    членом: одна из двух дверей о таком месте врёт, и вычитать его из
    знаменателя значило бы считать по невыясненному."""
    out = _measure(_scene(tmp_path, source=CONTRADICTION))
    assert out["member_outcomes"][C.MEMBER_FALSE] == 0
    assert out["false_members_union"] == 0
    assert out["series_population_corrected"] == out["population"]
    assert out["correction_at_most"] == 1


def test_the_cross_table_is_closed_over_the_declared_verdicts(tmp_path):
    """Перечни обеих осей объявлены: класс вне них не завёл бы новый ключ."""
    out = _measure(_scene(tmp_path, source=ONE_SEQUENCE + ONE_MAPPING))
    cross = out["by_writer_verdict"]
    assert set(cross) == set(C._WRITER_OUTCOMES)
    for row in cross.values():
        assert set(row) == set(C._MEMBER_OUTCOMES)
    assert (sum(sum(row.values()) for row in cross.values())
            == out["population"])


# -------------------------------------- ПЕРЕЧЕНЬ НАБОРОВ ДВЕРЕЙ — ВЫВЕДЕН

def test_the_door_labels_are_derived_from_the_closed_list():
    """Наборов 2**n - 1, и перечень ВЫВЕДЕН, а не перепечатан рядом."""
    labels = C._door_labels(C._MEMBER_DOORS)
    assert len(labels) == 2 ** len(C._MEMBER_DOORS) - 1
    assert len(set(labels)) == len(labels)
    assert C._MEMBER_DOORS[0] in labels


def test_the_door_label_order_matches_the_order_the_site_names_them():
    """Ключ, собранный в другом порядке, молча завёл бы второй класс о том же."""
    labels = C._door_labels(C._MEMBER_DOORS)
    pair = C._MEMBER_DOORS[0] + "+" + C._MEMBER_DOORS[2]
    assert pair in labels
    assert C._MEMBER_DOORS[2] + "+" + C._MEMBER_DOORS[0] not in labels


def test_a_label_outside_the_declared_set_is_a_third_outcome(monkeypatch,
                                                             tmp_path):
    """Класс вне перечня НЕ заводит ключ: он едет отдельным числом."""
    monkeypatch.setattr(C, "_DOOR_LABELS", (C.DOOR_BINDING,))
    out = _measure(_scene(tmp_path, source=ONE_MAPPING))
    assert out["refuted_by_doors_outside_the_declared_labels"] == 1
    assert out["refuted_by_exactly_these_doors"] == {C.DOOR_BINDING: 0}


# ---------------------------------- ПРИБОР В НАСЕЛЕНИИ, КОТОРОЕ САМ МЕРИТ

def test_the_producer_declares_its_own_population():
    """Своё население объявлено ПОЛЕМ, а не оговоркой в тексте."""
    root = Path(C.__file__).resolve().parents[2]
    out = C.sequence_members_of_the_whole_population(
        root, C.open_class_counter_census(root))
    assert out["status"] == "MEASURED", out
    assert out["own_sites"]["producer"] == C.PRODUCER
    assert out["own_sites"]["in_the_population"] >= 0
    assert out["own_sites"]["in_the_false_cell"] == 0


def test_no_function_added_by_this_decision_is_an_open_counter():
    """СТАТИЧЕСКИЙ контроль по своему же исходнику.

    Правило, которым прибор мерит других, применяется к нему самому: ни одна
    функция этого решения не вправе держать открытый счётчик. Иначе головное
    число ряда зависело бы от того, доставлен прибор или нет, — и ни один
    сторож не сказал бы почему (замер заказа G98 п. 2, ADR-566).
    """
    path = Path(C.__file__)
    tree = ast.parse(path.read_text(encoding="utf-8"))
    rows, _peer = C._member_sites(C.PRODUCER, tree)
    mine = [r for r in rows if r["owner"] in OWN_FUNCTIONS]
    assert mine == [], mine


def test_the_step_writes_nothing(tmp_path):
    """Прибор только ЧИТАЕТ: в измеряемое дерево не идёт ни одного байта."""
    root = _scene(tmp_path, source=ONE_SEQUENCE)
    before = {p: p.stat().st_mtime_ns for p in sorted(root.rglob("*"))}
    _measure(root)
    after = {p: p.stat().st_mtime_ns for p in sorted(root.rglob("*"))}
    assert before == after


# ------------------------------------------------------------- ОТЧЁТ

def test_the_report_prints_the_head_number(tmp_path):
    """Число, которого нет в отчёте, не прочитает никто."""
    out = _measure(_scene(tmp_path, source=ONE_SEQUENCE))
    lines = C.report({STEP: out})
    head = [ln for ln in lines if ln.startswith("[ЗНАМЕНАТЕЛЬ РЯДА]")]
    assert len(head) == 1
    assert "класса нет ВОВСЕ у 1" in head[0]


def test_the_report_says_not_measured_when_the_step_is_absent():
    """Шага нет ⇒ «НЕ ИЗМЕРЕНО», а не молчание (инв. #17)."""
    lines = C.report({})
    assert any("[ЗНАМЕНАТЕЛЬ РЯДА] НЕ ИЗМЕРЕНО" in ln for ln in lines)


def test_the_report_names_the_refusal_class():
    """Отказ в отчёте НАЗВАН своим классом, а не общим словом."""
    out = C.sequence_members_of_the_whole_population(Path("."), None)
    lines = C.report({STEP: out})
    assert any(C.UNMEASURED_MEMBER_NEIGHBOUR in ln for ln in lines)


@pytest.mark.parametrize("name", [
    "the_sequence_cause", "the_enumeration_cause", "the_interval",
    "the_two_doors", "the_own_population",
])
def test_the_report_carries_every_promised_line(tmp_path, name):
    """Каждая обещанная строка отчёта предъявлена ОДНИМ замером, не прозой."""
    out = _measure(_scene(tmp_path, source=ONE_SEQUENCE))
    lines = "\n".join(C.report({STEP: out}))
    needed = {
        "the_sequence_cause": "ДВЕ ПРИЧИНЫ ОДНИМ ПОЛЕМ",
        "the_enumeration_cause": "ключ-элемент объявленного перечня",
        "the_interval": "ПОПРАВКА ЕСТЬ ПРОМЕЖУТОК",
        "the_two_doors": "ЧЕМ ОПРОВЕРГНУТО",
        "the_own_population": "ПРИБОР В СВОЁМ НАСЕЛЕНИИ",
    }[name]
    assert needed in lines
