"""Батарея шага «ДОСТИЖИМ ли раскол ряда» (заказ G85 п. 1, ADR-516).

Предмет шага — не новое население, а СТЫК двух уже сделанных замеров: расколы
у читателя (ADR-466 — шаг по связанному имени, ADR-467 — шаг за защитным
хвостом) и форма вреда у писателя (ADR-469). Вопрос заказа дословно:

    Сколько из СЕМИ расколов ADR-466 и ТРЁХ ADR-467 стоят на писателе, который
    молчит, а сколько — на падающем. Раскол у читателя, до которого класс не
    долетает, есть находка НЕДОСТИЖИМАЯ, и отличить её от достижимой обязано
    ЗВЕНО, а не оговорка.

Поэтому и батарея устроена по ЗВЕНЬЯМ: зелёный контур целиком, красное на
КАЖДОМ порванном звене с НАЗВАННЫМ звеном, и отказ там, где предпосылка не
обеспечена. Ни одного литерала даты и ни одного литерала pid здесь нет вовсе —
предмет шага не зависит ни от календаря, ни от того, какой номер сегодня занят.
"""
from __future__ import annotations

import ast
import sys
from pathlib import Path

import pytest

if __package__ in (None, ""):                      # прямой запуск без conftest
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from spa_core.monitoring import rule_second_copy_census as C

REACH = "split_reachability_at_the_writer"


# --------------------------------------------------------------- вход сцены

def _hit():
    return C._reach_sites("<scene>", ast.parse(C.REACH_CONTROL_SOURCE))


def _clean():
    return C._reach_sites("<scene-clean>", ast.parse(C.REACH_CONTROL_CLEAN))


def _neighbours(bound=7, tail=2):
    """Соседи, ответившие как на живом дереве: 7 расколов + 2 расколa."""
    return (
        {"status": "MEASURED",
         "bound_step_outcomes": {C.ONE_STEP_SPLITS: bound,
                                 C.ONE_STEP_WHOLESALE: 0,
                                 C.ONE_STEP_UNRESOLVED: 0}},
        {"status": "MEASURED",
         "tail_step_outcomes": {C.ONE_STEP_SPLITS: tail,
                                C.ONE_STEP_WHOLESALE: 0,
                                C.ONE_STEP_UNRESOLVED: 0}},
        {"status": "MEASURED"},
    )


# ------------------------------------------------- ЗЕЛЁНЫЙ КОНТУР ЦЕЛИКОМ

def test_control_passes_on_the_declared_rule():
    """Правило объявлено ДО замера и обе половины контроля сходятся."""
    control = C._reach_control()
    assert control["passed"], control.get("reason")
    assert control["reachable"] == 1
    assert control["unreachable"] == 1


def test_the_scene_splits_two_identical_readers_by_their_writer():
    """Оба контура доезжают до читателя ОДИНАКОВО и различаются писателем.

    Это и есть предмет заказа: если правило не разведёт эти два, «сколько
    расколов достижимо» было бы свойством формы побега, а не населения.
    """
    rows = _hit()
    assert len(rows) == 2, rows
    verdicts = {r["owner"]: r["reach"] for r in rows}
    assert verdicts == {"loud_writer": C.REACH_UNREACHABLE,
                        "quiet_writer": C.REACH_REACHABLE}


def test_join_goes_by_node_not_by_the_counter_name():
    """Стык — УЗЕЛ, а не имя: оба счётчика сцены зовутся `counts`.

    Имя не есть адрес (урок ADR-465). Связывай шаг по имени счётчика — и два
    противоположных писателя сцены слились бы в один вердикт.
    """
    rows = _hit()
    assert {r["counter"] for r in rows} == {"counts"}
    assert len({r["line"] for r in rows}) == 2
    assert {r["reach"] for r in rows} == {C.REACH_REACHABLE,
                                          C.REACH_UNREACHABLE}


def test_unreachable_names_the_accumulator_kind():
    """Недостижимость доказана РОДОМ накопителя, а не догадкой."""
    dead = [r for r in _hit() if r["reach"] == C.REACH_UNREACHABLE]
    assert [r["accumulator"] for r in dead] == ["strict"]
    assert [r["proved_by"] for r in dead] == [C.WRITER_BY_KIND]


def test_reachable_is_proved_by_the_form_not_by_the_kind():
    """`X[k] = X.get(k, 0) + 1` открыт ФОРМОЙ — род тут вообще не при чём."""
    live = [r for r in _hit() if r["reach"] == C.REACH_REACHABLE]
    assert [r["proved_by"] for r in live] == [C.WRITER_BY_FORM]
    assert [r["accumulator"] for r in live] == [None]


def test_both_splitting_steps_are_asked():
    """Население приходит от ДВУХ шагов, и оба названы у каждой строки."""
    rows = _reach_rows_of_both_steps()
    assert {r["split_found_by"] for r in rows} == {"bound_name_step",
                                                  "defensive_tail_step"}


def _reach_rows_of_both_steps():
    """Сцена, где раскол находит и шаг по имени, и шаг за защитным хвостом."""
    source = C.REACH_CONTROL_SOURCE + '''

def tail_writer(rows):
    counts = {}
    for row in rows:
        cls = str(row.get("verdict"))
        counts[cls] = counts.get(cls, 0) + 1
    return {"tailed": counts}


def tail_caller(rows):
    doc = tail_writer(rows)
    return len(doc)


def tail_reader(doc):
    c = doc.get("tailed") or {}
    return c[VERDICT_DIRTY] > 0
'''
    return C._reach_sites("<scene-both>", ast.parse(source))


# --------------------------------- КРАСНОЕ НА КАЖДОМ ПОРВАННОМ ЗВЕНЕ

def test_control_reddens_when_the_writer_step_is_torn_off(monkeypatch):
    """Звено «вердикт писателя»: без него достижимость не измерить вовсе."""
    monkeypatch.setattr(C, "_writer_kind_sites", lambda rel, tree: [])
    control = C._reach_control()
    assert control["passed"] is False
    assert control["reachable"] == 0 and control["unreachable"] == 0
    assert "недостижимых расколов вместо 1 и 1" in control["reason"]


def test_control_reddens_when_the_bound_name_step_is_torn_off(monkeypatch):
    """Звено «раскол по связанному имени»: населения не остаётся."""
    monkeypatch.setattr(C, "_bound_name_sites", lambda rel, tree: [])
    control = C._reach_control()
    assert control["passed"] is False
    assert control["sites"] == 0


def test_control_reddens_when_the_kind_rule_calls_everything_forgiving(
        monkeypatch):
    """Звено «род накопителя»: объяви всё снисходительным — оба достижимы."""
    monkeypatch.setattr(C, "_accumulator_kind", lambda expr: "forgiving")
    control = C._reach_control()
    assert control["passed"] is False
    assert control["reachable"] == 2 and control["unreachable"] == 0


def test_control_reddens_when_the_kind_rule_calls_everything_strict(
        monkeypatch):
    """Обратное звено: объяви всё строгим — ловит ОТРИЦАТЕЛЬНАЯ половина.

    Положительная половина этого не заметит, и это верно: `.get(k, D)`
    открывает класс ЛЮБЫМ родом, поэтому молчащий раскол доказан ФОРМОЙ и
    подмена рода его не трогает. Пойман подлог там, где непрозрачный род стал
    решённым, — то есть ровно там, где исчез третий исход.
    """
    monkeypatch.setattr(C, "_accumulator_kind", lambda expr: "strict")
    control = C._reach_control()
    assert control["passed"] is False
    assert control["clean_gap"] is None
    assert "не назвала причину третьего исхода" in control["reason"]
    # положительная половина при этом цела — и это НЕ слабость сцены, а факт
    # о доказательстве: форма сильнее рода и от его подмены не зависит.
    assert {r["reach"] for r in _hit()} == {C.REACH_REACHABLE,
                                            C.REACH_UNREACHABLE}


def test_control_reddens_when_the_clean_half_resolves(monkeypatch):
    """Отрицательная половина: разреши непрозрачный род — и она соврёт.

    Без этой половины «шаг нашёл N достижимых» было бы неотличимо от «шаг
    объявляет достижимым что угодно».
    """
    real = C._accumulator_kind

    def _always(expr):
        got = real(expr)
        return "forgiving" if got is None else got

    monkeypatch.setattr(C, "_accumulator_kind", _always)
    control = C._reach_control()
    assert control["passed"] is False
    assert control["clean_false_positives"] == 1


def test_clean_half_answers_with_the_third_outcome_and_names_it():
    """Непрозрачный накопитель ⇒ НЕ ИЗМЕРЕНО с причиной, а не «достижимо»."""
    rows = _clean()
    assert len(rows) == 1, rows
    assert rows[0]["reach"] == C.REACH_UNRESOLVED
    assert rows[0]["reach_gap"] == C.REACH_GAP_WRITER_UNRESOLVED
    assert rows[0]["writer_gap"] == C.WRITER_GAP_OPAQUE


# ------------------------------------------- ВЕТКИ ОДНОГО РАСКОЛА

def test_missing_writer_site_is_the_third_outcome_not_a_verdict():
    """Писателя в узле нет ⇒ отказ поимённо, а не досчитанный раскол.

    По построению две дороги к населению разойтись не могут — обе зовут одну и
    ту же соседскую функцию отбора. Ветка и остаётся затем, чтобы расхождение
    ОДНАЖДЫ стало отказом, и проверяется она ПРЯМО: сцены, которая рассорит
    две копии одного правила, не существует.
    """
    out = C._reach_site({"file": "f.py", "line": 1}, None)
    assert out["reach"] == C.REACH_UNRESOLVED
    assert out["reach_gap"] == C.REACH_GAP_NO_WRITER_SITE
    assert out["writer"] is None and out["accumulator"] is None


@pytest.mark.parametrize("gap", list(C._WRITER_GAPS))
def test_every_writer_gap_lands_in_the_third_outcome(gap):
    """Любая причина «род не доказан» ⇒ третий исход, и причина СОХРАНЕНА."""
    out = C._reach_site({"file": "f.py", "line": 1},
                        {"writer": C.WRITER_UNRESOLVED, "writer_gap": gap,
                         "accumulator": None, "proved_by": None,
                         "keyerror_reaches_the_caller": None})
    assert out["reach"] == C.REACH_UNRESOLVED
    assert out["reach_gap"] == C.REACH_GAP_WRITER_UNRESOLVED
    assert out["writer_gap"] == gap


def test_verdict_is_read_by_equality_not_by_substring():
    """Вердикт писателя читается РАВЕНСТВОМ (ADR-333).

    Имя, лишь СОДЕРЖАЩЕЕ вердикт, вердиктом не является: приняв подстроку, шаг
    объявил бы достижимым то, о чём писатель не сказал ничего.
    """
    for near in (C.WRITER_SILENT + "_extra", "not_" + C.WRITER_SILENT,
                 C.WRITER_LOUD + "_extra", "x" + C.WRITER_LOUD):
        out = C._reach_site({"file": "f.py", "line": 1},
                            {"writer": near, "writer_gap": None,
                             "accumulator": None, "proved_by": None,
                             "keyerror_reaches_the_caller": None})
        assert out["reach"] == C.REACH_UNRESOLVED, near
        assert out["reach_gap"] == C.REACH_GAP_WRITER_UNRESOLVED


def test_the_two_outcome_names_are_not_substrings_of_each_other():
    """Имена исходов не вкладываются друг в друга — иначе читатель отчёта
    (grep, дашборд, соседний сторож) считал бы одно за другое."""
    assert C.REACH_REACHABLE not in C.REACH_UNREACHABLE
    assert C.REACH_UNREACHABLE not in C.REACH_REACHABLE


def test_swallowed_keyerror_is_carried_not_dropped():
    """Оговорка к недостижимому доезжает ЧИСЛОМ, а не исчезает."""
    out = C._reach_site({"file": "f.py", "line": 1},
                        {"writer": C.WRITER_LOUD, "writer_gap": None,
                         "accumulator": "strict",
                         "proved_by": C.WRITER_BY_KIND,
                         "keyerror_reaches_the_caller": False})
    assert out["reach"] == C.REACH_UNREACHABLE
    assert out["keyerror_reaches_the_caller"] is False


# ------------------------------------------------- ОТКАЗЫ САМОГО ШАГА

@pytest.mark.parametrize("which", [0, 1, 2])
def test_step_refuses_when_any_neighbour_is_unmeasured(tmp_path, which):
    """Любой сосед не измерен ⇒ отказ, а НЕ «недостижимых нет»."""
    steps = list(_neighbours())
    steps[which] = {"status": "UNMEASURED"}
    out = C.split_reachability_at_the_writer(tmp_path, *steps)
    assert out["status"] == "UNMEASURED"
    assert out["unmeasured_class"] == C.UNMEASURED_REACH_NEIGHBOUR
    assert "НЕ «недостижимых нет»" in out["reason"]


@pytest.mark.parametrize("which", [0, 1, 2])
def test_step_refuses_when_any_neighbour_is_absent(tmp_path, which):
    """Отсутствующий сосед — тот же отказ: `None` не есть измеренный ноль."""
    steps = list(_neighbours())
    steps[which] = None
    out = C.split_reachability_at_the_writer(tmp_path, *steps)
    assert out["status"] == "UNMEASURED"
    assert out["unmeasured_class"] == C.UNMEASURED_REACH_NEIGHBOUR


def test_step_refuses_when_the_neighbour_has_no_outcomes(tmp_path):
    """Соседа спрашивают ЧЕСТНО: поля нет ⇒ сверять не с чем, а не ноль."""
    bound, tail, writer = _neighbours()
    out = C.split_reachability_at_the_writer(tmp_path, {"status": "MEASURED"},
                                            tail, writer)
    assert out["unmeasured_class"] == C.UNMEASURED_REACH_NEIGHBOUR
    assert "не назвал исходов" in out["reason"]


def test_step_refuses_when_the_neighbour_has_no_split_count(tmp_path):
    """Нет числа расколов ⇒ отказ: отсутствие поля не есть ноль расколов."""
    bound, tail, writer = _neighbours()
    bound = {"status": "MEASURED", "bound_step_outcomes": {}}
    out = C.split_reachability_at_the_writer(tmp_path, bound, tail, writer)
    assert out["unmeasured_class"] == C.UNMEASURED_REACH_NEIGHBOUR
    assert "не есть ноль расколов" in out["reason"]


def test_step_refuses_when_its_own_control_fails(tmp_path, monkeypatch):
    """Правило, промахнувшееся по известному случаю, не мерит НИЧЕГО."""
    monkeypatch.setattr(C, "_reach_control",
                        lambda: {"passed": False, "reason": "сцена порвана"})
    out = C.split_reachability_at_the_writer(tmp_path, *_neighbours())
    assert out["unmeasured_class"] == C.UNMEASURED_REACH_CONTROL
    assert "сцена порвана" in out["reason"]


def test_step_refuses_when_a_directory_is_missing(tmp_path):
    """Каталога нет ⇒ НЕ ИЗМЕРЕНО с причиной, а не «расколов ноль».

    Прямое требование инварианта #17: неполное население не есть измеренное.
    """
    out = C.split_reachability_at_the_writer(tmp_path, *_neighbours())
    assert out["status"] == "UNMEASURED"
    assert out["unmeasured_class"] == C.UNMEASURED_REACH_POPULATION
    assert out["files_unreadable"]
    assert "население неполно" in out["reason"]


def test_step_refuses_when_the_population_disagrees_with_the_neighbours(
        tmp_path):
    """Две дороги к одному населению разошлись ⇒ отказ, а не своё число."""
    for sub in C.OPEN_COUNTER_DIRS:
        (tmp_path / sub).mkdir(parents=True, exist_ok=True)
    (tmp_path / C.OPEN_COUNTER_DIRS[0] / "scene.py").write_text(
        C.REACH_CONTROL_SOURCE, encoding="utf-8")
    out = C.split_reachability_at_the_writer(tmp_path, *_neighbours())
    assert out["status"] == "UNMEASURED"
    assert out["unmeasured_class"] == C.UNMEASURED_REACH_POPULATION
    assert out["population"] == 2 and out["declared_population"] == 9
    assert "отвечают на разные вопросы" in out["reason"]


def test_step_measures_when_the_neighbours_agree(tmp_path):
    """Согласились числа — шаг отвечает, и ответ разложен по исходам."""
    for sub in C.OPEN_COUNTER_DIRS:
        (tmp_path / sub).mkdir(parents=True, exist_ok=True)
    (tmp_path / C.OPEN_COUNTER_DIRS[0] / "scene.py").write_text(
        C.REACH_CONTROL_SOURCE, encoding="utf-8")
    out = C.split_reachability_at_the_writer(tmp_path,
                                            *_neighbours(bound=2, tail=0))
    assert out["status"] == "MEASURED", out.get("reason")
    assert out["population"] == 2
    assert out["reach_outcomes"][C.REACH_REACHABLE] == 1
    assert out["reach_outcomes"][C.REACH_UNREACHABLE] == 1
    assert out["reach_outcomes"][C.REACH_UNRESOLVED] == 0
    assert out["unreachable_reaching_the_caller"] == 1
    assert out["unreachable_but_swallowed_here"] == 0


def test_measured_answer_keeps_the_third_outcome_key_at_zero(tmp_path):
    """Ноль третьего исхода ОБЪЯВЛЕН, а не пропущен.

    «Измерено и равно нулю» обязано быть отличимо от «не спрашивали» у самого
    читателя отчёта (инвариант #17), поэтому форма исходов ЗАКРЫТА.
    """
    for sub in C.OPEN_COUNTER_DIRS:
        (tmp_path / sub).mkdir(parents=True, exist_ok=True)
    (tmp_path / C.OPEN_COUNTER_DIRS[0] / "scene.py").write_text(
        C.REACH_CONTROL_SOURCE, encoding="utf-8")
    out = C.split_reachability_at_the_writer(tmp_path,
                                            *_neighbours(bound=2, tail=0))
    assert set(out["reach_outcomes"]) == set(C._REACH_OUTCOMES)
    assert set(out["unresolved_reasons"]) == set(C._REACH_GAPS)
    assert out["unresolved_reasons"][C.REACH_GAP_NO_WRITER_SITE] == 0


def test_step_reads_only_and_says_so(tmp_path):
    """ADVISORY объявлен полем, а не прозой в заметке."""
    out = C.split_reachability_at_the_writer(tmp_path, *_neighbours())
    assert out["applied"] is False
    assert out["order"] == "G85.1"


# ------------------------------------------------------------- ПРОВОДКА

def test_the_step_is_wired_into_the_report_and_says_unmeasured_when_absent():
    """Шага в артефакте нет ⇒ отчёт говорит НЕ ИЗМЕРЕНО, а не молчит.

    Урок всего ряда: сторож, который при отсутствии своего входа МОЛЧИТ,
    неотличим от сторожа, сказавшего «чисто».
    """
    lines = C.report({"status": "CLEAN"})
    hit = [ln for ln in lines if ln.startswith("[ДОСТИЖИМОСТЬ РАСКОЛА]")]
    assert len(hit) == 1, lines
    assert "НЕ ИЗМЕРЕНО" in hit[0]
    assert "НЕ «все расколы достижимы»" in hit[0]


def test_the_report_names_the_refusal_class_of_the_step():
    """Отказ шага доезжает до отчёта ИМЕНЕМ класса, а не одним словом."""
    lines = C.report({REACH: {"status": "UNMEASURED",
                              "unmeasured_class": C.UNMEASURED_REACH_CONTROL,
                              "reason": "правило промахнулось"}})
    hit = [ln for ln in lines if ln.startswith("[ДОСТИЖИМОСТЬ РАСКОЛА]")]
    assert C.UNMEASURED_REACH_CONTROL in hit[0]
    assert "правило промахнулось" in hit[0]


def test_the_report_prints_both_numbers_and_the_unreachable_rows(tmp_path):
    """Отчёт называет ОБА числа и перечисляет недостижимые расколы."""
    for sub in C.OPEN_COUNTER_DIRS:
        (tmp_path / sub).mkdir(parents=True, exist_ok=True)
    (tmp_path / C.OPEN_COUNTER_DIRS[0] / "scene.py").write_text(
        C.REACH_CONTROL_SOURCE, encoding="utf-8")
    step = C.split_reachability_at_the_writer(tmp_path,
                                             *_neighbours(bound=2, tail=0))
    lines = C.report({REACH: step})
    head = [ln for ln in lines if ln.startswith("[ДОСТИЖИМОСТЬ РАСКОЛА]")][0]
    assert "из 2 раскол(ов)" in head
    assert [ln for ln in lines
            if ln.startswith("[ДОСТИЖИМОСТЬ · НЕДОСТИЖИМ]")]
    assert [ln for ln in lines if ln.startswith("[ДОСТИЖИМОСТЬ · КОНТРОЛЬ]")]
    assert [ln for ln in lines
            if ln.startswith("[ДОСТИЖИМОСТЬ · ОГОВОРКА К НЕДОСТИЖИМОМУ]")]


def test_the_step_is_wired_into_measure():
    """Шаг объявлен в сборщике, и зовут его ТРЕМЯ соседями, а не одним."""
    source = Path(C.__file__).read_text(encoding="utf-8")
    assert f'"{REACH}": reach_step,' in source
    assert ("reach_step = split_reachability_at_the_writer(root, bound_step, "
            "tail_step,") in source


# ------------------------------------- КОНТРОЛЬ НА КОНТРОЛЬ (цикл #733)
#
# Мутационная батарея региона нашла ЧЕТЫРЕ выживших, и три из них были
# слабостью ИМЕННО этой батареи: клаузы контроля проверялись только своим
# исходом «passed», а поодиночке их не трогал никто — снять любую можно было
# молча. Тот же урок, что закрыл ADR-469 (#690). Четвёртый выживший — дыра в
# СЦЕНЕ: в ней не было ни одного НЕ раскола, и отбор можно было снять,
# ничего не сломав.

def test_non_split_counters_never_enter_the_population():
    """Счётчик, чей читатель безвреден, в население НЕ попадает.

    Отбор по `ONE_STEP_SPLITS` — не украшение: сними его, и шаг начнёт
    считать достижимость у находок, которых нет. На живом дереве это поймала
    бы сверка с соседями, но ловить обязано ЗВЕНО, а не последствие.
    """
    source = C.REACH_CONTROL_SOURCE + '''

def whole_writer(rows):
    counts = {}
    for row in rows:
        cls = str(row.get("verdict"))
        counts[cls] = counts.get(cls, 0) + 1
    return {"whole": counts}


def whole_caller(rows):
    doc = whole_writer(rows)
    return len(doc)


def whole_reader(doc):
    c = doc["whole"]
    return sum(c.values())
'''
    tree = ast.parse(source)
    neighbour = {r["owner"]: r["bound_step"]
                 for r in C._bound_name_sites("<scene-whole>", tree)}
    assert neighbour["whole_writer"] == C.ONE_STEP_WHOLESALE
    rows = C._reach_sites("<scene-whole>", tree)
    assert {r["owner"] for r in rows} == {"loud_writer", "quiet_writer"}


def test_control_requires_the_accumulator_kind_of_the_unreachable(monkeypatch):
    """Клауза контроля о РОДЕ: снять её нельзя молча.

    Недостижимость без названного рода означает, что вердикт писателя не
    доехал, — а значит достижимость доказана не им.
    """
    real = C._writer_kind_site
    monkeypatch.setattr(C, "_writer_kind_site",
                        lambda *a, **k: {**real(*a, **k),
                                         "accumulator": None})
    control = C._reach_control()
    assert control["passed"] is False
    assert control["accumulator"] is None
    assert "без рода накопителя" in control["reason"]


def test_control_requires_the_form_proof_of_the_reachable(monkeypatch):
    """Клауза контроля о ФОРМЕ: достижимость молчащего доказана `.get(k, D)`.

    Подменится доказательство — и «достижимо» станет словом, за которым не
    стои́т ни форма, ни род.
    """
    real = C._writer_kind_site
    monkeypatch.setattr(C, "_writer_kind_site",
                        lambda *a, **k: {**real(*a, **k), "proved_by": None})
    control = C._reach_control()
    assert control["passed"] is False
    assert control["proved_by"] is None
    assert "доказана не формой" in control["reason"]


def test_control_requires_the_missing_writer_branch(monkeypatch):
    """Клауза контроля о ПРОПАВШЕМ писателе: её тоже нельзя снять молча.

    Ветка существует ради дня, когда две дороги к населению разойдутся; без
    своей клаузы она осталась бы кодом, который никто ни разу не спросил.
    """
    real = C._reach_site

    def _blind(split, writer):
        out = real(split, writer)
        return {**out, "reach": C.REACH_REACHABLE} if writer is None else out

    monkeypatch.setattr(C, "_reach_site", _blind)
    control = C._reach_control()
    assert control["passed"] is False
    assert "не отвечает третьим исходом" in control["reason"]
