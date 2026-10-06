"""Батарея шага «кому из расколов достаётся судья достижимости» (заказ G100 п. 2).

Предмет шага — не новое население, а ПРОВОДКА уже сделанных замеров. Заказ
дословно (ADR-519):

    Раскол этого шага не передан тому, кто судит его достижимость. Население
    ``split_reachability_at_the_writer`` набрано у ДВУХ шагов (ADR-466,
    ADR-467), и десятый раскол ряда для него не существует. Спросить прямо:
    достижим ли он — и заодно перемерить, сколько расколов ряда вообще доходит
    до этого судьи, а сколько рождается после него.

Главная ловушка предмета: «рождается после» есть утверждение о ПОРЯДКЕ ЗОВОВ,
и проверить его можно либо разбором сборки, либо верой в прозу ADR. Поэтому
батарея давит именно на это: имя судьи в комментарии и в строке зовом НЕ
является (ADR-333), зов в чужой функции тоже, а сборка без судьи обязана
обрывать замер целиком, а не объявлять все расколы рождёнными позже.

Ни одного литерала даты и ни одного литерала pid здесь нет вовсе — предмет
шага не зависит ни от календаря, ни от того, какой номер процесса сегодня
занят. Порядок зовов — ВХОД сцены (`assembly_source=`), а не свойство файла,
поэтому батарея не краснеет от того, что модуль переехал на другие строки.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

if __package__ in (None, ""):                      # прямой запуск без conftest
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from spa_core.monitoring import rule_second_copy_census as C

HANDOVER = "splits_handed_to_the_reachability_judge"
JUDGE = "JUDGE"
#: Шаги ряда в том порядке, в котором их зовёт сборка. Имена берутся у
#: ОБЪЯВЛЕНИЯ модуля, а не перепечатываются: разойдись список с объявлением —
#: батарея мерила бы свой список.
STEP_NAMES = tuple(name for name, _k, _o, _p in C.SPLIT_STEPS_OF_THE_SERIES)
DEFAULT_ORDER = STEP_NAMES[:5] + (JUDGE,) + STEP_NAMES[5:]


# --------------------------------------------------------------- вход сцены

def _assembly(order=DEFAULT_ORDER, *, head="measure"):
    """Сборка как ВХОД: порядок зовов задаётся сценой, а не файлом модуля."""
    lines = [f"def {head}(root):"]
    for index, name in enumerate(order):
        called = C.REACHABILITY_JUDGE_STEP if name == JUDGE else name
        lines.append(f"    v{index} = {called}(root)")
    lines.append("    return 0")
    return "\n".join(lines) + "\n"


def _steps(counts=None):
    """Шесть соседей, каждый со своим перечнем исходов и своим числом.

    Число берётся ПО ИМЕНИ шага, а не по месту в кортеже: переставь
    объявление модуля — и позиционная сцена молча приписала бы число чужому
    шагу (урок ADR-465: имя не есть адрес, но и место не есть имя).
    """
    counts = counts or {}
    out = {}
    for name, _key, outcomes_key, _producer in C.SPLIT_STEPS_OF_THE_SERIES:
        out[name] = {"status": "MEASURED",
                     outcomes_key: {C.ONE_STEP_SPLITS: int(counts.get(name, 0)),
                                    C.ONE_STEP_WHOLESALE: 0,
                                    C.ONE_STEP_UNRESOLVED: 0}}
    return out


def _judge(population=0):
    return {"status": "MEASURED", "population": population}


#: Сцены ряда, у каждой свой производитель раскола. Все пять — СОБСТВЕННЫЕ
#: контрольные сцены соседних шагов: сочинить свои значило бы мерить своё
#: правило о расколе, которого у этого шага нет.
SCENES = {
    "bound_scene.py": C.REACH_CONTROL_SOURCE,
    "tail_scene.py": C.TAIL_CONTROL_SOURCE,
    "loop_scene.py": C.LOOP_KEY_CONTROL_SOURCE,
    "doc_scene.py": C.DOC_READER_CONTROL_SOURCE,
    "field_scene.py": C.FIELD_STEP_CONTROL_SOURCE,
}
#: Замер сцены, снятый ОДИН раз и закреплённый: так батарея знает, какие
#: числа обязаны выйти, и расхождение читается как находка, а не как шум.
SCENE_SPLITS = {"escaped_counter_one_step": 0,
                "container_counter_field_step": 3,
                "document_field_reader_in_file": 4,
                "bound_name_read_in_this_scope": 2,
                "defensive_tail_binding": 3,
                "loop_key_over_a_declared_list": 3}
SCENE_JUDGE = 5


def _tree(tmp_path, scenes=None):
    for sub in C.OPEN_COUNTER_DIRS:
        (tmp_path / sub).mkdir(parents=True, exist_ok=True)
    for name, source in (SCENES if scenes is None else scenes).items():
        (tmp_path / C.OPEN_COUNTER_DIRS[0] / name).write_text(
            source, encoding="utf-8")
    return tmp_path


def _measured(tmp_path, **kw):
    return C.splits_handed_to_the_reachability_judge(
        _tree(tmp_path), _steps(SCENE_SPLITS), _judge(SCENE_JUDGE),
        assembly_source=kw.pop("assembly_source", _assembly()), **kw)


# ------------------------------------------- ПРАВИЛО ПОРЯДКА: ЧТО ЕСТЬ ЗОВ

def test_order_rule_finds_the_call_and_names_its_line():
    order = C._assembly_call_lines(_assembly(), STEP_NAMES
                                   + (C.REACHABILITY_JUDGE_STEP,))
    assert all(order[name] is not None for name in STEP_NAMES)
    judge = order[C.REACHABILITY_JUDGE_STEP]
    assert judge is not None
    before = [n for n in STEP_NAMES if order[n] < judge]
    after = [n for n in STEP_NAMES if order[n] > judge]
    assert len(before) == 5 and after == [STEP_NAMES[5]]


def test_order_rule_answers_none_for_a_name_never_called():
    """`None` — не ноль и не «позже»: имени в сборке НЕТ."""
    order = C._assembly_call_lines(_assembly(), ("never_called_step",))
    assert order == {"never_called_step": None}


def test_a_name_in_a_comment_is_not_a_call():
    """ADR-333: правило не имеет права проходить подстрокой."""
    source = ("def measure(root):\n"
              "    # split_reachability_at_the_writer(root)\n"
              "    return 0\n")
    order = C._assembly_call_lines(source, (C.REACHABILITY_JUDGE_STEP,))
    assert order[C.REACHABILITY_JUDGE_STEP] is None


def test_a_name_in_a_string_is_not_a_call():
    source = ('def measure(root):\n'
              '    note = "split_reachability_at_the_writer(root)"\n'
              '    return note\n')
    order = C._assembly_call_lines(source, (C.REACHABILITY_JUDGE_STEP,))
    assert order[C.REACHABILITY_JUDGE_STEP] is None


def test_a_call_outside_the_assembly_is_not_counted():
    """Зов в ЧУЖОЙ функции порядка сборки не задаёт.

    Иначе любой помощник модуля, позвавший судью, переписал бы ответ на
    вопрос «когда судья спрошен в сборке».
    """
    source = ("def helper(root):\n"
              "    return split_reachability_at_the_writer(root)\n"
              "\n"
              "def measure(root):\n"
              "    return helper(root)\n")
    order = C._assembly_call_lines(source, (C.REACHABILITY_JUDGE_STEP,))
    assert order[C.REACHABILITY_JUDGE_STEP] is None


def test_an_attribute_call_is_a_call():
    """`mod.step(...)` зовом является: предмет — зов, а не форма имени."""
    source = ("def measure(root):\n"
              "    return mod.split_reachability_at_the_writer(root)\n")
    order = C._assembly_call_lines(source, (C.REACHABILITY_JUDGE_STEP,))
    assert order[C.REACHABILITY_JUDGE_STEP] == 2


def test_a_nested_call_is_found():
    """Зов внутри `with`/`if` — всё ещё зов сборки."""
    source = ("def measure(root):\n"
              "    with memo():\n"
              "        if root:\n"
              "            v = split_reachability_at_the_writer(root)\n"
              "    return v\n")
    order = C._assembly_call_lines(source, (C.REACHABILITY_JUDGE_STEP,))
    assert order[C.REACHABILITY_JUDGE_STEP] == 4


def test_two_calls_of_one_name_give_the_earliest_line():
    """Судья, спрошенный дважды, отвечает ПЕРВЫМ зовом.

    Порядок «раньше судьи» обязан мериться от первого его зова: взять
    последний значило бы объявить переданным раскол, которого при первом
    ответе ещё не было.
    """
    source = ("def measure(root):\n"
              "    a = split_reachability_at_the_writer(root)\n"
              "    b = split_reachability_at_the_writer(root)\n"
              "    return a, b\n")
    order = C._assembly_call_lines(source, (C.REACHABILITY_JUDGE_STEP,))
    assert order[C.REACHABILITY_JUDGE_STEP] == 2


def test_order_rule_answers_none_when_there_is_no_assembly_at_all():
    order = C._assembly_call_lines(_assembly(head="not_measure"),
                                   (C.REACHABILITY_JUDGE_STEP,))
    assert order[C.REACHABILITY_JUDGE_STEP] is None


def test_order_rule_does_not_swallow_a_broken_source():
    """Нечитаемая сборка — третий исход у зовущего, а не пустая карта."""
    with pytest.raises(SyntaxError):
        C._assembly_call_lines("def measure(:\n", (JUDGE,))


# ------------------------------------------ ПРАВИЛО ИСХОДА: ТРИ РАЗНЫХ ВРЕДА

def test_a_split_in_the_judge_population_is_handed():
    order = C._assembly_call_lines(_assembly(), STEP_NAMES
                                   + (C.REACHABILITY_JUDGE_STEP,))
    judge = order[C.REACHABILITY_JUDGE_STEP]
    out = C._handover_site(STEP_NAMES[0], True, order, judge)
    assert out["handover"] == C.HANDOVER_HANDED
    assert out["handover_gap"] is None


def test_membership_decides_handover_even_when_the_step_is_not_called():
    """Принадлежность решает УЗЕЛ, а не порядок.

    Два шага ряда вправе найти раскол в одном месте, и тогда вопрос о нём
    ЗАДАН, кем бы он ни был найден. Поставь здесь порядок выше узла — и
    раскол, о котором судья ответил, числился бы непереданным.
    """
    out = C._handover_site("never_called_step", True, {}, 10)
    assert out["handover"] == C.HANDOVER_HANDED


def test_a_step_called_before_the_judge_is_born_before():
    out = C._handover_site("early", False, {"early": 3}, 10)
    assert out["handover"] == C.HANDOVER_BORN_BEFORE
    assert out["handover_gap"] is None
    assert out["step_line"] == 3


def test_a_step_called_after_the_judge_is_born_after():
    out = C._handover_site("late", False, {"late": 30}, 10)
    assert out["handover"] == C.HANDOVER_BORN_AFTER
    assert out["step_line"] == 30


def test_a_step_absent_from_the_assembly_is_the_third_outcome():
    """Шага в сборке нет ⇒ НЕ ИЗМЕРЕНО с причиной, а не «рождён позже»."""
    out = C._handover_site("ghost", False, {"ghost": None}, 10)
    assert out["handover"] == C.HANDOVER_UNMEASURED
    assert out["handover_gap"] == C.HANDOVER_GAP_STEP_NOT_CALLED


def test_the_judge_own_line_is_not_born_after_itself():
    """Зов РОВНО на строке судьи рождённым позже не считается.

    Граница `>` против `>=` — та самая, на которой ряд уже ошибался
    (стоп-кран, ADR-048): раскол, найденный тем же зовом, уже существует.
    """
    out = C._handover_site("same", False, {"same": 10}, 10)
    assert out["handover"] == C.HANDOVER_BORN_BEFORE


def test_the_four_outcomes_are_four_distinct_names():
    assert len(set(C._HANDOVER_OUTCOMES)) == 4


def test_no_outcome_name_is_a_substring_of_another():
    """Имена не вкладываются друг в друга: иначе грубый читатель (grep,
    дашборд, соседний сторож) считал бы одно за другое."""
    for first in C._HANDOVER_OUTCOMES:
        for second in C._HANDOVER_OUTCOMES:
            if first is not second:
                assert first not in second


# --------------------------------------------------- КОНТРОЛЬ ПРАВИЛА

def test_control_passes_on_the_declared_rule():
    control = C._handover_control()
    assert control["passed"], control.get("reason")
    assert control["before"] == 2
    assert control["negative_judge_calls"] == 0
    assert control["outcomes"] == [C.HANDOVER_HANDED, C.HANDOVER_BORN_BEFORE,
                                   C.HANDOVER_BORN_AFTER,
                                   C.HANDOVER_UNMEASURED]


def test_control_scene_mentions_the_judge_without_calling_it():
    """Отрицательная половина существует ровно затем, чтобы правило,
    проходящее подстрокой, краснело: имя судьи в ней ЕСТЬ."""
    assert C.REACHABILITY_JUDGE_STEP in C.HANDOVER_CONTROL_NO_JUDGE
    order = C._assembly_call_lines(C.HANDOVER_CONTROL_NO_JUDGE,
                                   (C.REACHABILITY_JUDGE_STEP,))
    assert order[C.REACHABILITY_JUDGE_STEP] is None


def test_positive_control_scene_also_mentions_the_judge_in_a_comment():
    assert C.HANDOVER_CONTROL_SOURCE.count(C.REACHABILITY_JUDGE_STEP) == 2


def test_control_refuses_when_the_judge_is_not_found_in_the_positive_half(
        monkeypatch):
    monkeypatch.setattr(C, "_assembly_call_lines",
                        lambda src, names: {name: None for name in names})
    control = C._handover_control()
    assert control["passed"] is False
    assert "зов судьи не найден" in control["reason"]


def test_control_refuses_when_an_absent_name_is_given_a_line(monkeypatch):
    """Имя, которого в сборке нет, получило строку ⇒ порядок стал выдумкой."""
    def doctored(src, names):
        return {name: 5 for name in names}
    monkeypatch.setattr(C, "_assembly_call_lines", doctored)
    control = C._handover_control()
    assert control["passed"] is False
    assert "которого в сборке нет" in control["reason"]


def test_control_refuses_when_the_rule_does_not_split_before_and_after(
        monkeypatch):
    def doctored(src, names):
        out = {name: 5 for name in names}
        out["absent_step"] = None
        out[C.REACHABILITY_JUDGE_STEP] = 5
        return out
    monkeypatch.setattr(C, "_assembly_call_lines", doctored)
    control = C._handover_control()
    assert control["passed"] is False
    assert "РАНЬШЕ судьи и зов ПОЗЖЕ" in control["reason"]


def test_control_refuses_when_the_negative_half_finds_a_judge_call(
        monkeypatch):
    real = C._assembly_call_lines

    def doctored(src, names):
        out = real(src, names)
        if src is C.HANDOVER_CONTROL_NO_JUDGE:
            out[C.REACHABILITY_JUDGE_STEP] = 2
        return out
    monkeypatch.setattr(C, "_assembly_call_lines", doctored)
    control = C._handover_control()
    assert control["passed"] is False
    assert "проходит подстрокой" in control["reason"]


def test_control_refuses_when_the_four_outcomes_collapse(monkeypatch):
    monkeypatch.setattr(C, "_handover_site",
                        lambda *a, **k: {"handover": C.HANDOVER_HANDED,
                                         "handover_gap": None,
                                         "step_line": 1})
    control = C._handover_control()
    assert control["passed"] is False
    assert "четырёх разных" in control["reason"]


def test_control_refuses_when_the_third_outcome_has_no_reason(monkeypatch):
    real = C._handover_site

    def doctored(step_name, in_judge, order, judge_line):
        out = real(step_name, in_judge, order, judge_line)
        if out["handover"] == C.HANDOVER_UNMEASURED:
            out["handover_gap"] = None
        return out
    monkeypatch.setattr(C, "_handover_site", doctored)
    control = C._handover_control()
    assert control["passed"] is False
    assert "без причины" in control["reason"]


def test_control_refuses_when_its_own_scene_is_broken(monkeypatch):
    monkeypatch.setattr(C, "HANDOVER_CONTROL_SOURCE", "def measure(:\n")
    control = C._handover_control()
    assert control["passed"] is False
    assert "сцена контроля не разобрана" in control["reason"]


# ------------------------------------------------- ОТКАЗЫ САМОГО ШАГА

def test_step_refuses_without_the_steps_at_all(tmp_path):
    out = C.splits_handed_to_the_reachability_judge(tmp_path, None, _judge())
    assert out["status"] == "UNMEASURED"
    assert out["unmeasured_class"] == C.UNMEASURED_HANDOVER_NEIGHBOUR
    assert "НЕ «расколов нет»" in out["reason"]


@pytest.mark.parametrize("name", STEP_NAMES)
def test_step_refuses_when_any_neighbour_is_unmeasured(tmp_path, name):
    steps = _steps()
    steps[name] = {"status": "UNMEASURED"}
    out = C.splits_handed_to_the_reachability_judge(tmp_path, steps, _judge())
    assert out["unmeasured_class"] == C.UNMEASURED_HANDOVER_NEIGHBOUR
    assert name in out["reason"]


@pytest.mark.parametrize("name", STEP_NAMES)
def test_step_refuses_when_any_neighbour_is_absent(tmp_path, name):
    """`None` у соседа не есть измеренный ноль расколов."""
    steps = _steps()
    steps[name] = None
    out = C.splits_handed_to_the_reachability_judge(tmp_path, steps, _judge())
    assert out["unmeasured_class"] == C.UNMEASURED_HANDOVER_NEIGHBOUR


def test_step_refuses_when_a_neighbour_has_no_outcomes(tmp_path):
    steps = _steps()
    steps[STEP_NAMES[0]] = {"status": "MEASURED"}
    out = C.splits_handed_to_the_reachability_judge(tmp_path, steps, _judge())
    assert out["unmeasured_class"] == C.UNMEASURED_HANDOVER_NEIGHBOUR
    assert "не назвал исходов" in out["reason"]


def test_step_refuses_when_a_neighbour_has_no_split_count(tmp_path):
    name, _key, outcomes_key, _p = C.SPLIT_STEPS_OF_THE_SERIES[0]
    steps = _steps()
    steps[name] = {"status": "MEASURED", outcomes_key: {}}
    out = C.splits_handed_to_the_reachability_judge(tmp_path, steps, _judge())
    assert out["unmeasured_class"] == C.UNMEASURED_HANDOVER_NEIGHBOUR
    assert "не есть ноль расколов" in out["reason"]


@pytest.mark.parametrize("judge", [None, {"status": "UNMEASURED"}])
def test_step_refuses_when_the_judge_itself_is_unmeasured(tmp_path, judge):
    """Судья не измерен ⇒ «ни один раскол не дошёл» было бы ложью."""
    out = C.splits_handed_to_the_reachability_judge(tmp_path, _steps(), judge)
    assert out["unmeasured_class"] == C.UNMEASURED_HANDOVER_NEIGHBOUR
    assert "было бы ложью о проводке" in out["reason"]


def test_step_refuses_when_the_judge_has_no_population(tmp_path):
    out = C.splits_handed_to_the_reachability_judge(tmp_path, _steps(),
                                                    {"status": "MEASURED"})
    assert out["unmeasured_class"] == C.UNMEASURED_HANDOVER_NEIGHBOUR
    assert "не назвал своего населения" in out["reason"]


def test_step_refuses_when_its_own_control_fails(tmp_path, monkeypatch):
    monkeypatch.setattr(C, "_handover_control",
                        lambda: {"passed": False, "reason": "сцена порвана"})
    out = C.splits_handed_to_the_reachability_judge(tmp_path, _steps(),
                                                    _judge())
    assert out["unmeasured_class"] == C.UNMEASURED_HANDOVER_CONTROL
    assert "сцена порвана" in out["reason"]


def test_step_refuses_when_the_assembly_file_is_not_in_the_tree(tmp_path):
    """Сборки в дереве нет ⇒ порядок НЕ ИЗМЕРЕН, а не «все позже»."""
    out = C.splits_handed_to_the_reachability_judge(tmp_path, _steps(),
                                                    _judge())
    assert out["unmeasured_class"] == C.UNMEASURED_HANDOVER_ASSEMBLY
    assert "не прочитана" in out["reason"]


def test_step_refuses_when_the_assembly_is_not_parsed(tmp_path):
    out = C.splits_handed_to_the_reachability_judge(
        tmp_path, _steps(), _judge(), assembly_source="def measure(:\n")
    assert out["unmeasured_class"] == C.UNMEASURED_HANDOVER_ASSEMBLY
    assert "не разобрана" in out["reason"]


def test_step_refuses_when_the_assembly_never_calls_the_judge(tmp_path):
    """Судьи в сборке нет ⇒ отказ целиком.

    Это и есть fail-OPEN, против которого шаг написан: объявить все расколы
    рождёнными после судьи там, где судьи нет вовсе, значило бы ответить
    числом на вопрос, которого никто не задал.
    """
    out = C.splits_handed_to_the_reachability_judge(
        tmp_path, _steps(), _judge(),
        assembly_source=_assembly(order=STEP_NAMES))
    assert out["unmeasured_class"] == C.UNMEASURED_HANDOVER_ASSEMBLY
    assert "судьи нет вовсе" in out["reason"]
    assert out["steps_called"][STEP_NAMES[0]] is not None


def test_step_refuses_when_a_directory_is_missing(tmp_path):
    """Каталога нет ⇒ НЕ ИЗМЕРЕНО: неполное население не есть измеренное."""
    out = C.splits_handed_to_the_reachability_judge(
        tmp_path, _steps(), _judge(), assembly_source=_assembly())
    assert out["unmeasured_class"] == C.UNMEASURED_HANDOVER_POPULATION
    assert out["files_unreadable"]
    assert "население неполно" in out["reason"]


def test_step_refuses_when_a_file_is_not_parsed(tmp_path):
    tree = _tree(tmp_path)
    (tree / C.OPEN_COUNTER_DIRS[0] / "broken.py").write_text(
        "def measure(:\n", encoding="utf-8")
    out = C.splits_handed_to_the_reachability_judge(
        tree, _steps(SCENE_SPLITS), _judge(SCENE_JUDGE),
        assembly_source=_assembly())
    assert out["unmeasured_class"] == C.UNMEASURED_HANDOVER_POPULATION


@pytest.mark.parametrize("name", STEP_NAMES[1:])
def test_step_refuses_when_a_declared_count_disagrees(tmp_path, name):
    """Две дороги к одному населению разошлись ⇒ отказ ИМЕНЕМ шага."""
    declared = dict(SCENE_SPLITS)
    declared[name] = declared[name] + 1
    out = C.splits_handed_to_the_reachability_judge(
        _tree(tmp_path), _steps(declared), _judge(SCENE_JUDGE),
        assembly_source=_assembly())
    assert out["unmeasured_class"] == C.UNMEASURED_HANDOVER_POPULATION
    assert out["step"] == name
    assert "разные вопросы" in out["reason"]


def test_step_refuses_when_the_judge_population_disagrees(tmp_path):
    out = C.splits_handed_to_the_reachability_judge(
        _tree(tmp_path), _steps(SCENE_SPLITS), _judge(SCENE_JUDGE + 1),
        assembly_source=_assembly())
    assert out["unmeasured_class"] == C.UNMEASURED_HANDOVER_POPULATION
    assert out["judge_population"] == SCENE_JUDGE
    assert "принадлежность мерить не от чего" in out["reason"]


# -------------------------------------------------- ИЗМЕРЕННЫЙ КОНТУР

def test_the_scene_carries_all_three_classes_at_once(tmp_path):
    """Сцена обязана нести ВСЕ три исхода: батарея, видевшая один, ничего не
    доказывает о разведении."""
    out = _measured(tmp_path)
    assert out["status"] == "MEASURED", out.get("reason")
    assert out["population"] == sum(SCENE_SPLITS.values())
    assert out["handover_outcomes"][C.HANDOVER_HANDED] == SCENE_JUDGE
    assert out["handover_outcomes"][C.HANDOVER_BORN_AFTER] == \
        SCENE_SPLITS["loop_key_over_a_declared_list"]
    assert out["handover_outcomes"][C.HANDOVER_BORN_BEFORE] == \
        SCENE_SPLITS["document_field_reader_in_file"] \
        + SCENE_SPLITS["container_counter_field_step"]
    assert out["handover_outcomes"][C.HANDOVER_UNMEASURED] == 0


def test_moving_the_judge_moves_the_answer(tmp_path):
    """Порядок зовов есть ВХОД: передвинь судью — и «рождён позже» меняется.

    Положительный контроль самой проводки: число, не зависящее от порядка,
    было бы свойством правила, а не сборки.
    """
    late = STEP_NAMES + (JUDGE,)
    out = _measured(tmp_path, assembly_source=_assembly(order=late))
    assert out["handover_outcomes"][C.HANDOVER_BORN_AFTER] == 0
    assert out["handover_outcomes"][C.HANDOVER_BORN_BEFORE] == \
        sum(SCENE_SPLITS.values()) - SCENE_JUDGE


def test_a_step_missing_from_the_assembly_is_counted_as_unmeasured(tmp_path):
    """Шаг не зван ⇒ его расколы НЕ ИЗМЕРЕНЫ с названной причиной."""
    short = tuple(n for n in DEFAULT_ORDER
                  if n != "document_field_reader_in_file")
    out = _measured(tmp_path, assembly_source=_assembly(order=short))
    assert out["handover_outcomes"][C.HANDOVER_UNMEASURED] == \
        SCENE_SPLITS["document_field_reader_in_file"]
    assert out["unmeasured_reasons"][C.HANDOVER_GAP_STEP_NOT_CALLED] == \
        SCENE_SPLITS["document_field_reader_in_file"]


def test_the_order_answers_the_question_it_was_asked(tmp_path):
    """ОТВЕТ заказа: достижимость НЕПЕРЕДАННЫХ снята правилом судьи."""
    out = _measured(tmp_path)
    reach = out["reachability_of_the_unhanded_splits"]
    assert set(reach) == set(C._REACH_OUTCOMES)
    assert sum(reach.values()) == sum(SCENE_SPLITS.values()) - SCENE_JUDGE
    assert reach[C.REACH_REACHABLE] > 0


def test_the_handed_split_is_not_judged_twice(tmp_path):
    """О переданном расколе шаг достижимости НЕ переспрашивает.

    Вторая дорога к уже данному ответу и есть предмет, который перепись
    ищет: разойдись она с судьёй — числа спорили бы между собой.
    """
    out = _measured(tmp_path)
    assert all(item["reach_asked_here"] is False
               for item in out["handed_sample"])


def test_the_closed_form_declares_every_zero(tmp_path):
    """Форма исходов ЗАКРЫТА, и ноль ОБЪЯВЛЕН (инв. #17)."""
    out = _measured(tmp_path)
    assert set(out["handover_outcomes"]) == set(C._HANDOVER_OUTCOMES)
    assert set(out["unmeasured_reasons"]) == set(C._HANDOVER_GAPS)
    assert out["unmeasured_reasons"][C.HANDOVER_GAP_NO_COORDINATE] == 0


def test_the_sum_of_outcomes_equals_the_population(tmp_path):
    out = _measured(tmp_path)
    assert sum(out["handover_outcomes"].values()) == out["population"]


def test_the_step_names_both_roads_to_the_population(tmp_path):
    out = _measured(tmp_path)
    assert out["splits_by_step"] == SCENE_SPLITS
    assert out["declared_by_step"] == SCENE_SPLITS
    assert out["judge_population"] == out["declared_judge_population"]


def test_the_step_names_the_shared_node_count(tmp_path):
    """Узел, найденный двумя шагами, назван числом, а не промолчан."""
    out = _measured(tmp_path)
    assert out["splits_sharing_a_node_with_another_step"] == 0


def test_the_step_reads_only_and_says_so(tmp_path):
    out = C.splits_handed_to_the_reachability_judge(tmp_path, _steps(),
                                                    _judge())
    assert out["applied"] is False
    assert out["order"] == "G100.2"
    assert out["judge"] == C.REACHABILITY_JUDGE_STEP


def test_the_declared_step_list_is_not_empty_and_has_no_duplicates():
    assert len(STEP_NAMES) == len(set(STEP_NAMES)) == 6


# ------------------------------------------------------------- ОТЧЁТ

def test_the_report_says_unmeasured_when_the_step_is_absent():
    """Шага в артефакте нет ⇒ отчёт говорит НЕ ИЗМЕРЕНО, а не молчит."""
    lines = C.report({"status": "CLEAN"})
    hit = [ln for ln in lines if ln.startswith("[КОМУ ДОСТАЁТСЯ СУДЬЯ]")]
    assert len(hit) == 1, lines
    assert "НЕ ИЗМЕРЕНО" in hit[0]
    assert "НЕ «судья достаётся всем расколам»" in hit[0]


def test_the_report_names_the_refusal_class():
    lines = C.report({HANDOVER: {
        "status": "UNMEASURED",
        "unmeasured_class": C.UNMEASURED_HANDOVER_ASSEMBLY,
        "reason": "порядок не измерен"}})
    hit = [ln for ln in lines if ln.startswith("[КОМУ ДОСТАЁТСЯ СУДЬЯ]")]
    assert C.UNMEASURED_HANDOVER_ASSEMBLY in hit[0]
    assert "порядок не измерен" in hit[0]


def test_the_report_prints_the_three_numbers_and_the_answer(tmp_path):
    step = _measured(tmp_path)
    lines = C.report({HANDOVER: step}, max_rows=10)
    head = [ln for ln in lines if ln.startswith("[КОМУ ДОСТАЁТСЯ СУДЬЯ]")][0]
    assert f"из {step['population']} раскол(ов)" in head
    assert "РОЖДЕНЫ ПОСЛЕ" in head and "УЖЕ СУЩЕСТВОВАЛИ" in head
    for tag in ("[СУДЬЯ · ОТВЕТ ЗАКАЗА]", "[СУДЬЯ · ЧЬИ РАСКОЛЫ]",
                "[СУДЬЯ · ПОРЯДОК СБОРКИ]", "[СУДЬЯ · ПОЧЕМУ НЕ ИЗМЕРЕНО]",
                "[СУДЬЯ · КОНТРОЛЬ]", "[СУДЬЯ · НЕ ПЕРЕДАН]"):
        assert [ln for ln in lines if ln.startswith(tag)], tag
    assert [ln for ln in lines if ln.startswith("[СЛЕПОТА]")]


def test_the_report_names_every_step_of_the_series(tmp_path):
    step = _measured(tmp_path)
    line = [ln for ln in C.report({HANDOVER: step})
            if ln.startswith("[СУДЬЯ · ЧЬИ РАСКОЛЫ]")][0]
    for name in STEP_NAMES:
        assert name in line


# ----------------------------------------------------------- ПРОВОДКА

def test_the_step_is_wired_into_the_document():
    source = Path(C.__file__).read_text(encoding="utf-8")
    assert f'"{HANDOVER}": handover_step,' in source


def test_the_assembly_calls_the_judge_and_all_six_steps():
    """Живая сборка зовёт судью и все шесть шагов.

    Иначе собственный замер шага нёс бы НЕ ИЗМЕРЕНО по причине, не имеющей
    отношения к предмету: шага в сборке просто нет.
    """
    source = Path(C.__file__).read_text(encoding="utf-8")
    order = C._assembly_call_lines(source, STEP_NAMES
                                   + (C.REACHABILITY_JUDGE_STEP,))
    assert all(order[name] is not None for name in order), order


def test_the_step_itself_is_called_after_every_step_it_reads():
    """Шаг зовётся ПОСЛЕ всех шести и после судьи.

    Позови его раньше — и он доложил бы о НЕ ИЗМЕРЕНО у поздних соседей,
    то есть о собственной проводке вместо предмета.
    """
    source = Path(C.__file__).read_text(encoding="utf-8")
    names = STEP_NAMES + (C.REACHABILITY_JUDGE_STEP, HANDOVER)
    order = C._assembly_call_lines(source, names)
    mine = order[HANDOVER]
    assert mine is not None
    assert all(order[name] < mine for name in names if name != HANDOVER)


def test_the_assembly_file_constant_points_at_this_module():
    """Константа пути и есть разбираемый файл: разойдись она — шаг мерил бы
    порядок в чужой сборке."""
    assert Path(C.__file__).as_posix().endswith(C.HANDOVER_ASSEMBLY_FILE)


# ------------------------------- КОНТРОЛЬ НА КОНТРОЛЬ (мутации региона #784)
#
# Первый проход мутационного стенда дал 48 выживших, и почти все оказались
# дырами ЭТОЙ батареи, а не силой правила. Каждый тест ниже назван по своему
# мутанту, потому что «просто добавить проверок» — не то же самое, что
# закрыть названное место.

def test_a_call_whose_func_is_neither_a_name_nor_an_attribute_is_skipped():
    """Мутант: ветка `elif isinstance(func, ast.Attribute)` всегда истинна.

    Сцена без такого зова его не ловила: у вызова вида `factory()()` функция
    не есть ни имя, ни атрибут, и объявленная ветка `else: continue` была
    непроверена ничем — то есть её можно было снять молча.
    """
    source = ("def measure(root):\n"
              "    v = factory(root)(root)\n"
              "    return v\n")
    order = C._assembly_call_lines(source, ("factory", "measure"))
    assert order["factory"] == 2


def test_control_refuses_when_a_step_line_is_none_in_the_order(monkeypatch):
    """Мутант: `is not None and` → `or` в отборе «раньше судьи».

    Сцена контроля всегда даёт обе половины условия истинными, поэтому
    `and`/`or` в ней неотличимы. Подставленный порядок, где у шага строки НЕТ,
    разводит их: при `or` отбор полез бы сравнивать `None` с числом.
    """
    real = C._assembly_call_lines

    def doctored(src, names):
        out = real(src, names)
        if src is C.HANDOVER_CONTROL_SOURCE:
            out["early_step"] = None
        return out
    monkeypatch.setattr(C, "_assembly_call_lines", doctored)
    control = C._handover_control()
    assert control["passed"] is False
    assert "РАНЬШЕ судьи и зов ПОЗЖЕ" in control["reason"]


def test_control_refuses_when_a_step_stands_on_the_judge_own_line(monkeypatch):
    """Мутант: `order[name] < judge` → `<=`.

    Шаг, позванный РОВНО тем же зовом, что судья, «раньше» не стои́т — и
    граница `<` против `<=` обязана быть проверена равенством, иначе её можно
    сдвинуть молча.
    """
    real = C._assembly_call_lines

    def doctored(src, names):
        out = real(src, names)
        if src is C.HANDOVER_CONTROL_SOURCE:
            out["early_step"] = out[C.REACHABILITY_JUDGE_STEP]
        return out
    monkeypatch.setattr(C, "_assembly_call_lines", doctored)
    control = C._handover_control()
    assert control["passed"] is False
    assert "РАНЬШЕ судьи и зов ПОЗЖЕ" in control["reason"]


def test_control_refuses_when_the_late_step_stands_on_the_judge_line(
        monkeypatch):
    """Мутант: `after <= judge` → `after < judge`.

    Та же граница с другой стороны: зов на строке судьи «позже» не стои́т.
    """
    real = C._assembly_call_lines

    def doctored(src, names):
        out = real(src, names)
        if src is C.HANDOVER_CONTROL_SOURCE:
            out["late_step"] = out[C.REACHABILITY_JUDGE_STEP]
        return out
    monkeypatch.setattr(C, "_assembly_call_lines", doctored)
    control = C._handover_control()
    assert control["passed"] is False
    assert "РАНЬШЕ судьи и зов ПОЗЖЕ" in control["reason"]


def test_the_two_neighbour_refusals_name_different_reasons(tmp_path):
    """Мутант: снятие гейта «сосед не измерен» (его класс отказа тот же).

    Класс отказа у «сосед не измерен» и «сосед не назвал исходов» ОДИН, и
    батарея, проверявшая только класс, не видела разницы — снять первый гейт
    можно было молча, второй ответил бы вместо него. Разводит их ПРИЧИНА.
    """
    steps = _steps()
    steps[STEP_NAMES[0]] = {"status": "UNMEASURED"}
    out = C.splits_handed_to_the_reachability_judge(tmp_path, steps, _judge())
    assert "не измерен" in out["reason"]
    assert "не назвал исходов" not in out["reason"]


def test_the_step_counts_the_files_it_looked_at(tmp_path):
    """Мутанты: `scanned = 0` → 1 и `scanned += 1` → `+= 2`.

    Число просмотренных файлов не проверял никто, и счётчик можно было сбить
    молча — а это и есть знаменатель цены шага.
    """
    out = _measured(tmp_path)
    assert out["files_scanned"] == len(SCENES)


def test_the_cheap_gate_declares_its_own_number(tmp_path):
    """Мутант: снятие ворота `_open_counter_sites`.

    Ворот цены по построению не меняет вердикт — значит его мутация не
    наблюдаема НИЧЕМ, пока он не называет своё число. Теперь называет.
    """
    tree = _tree(tmp_path)
    (tree / C.OPEN_COUNTER_DIRS[0] / "empty_scene.py").write_text(
        "X = 1\n", encoding="utf-8")
    out = C.splits_handed_to_the_reachability_judge(
        tree, _steps(SCENE_SPLITS), _judge(SCENE_JUDGE),
        assembly_source=_assembly())
    assert out["status"] == "MEASURED", out.get("reason")
    assert out["files_scanned"] == len(SCENES) + 1
    assert out["files_carrying_an_open_counter"] == len(SCENES)


def test_the_lazy_writer_gate_declares_its_own_number(tmp_path):
    """Мутант: `if any(... != HANDED)` всегда истинно / имя подменено.

    Ленивый разбор писателя — тоже ворот цены: вердикт от него не зависит, и
    без своего числа он снимается молча. Файл, все расколы которого ПЕРЕДАНЫ,
    писателя не стои́т.
    """
    out = C.splits_handed_to_the_reachability_judge(
        _tree(tmp_path, {"bound_scene.py": C.REACH_CONTROL_SOURCE}),
        _steps({"bound_name_read_in_this_scope": 2}), _judge(2),
        assembly_source=_assembly())
    assert out["status"] == "MEASURED", out.get("reason")
    assert out["handover_outcomes"][C.HANDOVER_HANDED] == 2
    assert out["files_whose_writer_was_parsed"] == 0


def test_the_writer_is_parsed_exactly_where_an_unhanded_split_stands(tmp_path):
    out = _measured(tmp_path)
    assert out["files_whose_writer_was_parsed"] == 3


def test_the_unhanded_row_says_its_reachability_was_asked_here(tmp_path):
    """Мутант: `row["reach_asked_here"] = True` → `False`.

    Поле есть ОТВЕТ на вопрос «кто судил этот раскол», и перевёрнутое оно
    приписало бы ответ судье. Проверяется с ОБЕИХ сторон, не с одной.
    """
    out = _measured(tmp_path)
    assert out["unhanded_sample"]
    assert all(item["reach_asked_here"] is True
               for item in out["unhanded_sample"])


def _fake_step(site):
    """Производитель-подставка: отдаёт РОВНО один названный раскол."""
    key = "escaped_counter_one_step"
    outcomes_key = "one_step_outcomes"

    def producer(rel, tree):
        if rel.endswith("bound_scene.py"):
            return [dict(site, one_step=C.ONE_STEP_SPLITS)]
        return []
    return ((key, "one_step", outcomes_key, producer),) \
        + C.SPLIT_STEPS_OF_THE_SERIES[1:]


def test_a_split_without_a_coordinate_is_the_third_outcome(tmp_path,
                                                           monkeypatch):
    """Мутанты: ветка «у раскола нет координаты» и её имена.

    Живые производители координату дают всегда, поэтому объявленную ветку не
    трогал никто — и снять её, или назвать её чужим именем, можно было молча.
    Подставной производитель её обеспечивает.
    """
    site = {"file": None, "line": None, "owner": "ghost", "counter": "c",
            "field": None}
    monkeypatch.setattr(C, "SPLIT_STEPS_OF_THE_SERIES", _fake_step(site))
    declared = dict(SCENE_SPLITS)
    declared["escaped_counter_one_step"] = 1
    out = C.splits_handed_to_the_reachability_judge(
        _tree(tmp_path), _steps(declared), _judge(SCENE_JUDGE),
        assembly_source=_assembly())
    assert out["status"] == "MEASURED", out.get("reason")
    assert out["handover_outcomes"][C.HANDOVER_UNMEASURED] == 1
    assert out["unmeasured_reasons"][C.HANDOVER_GAP_NO_COORDINATE] == 1
    assert out["unmeasured_reasons"][C.HANDOVER_GAP_STEP_NOT_CALLED] == 0


def test_a_node_found_by_two_steps_is_counted_as_shared(tmp_path,
                                                        monkeypatch):
    """Мутанты: `len(owners) > 1` → `> 2` и `sum(1 ...)` → `sum(2 ...)`.

    На живом дереве общих узлов ноль, поэтому число не проверял никто — а
    именно оно не даёт «дошло» тихо раздуваться чужой находкой.
    """
    shared_file = f"{C.OPEN_COUNTER_DIRS[0]}/bound_scene.py"
    site = {"file": shared_file, "line": 10, "owner": "loud_writer",
            "counter": "counts", "field": None}
    monkeypatch.setattr(C, "SPLIT_STEPS_OF_THE_SERIES", _fake_step(site))
    declared = dict(SCENE_SPLITS)
    declared["escaped_counter_one_step"] = 1
    out = C.splits_handed_to_the_reachability_judge(
        _tree(tmp_path), _steps(declared), _judge(SCENE_JUDGE),
        assembly_source=_assembly())
    assert out["status"] == "MEASURED", out.get("reason")
    assert out["splits_sharing_a_node_with_another_step"] == 1
    assert out["handover_outcomes"][C.HANDOVER_HANDED] == SCENE_JUDGE + 1


def test_the_scalar_aliases_name_the_same_numbers_as_the_outcomes(tmp_path):
    """Мутанты: подмена имени исхода в трёх скалярных полях ответа.

    Три скаляра — удобство читателя, и разойдясь с перечнем исходов, они
    спорили бы с ним молча.
    """
    out = _measured(tmp_path)
    outcomes = out["handover_outcomes"]
    assert out["reaches_the_judge"] == outcomes[C.HANDOVER_HANDED]
    assert out["born_after_the_judge"] == outcomes[C.HANDOVER_BORN_AFTER]
    assert out["existed_before_and_still_unhanded"] == \
        outcomes[C.HANDOVER_BORN_BEFORE]


def test_the_skipped_directory_is_not_scanned(tmp_path):
    """Мутант: снятие отбора по `OPEN_COUNTER_SKIP`.

    В сцене не было ни одного файла из пропускаемого каталога, и отбор можно
    было снять молча — население выросло бы на чужих файлах.
    """
    tree = _tree(tmp_path)
    skipped = tmp_path / C.OPEN_COUNTER_SKIP[0]
    skipped.mkdir(parents=True, exist_ok=True)
    (skipped / "archived_scene.py").write_text(C.REACH_CONTROL_SOURCE,
                                               encoding="utf-8")
    out = C.splits_handed_to_the_reachability_judge(
        tree, _steps(SCENE_SPLITS), _judge(SCENE_JUDGE),
        assembly_source=_assembly())
    assert out["status"] == "MEASURED", out.get("reason")
    assert out["files_scanned"] == len(SCENES)


def test_the_report_prints_the_numbers_and_not_just_the_words(tmp_path):
    """Мутанты: `or {}` → `and {}` и подмена имени исхода в самих строках.

    Батарея проверяла СЛОВА отчёта и не проверяла ЧИСЕЛ, поэтому отчёт мог
    печатать `None` на месте любого из них или чужое число — и остаться
    зелёным. Числа читаются из ответа шага, а не перепечатываются.
    """
    step = _measured(tmp_path)
    lines = C.report({HANDOVER: step}, max_rows=10)
    outcomes = step["handover_outcomes"]
    head = [ln for ln in lines if ln.startswith("[КОМУ ДОСТАЁТСЯ СУДЬЯ]")][0]
    assert f"из {step['population']} раскол(ов)" in head
    assert f"спрошен о {outcomes[C.HANDOVER_HANDED]}" in head
    assert f"{outcomes[C.HANDOVER_BORN_AFTER]} РОЖДЕНЫ ПОСЛЕ" in head
    assert f"а {outcomes[C.HANDOVER_BORN_BEFORE]} к его зову" in head
    assert f"не измерено у {outcomes[C.HANDOVER_UNMEASURED]}" in head
    reach = step["reachability_of_the_unhanded_splits"]
    answer = [ln for ln in lines
              if ln.startswith("[СУДЬЯ · ОТВЕТ ЗАКАЗА]")][0]
    assert f"достижим {reach[C.REACH_REACHABLE]} раскол(ов)" in answer
    assert f"недостижим {reach[C.REACH_UNREACHABLE]}" in answer
    assert f"не измерено {reach[C.REACH_UNRESOLVED]}" in answer
    why = [ln for ln in lines
           if ln.startswith("[СУДЬЯ · ПОЧЕМУ НЕ ИЗМЕРЕНО]")][0]
    gaps = step["unmeasured_reasons"]
    assert f"не зван {gaps[C.HANDOVER_GAP_STEP_NOT_CALLED]}" in why
    assert f"координаты {gaps[C.HANDOVER_GAP_NO_COORDINATE]}" in why
    assert (f"двух шагов — "
            f"{step['splits_sharing_a_node_with_another_step']}") in why
    order_line = [ln for ln in lines
                  if ln.startswith("[СУДЬЯ · ПОРЯДОК СБОРКИ]")][0]
    assert f"строке {step['judge_call_line']}" in order_line
    whose = [ln for ln in lines if ln.startswith("[СУДЬЯ · ЧЬИ РАСКОЛЫ]")][0]
    assert f"судья назвал {step['declared_judge_population']}" in whose
    assert f"{step['judge_population']} узл(ов)" in whose


def test_the_report_prints_the_price_of_both_gates(tmp_path):
    """Отчёт называет цену ОБОИХ воротов — иначе их не измеряет никто."""
    step = _measured(tmp_path)
    line = [ln for ln in C.report({HANDOVER: step})
            if ln.startswith("[СУДЬЯ · ЦЕНА]")][0]
    assert f"файлов {step['files_scanned']}" in line
    assert f"счётчик {step['files_carrying_an_open_counter']}" in line
    assert f"разобран у {step['files_whose_writer_was_parsed']}" in line


# -------------------- ВТОРОЙ ПРОХОД СТЕНДА: десять выживших, десять дыр сцены

def test_a_split_with_only_the_line_missing_is_the_third_outcome(tmp_path,
                                                                 monkeypatch):
    """Мутант: `file is None or line is None` → `and`.

    Первая сцена без координаты роняла СРАЗУ ОБА поля, и `and` в ней вёл себя
    точно так же. Раскол без строки, но с файлом, разводит их: узлом он не
    является, а `and` счёл бы его полноценным.
    """
    site = {"file": f"{C.OPEN_COUNTER_DIRS[0]}/bound_scene.py", "line": None,
            "owner": "ghost", "counter": "c", "field": None}
    monkeypatch.setattr(C, "SPLIT_STEPS_OF_THE_SERIES", _fake_step(site))
    declared = dict(SCENE_SPLITS)
    declared["escaped_counter_one_step"] = 1
    out = C.splits_handed_to_the_reachability_judge(
        _tree(tmp_path), _steps(declared), _judge(SCENE_JUDGE),
        assembly_source=_assembly())
    assert out["status"] == "MEASURED", out.get("reason")
    assert out["unmeasured_reasons"][C.HANDOVER_GAP_NO_COORDINATE] == 1


def test_a_coordinateless_split_carries_the_third_reach_outcome(tmp_path,
                                                                monkeypatch):
    """Мутанты: подмена `REACH_UNRESOLVED` и `REACH_GAP_NO_WRITER_SITE`.

    Раскол без узла достижимым объявлен быть не может — писателя искать
    негде. Батарея проверяла только исход ПРОВОДКИ такой строки и не
    проверяла её достижимости, то есть эти два имени можно было подменить
    молча.
    """
    site = {"file": None, "line": None, "owner": "ghost", "counter": "c",
            "field": None}
    monkeypatch.setattr(C, "SPLIT_STEPS_OF_THE_SERIES", _fake_step(site))
    declared = dict(SCENE_SPLITS)
    declared["escaped_counter_one_step"] = 1
    out = C.splits_handed_to_the_reachability_judge(
        _tree(tmp_path), _steps(declared), _judge(SCENE_JUDGE),
        assembly_source=_assembly())
    reach = out["reachability_of_the_unhanded_splits"]
    assert reach[C.REACH_UNRESOLVED] == 1
    ghost = [item for item in out["unhanded_sample"]
             if item["handover"] == C.HANDOVER_UNMEASURED]
    assert ghost and ghost[0]["reach"] == C.REACH_UNRESOLVED
    assert ghost[0]["reach_gap"] == C.REACH_GAP_NO_WRITER_SITE


def test_the_blind_line_names_both_classes_it_contrasts(tmp_path):
    """Мутанты: подмена имени исхода В САМОЙ строке слепоты.

    Строка слепоты противопоставляет ДВА класса и объясняет, почему они
    чинятся разным. Назови она один класс дважды или не тот — объяснение
    стало бы ложью, и ни один тест этого не видел.
    """
    out = _measured(tmp_path)
    first = out["blind"][0]
    assert C.HANDOVER_BORN_BEFORE in first
    assert C.HANDOVER_BORN_AFTER in first
    assert C.HANDOVER_UNMEASURED not in first
    assert C.HANDOVER_HANDED not in first


def test_the_report_prints_the_number_of_each_step(tmp_path):
    """Мутант: `observed(..., 'splits_by_step') or {}` → `and {}`.

    Строка называла ИМЕНА шагов, и числа при них могли все стать `None`.
    """
    step = _measured(tmp_path)
    line = [ln for ln in C.report({HANDOVER: step})
            if ln.startswith("[СУДЬЯ · ЧЬИ РАСКОЛЫ]")][0]
    for name, count in step["splits_by_step"].items():
        assert f"{name} {count}" in line


def test_the_report_prints_the_call_line_of_each_step(tmp_path):
    """Мутант: `observed(..., 'assembly_order') or {}` → `and {}`.

    Проверялась только строка зова СУДЬИ; строки шести шагов могли стать
    `None` все разом, и ответ «кто позван когда» исчез бы молча.
    """
    step = _measured(tmp_path)
    line = [ln for ln in C.report({HANDOVER: step})
            if ln.startswith("[СУДЬЯ · ПОРЯДОК СБОРКИ]")][0]
    for name in STEP_NAMES:
        assert f"{name}:{step['assembly_order'][name]}" in line


def test_the_report_tells_the_two_gaps_apart(tmp_path):
    """Мутанты: подмена `GAP_STEP_NOT_CALLED` ↔ `GAP_NO_COORDINATE`.

    На прежней сцене ОБА числа были нулями, и переставить их местами можно
    было молча. Сцена с непозванным шагом разводит их: 3 против 0.
    """
    short = tuple(n for n in DEFAULT_ORDER
                  if n != "document_field_reader_in_file")
    step = _measured(tmp_path, assembly_source=_assembly(order=short))
    gaps = step["unmeasured_reasons"]
    assert gaps[C.HANDOVER_GAP_STEP_NOT_CALLED] != \
        gaps[C.HANDOVER_GAP_NO_COORDINATE]
    line = [ln for ln in C.report({HANDOVER: step})
            if ln.startswith("[СУДЬЯ · ПОЧЕМУ НЕ ИЗМЕРЕНО]")][0]
    assert f"не зван {gaps[C.HANDOVER_GAP_STEP_NOT_CALLED]}" in line
    assert f"координаты {gaps[C.HANDOVER_GAP_NO_COORDINATE]}" in line


def test_the_report_prints_the_numbers_of_the_control(tmp_path):
    """Мутант: `observed(handover, 'control') or {}` → `and {}`.

    Строка контроля — единственное место, где читатель отчёта видит, что
    правило порядка вообще пробовали на известных случаях. Её числа могли
    стать `None` все разом.
    """
    step = _measured(tmp_path)
    control = step["control"]
    line = [ln for ln in C.report({HANDOVER: step})
            if ln.startswith("[СУДЬЯ · КОНТРОЛЬ]")][0]
    assert f"строке {control['positive']}" in line
    assert f"{control['before']} зов(а)" in line
    assert f"строка {control['after']}" in line
    assert f"найдено {control['negative_judge_calls']}" in line
