"""Батарея шага «стык двух осей у ОСТАЛЬНЫХ открытых счётчиков» (ADR-566).

Каждый тест — ПОЛОЖИТЕЛЬНЫЙ КОНТРОЛЬ на одну форму тихого вреда, а не
украшение: проверка, никогда не видевшая настоящей поломки, ничего не держит
(`.claude/rules/deployment.md`, «Проверка сторожа сторожей»).

Время и строки обеих осей здесь ВХОДЫ, а не окружение: литеральных дат и
литеральных pid в файле нет вовсе, поэтому ни календарь, ни номера процессов
хоста вердикта не меняют.
"""

from __future__ import annotations

import ast
import datetime as dt
import json
from pathlib import Path

import pytest

from spa_core.monitoring import reachability_of_the_rest as step
from spa_core.monitoring import rule_second_copy_census as census

# FROZEN-DATE-OK: injected-clock — ЕДИНСТВЕННЫЙ якорь файла (`NOW`) уходит
# аргументом `now=` в `step.measure`/`step.run`, а все отметки, с которыми шаг
# его сравнивает, производны от ТОГО ЖЕ якоря (`NOW.isoformat()`,
# `NOW - dt.timedelta(...)`). Закреплены обе стороны сравнения, поэтому
# календарь хоста вердикта не меняет: стенных часов в файле нет ни одних.
NOW = dt.datetime(2000, 1, 2, 3, 4, 5, tzinfo=dt.timezone.utc)


def _rd(line, verdict, *, file="a.py", counter="c", gap=None):
    return {"file": file, "line": line, "counter": counter,
            "verdict": verdict, "gap": gap}


def _wr(line, writer, *, file="a.py", counter="c", gap=None):
    return {"file": file, "line": line, "counter": counter,
            "writer": writer, "writer_gap": gap}


def _scene():
    """Сцена: по одному узлу на КАЖДУЮ клетку стыка плюс состыкованный."""
    reader = [
        _rd(1, census.READER_SPLITS_DECLARED),      # + silent  -> главное
        _rd(2, census.READER_SPLITS_DECLARED),      # + loud
        _rd(3, census.READER_SPLITS_DECLARED),      # + unresolved
        _rd(4, census.READER_UNRESOLVED),           # + silent  -> тёмная
        _rd(5, census.READER_UNRESOLVED),           # + loud
        _rd(6, census.READER_UNRESOLVED),           # + unresolved -> оба
        _rd(7, census.READER_WHOLESALE_ONLY),       # лишняя строка
        _rd(8, census.READER_SPLITS_DECLARED),      # СОСТЫКОВАННЫЙ соседом
    ]
    writer = [
        _wr(1, census.WRITER_SILENT), _wr(2, census.WRITER_LOUD),
        _wr(3, census.WRITER_UNRESOLVED), _wr(4, census.WRITER_SILENT),
        _wr(5, census.WRITER_LOUD), _wr(6, census.WRITER_UNRESOLVED),
        _wr(7, census.WRITER_SILENT), _wr(8, census.WRITER_SILENT),
    ]
    asked = [{"file": "a.py", "line": 8, "counter": "c"}]
    return reader, writer, asked


def _published(reader, writer, asked, *, stamp=None):
    rm, wm = {}, {}
    for r in reader:
        rm[r["verdict"]] = rm.get(r["verdict"], 0) + 1
    for w in writer:
        wm[w["writer"]] = wm.get(w["writer"], 0) + 1
    return {"reader_population": len(reader), "writer_population": len(writer),
            "asked_population": len(asked), "reader_margin": rm,
            "writer_margin": wm,
            "generated_at": (stamp or NOW).isoformat()}


def _measure(reader=None, writer=None, asked=None, published=None, **kw):
    reader, writer, asked = (reader, writer, asked) if reader is not None \
        else _scene()
    return step.measure(Path("/nonexistent"), now=NOW,
                        published=published or _published(reader, writer,
                                                          asked),
                        reader_rows=reader, writer_rows=writer,
                        asked_rows=asked, **kw)


# --- 1. КЛЕТКИ: каждая пара вердиктов даёт своё имя ------------------------

def test_every_cell_of_the_cross_is_counted_once():
    doc = _measure()
    assert doc["status"] == "MEASURED"
    assert doc["cross"] == {
        step.CELL_HARM_REACHABLE: 1, step.CELL_HARM_UNREACHABLE: 1,
        step.CELL_HARM_WRITER_UNMEASURED: 1, step.CELL_DARK: 1,
        step.CELL_READER_UNMEASURED_LOUD: 1, step.CELL_BOTH_UNMEASURED: 1,
        step.CELL_EXTRA_LINE: 1, step.CELL_UNJOINED: 0}


@pytest.mark.parametrize("reader_verdict,writer_verdict,cell", [
    (census.READER_SPLITS_DECLARED, census.WRITER_SILENT,
     step.CELL_HARM_REACHABLE),
    (census.READER_SPLITS_DECLARED, census.WRITER_LOUD,
     step.CELL_HARM_UNREACHABLE),
    (census.READER_SPLITS_DECLARED, census.WRITER_UNRESOLVED,
     step.CELL_HARM_WRITER_UNMEASURED),
    (census.READER_UNRESOLVED, census.WRITER_SILENT, step.CELL_DARK),
    (census.READER_UNRESOLVED, census.WRITER_LOUD,
     step.CELL_READER_UNMEASURED_LOUD),
    (census.READER_UNRESOLVED, census.WRITER_UNRESOLVED,
     step.CELL_BOTH_UNMEASURED),
    (census.READER_WHOLESALE_ONLY, census.WRITER_SILENT,
     step.CELL_EXTRA_LINE),
    (None, census.WRITER_SILENT, step.CELL_UNJOINED),
    (census.READER_SPLITS_DECLARED, None, step.CELL_UNJOINED),
])
def test_the_cell_rule_names_each_pair(reader_verdict, writer_verdict, cell):
    assert step._cell(reader_verdict, writer_verdict) == cell


def test_a_silent_writer_under_a_split_reader_is_the_headline_not_a_footnote():
    """Главное число заказа обязано стоять ПОЛЕМ, а не тонуть в сводке."""
    doc = _measure()
    assert doc["cross"][step.CELL_HARM_REACHABLE] == 1
    headline = [line for line in step.report(doc) if "❗ОТВЕТ" in line]
    assert len(headline) == 1, "главного числа в отчёте нет или их несколько"
    # Число стои́т В САМОЙ строке ответа, а не только в сводке клеток ниже.
    assert "— 1;" in headline[0]
    assert "spa_core" not in headline[0]


# --- 2. СОСТЫКОВАННЫЙ УЗЕЛ исключён из остатка ----------------------------

def test_the_node_the_neighbour_already_asked_is_out_of_the_rest():
    reader, writer, asked = _scene()
    doc = _measure(reader, writer, asked)
    assert doc["asked_by_the_neighbour"] == 1
    assert doc["the_rest"] == 7
    assert sum(doc["cross"].values()) == 7


def test_asking_nothing_leaves_the_whole_population_in_the_rest():
    reader, writer, _ = _scene()
    doc = _measure(reader, writer, [], published=_published(reader, writer, []))
    assert doc["the_rest"] == 8
    assert doc["cross"][step.CELL_HARM_REACHABLE] == 2


# --- 3. ТРЕТИЙ ИСХОД СТЫКА: узел без пары не пропадает --------------------

def test_a_node_only_in_the_reader_census_is_a_third_outcome_not_a_zero():
    reader, writer, asked = _scene()
    reader.append(_rd(9, census.READER_SPLITS_DECLARED))
    doc = _measure(reader, writer, asked)
    assert doc["cross"][step.CELL_UNJOINED] == 1
    assert doc["cross"][step.CELL_HARM_REACHABLE] == 1, (
        "узел без вердикта писателя зачтён вредом — стык выдумал пару")
    assert doc["do_not_sum"]["the_join_itself_failed"] == 1


def test_a_node_only_in_the_writer_census_is_a_third_outcome_too():
    reader, writer, asked = _scene()
    writer.append(_wr(9, census.WRITER_SILENT))
    doc = _measure(reader, writer, asked)
    assert doc["cross"][step.CELL_UNJOINED] == 1


def test_the_join_goes_by_node_not_by_counter_name():
    """«Имя не есть адрес» (ADR-465): две строки одного имени — два узла."""
    reader = [_rd(1, census.READER_SPLITS_DECLARED),
              _rd(2, census.READER_WHOLESALE_ONLY)]
    writer = [_wr(1, census.WRITER_LOUD), _wr(2, census.WRITER_SILENT)]
    doc = _measure(reader, writer, [], published=_published(reader, writer, []))
    assert doc["cross"][step.CELL_HARM_UNREACHABLE] == 1
    assert doc["cross"][step.CELL_HARM_REACHABLE] == 0, (
        "стык пошёл по имени счётчика и слил два разных узла")


def test_the_same_counter_name_in_two_files_stays_two_nodes():
    reader = [_rd(1, census.READER_SPLITS_DECLARED, file="a.py"),
              _rd(1, census.READER_SPLITS_DECLARED, file="b.py")]
    writer = [_wr(1, census.WRITER_SILENT, file="a.py"),
              _wr(1, census.WRITER_LOUD, file="b.py")]
    doc = _measure(reader, writer, [], published=_published(reader, writer, []))
    assert doc["cross"][step.CELL_HARM_REACHABLE] == 1
    assert doc["cross"][step.CELL_HARM_UNREACHABLE] == 1


# --- 4. «НЕ СКЛАДЫВАТЬ»: запрет заказа держится арифметикой ---------------

def test_the_three_ignorances_are_published_separately():
    doc = _measure()
    dns = doc["do_not_sum"]
    assert dns["reader_axis_unmeasured"] == 3
    assert dns["writer_axis_unmeasured"] == 2
    assert dns["both_axes_unmeasured"] == 1
    assert dns["the_join_itself_failed"] == 0
    assert "складывать" in dns["rule"]


def test_no_published_field_equals_the_forbidden_sum():
    """Сумма двух незнаний не должна стоять в документе НИ ОДНИМ числом."""
    doc = _measure()
    dns = doc["do_not_sum"]
    forbidden = dns["reader_axis_unmeasured"] + dns["writer_axis_unmeasured"]
    assert forbidden == 5
    assert all(v != forbidden for k, v in dns.items() if isinstance(v, int))
    assert all(v != forbidden for v in doc["cross"].values())


def test_both_axes_unmeasured_may_not_exceed_either_margin():
    """Клетка больше краевого незнания = стык выдумал пару. Отказ, не вердикт."""
    reader, writer, asked = _scene()
    # у узла 7 читатель измерен, а писателя объявим неизмеренным: клетка
    # «оба» не вправе вырасти от этого
    broken = [dict(r) for r in reader]
    for r in broken:
        if r["line"] in (4, 5, 7):
            r["verdict"] = census.READER_UNRESOLVED
    doc = _measure(broken, writer, asked)
    assert doc["cross"][step.CELL_BOTH_UNMEASURED] <= min(
        doc["do_not_sum"]["reader_axis_unmeasured"],
        doc["do_not_sum"]["writer_axis_unmeasured"])


# --- 5. ПРЕДПОСЫЛКА ЗАКАЗА мерится, а не принимается на слово -------------

def test_the_premise_of_the_order_is_refuted_when_a_reader_is_measured():
    doc = _measure()
    premise = doc["premise_of_the_order"]
    assert premise["verdict"] == "ОПРОВЕРГНУТА"
    assert premise["reader_measured_among_the_rest"] == 4
    assert premise["reader_unmeasured_among_the_rest"] == 3


def test_the_premise_is_confirmed_when_no_reader_is_measured():
    """Обратная сторона: правило обязано уметь и ПОДТВЕРДИТЬ предпосылку."""
    reader = [_rd(i, census.READER_UNRESOLVED) for i in (1, 2, 3)]
    writer = [_wr(1, census.WRITER_SILENT), _wr(2, census.WRITER_LOUD),
              _wr(3, census.WRITER_UNRESOLVED)]
    doc = _measure(reader, writer, [], published=_published(reader, writer, []))
    assert doc["premise_of_the_order"]["verdict"] == "ПОДТВЕРЖДЕНА"
    assert doc["premise_of_the_order"]["reader_measured_among_the_rest"] == 0


def test_the_reader_verdicts_of_the_asked_nodes_are_named():
    """Раскладка состыкованных узлов по читателю — поимённая.

    С цикла #776 раскладка СТРОГАЯ (`_tally`), поэтому каждый объявленный
    класс стои́т в ней своим нулём: «нуль измерен» и «класса в ответе нет»
    перестают быть одной записью (инв. #17). Предмет теста не изменился —
    проверяется, что вердикт состыкованного узла назван, а не потерян.
    """
    doc = _measure()
    named = doc["premise_of_the_order"]["asked_nodes_by_reader_verdict"]
    assert named[census.READER_SPLITS_DECLARED] == 1
    assert set(named) == set(step.READER_CLASSES) | {step.READER_ABSENT}
    assert sum(named.values()) == doc["asked_by_the_neighbour"] == 1


# --- 6. ПАРИТЕТ: расхождение с соседом = отказ ЦЕЛИКОМ --------------------

@pytest.mark.parametrize("field", ["reader_population", "writer_population",
                                   "asked_population"])
def test_a_population_that_disagrees_with_the_neighbour_refuses(field):
    reader, writer, asked = _scene()
    pub = _published(reader, writer, asked)
    pub[field] = pub[field] + 1
    with pytest.raises(step.NotMeasured) as exc:
        _measure(reader, writer, asked, published=pub)
    assert "разные вопросы" in str(exc.value)


def test_a_missing_population_field_is_not_zero():
    reader, writer, asked = _scene()
    pub = _published(reader, writer, asked)
    del pub["writer_population"]
    with pytest.raises(step.NotMeasured) as exc:
        _measure(reader, writer, asked, published=pub)
    assert "не назвал населения" in str(exc.value)


def test_a_margin_that_disagrees_refuses_even_when_the_population_matches():
    """Единственная проверка, ловящая потерю узла: население не меняется."""
    reader, writer, asked = _scene()
    pub = _published(reader, writer, asked)
    pub["reader_margin"][census.READER_SPLITS_DECLARED] += 1
    pub["reader_margin"][census.READER_WHOLESALE_ONLY] -= 1
    with pytest.raises(step.NotMeasured) as exc:
        _measure(reader, writer, asked, published=pub)
    assert "состав нет" in str(exc.value)


@pytest.mark.parametrize("field", ["reader_margin", "writer_margin"])
def test_a_missing_margin_refuses(field):
    reader, writer, asked = _scene()
    pub = _published(reader, writer, asked)
    del pub[field]
    with pytest.raises(step.NotMeasured) as exc:
        _measure(reader, writer, asked, published=pub)
    assert "раскладки" in str(exc.value)


# --- 7. ЧТЕНИЕ СОСЕДСКОГО АРТЕФАКТА: каждый отказ со своей причиной -------

def _neighbour_doc(tmp_path, steps):
    data = tmp_path / "data"
    data.mkdir(parents=True, exist_ok=True)
    (data / "rule_second_copy_census.json").write_text(
        json.dumps({"generated_at": NOW.isoformat(), **steps}),
        encoding="utf-8")


def test_an_absent_neighbour_artifact_is_a_named_third_outcome(tmp_path):
    got, why = step._published(tmp_path)
    assert got is None and "FileNotFoundError" in why


def test_an_absent_neighbour_step_is_not_zero(tmp_path):
    _neighbour_doc(tmp_path, {})
    got, why = step._published(tmp_path)
    assert got is None and "это НЕ ноль" in why


def test_an_unmeasured_neighbour_step_is_not_an_absence_of_harm(tmp_path):
    _neighbour_doc(tmp_path, {step.STEP_READER: {"status": "UNMEASURED"}})
    got, why = step._published(tmp_path)
    assert got is None and "это НЕ «вреда нет»" in why


def test_a_neighbour_step_without_a_population_refuses(tmp_path):
    _neighbour_doc(tmp_path, {step.STEP_READER: {"status": "MEASURED"}})
    got, why = step._published(tmp_path)
    assert got is None and "не есть ноль" in why


def test_all_three_neighbour_steps_are_read(tmp_path):
    _neighbour_doc(tmp_path, {
        step.STEP_READER: {"status": "MEASURED", "population": 2,
                           "reader_verdicts": {"x": 2}},
        step.STEP_WRITER: {"status": "MEASURED", "population": 2,
                           "writer_outcomes": {"y": 2}},
        step.STEP_ASKED: {"status": "MEASURED", "population": 1}})
    got, why = step._published(tmp_path)
    assert why is None
    assert got["reader_population"] == 2 and got["asked_population"] == 1
    assert got["reader_margin"] == {"x": 2}


# --- 8. ВОЗРАСТ соседского замера — поле, а не сноска ---------------------

def test_the_age_of_the_neighbour_measurement_is_a_field():
    reader, writer, asked = _scene()
    pub = _published(reader, writer, asked,
                     stamp=NOW - dt.timedelta(hours=9, minutes=30))
    doc = _measure(reader, writer, asked, published=pub)
    assert doc["neighbour_age_hours"] == pytest.approx(9.5)


def test_a_missing_stamp_makes_the_age_unmeasured_not_zero():
    reader, writer, asked = _scene()
    pub = _published(reader, writer, asked)
    del pub["generated_at"]
    doc = _measure(reader, writer, asked, published=pub)
    assert doc["neighbour_age_hours"] is None
    assert "НЕ ИЗМЕРЕН" in "\n".join(step.report(doc))


def test_an_unparsable_stamp_is_unmeasured_too():
    assert step._age_hours("не дата", NOW) is None


# --- 9. ПОЛОЖИТЕЛЬНЫЙ КОНТРОЛЬ — и контроль НА КОНТРОЛЬ ------------------

def test_the_declared_join_rule_passes_its_own_control():
    assert step._join_control()["passed"], step._join_control()["reason"]


def test_the_control_is_published_with_the_verdict():
    doc = _measure()
    assert doc["control"]["passed"] is True
    assert doc["control"]["broken"] == []


@pytest.mark.parametrize("cell_name", [
    "CELL_HARM_REACHABLE", "CELL_DARK", "CELL_BOTH_UNMEASURED",
    "CELL_EXTRA_LINE", "CELL_UNJOINED"])
def test_the_control_goes_red_when_a_cell_name_is_broken(monkeypatch,
                                                         cell_name):
    """Контроль НА КОНТРОЛЬ: сломав звено, обязан получить КРАСНЫЙ контроль.

    Проверяются КЛАУЗЫ поодиночке, а не сводный `passed`: сводка зеленеет от
    одной верной клаузы, и именно так контроль однажды пропустил поломку
    (урок #690, закреплённый в приёмке ADR-517).
    """
    monkeypatch.setattr(step, cell_name, "СЛОМАНО")
    verdict = step._join_control()
    assert not verdict["passed"], (
        f"звено {cell_name} порвано, а контроль зелен — он ничего не держит")
    assert verdict["broken"], "контроль не НАЗВАЛ порванного звена"
    assert verdict["reason"] and "порванные звенья" in verdict["reason"]


def test_a_failed_control_refuses_the_whole_step(monkeypatch):
    monkeypatch.setattr(step, "_join_control",
                        lambda: {"passed": False, "reason": "сцена порвана",
                                 "checks": {}, "broken": ["x"]})
    with pytest.raises(step.NotMeasured) as exc:
        _measure()
    assert "не прошло контроль" in str(exc.value)


def test_the_control_catches_an_asked_node_leaking_into_the_rest(monkeypatch):
    """Звено «состыкованный исключён» порвано ⇒ контроль красный."""
    real = step._cross

    def leaky(reader_rows, writer_rows, asked):
        return real(reader_rows, writer_rows, set())

    monkeypatch.setattr(step, "_cross", leaky)
    assert not step._join_control()["passed"]


# --- 10. АРИФМЕТИКА СТЫКА: клетки обязаны сойтись с остатком -------------

def test_the_cells_sum_to_the_rest():
    doc = _measure()
    assert sum(doc["cross"].values()) == doc["the_rest"]


def _green_control(monkeypatch):
    """Контроль зелен НАСИЛЬНО — чтобы мерить ИМЕННО арифметику замера.

    Без этого оба теста ниже краснели бы на контроле: он зовёт тот же
    `_cross` и ловит поломку ПЕРВЫМ. Это верное поведение и оно закреплено
    отдельно (`test_the_control_catches_...`); здесь же проверяется ВТОРОЙ,
    независимый сторож — арифметика стыка. Два сторожа на одну поломку есть
    замысел, а не дублирование: контроль мерит ПРАВИЛО, арифметика — ЗАМЕР.
    """
    monkeypatch.setattr(step, "_join_control",
                        lambda: {"passed": True, "checks": {}, "broken": [],
                                 "reason": None})


def test_a_cross_that_loses_a_cell_refuses(monkeypatch):
    _green_control(monkeypatch)
    real = step._cross

    def lossy(reader_rows, writer_rows, asked):
        out = real(reader_rows, writer_rows, asked)
        out["cross"][step.CELL_EXTRA_LINE] = 0        # клетка потеряна
        return out

    monkeypatch.setattr(step, "_cross", lossy)
    with pytest.raises(step.NotMeasured) as exc:
        _measure()
    assert "потеряна или посчитана дважды" in str(exc.value)


def test_a_cross_that_invents_a_pair_refuses(monkeypatch):
    _green_control(monkeypatch)
    real = step._cross

    def inflating(reader_rows, writer_rows, asked):
        out = real(reader_rows, writer_rows, asked)
        out["cross"][step.CELL_BOTH_UNMEASURED] += 4
        out["cross"][step.CELL_EXTRA_LINE] -= 4
        return out

    monkeypatch.setattr(step, "_cross", inflating)
    with pytest.raises(step.NotMeasured) as exc:
        _measure()
    assert "выдумал пару" in str(exc.value)


def test_breaking_the_cross_is_caught_by_the_control_first(monkeypatch):
    """Порядок сторожей: ПРАВИЛО проверяется до ЗАМЕРА, и это не случайность."""
    monkeypatch.setattr(step, "CELL_EXTRA_LINE", "СЛОМАНО")
    with pytest.raises(step.NotMeasured) as exc:
        _measure()
    assert "не прошло контроль" in str(exc.value)


def test_a_cell_name_outside_the_enumeration_is_loud_in_the_measurement():
    """В ЗАМЕРЕ незнакомая клетка обязана быть ГРОМКОЙ, а не тихой строкой.

    Накопитель `cross` строгий намеренно (ADR-469): перехват живёт только в
    контроле. Открой его `.get(cell, 0) + 1` — и прибор завёл бы у себя ровно
    тот открытый счётчик, который мерит.
    """
    rd = [_rd(1, census.READER_SPLITS_DECLARED)]
    wr = [_wr(1, census.WRITER_SILENT)]
    original = step._cell
    try:
        step._cell = lambda a, b: "КЛАСС-ВНЕ-ПЕРЕЧНЯ"
        with pytest.raises(KeyError):
            step._cross(rd, wr, set())
    finally:
        step._cell = original


# --- 11. ТРЕТИЙ ИСХОД НА ЛЮБОЙ ГЛУБИНЕ: run() не отдаёт трассировку -----

def test_run_turns_a_refusal_into_an_unmeasured_document(tmp_path):
    out = step.run(tmp_path, dest=tmp_path / "out.json", write=True, now=NOW)
    assert out["measured"] is False
    doc = json.loads((tmp_path / "out.json").read_text(encoding="utf-8"))
    assert doc["status"] == "UNMEASURED"
    assert doc["applied"] is False
    assert "FileNotFoundError" in doc["reason"]
    assert doc["cross"] == {}


def test_main_returns_two_when_nothing_is_measured(tmp_path, capsys):
    code = step.main(["--root", str(tmp_path), "--out",
                      str(tmp_path / "x.json")])
    assert code == 2
    assert "[НЕ ИЗМЕРЕНО]" in capsys.readouterr().out


def test_the_unmeasured_report_names_the_reason_not_an_empty_line():
    lines = step.report({"status": "UNMEASURED", "order": step.ORDER,
                         "reason": "сосед не прочитан"})
    assert len(lines) == 1 and "сосед не прочитан" in lines[0]


# --- 12. КРУГОВОЙ ХОД по НАСТОЯЩЕМУ дереву -------------------------------

_SUBJECT = '''
VERDICTS = ("ok", "bad")


def measure(rows):
    counts = {}
    for r in rows:
        counts[r["kind"]] = counts.get(r["kind"], 0) + 1
    return {"ok": counts.get("ok", 0), "total": sum(counts.values())}
'''


def test_a_real_walk_of_a_disposable_tree_agrees_with_the_neighbour(tmp_path):
    """Обход, паритет и стык — на НАСТОЯЩЕМ дереве, одноразовом.

    Числа населения берутся у СОСЕДСКИХ шагов, прогнанных на том же дереве:
    выдуманное «ожидаемое» число проверяло бы мою арифметику, а не стык.
    """
    for sub in census.OPEN_COUNTER_DIRS:
        (tmp_path / sub).mkdir(parents=True, exist_ok=True)
    (tmp_path / "spa_core" / "monitoring" / "subject.py").write_text(
        _SUBJECT, encoding="utf-8")

    reader, writer, asked, unreadable, _ = step._walk(tmp_path)
    assert not unreadable, unreadable
    assert reader, "сцена без открытых счётчиков ничего не проверяет"

    _neighbour_doc(tmp_path, {
        step.STEP_READER: {
            "status": "MEASURED", "population": len(reader),
            "reader_verdicts": {r["verdict"]: sum(
                1 for x in reader if x["verdict"] == r["verdict"])
                for r in reader}},
        step.STEP_WRITER: {
            "status": "MEASURED", "population": len(writer),
            "writer_outcomes": {w["writer"]: sum(
                1 for x in writer if x["writer"] == w["writer"])
                for w in writer}},
        step.STEP_ASKED: {"status": "MEASURED", "population": len(asked)}})

    out = step.run(tmp_path, dest=tmp_path / "out.json", now=NOW)
    assert out["measured"] is True, out["doc"].get("reason")
    doc = out["doc"]
    assert doc["population"] == len(reader)
    assert doc["the_rest"] == len(reader) - len(asked)
    assert sum(doc["cross"].values()) == doc["the_rest"]
    assert doc["applied"] is False


def test_the_walk_refuses_an_unreadable_file_instead_of_shrinking(tmp_path):
    for sub in census.OPEN_COUNTER_DIRS:
        (tmp_path / sub).mkdir(parents=True, exist_ok=True)
    (tmp_path / "spa_core" / "monitoring" / "broken.py").write_text(
        "def f(:\n", encoding="utf-8")
    _, _, _, unreadable, _ = step._walk(tmp_path)
    assert unreadable and "SyntaxError" in unreadable[0]["reason"]
    with pytest.raises(step.NotMeasured) as exc:
        step.measure(tmp_path, now=NOW,
                     published=_published([], [], []))
    assert "неполное население не есть измеренное" in str(exc.value)


def test_an_absent_population_directory_is_named_not_skipped(tmp_path):
    _, _, _, unreadable, _ = step._walk(tmp_path)
    assert {u["file"] for u in unreadable} == set(census.OPEN_COUNTER_DIRS)


# --- 13. ADVISORY и гигиена --------------------------------------------

def test_the_step_writes_nothing_but_its_own_artifact(tmp_path):
    for sub in census.OPEN_COUNTER_DIRS:
        (tmp_path / sub).mkdir(parents=True, exist_ok=True)
    subject = tmp_path / "spa_core" / "monitoring" / "subject.py"
    subject.write_text(_SUBJECT, encoding="utf-8")
    before = subject.read_bytes()
    step.run(tmp_path, dest=tmp_path / "out.json", now=NOW)
    assert subject.read_bytes() == before, "прибор написал в измеряемый файл"


def test_applied_is_false_in_every_outcome(tmp_path):
    assert _measure()["applied"] is False
    assert step.run(tmp_path, dest=tmp_path / "o.json",
                    now=NOW)["doc"]["applied"] is False


def test_the_module_declares_no_rule_of_its_own_about_counters():
    """Ни одного своего правила: вердикты обеих осей приходят соседскими.

    Проверяется ФОРМОЙ, а не подстрокой: имена вердиктов, по которым шаг
    судит, обязаны быть атрибутами соседа, а не литералами этого файла.
    """
    src = Path(step.__file__).read_text(encoding="utf-8")
    tree = ast.parse(src)
    literals = {n.value for n in ast.walk(tree)
                if isinstance(n, ast.Constant) and isinstance(n.value, str)}
    for name in (census.READER_SPLITS_DECLARED, census.READER_UNRESOLVED,
                 census.READER_WHOLESALE_ONLY, census.WRITER_SILENT,
                 census.WRITER_LOUD, census.WRITER_UNRESOLVED):
        assert name not in literals, (
            f"вердикт соседа `{name}` перепечатан литералом — это вторая "
            f"копия правила, ровно тот предмет, который ряд и ищет")


def test_the_report_names_what_the_step_does_not_report():
    doc = _measure()
    assert len(doc["blind"]) >= 5
    text = "\n".join(step.report(doc))
    assert "НЕ ДОКЛАДЫВАЕТ" in text and "ADVISORY" in text


def test_the_short_report_keeps_the_headline_and_the_refusal():
    doc = _measure()
    short = step.format_report(doc)
    assert any("❗ОТВЕТ" in line for line in short)
    assert step.format_report({"status": "UNMEASURED", "order": step.ORDER,
                               "reason": "x"})[0].startswith("[НЕ ИЗМЕРЕНО]")


# --- 14. СТРОГАЯ РАСКЛАДКА и САМ ПРИБОР в своём населении ------------------
# Раздел дописан циклом #776, доставившим работу: первый живой прогон на
# дереве С ПРИБОРОМ дал головное число 36 против 33 на дереве без него, и
# разница ровно в трёх СВОИХ накопителях открытой формы. То есть прибор мерил
# предмет, который сам же и заводил, а головное число молча зависело от того,
# доставлен он или нет.

def test_an_unknown_reader_class_is_a_named_third_outcome_not_a_zero():
    """Класс вне объявленного перечня — отказ с ИМЕНЕМ, а не тихая строка."""
    reader, writer, asked = _scene()
    reader[0] = _rd(1, "a_brand_new_reader_verdict_the_neighbour_invented")
    with pytest.raises(step.NotMeasured) as exc:
        _measure(reader, writer, asked)
    assert step.UNMEASURED_CLASS in str(exc.value)
    assert "a_brand_new_reader_verdict_the_neighbour_invented" in str(exc.value)


def test_an_unknown_writer_class_refuses_on_its_own_axis():
    reader, writer, asked = _scene()
    writer[0] = _wr(1, "a_brand_new_writer_outcome")
    with pytest.raises(step.NotMeasured) as exc:
        _measure(reader, writer, asked)
    assert step.UNMEASURED_CLASS in str(exc.value)
    assert "писателя" in str(exc.value)


def test_a_renamed_class_may_not_become_a_quiet_zero():
    """Авария, ради которой раскладка строгая.

    Переименуй сосед `READER_UNRESOLVED` — и ОТКРЫТАЯ раскладка отдала бы
    «читатель не измерен у 0», а `premise_of_the_order` объявил бы предпосылку
    заказа опровергнутой по ложному счёту. Контроль: сцена целиком на новом
    имени обязана дать ОТКАЗ, а не ноль.
    """
    renamed = "reader_of_the_counter_not_measured_v2"
    reader = [_rd(i, renamed) for i in (1, 2, 3)]
    writer = [_wr(i, census.WRITER_SILENT) for i in (1, 2, 3)]
    # открытая форма дала бы именно ноль — и это не теория:
    assert {}.get(census.READER_UNRESOLVED, 0) == 0
    with pytest.raises(step.NotMeasured) as exc:
        _measure(reader, writer, [])
    assert step.UNMEASURED_CLASS in str(exc.value)


def test_the_tally_is_strict_in_both_directions():
    """Объявленный класс считается, незнакомый — громко отказывает."""
    assert step._tally([census.WRITER_SILENT, census.WRITER_SILENT],
                       step.WRITER_CLASSES, axis="x") == {
        census.WRITER_SILENT: 2, census.WRITER_LOUD: 0,
        census.WRITER_UNRESOLVED: 0}
    with pytest.raises(step.NotMeasured):
        step._tally(["нет такого класса"], step.WRITER_CLASSES, axis="x")


def test_an_asked_node_absent_from_the_reader_census_has_its_own_name():
    """`None` строкой — не вердикт. У отсутствия узла объявленное имя."""
    reader, writer, _ = _scene()
    asked = [{"file": "z.py", "line": 99, "counter": "c"}]
    published = _published(reader, writer, asked)
    doc = _measure(reader, writer, asked, published=published)
    named = doc["premise_of_the_order"]["asked_nodes_by_reader_verdict"]
    assert named[step.READER_ABSENT] == 1
    assert "None" not in named


def test_the_step_declares_its_own_counters_in_the_population():
    """Свои строки объявлены полем: доставка не меняет ответ молча."""
    reader, writer, asked = _scene()
    reader.append(_rd(10, census.READER_SPLITS_DECLARED, file=step.PRODUCER))
    writer.append(_wr(10, census.WRITER_SILENT, file=step.PRODUCER))
    doc = _measure(reader, writer, asked)
    own = doc["own_counters"]
    assert own["producer"] == step.PRODUCER
    assert own["count"] == 1 and own["in_the_head_cell"] == 1
    assert own["head_cell_without_the_step"] == doc["named_rows_total"] - 1
    assert "САМ ПРИБОР" in "\n".join(step.report(doc))


def test_a_tree_without_the_step_gives_the_same_head_number():
    """Головное число без прибора равно головному, когда своих строк нет."""
    doc = _measure()
    own = doc["own_counters"]
    assert own["count"] == 0
    assert own["head_cell_without_the_step"] == doc["named_rows_total"]


def test_the_step_contains_no_open_accumulator_of_the_form_it_measures():
    """Прибор не смеет нести форму вреда, которую мерит.

    Статический контроль по СВОЕМУ исходнику: ``X[k] = X.get(k, 0) + 1`` —
    ровно та открытая форма, которую ось писателя зовёт `WRITER_SILENT`.
    Первая редакция этого файла несла её в четырёх местах, и три из них
    встали в ГОЛОВНУЮ клетку собственного замера.
    """
    tree = ast.parse(Path(step.__file__).read_text(encoding="utf-8"))
    offenders = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        value = node.value
        if not (isinstance(value, ast.BinOp) and isinstance(value.op, ast.Add)):
            continue
        call = value.left
        if (isinstance(call, ast.Call)
                and isinstance(call.func, ast.Attribute)
                and call.func.attr == "get"
                and len(call.args) == 2):
            offenders.append(node.lineno)
    assert not offenders, (
        f"открытый накопитель остался в строках {offenders} — прибор завёл "
        f"у себя предмет, который мерит у других")
