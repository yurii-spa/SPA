"""Заказ G102 п. 1 — ПРАВА ли другая дорога, которой судится класс вне
набора ИМЕНОВАННЫХ ключей вердикта (ADR-581, цикл #785).

Сосед `verdict_over_named_keys` (ADR-522) доказал, что класс вне набора
УПОМЯНУТ в области вердикта, и остановился там, где начинается вопрос.
Каждый тест ниже — положительный контроль одной клаузы объявленного правила:
снимешь клаузу — тест краснеет, и краснеет С НАЗВАННЫМ ЗВЕНОМ.

Литеральных дат и литеральных номеров процессов в файле нет вовсе: предмет
разбирается статически, часов и ОС он не спрашивает ни одной дверью.
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

from spa_core.monitoring import rule_second_copy_census as C

#: Тесты с префиксом ``test_live_`` ходят по ЖИВОМУ дереву (550 файлов).
#: Префикс существует ради мутационного стенда и назван здесь, а не в голове:
#: мутант способен сделать обход патологически медленным (замер: прогон
#: батареи с 18 с уезжал за минуты, и 409 мутантов не укладывались ни в один
#: разумный срок), поэтому стенд гоняет батарею БЕЗ них — `-k "not test_live_"`.
#: В CI они идут всегда. Это НЕ ослабление: логика региона доказывается
#: синтетическими сценами, а живые тесты сторожат СВОДКИ и проводку, и
#: мутант, которого ловят только они, обязан быть разобран поимённо.


# ─────────────────────── сцены ───────────────────────

#: Счётчик заведён СВОИМ ЖЕ перечнем классов — форма, на которой первая
#: редакция шага дала 4 ложных `ROAD_IN_THE_VERDICT` из 8 строк населения.
_UNIVERSE_COUNTER = '''
OK = "ok"
WARN = "warn"
BAD = "bad"
CLEAN = "clean"
HARSH = "harsh"
SPLIT = "split"


def classify(row):
    if row.get("harsh"):
        return HARSH
    if row.get("split"):
        return SPLIT
    return CLEAN


def judge(rows):
    counts = {k: 0 for k in (CLEAN, HARSH, SPLIT)}
    for row in rows:
        cls = classify(row)
        counts[cls] = counts.get(cls, 0) + 1
    if counts.get(HARSH):
        status = BAD
    if counts.get(SPLIT):
        status = WARN
    else:
        status = OK
    return {"status": status}


def main(argv=None) -> int:
    doc = judge([])
    return 0 if doc["status"] in (OK, WARN) else 1
'''

#: Класс доходит до условия дороги ЦЕПОЧКОЙ связываний — форма
#: `owner_visibility_census`: `delivered_field_names` → `surface_fields` → тест.
_TRANSITIVE = '''
OK = "ok"
WARN = "warn"
BAD = "bad"
CLEAN = "clean"
FAR = "far"
SPLIT = "split"


def classify(row):
    if row.get("far"):
        return FAR
    if row.get("split"):
        return SPLIT
    return CLEAN


def judge(rows):
    counts = {}
    for row in rows:
        cls = classify(row)
        counts[cls] = counts.get(cls, 0) + 1
    picked = [r for r in rows if r.get("kind") == FAR]
    relayed = len(picked)
    seen = counts.get(CLEAN)
    if relayed:
        status = BAD
    if counts.get(SPLIT):
        status = WARN
    else:
        status = OK
    return {"status": status, "seen": seen}


def main(argv=None) -> int:
    doc = judge([])
    return 0 if doc["status"] in (OK, WARN) else 1
'''


@pytest.fixture(scope="module")
def live_population() -> dict:
    """Население соседа — ОДИН обход дерева на весь модуль.

    По разу на тест это стоило бы 4 с × 9; на мутационном стенде, где батарея
    гоняется по разу на мутанта, та же небрежность умножилась бы на сотни.
    """
    return C._verdict_population(Path("."))


@pytest.fixture(scope="module")
def live_step(live_population: dict) -> dict:
    return C.the_other_road_of_a_named_class(Path("."),
                                            population=live_population)


def _rows(source: str) -> list[dict]:
    return C._road_rows_of_scene("<scene>", source)


def _by_class(source: str) -> dict[str, dict]:
    return {row["cls"]: row for row in _rows(source)}


# ─────────────────── контроль правила ───────────────────

def test_the_declared_rule_passes_its_own_control() -> None:
    control = C._road_control()
    assert control["passed"], control["reason"]


def test_the_control_presents_every_road_grade_and_refusal_name() -> None:
    """Исход, которого сцена не предъявила, правилом НЕ ДОКАЗАН."""
    control = C._road_control()
    assert sorted(control["roads"]) == sorted(C._ROADS)
    assert sorted(control["grades"]) == sorted(C._GRADES)
    assert sorted(control["gaps"]) == sorted(C._ROAD_GAPS)


def test_the_control_anchors_the_known_cases_by_name() -> None:
    """Не «исходы встретились», а ИМЕННО ТЕ у ИМЕННО ТЕХ классов."""
    control = C._road_control()
    assert control["anchors"]["judge_low:harsh"] == C.GRADE_HARSHER
    assert control["anchors"]["judge_high:soft"] == C.GRADE_SOFTER
    assert control["anchors"]["judge_low:mute"] == C.ROAD_ONLY_REPORTED
    assert control["anchors"]["judge_bound:harsh"] == C.ROAD_IN_THE_VERDICT


def test_a_control_that_misses_the_known_case_refuses_the_whole_step(monkeypatch) -> None:
    """Правило не узнало своей сцены ⇒ население НЕ ПЕЧАТАЕТСЯ.

    Печатать число при непройденном контроле значило бы выдать неизмеренное
    за чистое — ровно подделка, против которой написан весь ряд.
    """
    monkeypatch.setattr(C, "_road_control",
                        lambda: {"passed": False, "reason": "сцена подменена"})
    out = C.the_other_road_of_a_named_class(Path("."))
    assert out["status"] == "UNMEASURED"
    assert out["unmeasured_class"] == C.UNMEASURED_ROAD_CONTROL
    assert "population" not in out


# ───── у КОНТРОЛЯ СЦЕНЫ не было своего контроля (замер мутаций #786) ─────
#
# Прогон мутаций цикла #785 оставил в `_road_control` девять выживших, и все
# девять одного рода: они правят ветви, которые на ЖИВЫХ сценах не
# исполняются ни разу. `'passed': False` в любой из ветвей отказа можно было
# переписать на `True`, и ни один тест батареи не покраснел бы — то есть
# отказ контроля был УКРАШЕНИЕМ (`.claude/rules/deployment.md`, «проверка
# сторожа сторожей»), и доказал это мутант, а не чтение глазами.
#
# Тест выше (`test_a_control_that_misses_the_known_case_refuses_the_whole_step`)
# подменяет контроль ЦЕЛИКОМ и потому проверяет реакцию ПОТРЕБИТЕЛЯ; ветвей
# самого контроля он не исполняет вовсе. Ниже — по тесту на каждую ветвь.

#: Второй владелец по имени `judge_low` — ДОСЛОВНАЯ копия `judge_bound` из
#: положительной сцены под чужим именем. У него `clean` только печатается в
#: отчётное поле (`ROAD_ONLY_REPORTED`), тогда как якорь `judge_low:clean`
#: объявлен `GRADE_SAME`: слияние двух владельцев в одно имя обязано
#: предъявить у ключа ДВА исхода вместо одного.
_SHADOW_JUDGE_LOW = '''

def judge_low(rows):
    counts = {}
    for row in rows:
        cls = classify(row)
        counts[cls] = counts.get(cls, 0) + 1
    extra = counts.get(HARSH)
    reported = (counts.get(CLEAN), counts.get(MUTE), counts.get(SOFT), counts.get(TWO))
    if counts.get(SPLIT) or extra:
        status = BAD
    else:
        status = WARN
    return {"status": status, "seen": reported}
'''


def test_a_scene_that_does_not_parse_is_a_refusal_not_a_pass(monkeypatch) -> None:
    """Сцена не разобралась ⇒ правило НЕ ДОКАЗАНО (и это не «прошло»)."""
    monkeypatch.setattr(C, "_ROAD_SCENES", (("broken", "def f(:\n"),))
    control = C._road_control()
    assert control["passed"] is False
    assert "не разобрана" in control["reason"]
    assert "broken" in control["reason"]


def test_a_scene_that_yields_no_pair_at_all_is_a_refusal(monkeypatch) -> None:
    """Разобралась, но правило не узнало НИ ОДНОЙ пары «вердикт × класс».

    Это не то же, что «сцена не разобралась»: синтаксис цел, а узнавания нет,
    и чинится это разным — потому у отказа и своя причина.
    """
    monkeypatch.setattr(C, "_ROAD_SCENES", (("empty", "VALUE = 1\n"),))
    control = C._road_control()
    assert control["passed"] is False
    assert "не дала ни одной пары" in control["reason"]
    assert "empty" in control["reason"]


def test_an_anchor_that_lands_a_second_outcome_is_a_refusal(monkeypatch) -> None:
    """У ИМЕННО ТОГО класса вышел не тот исход ⇒ отказ с НАЗВАННЫМ ключом.

    Причина обязана назвать и ожидаемое, и ВЫШЕДШЕЕ: «ожидался X, вышло
    пусто» нечем отличить от «ключа не было вовсе», а чинится это разным.
    """
    monkeypatch.setattr(
        C, "_ROAD_SCENES",
        (("positive", C.ROAD_CONTROL_SOURCE + _SHADOW_JUDGE_LOW),))
    control = C._road_control()
    assert control["passed"] is False
    assert "judge_low:clean" in control["reason"]
    assert C.GRADE_SAME in control["reason"]
    assert C.ROAD_ONLY_REPORTED in control["reason"]


def test_an_outcome_the_scenes_never_present_is_a_refusal(monkeypatch) -> None:
    """Исход, которого сцена не предъявила, правилом НЕ ДОКАЗАН — это отказ.

    Положительной сцены одной мало: все четыре ИМЕНИ ОТКАЗА живут в
    отрицательных половинах, и без них контроль обязан сказать, чего не
    предъявил, а не промолчать.
    """
    monkeypatch.setattr(C, "_ROAD_SCENES",
                        (("positive", C.ROAD_CONTROL_SOURCE),))
    control = C._road_control()
    assert control["passed"] is False
    assert "контроль не предъявил" in control["reason"]


def test_a_scene_that_is_not_the_positive_one_does_not_set_anchors(monkeypatch) -> None:
    """Якорь читается ТОЛЬКО с положительной сцены, и это НЕСУЩЕЕ условие.

    Отрицательные половины существуют затем, чтобы предъявить имена отказа;
    исходы у тех же `owner:cls` там другие по построению. Приняв их якорями,
    контроль отказал бы на ВЕРНОМ правиле — то есть охрана `label ==
    'positive'` держит сам факт прохождения контроля, а не аккуратность.
    """
    original = C._ROAD_SCENES
    shadow = ("shadow", C.ROAD_CONTROL_SOURCE + _SHADOW_JUDGE_LOW)
    monkeypatch.setattr(C, "_ROAD_SCENES", original + (shadow,))
    assert C._road_control()["passed"] is True, C._road_control()["reason"]
    # обратная половина: та же тень, объявленная ПОЛОЖИТЕЛЬНОЙ, обязана
    # контроль уронить — иначе проверка выше не доказывает ничего
    monkeypatch.setattr(C, "_ROAD_SCENES",
                        original + (("positive", shadow[1]),))
    spoiled = C._road_control()
    assert spoiled["passed"] is False
    assert "judge_low:clean" in spoiled["reason"]


# ─────────── счётчик носителем НЕ является (настоящая бомба) ───────────

def test_a_counter_declared_by_its_own_universe_is_not_a_carrier() -> None:
    """Главная клауза: ИМЯ счётчика несёт все классы разом.

    `counts = {k: 0 for k in (CLEAN, HARSH, SPLIT)}` — и если принять счётчик
    носителем, условие вердикта, читающее счётчик по ЛЮБОМУ ключу, объявится
    «дошедшим до класса само», то есть НЕПОЛНЫЙ перечень ключей объявится
    полным. Это не гипотеза: замер первой редакции шага — 4 ложных
    `ROAD_IN_THE_VERDICT` из 8 строк живого населения.
    """
    rows = _by_class(_UNIVERSE_COUNTER)
    assert rows["harsh"]["road"] == C.ROAD_FOUND
    assert rows["harsh"]["grade"] == C.GRADE_HARSHER
    assert rows["harsh"]["road"] != C.ROAD_IN_THE_VERDICT


def test_the_counter_exclusion_is_load_bearing_not_decoration() -> None:
    """ОТРИЦАТЕЛЬНАЯ половина той же клаузы: сними её — вердикт изменится.

    Исключение проверяется по ИМЕНИ счётчика, поэтому достаточно назвать
    правилу другое имя: счётчик снова становится носителем, и класс ложно
    оказывается дошедшим до условия вердикта.
    """
    tree = ast.parse(_UNIVERSE_COUNTER)
    scope = next(n for n in ast.walk(tree)
                 if isinstance(n, ast.FunctionDef) and n.name == "judge")
    consts = C.toplevel_constants(tree)
    binds = C._scope_bindings(scope)
    token = ("value", "harsh")
    honest = C._carriers_of_the_class(token, consts, binds, "counts")
    blind = C._carriers_of_the_class(token, consts, binds, "<не тот счётчик>")
    assert "counts" not in honest
    assert "counts" in blind, "сцена не воспроизводит бомбу — тест ничего не охраняет"


def test_a_class_reaching_the_test_through_a_chain_of_bindings_is_found() -> None:
    """Пропущенная дорога объявила бы класс НЕПОДСУДНЫМ там, где его судят."""
    rows = _by_class(_TRANSITIVE)
    assert rows["far"]["road"] == C.ROAD_FOUND
    assert rows["far"]["grade"] == C.GRADE_HARSHER
    assert rows["clean"]["road"] == C.ROAD_ONLY_REPORTED


# ─────────────────── исходы дороги ───────────────────

def test_every_road_outcome_is_reachable_and_the_set_is_closed() -> None:
    seen = {row["road"] for _label, src in C._ROAD_SCENES for row in _rows(src)}
    assert seen == set(C._ROADS)


def test_a_class_only_counted_into_a_report_field_is_judged_by_nobody() -> None:
    """«Назван» и «судим» — РАЗНОЕ, и слить их значило бы выдать печать
    числа за вердикт."""
    rows = _by_class(C.ROAD_CONTROL_SOURCE)
    assert rows["mute"]["road"] == C.ROAD_ONLY_REPORTED
    assert rows["mute"]["grade"] is None
    assert rows["mute"]["named_at"], "класс обязан быть НАЗВАН — иначе это не этот исход"


def test_roads_that_disagree_are_not_adjudicated_by_picking_one() -> None:
    # Ключ — ВЛАДЕЛЕЦ и класс: один класс живёт в трёх функциях сцены, и
    # сборка по одному классу молча оставила бы последнюю из трёх.
    rows = {f"{r['owner']}:{r['cls']}": r for r in _rows(C.ROAD_CONTROL_SOURCE)}
    disagreeing = rows["judge_low:two"]
    assert disagreeing["road"] == C.ROAD_DISAGREE
    assert disagreeing["grade"] is None
    assert len(disagreeing["outcomes_of_the_roads"]) > 1
    # тот же класс у соседней функции судим ИНАЧЕ — область решает, не имя
    assert rows["judge_high:two"]["road"] == C.ROAD_ONLY_REPORTED


def test_a_class_reaching_the_verdicts_own_test_is_not_called_another_road() -> None:
    rows = {f"{r['owner']}:{r['cls']}": r for r in _rows(C.ROAD_CONTROL_SOURCE)}
    assert rows["judge_bound:harsh"]["road"] == C.ROAD_IN_THE_VERDICT
    assert rows["judge_bound:harsh"]["roads"] == []


# ─────────────────── оценка сравнения ───────────────────

def test_the_four_grades_are_measured_against_the_branch_the_counter_guards() -> None:
    rows = {f"{r['owner']}:{r['cls']}": r for r in _rows(C.ROAD_CONTROL_SOURCE)}
    assert rows["judge_low:harsh"]["grade"] == C.GRADE_HARSHER
    assert rows["judge_low:clean"]["grade"] == C.GRADE_SAME
    assert rows["judge_low:soft"]["grade"] == C.GRADE_EQUALLY_GRADED
    assert rows["judge_high:soft"]["grade"] == C.GRADE_SOFTER
    # база — исход ветви, которую охраняет САМ счётчик (выбор структурный)
    assert rows["judge_low:harsh"]["baseline"] == "warn"
    assert rows["judge_high:soft"]["baseline"] == "bad"


def test_a_different_outcome_of_the_same_rank_is_not_called_the_same_verdict() -> None:
    """Файл градуирует их одинаково — но исход РАЗНЫЙ, и стереть это
    различие значило бы решить за файл то, чего он не решал."""
    rows = {f"{r['owner']}:{r['cls']}": r for r in _rows(C.ROAD_CONTROL_SOURCE)}
    soft = rows["judge_low:soft"]
    assert soft["grade"] == C.GRADE_EQUALLY_GRADED
    assert soft["ranks"]["road"] == soft["ranks"]["baseline"]
    assert soft["road_outcome"] != soft["baseline"]


# ─────────────── объявленный порядок исходов ───────────────

def test_the_exit_code_of_main_is_the_admitted_declaration_of_direction() -> None:
    rows = _by_class(_UNIVERSE_COUNTER)
    assert rows["harsh"]["ordering_form"] == C.ORDER_BY_EXIT_CODE
    assert rows["harsh"]["ordering_names"] == ["ok", "warn"]


def test_a_bare_ordered_enumeration_declares_no_direction_and_is_refused() -> None:
    """Считать первый элемент самым мягким есть ровно та догадка о смысле
    имён, которую заказ запретил прямо."""
    rows = _by_class(C.ROAD_CONTROL_NO_DIRECTION)
    assert rows["harsh"]["grade"] == C.GRADE_UNMEASURED
    assert rows["harsh"]["gap"] == C.ROAD_GAP_NO_DIRECTION


def test_no_ordering_at_all_is_a_different_refusal_than_no_direction() -> None:
    """«Порядка нет вовсе» и «порядок есть, направления нет» чинятся РАЗНЫМ."""
    rows = _by_class(C.ROAD_CONTROL_NO_ORDERING)
    assert rows["harsh"]["gap"] == C.ROAD_GAP_NO_ORDERING
    assert C.ROAD_GAP_NO_ORDERING != C.ROAD_GAP_NO_DIRECTION


def test_two_declared_orderings_that_disagree_are_an_absence_of_an_answer() -> None:
    rows = _by_class(C.ROAD_CONTROL_DISAGREE)
    assert rows["harsh"]["gap"] == C.ROAD_GAP_ORDERINGS_DISAGREE
    assert rows["harsh"]["grade"] == C.GRADE_UNMEASURED


def test_an_exit_code_outside_main_is_not_a_declaration_of_direction() -> None:
    """Звено объявлено заранее: направление берётся у `main() -> int`."""
    source = _UNIVERSE_COUNTER.replace("def main(argv=None) -> int:",
                                       "def summarise(argv=None) -> int:")
    rows = _by_class(source)
    assert rows["harsh"]["gap"] == C.ROAD_GAP_NO_ORDERING


def test_a_main_without_the_int_annotation_is_not_a_declaration() -> None:
    source = _UNIVERSE_COUNTER.replace("def main(argv=None) -> int:",
                                       "def main(argv=None):")
    rows = _by_class(source)
    assert rows["harsh"]["gap"] == C.ROAD_GAP_NO_ORDERING


def test_an_exit_code_over_classes_outside_the_outcome_family_is_refused() -> None:
    """`return 1 if mode == MODE_FAST else 0` тоже код возврата по
    объявленным именам — но градуирует он не вердикт."""
    source = _UNIVERSE_COUNTER.replace(
        'return 0 if doc["status"] in (OK, WARN) else 1',
        'return 0 if doc["mode"] in (CLEAN, HARSH) else 1')
    rows = _by_class(source)
    assert rows["harsh"]["gap"] == C.ROAD_GAP_NO_ORDERING


def test_equal_exit_codes_on_both_branches_declare_no_order() -> None:
    source = _UNIVERSE_COUNTER.replace(
        'return 0 if doc["status"] in (OK, WARN) else 1',
        'return 0 if doc["status"] in (OK, WARN) else 0')
    rows = _by_class(source)
    assert rows["harsh"]["gap"] == C.ROAD_GAP_NO_ORDERING


def test_a_boolean_is_not_an_exit_code() -> None:
    source = _UNIVERSE_COUNTER.replace(
        'return 0 if doc["status"] in (OK, WARN) else 1',
        'return False if doc["status"] in (OK, WARN) else True')
    rows = _by_class(source)
    assert rows["harsh"]["gap"] == C.ROAD_GAP_NO_ORDERING


def test_a_negated_membership_inverts_the_ranks_it_declares() -> None:
    source = _UNIVERSE_COUNTER.replace(
        'return 0 if doc["status"] in (OK, WARN) else 1',
        'return 1 if doc["status"] not in (OK, WARN) else 0')
    rows = _by_class(source)
    assert rows["harsh"]["grade"] == C.GRADE_HARSHER
    assert rows["harsh"]["ranks"] == {"baseline": 0, "road": 1}


# ─────────────────── цель вердикта ───────────────────

def test_a_verdict_whose_target_is_not_followable_is_the_third_outcome() -> None:
    rows = _by_class(C.ROAD_CONTROL_LOOSE_TARGET)
    assert rows["harsh"]["road"] == C.ROAD_UNMEASURED
    assert rows["harsh"]["gap"] == C.ROAD_GAP_TARGET_UNKNOWN
    assert rows["harsh"]["target"] is None


def test_a_road_that_writes_a_different_target_is_not_a_road() -> None:
    """Обе дороги лежат в одной функции; общего у них только область."""
    source = _UNIVERSE_COUNTER.replace("""    if counts.get(HARSH):
        status = BAD""", """    if counts.get(HARSH):
        other = BAD""")
    rows = _by_class(source)
    assert rows["harsh"]["road"] == C.ROAD_ONLY_REPORTED


# ─────────────── третий исход шага целиком ───────────────

def test_an_unmeasured_parent_population_is_not_zero_roads(monkeypatch) -> None:
    """Инв. #17: «не измерено» обязано быть ОТДЕЛЬНЫМ значением."""
    monkeypatch.setattr(C, "_verdict_population", lambda root: {
        "status": "UNMEASURED", "control": {"passed": True},
        "unmeasured_class": C.UNMEASURED_VERDICT_TREE,
        "reason": "каталога нет в дереве", "files_unreadable": [{"file": "x"}]})
    out = C.the_other_road_of_a_named_class(Path("."))
    assert out["status"] == "UNMEASURED"
    assert out["unmeasured_class"] == C.UNMEASURED_ROAD_POPULATION
    assert "population" not in out and "road_outcomes" not in out
    assert C.UNMEASURED_VERDICT_TREE in out["reason"]


def test_live_the_step_reads_only_and_says_so(live_step: dict) -> None:
    out = live_step
    assert out["applied"] is False
    assert out["order"] == "G102.1"


def test_live_the_sum_of_road_outcomes_equals_the_population(live_step: dict) -> None:
    """Форма исхода ЗАКРЫТА: строка, не попавшая ни в один исход, была бы
    потеряна молча."""
    out = live_step
    assert out["status"] == "MEASURED"
    assert sum(out["road_outcomes"].values()) == out["population"]
    graded = out["road_outcomes"][C.ROAD_FOUND]
    assert sum(out["grades"].values()) == graded


# ─────────────────── отчётное поле точки входа ───────────────────

def test_whether_the_exit_code_reaches_the_os_is_measured_both_ways() -> None:
    assert C._exit_code_reaches_the_os(ast.parse(C.ROAD_CONTROL_DISAGREE)) is True
    assert C._exit_code_reaches_the_os(ast.parse(_UNIVERSE_COUNTER)) is False


def test_the_entry_point_does_not_gate_the_ordering() -> None:
    """Градуировка объявлена типом и значением; точка входа — другое
    утверждение, и смешать их значило бы ответить одним числом на два вопроса."""
    rows = _by_class(_UNIVERSE_COUNTER)
    assert rows["harsh"]["exit_code_reaches_the_os"] is False
    assert rows["harsh"]["ordering_form"] == C.ORDER_BY_EXIT_CODE


# ─────────────── проводка: у шага есть ЧИТАТЕЛЬ ───────────────

def test_live_the_step_has_a_reader_in_the_report(live_step: dict) -> None:
    """Шаг без читателя внутри цикла есть та самая форма, против которой
    написан весь ряд (ADR-526)."""
    doc = {"the_other_road_of_a_named_class": live_step}
    lines = C.format_report(doc)
    assert any("[ДРУГАЯ ДОРОГА]" in line for line in lines)
    assert any("ОТВЕТ ЗАКАЗУ G102" in line for line in lines)


def test_a_report_without_the_step_says_unmeasured_not_silence() -> None:
    lines = C.format_report({})
    assert any("[ДРУГАЯ ДОРОГА] НЕ ИЗМЕРЕНО" in line for line in lines)


def test_a_report_of_an_unmeasured_step_names_its_class() -> None:
    doc = {"the_other_road_of_a_named_class": {
        "status": "UNMEASURED", "unmeasured_class": C.UNMEASURED_ROAD_CONTROL,
        "reason": "сцена подменена"}}
    lines = C.format_report(doc)
    assert any(C.UNMEASURED_ROAD_CONTROL in line for line in lines)


# ─────────────── население не пересчитывается заново ───────────────

def test_live_the_population_is_asked_of_the_neighbour_not_rebuilt(
        live_population: dict, live_step: dict) -> None:
    """Второй обход дерева был бы второй копией правила «что есть вердикт»,
    а этот модуль ровно такие копии и ищет."""
    pop = live_population
    assert pop["status"] == "MEASURED"
    out = live_step
    assert out["parent_population"] == len(pop["rows"])
    assert out["sites"] == sum(1 for r in pop["rows"]
                              if r["verdict"] == C.VERDICT_NAMED_ELSEWHERE)


def test_live_both_steps_read_the_same_population_object(
        live_population: dict, live_step: dict) -> None:
    pop = live_population
    parent = C.verdict_over_named_keys(Path("."), population=pop)
    child = live_step
    assert parent["population"] == child["parent_population"]
    assert child["population"] >= child["sites"]


def test_live_the_context_key_never_leaves_the_step(live_step: dict) -> None:
    """`_ctx` несёт узлы разбора и в артефакт попасть не вправе."""
    import json
    out = live_step
    json.dumps(out, ensure_ascii=False, default=str)
    for item in out["per_site"] + out["sample"] + out["reported_only_sample"]:
        assert "_ctx" not in item


# ─────────────── сцена обязана быть ПРИГОДНОЙ ───────────────

@pytest.mark.parametrize("label,source", C._ROAD_SCENES)
def test_every_scene_actually_produces_population(label: str, source: str) -> None:
    """Сцена, не давшая ни одной пары, не охраняет ничего — и такой
    «зелёный» тест был бы украшением."""
    assert _rows(source), f"сцена {label} пуста"


# ─────────── проводка в шаг цикла: разбором, а не подстрокой ───────────

def _measure_body() -> ast.FunctionDef:
    """Сборка `measure` — ОДИН раз на файл, разбором собственного исходника.

    Подстрокой это не проверяется намеренно (ADR-333): имя шага в
    комментарии и в строке зовом НЕ является, а именно зов и есть предмет.
    """
    source = Path(C.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)
    return next(n for n in tree.body
                if isinstance(n, ast.FunctionDef) and n.name == "measure")


def test_the_cycle_step_actually_calls_the_new_step() -> None:
    calls = [n for n in ast.walk(_measure_body())
             if isinstance(n, ast.Call)
             and getattr(n.func, "id", None) == "the_other_road_of_a_named_class"]
    assert len(calls) == 1, "шаг цикла зовёт шаг ровно один раз"


def test_the_two_steps_share_one_tree_walk() -> None:
    """Обход 550 файлов стои́т секунды; заплатить его дважды значило бы
    купить вторым шагом повтор работы, а не ответ."""
    body = _measure_body()
    walks = [n for n in ast.walk(body) if isinstance(n, ast.Call)
             and getattr(n.func, "id", None) == "_verdict_population"]
    assert len(walks) == 1, "население снимается РОВНО один раз"
    for name in ("verdict_over_named_keys", "the_other_road_of_a_named_class"):
        call = next(n for n in ast.walk(body) if isinstance(n, ast.Call)
                    and getattr(n.func, "id", None) == name)
        assert [kw.arg for kw in call.keywords] == ["population"], \
            f"{name} обязан читать УЖЕ снятое население"


def test_the_step_lands_in_the_document_under_its_own_key() -> None:
    """Ключ, под которым шаг лёг в артефакт, — тот, который читает отчёт."""
    body = _measure_body()
    pairs = {}
    for node in ast.walk(body):
        if isinstance(node, ast.Dict):
            for key, value in zip(node.keys, node.values):
                if isinstance(key, ast.Constant) and isinstance(value, ast.Name):
                    pairs[key.value] = value.id
    assert pairs.get("the_other_road_of_a_named_class") == "road_step"
    assert pairs.get("verdict_over_named_keys") == "verdict_step"


# ─────── общее население: третьи исходы ОБЩЕГО обхода ───────

def test_a_missing_directory_makes_the_shared_population_unmeasured(tmp_path) -> None:
    """Неполное население не есть измеренное — и не есть ноль вердиктов."""
    pop = C._verdict_population(tmp_path)
    assert pop["status"] == "UNMEASURED"
    assert pop["unmeasured_class"] == C.UNMEASURED_VERDICT_TREE
    assert pop["files_unreadable"]
    assert "rows" not in pop


def test_an_unreadable_file_makes_the_shared_population_unmeasured(tmp_path) -> None:
    for sub in C.OPEN_COUNTER_DIRS:
        (tmp_path / sub).mkdir(parents=True, exist_ok=True)
    (tmp_path / C.OPEN_COUNTER_DIRS[0] / "broken.py").write_text(
        "def f(:\n", encoding="utf-8")
    pop = C._verdict_population(tmp_path)
    assert pop["status"] == "UNMEASURED"
    assert pop["unmeasured_class"] == C.UNMEASURED_VERDICT_TREE


def test_a_failed_parent_control_stops_the_shared_population(monkeypatch) -> None:
    monkeypatch.setattr(C, "_verdict_control",
                        lambda: {"passed": False, "reason": "подменено"})
    pop = C._verdict_population(Path("."))
    assert pop["status"] == "UNMEASURED"
    assert pop["unmeasured_class"] == C.UNMEASURED_VERDICT_CONTROL
    assert "rows" not in pop


def test_an_empty_tree_is_measured_with_no_rows_not_unmeasured(tmp_path) -> None:
    """«Измерено и равно нулю» ОБЯЗАНО отличаться от «не измерено» (инв. #17)."""
    for sub in C.OPEN_COUNTER_DIRS:
        (tmp_path / sub).mkdir(parents=True, exist_ok=True)
    pop = C._verdict_population(tmp_path)
    assert pop["status"] == "MEASURED"
    assert pop["rows"] == []
    out = C.the_other_road_of_a_named_class(tmp_path, population=pop)
    assert out["status"] == "MEASURED"
    assert out["population"] == 0 and out["sites"] == 0


# ─────── форма «пара return»: цель есть ВОЗВРАЩАЕМОЕ значение ───────

_RETURN_TARGET_SCENE = '''
OK = "ok"
WARN = "warn"
BAD = "bad"
CLEAN = "clean"
HARSH = "harsh"
SPLIT = "split"


def classify(row):
    if row.get("harsh"):
        return HARSH
    if row.get("split"):
        return SPLIT
    return CLEAN


def judge(rows):
    counts = {k: 0 for k in (CLEAN, HARSH, SPLIT)}
    for row in rows:
        cls = classify(row)
        counts[cls] = counts.get(cls, 0) + 1
    if counts.get(HARSH):
        return BAD
    if counts.get(SPLIT):
        return WARN
    else:
        return OK


def main(argv=None) -> int:
    return 0 if judge([]) in (OK, WARN) else 1
'''

_RETURN_IFEXP_SCENE = '''
OK = "ok"
WARN = "warn"
BAD = "bad"
CLEAN = "clean"
HARSH = "harsh"
SPLIT = "split"


def classify(row):
    if row.get("harsh"):
        return HARSH
    if row.get("split"):
        return SPLIT
    return CLEAN


def judge(rows):
    counts = {k: 0 for k in (CLEAN, HARSH, SPLIT)}
    for row in rows:
        cls = classify(row)
        counts[cls] = counts.get(cls, 0) + 1
    if counts.get(HARSH):
        return BAD
    return WARN if counts.get(SPLIT) else OK


def main(argv=None) -> int:
    return 0 if judge([]) in (OK, WARN) else 1
'''


def test_a_pair_of_returns_is_a_verdict_whose_target_is_the_return_value() -> None:
    rows = _by_class(_RETURN_TARGET_SCENE)
    assert rows["harsh"]["form"] == C.VERDICT_FORM_IF_RETURN
    assert rows["harsh"]["target"] == C.RETURN_TARGET
    assert rows["harsh"]["road"] == C.ROAD_FOUND
    assert rows["harsh"]["grade"] == C.GRADE_HARSHER
    assert rows["harsh"]["baseline"] == "warn"


def test_a_ternary_returned_directly_is_followed_to_the_return_value() -> None:
    rows = _by_class(_RETURN_IFEXP_SCENE)
    assert rows["harsh"]["form"] == C.VERDICT_FORM_IFEXP
    assert rows["harsh"]["target"] == C.RETURN_TARGET
    assert rows["harsh"]["grade"] == C.GRADE_HARSHER


def test_the_family_of_a_return_target_is_file_wide_and_that_is_declared() -> None:
    """Односторонность: у цели-возврата семья собирается по ВСЕМУ файлу, то
    есть вселенные возвратов разных функций сливаются. Названо вслух, потому
    что от этого зависит допуск объявленного порядка."""
    tree = ast.parse(_RETURN_TARGET_SCENE)
    consts = C.toplevel_constants(tree)
    declared = C._declared_constant_names(tree)
    family = C._outcome_family(tree, C.RETURN_TARGET, declared, consts)
    values = {value for _kind, value in family}
    assert {"ok", "warn", "bad"} <= values
    assert "harsh" in values, "возвраты `classify` попадают в ту же семью"


def test_an_assign_target_family_does_not_leak_across_names() -> None:
    tree = ast.parse(_UNIVERSE_COUNTER)
    consts = C.toplevel_constants(tree)
    declared = C._declared_constant_names(tree)
    family = {v for _k, v in C._outcome_family(tree, "status", declared, consts)}
    assert family == {"ok", "warn", "bad"}
    assert "harsh" not in family


# ─────────── формы сравнения в объявленном порядке ───────────

@pytest.mark.parametrize("expr,expected", [
    ('doc["status"] in (OK, WARN)', True),
    ('doc["status"] in [OK, WARN]', True),
    ('doc["status"] in {OK, WARN}', True),
    ('doc["status"] == OK', True),
    ('doc["status"] != OK', True),
    ('doc["status"] not in (OK, WARN)', True),
])
def test_the_forms_of_a_comparison_the_ordering_may_take(expr: str,
                                                         expected: bool) -> None:
    tree = ast.parse(f"OK='ok'\nWARN='warn'\nx = 0 if {expr} else 1\n")
    consts = C.toplevel_constants(tree)
    declared = C._declared_constant_names(tree)
    node = tree.body[-1].value.test
    got = C._compared_classes(node, declared, consts)
    assert (got is not None) is expected


@pytest.mark.parametrize("expr", [
    'doc["status"] < OK',
    'doc["status"] in OK',
    'OK < doc["status"] < WARN',
    'doc.get("status")',
])
def test_a_comparison_this_rule_cannot_read_is_not_an_ordering(expr: str) -> None:
    tree = ast.parse(f"OK='ok'\nWARN='warn'\nx = 0 if {expr} else 1\n")
    consts = C.toplevel_constants(tree)
    declared = C._declared_constant_names(tree)
    assert C._compared_classes(tree.body[-1].value.test, declared, consts) is None


def test_an_empty_membership_list_declares_nothing() -> None:
    tree = ast.parse("OK='ok'\nx = 0 if y in () else 1\n")
    consts = C.toplevel_constants(tree)
    declared = C._declared_constant_names(tree)
    assert C._compared_classes(tree.body[-1].value.test, declared, consts) is None


# ─────────── голый перечень: границы распознавания ───────────

def _bare(source: str, target: str = "status"):
    tree = ast.parse(source)
    consts = C.toplevel_constants(tree)
    declared = C._declared_constant_names(tree)
    family = C._outcome_family(tree, target, declared, consts)
    for node in ast.walk(tree):
        got = C._bare_enumeration(node, family, declared, consts)
        if got is not None:
            return got
    return None


def test_a_one_element_enumeration_is_not_an_order() -> None:
    base = _UNIVERSE_COUNTER.replace("SPLIT = \"split\"",
                                     "SPLIT = \"split\"\nRANK = (OK,)")
    assert _bare(base) is None


def test_an_enumeration_with_a_repeated_outcome_is_not_an_order() -> None:
    base = _UNIVERSE_COUNTER.replace("SPLIT = \"split\"",
                                     "SPLIT = \"split\"\nRANK = (OK, OK, WARN)")
    assert _bare(base) is None


def test_an_enumeration_naming_outcomes_outside_the_family_is_not_an_order() -> None:
    base = _UNIVERSE_COUNTER.replace("SPLIT = \"split\"",
                                     "SPLIT = \"split\"\nRANK = (CLEAN, HARSH)")
    assert _bare(base) is None


def test_an_enumeration_of_the_family_is_recognised_as_directionless() -> None:
    base = _UNIVERSE_COUNTER.replace("SPLIT = \"split\"",
                                     "SPLIT = \"split\"\nRANK = (OK, WARN, BAD)")
    got = _bare(base)
    assert got is not None
    assert got["form"] == C.ORDER_BARE_ENUMERATION
    assert got["default"] is None, "у перечня нет ранга для исхода вне него"


def test_a_rank_outside_a_bare_enumeration_is_unknown_not_zero() -> None:
    shape = {"form": C.ORDER_BARE_ENUMERATION,
             "ranks": {("value", "ok"): 0}, "default": None}
    assert C._rank_in(shape, ("value", "ok")) == 0
    assert C._rank_in(shape, ("value", "bad")) is None


def test_an_exit_code_partition_ranks_every_outcome_by_construction() -> None:
    shape = {"form": C.ORDER_BY_EXIT_CODE,
             "ranks": {("value", "ok"): 0}, "default": 1}
    assert C._rank_in(shape, ("value", "ok")) == 0
    assert C._rank_in(shape, ("value", "anything-at-all")) == 1


# ─────────── точка входа: что считается передачей в sys.exit ───────────

@pytest.mark.parametrize("tail,expected", [
    ("sys.exit(main())", True),
    ("exit(main())", True),
    ("sys.exit(summarise())", False),
    ("sys.exit(0)", False),
    ("sys.exit()", False),
    ("main()", False),
])
def test_what_counts_as_handing_the_code_to_the_os(tail: str,
                                                   expected: bool) -> None:
    tree = ast.parse("import sys\ndef main():\n    return 0\n" + tail + "\n")
    assert C._exit_code_reaches_the_os(tree) is expected


# ─────────── цель: две общие переменные суть неоднозначность ───────────

def test_two_shared_assigned_names_make_the_target_ambiguous() -> None:
    """Выбрать первую по алфавиту значило бы решить за файл."""
    source = _UNIVERSE_COUNTER.replace("""    if counts.get(SPLIT):
        status = WARN
    else:
        status = OK""", """    if counts.get(SPLIT):
        status = WARN
        other = BAD
    else:
        status = OK
        other = OK""")
    rows = _by_class(source)
    assert rows["harsh"]["road"] == C.ROAD_UNMEASURED
    assert rows["harsh"]["gap"] == C.ROAD_GAP_TARGET_UNKNOWN


# ─────────── сводка по вердикту: поля назначены правильному шагу ───────────

def test_live_per_site_rows_carry_the_classes_of_that_site_only(live_step: dict) -> None:
    """Поле, приписанное чужому вердикту, — та же ошибка «по месту, а не по
    имени», что уже стоила циклу #784 ложных чисел."""
    for site in live_step["per_site"]:
        assert site["classes"], "вердикт без классов в это население не входит"
        assert set(site["roads"]) <= set(C._ROADS)
        assert set(site["grades"]) <= set(C._GRADES)
        if C.ROAD_FOUND not in site["roads"]:
            assert site["grades"] == []


def test_live_the_answer_fields_agree_with_the_tallies(live_step: dict) -> None:
    assert live_step["leads_to_a_softer_verdict"] == \
        live_step["grades"][C.GRADE_SOFTER]
    assert live_step["judged_by_no_road_at_all"] == \
        live_step["road_outcomes"][C.ROAD_ONLY_REPORTED]


def test_a_partial_ordering_refuses_instead_of_comparing_none(monkeypatch) -> None:
    """ОХРАНА РАСШИРЕНИЯ, и тест говорит это прямо.

    Единственная допущенная форма порядка (код возврата) ранжирует любой
    исход по построению, поэтому живого файла с частичным порядком в дереве
    нет ни одного. Форма с ЧАСТИЧНЫМ порядком подставляется — и шаг обязан
    ОТКАЗАТЬ, а не сравнить `None` с числом и не угадать.
    """
    partial = {"form": C.ORDER_BARE_ENUMERATION, "line": 1, "names": ["ok"],
               "ranks": {("value", "ok"): 0}, "default": None}
    monkeypatch.setattr(C, "_declared_outcome_ordering",
                        lambda *a, **k: {"ordering": partial,
                                         "bare_enumeration_seen": True})
    rows = _by_class(_UNIVERSE_COUNTER)
    assert rows["harsh"]["road"] == C.ROAD_FOUND
    assert rows["harsh"]["grade"] == C.GRADE_UNMEASURED
    assert rows["harsh"]["gap"] == C.ROAD_GAP_NO_ORDERING


# ───── СБОРКА ОТЧЁТА была не проверена ничем (замер мутаций #786) ─────
#
# Прогон мутаций оставил в `the_other_road_of_a_named_class` одиннадцать
# выживших, и все одиннадцать живут не в ПРАВИЛЕ, а в сборке отчёта: счётчики
# по именам, раскладка по площадкам, образцы, строка слепоты. Живые тесты
# ловили сумму исходов дороги — и только её, поэтому `grades[GRADE_SOFTER]`
# можно было заменить на `grades[GRADE_SAME]`, и **главное число всего
# решения** («к более мягкому вердикту не ведёт ни одна дорога») сменило бы
# подлежащее МОЛЧА: на живом дереве оба равны нулю.
#
# Отчёт проверяется на ВНЕСЁННОМ населении, собранном из контрольных сцен, а
# не на дереве: там есть и мягкая дорога, и спор, и неподсудный класс, и все
# четыре имени отказа, — то есть ровно те исходы, которых живое дерево
# сегодня не производит. Обход дерева при этом не делается ни один.

def _population_of_scenes(sources) -> tuple[dict, list[dict]]:
    """Население ИЗ СЦЕН + строки, которых отчёт обязан быть проекцией.

    Ожидаемое считается ТЕМ ЖЕ `_other_road_row`: предмет проверки —
    СБОРКА отчёта, а не правило дороги (его судят тесты выше и контроль).
    Переписать правило второй копией значило бы проверять копию.
    """
    rows: list[dict] = []
    for label, src in sources:
        found, _skipped = C._verdict_sites(f"<{label}>", ast.parse(src))
        rows.extend(found)
    expected = [C._other_road_row(site, value)
                for site in rows
                if site["verdict"] == C.VERDICT_NAMED_ELSEWHERE
                for value in site.get("missing") or []]
    pop = {"status": "MEASURED", "control": {"passed": True},
           "rows": rows, "files_scanned": len(tuple(sources)),
           "counter_written_in_another_scope": 0, "files_unreadable": []}
    return pop, expected


def _scene_of_only(owner: str) -> str:
    """Положительная сцена, из которой УБРАНЫ все владельцы, кроме одного.

    Нужна затем, чтобы счёт исхода, читаемого отчётом ПО ИМЕНИ, отличался от
    счёта любого другого исхода: в полной сцене `SOFTER`, `SAME`, `HARSHER` и
    `EQUALLY` встречаются по одному разу, и подмена ИМЕНИ в
    `grades[GRADE_SOFTER]` там невидима — ровно этот мутант и выжил у #786 на
    первой редакции сцены. Сцена ПРОИЗВОДНАЯ, а не копия: разойтись с
    положительной она не может.
    """
    tree = ast.parse(C.ROAD_CONTROL_SOURCE)
    tree.body = [node for node in tree.body
                 if not (isinstance(node, ast.FunctionDef)
                         and node.name.startswith("judge_")
                         and node.name != owner)]
    return ast.unparse(tree).replace("judge_low(", f"{owner}(")


_ROAD_SCENES_FOR_REPORT = C._ROAD_SCENES + (("softer_only",
                                             _scene_of_only("judge_high")),)


@pytest.fixture(scope="module")
def scene_report() -> tuple[dict, list[dict]]:
    pop, expected = _population_of_scenes(_ROAD_SCENES_FOR_REPORT)
    return C.the_other_road_of_a_named_class(Path("."),
                                             population=pop), expected


def test_the_scene_population_carries_the_outcomes_the_tree_does_not() -> None:
    """Пригодность сцены — ОТДЕЛЬНЫЙ вопрос, и он задаётся ПЕРВЫМ.

    Сцена, не несущая мягкой дороги, спора и неподсудного класса, сделала бы
    все проверки ниже зелёными бесплатно (урок #785: сцена контроля заводила
    счётчик пустым и потому не несла живой формы).
    """
    _pop, expected = _population_of_scenes(_ROAD_SCENES_FOR_REPORT)
    grades = {r.get("grade") for r in expected}
    roads = {r["road"] for r in expected}
    gaps = {r.get("gap") for r in expected}
    assert C.GRADE_SOFTER in grades, "сцена не несёт МЯГКОЙ дороги"
    assert C.GRADE_HARSHER in grades
    assert C.ROAD_ONLY_REPORTED in roads, "сцена не несёт неподсудного класса"
    assert C.ROAD_DISAGREE in roads
    assert set(C._ROAD_GAPS) <= gaps, "сцена не несёт всех имён отказа"
    # и ОТДЕЛЬНО — различимость по СЧЁТУ, а не по наличию. Отчёт читает
    # `grades` по ИМЕНИ одного исхода (`leads_to_a_softer_verdict`), и если
    # счёт этого исхода равен счёту другого, подмена имени невидима ни одним
    # тестом. Первая редакция сцены давала всем четырём оценкам по одному
    # разу, и мутант `grades[GRADE_SOFTER]` → `grades[GRADE_SAME]` выжил
    # ровно поэтому.
    counts = {name: sum(1 for r in expected if r.get("grade") == name)
              for name in C._GRADES}
    others = [v for name, v in counts.items() if name != C.GRADE_SOFTER]
    assert counts[C.GRADE_SOFTER] not in others, counts


def test_every_tally_of_the_report_is_a_projection_of_its_rows(
        scene_report: tuple[dict, list[dict]]) -> None:
    """Счётчик по ИМЕНИ, а не сумма: подмена имени суммы не видна."""
    out, expected = scene_report
    assert out["status"] == "MEASURED"
    assert out["population"] == len(expected)
    for name in C._ROADS:
        assert out["road_outcomes"][name] == sum(
            1 for r in expected if r["road"] == name), name
    for name in C._GRADES:
        assert out["grades"][name] == sum(
            1 for r in expected if r.get("grade") == name), name
    for name in C._ROAD_GAPS:
        assert out["unmeasured_reasons"][name] == sum(
            1 for r in expected if r.get("gap") == name), name
    assert sum(out["road_outcomes"].values()) == len(expected)


def test_the_headline_numbers_name_the_grade_they_claim(
        scene_report: tuple[dict, list[dict]]) -> None:
    """Два числа решения обязаны считать ИМЕННО свой исход.

    На живом дереве `GRADE_SOFTER` и `GRADE_SAME` равны нулю оба, поэтому
    подмена подлежащего там не видна НИЧЕМ; сцена её видит.
    """
    out, expected = scene_report
    softer = sum(1 for r in expected if r.get("grade") == C.GRADE_SOFTER)
    mute = sum(1 for r in expected if r["road"] == C.ROAD_ONLY_REPORTED)
    assert softer > 0 and mute > 0, "сцена не различает подмену"
    assert out["leads_to_a_softer_verdict"] == softer
    assert out["judged_by_no_road_at_all"] == mute


def test_the_rows_of_a_site_are_the_rows_of_THAT_site(
        scene_report: tuple[dict, list[dict]]) -> None:
    """Раскладка по площадкам обязана РАЗБИВАТЬ население, а не размазывать.

    Склейка условия совпадения («и» → «или») отдала бы каждой площадке чужие
    строки, а сумма по площадкам при этом только выросла бы — поэтому
    проверяется и разбиение, и состав каждой доли.
    """
    out, expected = scene_report
    seen: list[str] = []
    for site in out["per_site"]:
        mine = [r for r in expected
                if (r["file"], r["line"], r["counter"])
                == (site["file"], site["line"], site["counter"])]
        assert site["classes"] == [r["cls"] for r in mine], site["file"]
        assert site["roads"] == sorted({r["road"] for r in mine})
        assert site["grades"] == sorted(
            {r["grade"] for r in mine if r.get("grade")})
        assert site["gaps"] == sorted({r["gap"] for r in mine if r.get("gap")})
        seen += [f"{r['file']}:{r['line']}:{r['counter']}:{r['cls']}"
                 for r in mine]
    assert sorted(seen) == sorted(
        f"{r['file']}:{r['line']}:{r['counter']}:{r['cls']}" for r in expected)


def test_the_per_site_answer_about_the_os_comes_from_a_row_that_has_it(
        scene_report: tuple[dict, list[dict]]) -> None:
    """«Дошёл ли код возврата до ОС» — поле СТРОКИ, а не площадки.

    Спросить его у строки, у которой поля нет, значило бы выдать `None`
    («не измерено») за ответ — а у шага это ОТДЕЛЬНОЕ наблюдение.
    """
    out, expected = scene_report
    for site in out["per_site"]:
        mine = [r for r in expected
                if (r["file"], r["line"], r["counter"])
                == (site["file"], site["line"], site["counter"])]
        want = next((r.get("exit_code_reaches_the_os") for r in mine
                     if "exit_code_reaches_the_os" in r), None)
        assert site["exit_code_reaches_the_os"] == want, site["file"]
    assert any(s["exit_code_reaches_the_os"] is not None
               for s in out["per_site"]), "сцена не несёт ни одного ответа"


def test_the_two_samples_are_disjoint_by_the_class_each_claims(
        scene_report: tuple[dict, list[dict]]) -> None:
    """Образец дорог и образец неподсудных — РАЗНЫЕ множества.

    Оба урезаны одним потолком, поэтому «не тот фильтр» виден только по
    составу, а не по длине.
    """
    out, expected = scene_report
    judged = [r for r in expected if r["road"] != C.ROAD_ONLY_REPORTED]
    mute = [r for r in expected if r["road"] == C.ROAD_ONLY_REPORTED]
    assert len(out["sample"]) == min(C.COSTED_SAMPLE, len(judged))
    assert len(out["reported_only_sample"]) == min(C.COSTED_SAMPLE, len(mute))
    assert all(s["road"] != C.ROAD_ONLY_REPORTED for s in out["sample"])
    assert [s["cls"] for s in out["sample"]] == [r["cls"] for r in judged][
        :C.COSTED_SAMPLE]
    assert [s["cls"] for s in out["reported_only_sample"]] == [
        r["cls"] for r in mute][:C.COSTED_SAMPLE]


def test_the_declared_blindness_names_the_admitted_form(
        scene_report: tuple[dict, list[dict]]) -> None:
    """Односторонность названа ИМЕНЕМ допущенной формы, а не намёком."""
    out, _expected = scene_report
    # имя ДОПУЩЕННОЙ формы стоит в строке дословно; отвергнутая названа
    # там словами («голый упорядоченный перечень»), и требовать её
    # константой значило бы требовать того, чего строка не обещает
    assert any(C.ORDER_BY_EXIT_CODE in line for line in out["blind"])
    assert sum(C.ORDER_BY_EXIT_CODE in line for line in out["blind"]) == 1


def test_an_unmeasured_population_carries_the_files_it_could_not_read() -> None:
    """Третий исход обязан НАЗВАТЬ, чего не прочёл.

    «Население не измерено» без перечня нечем отличить от «каталог пуст», и
    чинится это разным.
    """
    out = C.the_other_road_of_a_named_class(Path("."), population={
        "status": "UNMEASURED", "control": {"passed": True},
        "unmeasured_class": C.UNMEASURED_VERDICT_TREE,
        "reason": "один файл не прочитан",
        "files_unreadable": [{"file": "a/b.py", "reason": "OSError"}]})
    assert out["status"] == "UNMEASURED"
    assert out["unmeasured_class"] == C.UNMEASURED_ROAD_POPULATION
    assert out["files_unreadable"] == [{"file": "a/b.py", "reason": "OSError"}]
    assert "population" not in out
