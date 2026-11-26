"""Контроль ОСИ СБОРНОЙ ПАРЫ у прибора «дерево приёмки §49» (ADR-1119).

Предмет. До этого цикла `blind_everywhere_*` был КОНЦОМ вопроса: прибор печатал
«какая из причин есть свойство дерева, а какая свойство мира, НЕ ДОКЛАДЫВАЕТ» — и
это было честно про ДОГАДКУ, но неверно про возможность ЗАМЕРА. Сводка §49
(`cio_acceptance_rollup.measure`) принимает `measure_tree` и `data_dir`
РАЗДЕЛЬНО; прибор этой двери не звал ни разу. Замер #1264 на двух настоящих
деревьях: из 5 слепых повсюду критериев сборная пара отвечает у ОДНОГО
(`Owner visibility` — критерий приказа владельца, 12 предметов из 12), у трёх
тоже слепа (артефакт протух в проде и отсутствует в зеркале ⇒ свойство МИРА), а у
одного спросить НЕЛЬЗЯ (проба не объявляет входа `data_dir`).

Каждый тест ниже — положительный контроль на КОНКРЕТНЫЙ способ соврать этой осью:

* выдать «пару не спрашивали» за «пара тоже слепа» (fail-OPEN: тише красного, и
  потому дороже — критерий остался бы слепым, будучи ответимым);
* выдать «проба не принимает `data_dir`» за «пара слепа» (тот же fail-OPEN на шаг
  глубже: пара там вырождается в дерево поверхностей и о сборном дереве не
  отвечает вовсе — класс ADR-1107);
* признать ответом пары вердикт, вынесенный БЕЗ дошедшего `data_dir` (такая пара
  равна дереву поверхностей, а оно слепо: два замера СПОРЯТ, и спор ответом не
  является);
* объявить сборную пару ДЕРЕВОМ приёмки (такого дерева нет на диске);
* спросить пары МОЛЧА там, где их больше потолка (ответ о паре, которой не
  спрашивали, хуже отсутствия ответа);
* платить за ось, когда слепых критериев нет вовсе;
* подать сводке ОДНО и то же дерево обоими входами (тогда ось мерила бы уже
  снятый вердикт — зелёная по построению);
* промолчать об оси в отчёте (молчащая ось неотличима от ненашедшей).

Часы — ВХОД (`clock=`), литеральных дат в файле нет ни одной, живого `data/`
тесты не касаются, сети не касаются, настоящих проб не поднимают.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from spa_core.monitoring import acceptance_tree_capability as atc  # noqa: E402
from spa_core.monitoring.card_acceptance import UNMEASURED  # noqa: E402

ANSWERED = atc.SATISFIED
ANSWERED_NO = atc.NOT_SATISFIED
BLIND = UNMEASURED


# --------------------------------------------------------------------------- сцена


def row(criterion: str, verdict: str, detail: str = "", *,
        declared=("repo_root", "data_dir"), reached=("repo_root", "data_dir"),
        probe: str | None = "p") -> dict:
    """Строка сводки §49 с ОСЬЮ ДОСТИЖИМОСТИ входов.

    `tree_inputs_declared` / `tree_inputs_reached` воспроизводятся дословно: на них
    держится различие «пара собрана» ↔ «пара выродилась в дерево поверхностей», и
    без них ось не смогла бы отличить одно от другого даже в принципе.
    """
    return {"criterion": criterion, "probe": probe, "verdict": verdict,
            "detail": detail, "tree_inputs_declared": list(declared),
            "tree_inputs_reached": list(reached)}


class PairRollup:
    """Сводка §49, подменённая целиком, с ответом НА КАЖДУЮ пару входов.

    Ключ ответа — `(measure_tree, data_dir)`, а не одно дерево: предмет оси именно
    в том, что эти два входа МОГУТ прийти из разных деревьев. Фикция, знающая лишь
    одно дерево, вернула бы один и тот же ответ на обе половины и сделала бы
    проверку проводки зелёной по построению (урок ADR-505).
    """

    Unmeasured = atc.Unmeasured

    def __init__(self, answers: dict, *, refuse: set | None = None):
        self.answers = answers
        self.refuse = refuse or set()
        self.calls: list[dict] = []

    def measure(self, repo_root, **kw):
        # `data_dir` НЕ переданным означает «из дерева замера» — так ведёт себя и
        # настоящая сводка (`data_dir or os.path.join(measure_tree, "data")`).
        # Фикция, не повторившая это, объявила бы одиночный замер дерева парой с
        # неизвестным каталогом и ответила бы об обоих одинаково.
        tree = kw.get("measure_tree") or repo_root
        data_dir = kw.get("data_dir") or os.path.join(tree, "data")
        key = (tree, data_dir)
        self.calls.append({"repo_root": repo_root, **kw, "data_dir": data_dir})
        if key in self.refuse:
            raise atc.Unmeasured(f"сводка отказала о паре {key}")
        try:
            rows = self.answers[key]
        except KeyError:  # pragma: no cover — сцена обязана объявить каждую пару
            raise AssertionError(f"сцена не объявила пару {key}; есть: "
                                 f"{sorted(self.answers)}")
        if isinstance(rows, Exception):
            raise rows
        return {"population": len(rows), "rows": rows}


@pytest.fixture()
def trees(tmp_path):
    a, b = tmp_path / "alpha", tmp_path / "beta"
    a.mkdir()
    b.mkdir()
    return str(a), str(b)


def _data(tree: str) -> str:
    return os.path.join(tree, "data")


def solo(tree: str) -> tuple:
    """Ключ ОДИНОЧНОГО замера дерева: оба входа из него же."""
    return (tree, _data(tree))


def cross(surfaces: str, data_tree: str) -> tuple:
    """Ключ СБОРНОЙ пары: поверхности из одного дерева, артефакты из другого."""
    return (surfaces, _data(data_tree))


class Ticks:
    """Часы оси — ВХОД. Без инъекции цена оси пришла бы от стенных часов, и
    закрепить её числом было бы нельзя ни на одной машине."""

    def __init__(self, *values):
        self.values = list(values)

    def __call__(self):
        return self.values.pop(0) if self.values else 0.0


def measure(trees_, answers, *, refuse=None, **kw):
    fake = PairRollup(answers, refuse=refuse)
    doc = atc.measure(trees_[0], trees=list(trees_), rollup=fake,
                      clock=Ticks(10.0, 10.5), **kw)
    return doc, fake


def axis_of(doc, criterion: str) -> dict:
    return next(r["pairing"] for r in doc["rows"] if r["criterion"] == criterion)


def verdict_of(doc, criterion: str) -> str:
    return next(r["verdict"] for r in doc["rows"] if r["criterion"] == criterion)


def detail_of(doc, criterion: str) -> str:
    return next(r["detail"] for r in doc["rows"] if r["criterion"] == criterion)


# ---------------------------------------------- пара ОТВЕЧАЕТ: предмет ADR-1119


def test_a_pairing_that_ANSWERS_turns_blind_everywhere_into_an_answerable_criterion(trees):
    """Это дословно `Owner visibility` замера #1264: прод слеп (нет поверхности),
    зеркало слепо (нет живого `data/`), а пара «поверхности зеркала × артефакты
    прода» отвечает 12 из 12. Прежний прибор печатал тут «НЕ ДОКЛАДЫВАЕТ»."""
    a, b = trees
    doc, _ = measure(trees, {
        solo(a): [row("Owner visibility", BLIND, "поверхности в дереве нет")],
        solo(b): [row("Owner visibility", BLIND, "журнал решений пуст")],
        cross(a, b): [row("Owner visibility", BLIND, "и так, и так слепо")],
        cross(b, a): [row("Owner visibility", ANSWERED, "доходит полем 12 из 12")],
    })
    assert verdict_of(doc, "Owner visibility") == atc.ANSWERABLE_BY_PAIRING
    axis = axis_of(doc, "Owner visibility")
    assert axis["status"] == atc.PAIRING_ANSWERED, axis
    assert axis["answered_by"] == [{"surfaces": b, "data_dir": _data(a),
                                    "probe_verdict": ANSWERED,
                                    "detail": "доходит полем 12 из 12"}], axis


def test_the_answering_pairing_is_NAMED_and_is_NOT_called_a_tree(trees):
    """Дерева с таким составом НЕ СУЩЕСТВУЕТ. Назвать пару деревом приёмки значило
    бы объявить местом приёмки то, чего нет на диске."""
    a, b = trees
    doc, _ = measure(trees, {
        solo(a): [row("A", BLIND, "x")], solo(b): [row("A", BLIND, "y")],
        cross(a, b): [row("A", ANSWERED_NO, "не выполнен, но ИЗМЕРЕН")],
        cross(b, a): [row("A", BLIND, "z")]})
    text = detail_of(doc, "A")
    assert a in text and _data(b) in text, text
    assert "НЕ СУЩЕСТВУЕТ" in text, text
    assert doc["acceptance_tree"] in (None, a, b)
    assert atc.ANSWERABLE_BY_PAIRING not in (doc.get("acceptance_tree") or "")
    # «Не выполнен» — такой же ОТВЕТ, как «выполнен»: предмет оси в том, есть ли
    # вердикт вообще, а не каков он.
    assert verdict_of(doc, "A") == atc.ANSWERABLE_BY_PAIRING


def test_the_blind_detail_SURVIVES_the_promotion(trees):
    """Вердикт о ДЕРЕВЬЯХ верен и несёт причины по каждому дереву. Затереть его
    ответом пары значило бы потерять замер, который никто не опроверг."""
    a, b = trees
    doc, _ = measure(trees, {
        solo(a): [row("A", BLIND, "газ наблюдён слишком давно")],
        solo(b): [row("A", BLIND, "вердикта нет в каталоге")],
        cross(a, b): [row("A", ANSWERED, "ок")],
        cross(b, a): [row("A", BLIND, "нет")]})
    got = next(r for r in doc["rows"] if r["criterion"] == "A")
    assert "газ наблюдён слишком давно" in got["blind_detail"]
    assert "вердикта нет в каталоге" in got["blind_detail"]
    assert "газ наблюдён слишком давно" in got["detail"]


def test_an_answerable_criterion_IS_a_finding_and_the_exit_code_says_so(trees):
    """«Критерий ответим, и никто его не собирает» есть находка о МЕСТЕ приёмки —
    ровно то, о чём прибор. Считать её чистым прогоном значило бы спрятать её."""
    a, b = trees
    assert atc.ANSWERABLE_BY_PAIRING in atc.FINDING_VERDICTS
    doc, _ = measure(trees, {
        solo(a): [row("A", BLIND, "x")], solo(b): [row("A", BLIND, "y")],
        cross(a, b): [row("A", ANSWERED, "ок")], cross(b, a): [row("A", BLIND, "z")]})
    assert doc["findings"] == 1, doc["counts"]
    assert doc["counts"][atc.ANSWERABLE_BY_PAIRING] == 1, doc["counts"]


# ------------------------------- пара СПРОШЕНА и слепа: причина — свойство МИРА


def test_a_pairing_asked_and_still_blind_keeps_the_verdict_and_SAYS_it_was_asked(trees):
    """Три критерия замера #1264 (`Determinism`, `Auditability`, `Shadow
    verification`) именно такие: артефакт протух в проде и отсутствует в зеркале —
    сборка не помогает, и это ЗАМЕР, а не прежнее «не докладываем»."""
    a, b = trees
    doc, _ = measure(trees, {
        solo(a): [row("A", BLIND, "артефакт протух")],
        solo(b): [row("A", BLIND, "артефакта нет")],
        cross(a, b): [row("A", BLIND, "артефакта нет")],
        cross(b, a): [row("A", BLIND, "артефакт протух")]})
    assert verdict_of(doc, "A") == atc.BLIND_REASONS_DIFFER
    axis = axis_of(doc, "A")
    assert axis["status"] == atc.PAIRING_BLIND, axis
    assert axis["tried"] == 2, axis
    assert "свойство МИРА" in detail_of(doc, "A")


# -------------------- пару СПРОСИТЬ НЕЛЬЗЯ: это НЕ «пара слепа» (главный fail-OPEN)


def test_a_probe_that_does_not_DECLARE_data_dir_makes_the_pairing_UNMEASURED(trees):
    """Дословно `No regression` замера #1264. Проба принимает только `repo_root`,
    поэтому пара ВЫРОЖДАЕТСЯ в дерево поверхностей — а оно уже признано слепым.
    Назвать это «пара тоже слепа» значило бы выдать отсутствие замера за замер и
    закрыть вопрос, которого не задавали (инв. #17)."""
    a, b = trees
    only_root = {"declared": ("repo_root",), "reached": ("repo_root",)}
    doc, _ = measure(trees, {
        solo(a): [row("A", BLIND, "отчёта нет", **only_root)],
        solo(b): [row("A", BLIND, "запись старше предела", **only_root)],
        cross(a, b): [row("A", BLIND, "отчёта нет", **only_root)],
        cross(b, a): [row("A", BLIND, "запись старше предела", **only_root)]})
    axis = axis_of(doc, "A")
    assert axis["status"] == atc.PAIRING_UNMEASURED, axis
    assert axis["status"] != atc.PAIRING_BLIND
    assert "не объявляет входа `data_dir`" in axis["reason"], axis["reason"]
    assert verdict_of(doc, "A") == atc.BLIND_REASONS_DIFFER
    assert "НЕ ИЗМЕРЕНА" in detail_of(doc, "A")


def test_data_dir_DECLARED_but_NOT_REACHED_is_also_unmeasured_with_its_OWN_reason(trees):
    """Два положения дел и две причины: вход не объявлен ↔ объявлен и не дошёл.
    Слить их в одно слово значило бы потерять адрес починки (ADR-1107)."""
    a, b = trees
    half = {"declared": ("repo_root", "data_dir"), "reached": ("repo_root",)}
    doc, _ = measure(trees, {
        solo(a): [row("A", BLIND, "x")], solo(b): [row("A", BLIND, "y")],
        cross(a, b): [row("A", BLIND, "x", **half)],
        cross(b, a): [row("A", BLIND, "y", **half)]})
    axis = axis_of(doc, "A")
    assert axis["status"] == atc.PAIRING_UNMEASURED, axis
    assert "НЕ ДОШЁЛ" in axis["reason"], axis["reason"]
    assert "не объявляет" not in axis["reason"], axis["reason"]


def test_an_ANSWER_without_data_dir_reaching_is_a_CONTRADICTION_not_an_answer(trees):
    """Пара, ответившая без дошедшего `data_dir`, РАВНА дереву поверхностей — а то
    дерево слепо. Два замера спорят; принять спор за ответ значило бы объявить
    критерий ответимым на основании замера, который сам себе противоречит."""
    a, b = trees
    doc, _ = measure(trees, {
        solo(a): [row("A", BLIND, "x")], solo(b): [row("A", BLIND, "y")],
        cross(a, b): [row("A", ANSWERED, "ок",
                          declared=("repo_root", "data_dir"), reached=("repo_root",))],
        cross(b, a): [row("A", BLIND, "y")]})
    axis = axis_of(doc, "A")
    assert axis["status"] == atc.PAIRING_UNMEASURED, axis
    assert axis["answered_by"] == [], axis
    assert "СПОРЯТ" in axis["reason"], axis["reason"]
    assert verdict_of(doc, "A") != atc.ANSWERABLE_BY_PAIRING


# ------------------------------------- «не спрашивали» отличимо от «не нашли»


def test_a_criterion_that_is_NOT_blind_everywhere_gets_not_asked_NOT_blind(trees):
    """Вопрос о сборном дереве у такого критерия не стои́т. Сказать про него
    `blind` значило бы напечатать находку там, где её не искали."""
    a, b = trees
    doc, fake = measure(trees, {
        solo(a): [row("A", ANSWERED, "ок")], solo(b): [row("A", BLIND, "y")]})
    axis = axis_of(doc, "A")
    assert axis["status"] == atc.PAIRING_NOT_ASKED, axis
    assert axis["status"] != atc.PAIRING_BLIND
    assert "не стои́т" in axis["reason"], axis["reason"]
    assert verdict_of(doc, "A") == atc.TREE_BOUND


def test_no_blind_criteria_means_the_axis_costs_NOTHING(trees):
    """Ось платит отдельным прогоном настоящих проб за каждую пару. Платить за неё
    там, где слепых критериев нет, значило бы удвоить цену замера ни за что."""
    a, b = trees
    doc, fake = measure(trees, {
        solo(a): [row("A", ANSWERED, "ок")], solo(b): [row("A", ANSWERED, "ок")]})
    assert len(fake.calls) == 2, fake.calls
    assert doc["pairing_axis"]["pairings"] == [], doc["pairing_axis"]
    assert "не стои́т" in doc["pairing_axis"]["reason"]
    assert doc["pairing_counts"][atc.PAIRING_NOT_ASKED] == 1, doc["pairing_counts"]


def test_the_axis_switched_OFF_answers_unmeasured_with_a_reason_and_does_NOT_go_silent(trees):
    """Выключенная ось обязана СКАЗАТЬ, что выключена. Молчание сделало бы
    «не спрашивали» неотличимым от «спросили и не нашли» — инвариант #17."""
    a, b = trees
    doc, fake = measure(trees, {
        solo(a): [row("A", BLIND, "x")], solo(b): [row("A", BLIND, "y")]},
        pairings=False)
    axis = axis_of(doc, "A")
    assert axis["status"] == atc.PAIRING_UNMEASURED, axis
    assert "ВЫКЛЮЧЕНА" in axis["reason"], axis["reason"]
    assert len(fake.calls) == 2, fake.calls


# --------------------------------------------- пары УПОРЯДОЧЕНЫ, и это необходимо


def test_the_pairings_are_ORDERED_both_directions_are_asked(trees):
    """«Поверхности из A × артефакты из B» и обратное — РАЗНЫЕ вопросы: в замере
    #1264 отвечала ровно одна сторона из двух. Спросить одну значило бы потерять
    половину населения оси."""
    a, b = trees
    doc, fake = measure(trees, {
        solo(a): [row("A", BLIND, "x")], solo(b): [row("A", BLIND, "y")],
        cross(a, b): [row("A", BLIND, "x")], cross(b, a): [row("A", ANSWERED, "ок")]})
    asked = {(c.get("measure_tree"), c.get("data_dir")) for c in fake.calls}
    assert cross(a, b) in asked and cross(b, a) in asked, asked
    assert doc["pairing_axis"]["pairings_declared"] == 2, doc["pairing_axis"]


def test_the_pairing_call_gets_the_two_inputs_from_DIFFERENT_trees(trees):
    """Проводка оси целиком: подай сводке один и тот же каталог обоими входами — и
    ось мерила бы УЖЕ СНЯТЫЙ вердикт об одном дереве, то есть была бы зелена по
    построению и о сборном дереве не отвечала бы никогда."""
    a, b = trees
    _, fake = measure(trees, {
        solo(a): [row("A", BLIND, "x")], solo(b): [row("A", BLIND, "y")],
        cross(a, b): [row("A", BLIND, "x")], cross(b, a): [row("A", BLIND, "y")]})
    pair_calls = [c for c in fake.calls
                  if os.path.dirname(c["data_dir"]) != c["measure_tree"]]
    assert len(pair_calls) == 2, fake.calls
    for call in pair_calls:
        assert call["measure_tree"] != os.path.dirname(call["data_dir"]), call
        assert call["repo_root"] == call["measure_tree"], call
        assert os.path.basename(call["data_dir"]) == "data", call


# ----------------------------------------------- потолок пар и отказы, по-честному


def test_more_pairings_than_the_CAP_is_unmeasured_not_a_silent_truncation(trees,
                                                                         monkeypatch):
    """Усечь перечень молча значило бы ответить о паре, которой не спрашивали.
    Потолок — объявленное число, и его превышение есть НАЗВАННЫЙ третий исход."""
    a, b = trees
    monkeypatch.setattr(atc, "MAX_PAIRINGS", 1)
    doc, fake = measure(trees, {
        solo(a): [row("A", BLIND, "x")], solo(b): [row("A", BLIND, "y")]})
    axis = axis_of(doc, "A")
    assert axis["status"] == atc.PAIRING_UNMEASURED, axis
    assert "потолке 1" in axis["reason"], axis["reason"]
    assert axis["tried"] == 0, axis
    assert len(fake.calls) == 2, fake.calls  # ни одной пары не спрошено


def test_a_rollup_REFUSAL_on_a_pairing_is_unmeasured_with_the_reason_not_blind(trees):
    """Отказ сводки — исход, а не исключение, и не «пара слепа»: о сборном дереве
    при отказе не сказано ничего."""
    a, b = trees
    doc, _ = measure(trees, {
        solo(a): [row("A", BLIND, "x")], solo(b): [row("A", BLIND, "y")]},
        refuse={cross(a, b), cross(b, a)})
    axis = axis_of(doc, "A")
    assert axis["status"] == atc.PAIRING_UNMEASURED, axis
    assert "отказала" in axis["reason"], axis["reason"]


def test_a_pairing_that_does_not_mention_the_criterion_is_unmeasured_not_blind(trees):
    """Молчание сводки о критерии — расхождение населений, а не ответ о нём."""
    a, b = trees
    doc, _ = measure(trees, {
        solo(a): [row("A", BLIND, "x")], solo(b): [row("A", BLIND, "y")],
        cross(a, b): [row("B", BLIND, "чужой критерий")],
        cross(b, a): [row("B", BLIND, "чужой критерий")]})
    axis = axis_of(doc, "A")
    assert axis["status"] == atc.PAIRING_UNMEASURED, axis
    assert "РАСХОДЯТСЯ" in axis["reason"], axis["reason"]


# ------------------------------------------------------- отчёт обязан это печатать


def test_the_report_prints_EVERY_pairing_state_and_the_measured_COST(trees):
    """Молчащая ось неотличима от оси, не нашедшей ничего. Цена печатается ЧИСЛОМ:
    «дорого» ценой не является."""
    a, b = trees
    doc, _ = measure(trees, {
        solo(a): [row("A", BLIND, "x")], solo(b): [row("A", BLIND, "y")],
        cross(a, b): [row("A", BLIND, "x")], cross(b, a): [row("A", ANSWERED, "ок")]})
    text = "\n".join(atc.report(doc))
    for state in atc.PAIRING_STATES:
        assert state in text, (state, text)
    assert "0.5" in text, text          # часы инъектированы: 10.0 → 10.5
    assert "ось СБОРНОЙ ПАРЫ" in text, text
    assert f"поверхности {b} × артефакты {_data(a)}" in text, text


def test_a_doc_WITHOUT_the_axis_is_named_unmeasured_by_the_reader(trees):
    """Вердикт прежней редакции прибора (оси в документе нет ВОВСЕ) обязан читаться
    как «ось НЕ ИЗМЕРЕНА», а не как «находок у оси нет»."""
    text = "\n".join(atc.report({
        "status": "OK", "population": 1, "counts": {}, "rows": [],
        "trees_measured": ["x", "y"], "acceptance_detail": "—"}))
    assert "ось СБОРНОЙ ПАРЫ: НЕ ИЗМЕРЕНА" in text, text


def test_the_report_no_longer_claims_the_blindness_split_is_unknowable(trees):
    """Прежняя строка «какая из причин есть свойство дерева … НЕ ДОКЛАДЫВАЕТ» была
    верна до ADR-1119 и перестала быть верной после: ось это СПРАШИВАЕТ. Остаток
    границы назван отдельно — ось отвечает о паре ЦЕЛИКОМ."""
    a, b = trees
    doc, _ = measure(trees, {
        solo(a): [row("A", BLIND, "x")], solo(b): [row("A", BLIND, "y")],
        cross(a, b): [row("A", BLIND, "x")], cross(b, a): [row("A", BLIND, "y")]})
    text = "\n".join(atc.report(doc))
    assert "ВКЛАД КАЖДОЙ из разных причин" in text, text
    assert "такого дерева НЕТ" in text, text


# ------------------------------------------------- ось РАЗЛИЧАЕТ, а не зеленит всё


def test_the_axis_DISCRIMINATES_three_outcomes_on_one_population(trees):
    """Ось, отвечающая «ответила бы» всегда, мерой не является. Замер #1264 даёт
    1 ответ, 1 слепую пару и 1 неизмеримую на пяти критериях; здесь та же форма на
    трёх, собранная ОДНИМ прогоном — счётчики обязаны разойтись."""
    a, b = trees
    only_root = {"declared": ("repo_root",), "reached": ("repo_root",)}
    doc, _ = measure(trees, {
        solo(a): [row("ANS", BLIND, "x"), row("WORLD", BLIND, "x"),
                  row("CANT", BLIND, "x", **only_root)],
        solo(b): [row("ANS", BLIND, "y"), row("WORLD", BLIND, "y"),
                  row("CANT", BLIND, "y", **only_root)],
        cross(a, b): [row("ANS", BLIND, "x"), row("WORLD", BLIND, "x"),
                      row("CANT", BLIND, "x", **only_root)],
        cross(b, a): [row("ANS", ANSWERED, "ок"), row("WORLD", BLIND, "y"),
                      row("CANT", BLIND, "y", **only_root)]})
    assert axis_of(doc, "ANS")["status"] == atc.PAIRING_ANSWERED
    assert axis_of(doc, "WORLD")["status"] == atc.PAIRING_BLIND
    assert axis_of(doc, "CANT")["status"] == atc.PAIRING_UNMEASURED
    assert doc["pairing_counts"] == {atc.PAIRING_NOT_ASKED: 0,
                                     atc.PAIRING_ANSWERED: 1,
                                     atc.PAIRING_BLIND: 1,
                                     atc.PAIRING_UNMEASURED: 1}, doc["pairing_counts"]


def test_an_EMPTY_list_of_pairings_is_unmeasured_not_blind():
    """Ноль пар утверждением о парах не является.

    Сцена зовёт сведение НАПРЯМУЮ, и это названный выбор: через `ask_pairings` эта
    ветка НЕДОСТИЖИМА по построению (перечень пар там непуст, а каждая пара кладёт
    запись КАЖДОМУ слепому критерию — значит перечень ответов не бывает пустым).
    Мутация «пустой перечень = слепота» на прогоне через ось поэтому ВЫЖИВАЕТ: её
    убивает не сцена пооси, а контроль САМОГО контракта. Оставить ветку без
    контроля значило бы держать в приборе предохранитель, о котором не известно,
    что он скажет, если сработает.
    """
    got = atc._pairing_verdict("A", [])
    assert got["status"] == atc.PAIRING_UNMEASURED, got
    assert got["status"] != atc.PAIRING_BLIND
    assert got["tried"] == 0, got
    assert "ноль пар" in got["reason"], got["reason"]
