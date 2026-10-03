"""Контроль прибора «дерево приёмки §49» (`spa_core/monitoring/acceptance_tree_capability.py`).

Заказ G93 п. 2 приказа «Portfolio CIO» (ADR-505) утверждал: «дерево, способное
ответить на §49, не существует». Прибор мерит это утверждение, и каждый тест ниже —
положительный контроль на КОНКРЕТНЫЙ способ соврать при таком замере:

* объявить вердикт, имея ОДНО дерево (слепота дерева и отсутствие наблюдения на
  свете дают одно слово — различает их только второе дерево);
* принять отсутствующее дерево за слепое (тогда находка печаталась бы тем громче,
  чем хуже конфигурация прибора);
* сравнить причины отказа ВМЕСТЕ С путём дерева (пути различны по построению ⇒
  «причины разные» достаётся даром — зелёный по построению с обратным знаком);
* посчитать «мерки нет вовсе» находкой о дереве (её цена уже названа G93 п. 1);
* молча выбрать дерево приёмки при равном счёте;
* связать подменяемую мерку умолчанием в сигнатуре (урок ADR-505: контроль,
  думающий, что подменил мерку, мерил бы настоящую).

Фикстуры времени инъектируют часы, живого `data/` не трогают, сети не касаются.

Литеральные даты здесь закреплены С ОБЕИХ СТОРОН: отметку артефакта кладёт `_stamp`,
а часы приходят входом `run(..., now=…)`, — ни одна проверка свежести в этом файле не
спрашивает у стенных часов ничего (`.claude/rules/deployment.md`, приём №1).
"""

# FROZEN-DATE-OK: injected-clock — `acceptance_tree_capability.run` принимает часы
# аргументом `now=`, и тесты такта передают его литералом ВМЕСТЕ с литеральной отметкой
# артефакта (`_stamp`). Обе стороны сравнения закреплены, настоящие часы не опрашиваются
# ни в одном тесте файла, поэтому календарь этот файл уронить не может.

from __future__ import annotations

import datetime as dt
import json
import os
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from spa_core.monitoring import acceptance_tree_capability as atc  # noqa: E402
from spa_core.monitoring.card_acceptance import UNMEASURED  # noqa: E402


# --------------------------------------------------------------------------- сцена


class FakeRollup:
    """Сводка §49, подменённая целиком: настоящая гоняет настоящие пробы минутами.

    Держит ПО ДЕРЕВУ свой ответ, потому что предмет прибора — именно расхождение
    между деревьями. Отказ сводки изображается исключением её собственного типа.
    """

    Unmeasured = atc.Unmeasured

    def __init__(self, by_tree: dict):
        self.by_tree = by_tree
        self.calls: list[tuple] = []

    def measure(self, repo_root, **kw):
        self.calls.append((repo_root, tuple(sorted(kw))))
        answer = self.by_tree[repo_root]
        if isinstance(answer, Exception):
            raise answer
        return {"population": len(answer), "rows": answer}


def row(criterion: str, verdict: str, detail: str = "", probe: str | None = "p",
        priceable: bool | None = None):
    """Строка сводки §49.

    `priceable` воспроизводится дословно, потому что на нём держится РАЗЛИЧИЕ
    двух положений дел, у которых у сводки одна внешняя форма (`probe: None`):
    мерки НЕТ (`priceable: True`) и мерок БОЛЬШЕ ОДНОЙ (поля нет вовсе).
    """
    out = {"criterion": criterion, "probe": probe, "verdict": verdict,
           "detail": detail}
    if probe is None and priceable is None:
        priceable = True
    if priceable is not None:
        out["priceable"] = priceable
    return out


ANSWERED = atc.SATISFIED
ANSWERED_NO = atc.NOT_SATISFIED
BLIND = UNMEASURED


@pytest.fixture()
def two_trees(tmp_path):
    a, b = tmp_path / "alpha", tmp_path / "beta"
    a.mkdir()
    b.mkdir()
    return str(a), str(b)


def measure(trees, by_tree, **kw):
    fake = FakeRollup(by_tree)
    return atc.measure(trees[0], trees=list(trees), rollup=fake, **kw), fake


def _real_measure(root, fake, **kw):
    """Настоящая мерка с подменённой СВОДКОЙ — чтобы круговой ход такта шёл через
    настоящий `measure`, а не через фикцию, у которой отметки могло бы не быть."""
    kw.pop("rollup", None)
    return _MEASURE(root, rollup=fake, **kw)


_MEASURE = atc.measure


def verdict_of(doc, criterion):
    return next(r["verdict"] for r in doc["rows"] if r["criterion"] == criterion)


# ------------------------------------------------- дифференциал требует ДВУХ деревьев


def test_one_tree_is_a_REFUSAL_not_a_verdict(tmp_path):
    """У одного дерева «слепо здесь» неотличимо от «наблюдения нет на свете».

    Это и есть причина, по которой прибор дифференциальный: напечатать вердикт
    из одного дерева значило бы ответить на соседний вопрос.
    """
    only = tmp_path / "only"
    only.mkdir()
    with pytest.raises(atc.Unmeasured) as exc:
        atc.measure(str(only), trees=[str(only)],
                    rollup=FakeRollup({str(only): [row("A", ANSWERED)]}))
    assert "ДВУХ" in str(exc.value), str(exc.value)


def test_the_same_tree_named_twice_is_NOT_a_differential(tmp_path):
    """Дерево согласится с собой ПО ПОСТРОЕНИЮ и покрасило бы всё в
    `tree_independent`. Дубль снимается, и остаётся отказ, а не ложный зелёный."""
    one = tmp_path / "one"
    one.mkdir()
    nested = str(one) + os.sep + ".."  + os.sep + one.name  # то же дерево другим именем
    with pytest.raises(atc.Unmeasured) as exc:
        atc.measure(str(one), trees=[str(one), nested],
                    rollup=FakeRollup({str(one): [row("A", ANSWERED)]}))
    assert "ДВУХ" in str(exc.value), str(exc.value)


def test_an_ABSENT_tree_is_excluded_and_NAMED_not_treated_as_blind(tmp_path):
    """Отсутствующее дерево слепо на ВСЁ. Принять его за слепое значило бы
    объявить `tree_bound` каждый критерий — находка тем громче, чем хуже
    конфигурация прибора."""
    a, b, c = tmp_path / "a", tmp_path / "b", tmp_path / "ghost"
    a.mkdir()
    b.mkdir()
    doc, _ = measure([str(a), str(b), str(c)], {
        str(a): [row("A", ANSWERED)],
        str(b): [row("A", ANSWERED)],
    })
    assert verdict_of(doc, "A") == atc.TREE_INDEPENDENT, doc["rows"]
    assert doc["counts"][atc.TREE_BOUND] == 0, doc["counts"]
    excluded = doc["trees_excluded"]
    assert len(excluded) == 1 and excluded[0]["state"] == atc.TREE_ABSENT
    assert str(c) in excluded[0]["reason"], excluded


def test_absent_trees_leaving_fewer_than_two_is_a_REFUSAL(tmp_path):
    a, ghost = tmp_path / "a", tmp_path / "ghost"
    a.mkdir()
    with pytest.raises(atc.Unmeasured) as exc:
        atc.measure(str(a), trees=[str(a), str(ghost)],
                    rollup=FakeRollup({str(a): [row("A", ANSWERED)]}))
    assert "меньше двух" in str(exc.value) and str(ghost) in str(exc.value)


def test_a_tree_whose_rollup_REFUSES_is_excluded_with_its_own_reason(tmp_path):
    a, b, c = tmp_path / "a", tmp_path / "b", tmp_path / "c"
    for p in (a, b, c):
        p.mkdir()
    doc, _ = measure([str(a), str(b), str(c)], {
        str(a): [row("A", ANSWERED)],
        str(b): [row("A", BLIND, "нет файла")],
        str(c): atc.Unmeasured("карточки приказа в дереве нет"),
    })
    assert [e["tree"] for e in doc["trees_excluded"]] == [str(c)]
    assert "карточки приказа" in doc["trees_excluded"][0]["reason"]
    assert verdict_of(doc, "A") == atc.TREE_BOUND


# --------------------------------------------------------- пять исходов у критерия


def test_both_trees_answering_is_tree_independent_even_when_they_DISAGREE(two_trees):
    """«Выполнен» и «не выполнен» — ОДИН исход вопроса «дерево ответило».

    Слить их с «не измерено» значило бы спросить про исполнение приказа вместо
    места его приёмки.
    """
    a, b = two_trees
    doc, _ = measure([a, b], {a: [row("A", ANSWERED, "да")],
                              b: [row("A", ANSWERED_NO, "нет")]})
    assert verdict_of(doc, "A") == atc.TREE_INDEPENDENT
    assert doc["findings"] == 0, doc


def test_one_answers_and_one_is_blind_is_tree_bound_and_NAMES_both_sides(two_trees):
    a, b = two_trees
    doc, _ = measure([a, b], {a: [row("A", ANSWERED)],
                              b: [row("A", BLIND, "нет живого data/")]})
    got = next(r for r in doc["rows"] if r["criterion"] == "A")
    assert got["verdict"] == atc.TREE_BOUND
    assert got["answered_in"] == [a] and got["blind_in"] == [b]
    assert doc["findings"] == 1


def test_blind_everywhere_with_the_SAME_reason_blames_the_world_not_the_tree(two_trees):
    a, b = two_trees
    doc, _ = measure([a, b], {a: [row("A", BLIND, "ряда ставок нет на свете")],
                              b: [row("A", BLIND, "ряда ставок нет на свете")]})
    got = next(r for r in doc["rows"] if r["criterion"] == "A")
    assert got["verdict"] == atc.BLIND_SAME_REASON
    assert "в МИРЕ" in got["detail"]


def test_reasons_differing_ONLY_BY_THE_TREE_PATH_count_as_the_SAME_reason(two_trees):
    """Главный контроль против зелёного по построению С ОБРАТНЫМ ЗНАКОМ.

    Причина отказа почти всегда несёт абсолютный путь, а пути деревьев различны
    по построению. Сравни их как есть — и `blind_everywhere_reasons_differ`
    достанется даром на КАЖДОМ критерии.
    """
    a, b = two_trees
    doc, _ = measure([a, b], {
        a: [row("A", BLIND, f"нет файла {a}/data/apy_series_daily.json")],
        b: [row("A", BLIND, f"нет файла {b}/data/apy_series_daily.json")]})
    assert verdict_of(doc, "A") == atc.BLIND_SAME_REASON, doc["rows"]


def test_genuinely_different_reasons_are_named_so_and_claim_NOTHING_more(two_trees):
    a, b = two_trees
    doc, _ = measure([a, b], {a: [row("A", BLIND, "газ наблюдён слишком давно")],
                              b: [row("A", BLIND, "вердикта нет в каталоге")]})
    got = next(r for r in doc["rows"] if r["criterion"] == "A")
    assert got["verdict"] == atc.BLIND_REASONS_DIFFER
    # Прибор НЕ имеет права утверждать, что сборное дерево ответило бы: какая из
    # причин есть свойство дерева, он не мерил.
    assert "НЕ ДОКЛАДЫВАЕТ" in got["detail"]
    assert "сборн" not in got["detail"].lower()


def test_no_instrument_anywhere_is_NOT_a_finding_about_the_tree(two_trees):
    """Цену «мерки нет» уже назвал заказ G93 п. 1. Считать её ещё и здесь
    значило бы посчитать одну дыру дважды."""
    a, b = two_trees
    doc, _ = measure([a, b], {a: [row("A", BLIND, "мерки нет", probe=None)],
                              b: [row("A", BLIND, "мерки нет", probe=None)]})
    assert verdict_of(doc, "A") == atc.NO_INSTRUMENT
    assert doc["findings"] == 0, doc
    assert atc.NO_INSTRUMENT not in atc.FINDING_VERDICTS


def test_a_verdict_WITHOUT_a_named_measure_is_NOT_an_answer(two_trees):
    """Утверждение без мерки — претензия, а не ответ. Считать его ответом значило
    бы объявить дерево способным отвечать по критерию, которого никто не мерил.

    Прежняя редакция прибора требовала в этой ветке ещё и `verdict == unmeasured`,
    и строка `satisfied` с безымянной пробой проваливалась в «дерево ответило».
    Это fail-OPEN, и нашла его мутация, а не чтение.
    """
    a, b = two_trees
    claim = row("A", ANSWERED, "мерки нет, а вердикт есть", probe=None)
    doc, _ = measure([a, b], {a: [claim], b: [claim]})
    got = next(r for r in doc["rows"] if r["criterion"] == "A")
    assert got["verdict"] == atc.NO_INSTRUMENT, got
    assert doc["answered_by_tree"] == {a: 0, b: 0}, doc["answered_by_tree"]


def test_MORE_THAN_ONE_measure_is_not_ZERO_measures(two_trees):
    """Сводка отвечает о столкновении объявлений безымянной пробой — ТОЧНО ТАК ЖЕ,
    как о критерии без мерки. Прочесть одно как другое значило бы напечатать
    «мерки нет» о критерии, у которого мерок ДВЕ (инв. #17).

    Различие держит объявленное сводкой поле `priceable`, а не форма строки.
    """
    a, b = two_trees
    collision = row("A", BLIND, "критерий объявлен мерой сразу у 2 проб",
                    probe=None, priceable=False)
    doc, _ = measure([a, b], {a: [collision], b: [collision]})
    got = next(r for r in doc["rows"] if r["criterion"] == "A")
    assert got["verdict"] == atc.VERDICT_UNMEASURED, got
    assert "НЕСКОЛЬКИХ" in got["detail"] and "не ноль" in got["detail"], got
    assert doc["counts"][atc.NO_INSTRUMENT] == 0, doc["counts"]


def test_a_collision_beats_an_answer_from_the_other_tree(two_trees):
    """Пока не решено, какая проба есть мера, вердикт о дереве относится к
    неизвестно чему — и чужой ответ этого не отменяет."""
    a, b = two_trees
    doc, _ = measure([a, b], {
        a: [row("A", BLIND, "столкновение", probe=None, priceable=False)],
        b: [row("A", ANSWERED, "да")]})
    assert verdict_of(doc, "A") == atc.VERDICT_UNMEASURED


def test_a_registry_that_DIVERGED_between_trees_is_unmeasured_not_a_verdict(two_trees):
    """Реестр проб живёт в КОДЕ, один на все деревья. «Здесь мерки нет, а там
    есть» означает, что деревья исполняют разный код, — это находка о доставке,
    и вердикт о критерии из неё не выводится."""
    a, b = two_trees
    doc, _ = measure([a, b], {a: [row("A", BLIND, "мерки нет", probe=None)],
                              b: [row("A", ANSWERED, "да")]})
    got = next(r for r in doc["rows"] if r["criterion"] == "A")
    assert got["verdict"] == atc.VERDICT_UNMEASURED
    assert "РАЗОШЁЛСЯ" in got["detail"]


def test_trees_with_DIFFERENT_s49_populations_are_a_REFUSAL(two_trees):
    """Два разных населения — два разных приказа; свести их способности нельзя."""
    a, b = two_trees
    with pytest.raises(atc.Unmeasured) as exc:
        atc.measure(a, trees=[a, b], rollup=FakeRollup({
            a: [row("A", ANSWERED), row("B", ANSWERED)],
            b: [row("A", ANSWERED)]}))
    assert "РАЗНОЕ население" in str(exc.value)


# ------------------------------------------------------- кто есть дерево приёмки


def test_the_acceptance_tree_is_the_one_that_ANSWERS_MOST_and_it_is_named(two_trees):
    a, b = two_trees
    doc, _ = measure([a, b], {
        a: [row("A", ANSWERED), row("B", ANSWERED), row("C", BLIND, "x")],
        b: [row("A", ANSWERED), row("B", BLIND, "y"), row("C", BLIND, "z")]})
    assert doc["acceptance_tree"] == a
    assert doc["answered_by_tree"] == {a: 2, b: 1}
    assert a in doc["acceptance_detail"]


def test_a_TIE_is_named_as_ambiguity_and_NOT_resolved_silently(two_trees):
    a, b = two_trees
    doc, _ = measure([a, b], {
        a: [row("A", ANSWERED), row("B", BLIND, "x")],
        b: [row("A", BLIND, "y"), row("B", ANSWERED)]})
    assert doc["acceptance_tree"] is None
    assert "НЕ ИЗМЕРЕНО" in doc["acceptance_detail"]
    assert a in doc["acceptance_detail"] and b in doc["acceptance_detail"]


def test_when_NOBODY_answers_the_acceptance_tree_is_absent_with_a_reason(two_trees):
    a, b = two_trees
    doc, _ = measure([a, b], {a: [row("A", BLIND, "x")], b: [row("A", BLIND, "y")]})
    assert doc["acceptance_tree"] is None
    assert "нет вовсе" in doc["acceptance_detail"]


# ------------------------------------------------------- нормализация пути дерева


def test_normalise_replaces_the_LONGEST_path_first(tmp_path):
    """Подставь сначала короткий путь — и вложенное дерево потеряло бы остаток
    имени, превратив РАЗНЫЕ причины в одинаковые. Это fail-OPEN: он гасит находку."""
    outer, inner = "/srv/spa", "/srv/spa/wt"
    got = atc.normalise_reason(f"нет {inner}/data/f.json", [outer, inner])
    assert got == "нет <ДЕРЕВО>/data/f.json", got


def test_normalise_knows_the_realpath_alias_of_a_tree(tmp_path):
    """На Маке одно дерево доступно под двумя именами (`/tmp` ↔ `/private/tmp`).
    Сравнение, знающее лишь объявленное имя, объявило бы причины разными молча."""
    real = tmp_path.resolve()
    link = tmp_path / "link"
    target = tmp_path / "target"
    target.mkdir()
    link.symlink_to(target)
    got = atc.normalise_reason(f"нет {target}/data/f.json", [str(link)])
    assert "<ДЕРЕВО>" in got, (got, real)


def test_normalise_leaves_a_reason_without_any_tree_path_untouched():
    assert atc.normalise_reason("газ наблюдён слишком давно", ["/srv/spa"]) == \
        "газ наблюдён слишком давно"


# ------------------------------------------------------------- подмена мерки


def test_the_rollup_is_resolved_AT_CALL_TIME_not_bound_as_a_default(two_trees):
    """Урок ADR-505: умолчание связывается при ОПРЕДЕЛЕНИИ функции, поэтому
    контроль, думающий, что подменил сводку, мерил бы настоящую — зелёный по
    построению. Здесь проверяется, что подменённая сводка ДОХОДИТ."""
    a, b = two_trees
    fake = FakeRollup({a: [row("A", ANSWERED)], b: [row("A", BLIND, "x")]})
    atc.measure(a, trees=[a, b], rollup=fake)
    assert sorted(c[0] for c in fake.calls) == sorted([a, b]), fake.calls


def test_every_tree_is_given_to_the_rollup_as_BOTH_root_and_measure_tree(two_trees):
    """Прочитать население из одного дерева, а мерить другое значило бы сделать
    проверку расхождения населений недостижимой по построению."""
    a, b = two_trees
    fake = FakeRollup({a: [row("A", ANSWERED)], b: [row("A", BLIND, "x")]})
    atc.measure(a, trees=[a, b], rollup=fake)
    for repo_root, kw in fake.calls:
        assert "measure_tree" in kw, (repo_root, kw)


def test_probe_runner_reaches_the_rollup_when_given(two_trees):
    a, b = two_trees
    fake = FakeRollup({a: [row("A", ANSWERED)], b: [row("A", BLIND, "x")]})
    atc.measure(a, trees=[a, b], rollup=fake, probe_runner=lambda *x, **k: None)
    assert all("probe_runner" in kw for _, kw in fake.calls), fake.calls


# ------------------------------------------------------------- такт и артефакт


def _stamp(path: Path, iso: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('{"generated_at": "%s", "status": "OK"}' % iso, encoding="utf-8")


def test_inside_the_tact_the_stage_does_NOT_measure_and_says_so(tmp_path, monkeypatch):
    """«Не мерили» и «измерено» — РАЗНЫЕ исходы (инв. #17): ноль находок внутри
    такта был бы утверждением о населении, которого никто не смотрел."""
    called = []
    monkeypatch.setattr(atc, "measure",
                        lambda *a, **kw: called.append(1) or {"status": "OK"})
    art = tmp_path / "data" / atc.ARTIFACT
    _stamp(art, "2026-10-03T00:00:00+00:00")
    out = atc.run(tmp_path, dest=art, write=False,
                  now=dt.datetime(2026, 10, 5, tzinfo=dt.timezone.utc))
    assert out["measured"] is False and out.get("reason"), out
    assert called == [], "внутри такта прибор звать не должны"


def test_when_the_tact_is_over_the_stage_measures(tmp_path, monkeypatch):
    monkeypatch.setattr(atc, "measure",
                        lambda *a, **kw: {"status": "OK", "counts": {}, "findings": 0})
    art = tmp_path / "data" / atc.ARTIFACT
    _stamp(art, "2026-09-01T00:00:00+00:00")
    out = atc.run(tmp_path, dest=art, write=False,
                  now=dt.datetime(2026, 10, 5, tzinfo=dt.timezone.utc))
    assert out["measured"] is True and out["doc"]["status"] == "OK", out


def test_an_absent_artifact_means_MEASURE_not_skip(tmp_path, monkeypatch):
    """«Не смогли прочитать, когда мерили» не имеет права означать «мерили
    недавно»."""
    monkeypatch.setattr(atc, "measure",
                        lambda *a, **kw: {"status": "OK", "counts": {}, "findings": 0})
    out = atc.run(tmp_path, dest=tmp_path / "data" / atc.ARTIFACT, write=False)
    assert out["measured"] is True, out


def test_a_refusal_is_written_as_UNMEASURED_not_as_an_empty_clean_report(tmp_path,
                                                                        monkeypatch):
    def _boom(*a, **kw):
        raise atc.Unmeasured("деревьев меньше двух")
    monkeypatch.setattr(atc, "measure", _boom)
    dest = tmp_path / "data" / atc.ARTIFACT
    out = atc.run(tmp_path, dest=dest, if_due=False)
    assert out["doc"]["status"] == "UNMEASURED"
    saved = json.loads(dest.read_text(encoding="utf-8"))
    assert saved["status"] == "UNMEASURED" and "меньше двух" in saved["reason"]
    assert "counts" not in saved, "у отказа не может быть счёта находок"


def test_the_artifact_CARRIES_the_moment_it_was_measured(tmp_path, two_trees):
    """Вердикт есть ЗАМЕР С ДАТОЙ, а не состояние: два прогона 03.10 с разницей в
    час дали разные числа. Число без даты — перепечатка, которая молча перестаёт
    быть правдой."""
    a, b = two_trees
    when = dt.datetime(2026, 10, 3, 6, 23, tzinfo=dt.timezone.utc)
    fake = FakeRollup({a: [row("A", ANSWERED)], b: [row("A", ANSWERED)]})
    doc = atc.measure(a, trees=[a, b], rollup=fake, now=when)
    assert doc["generated_at"] == when.isoformat(), doc.get("generated_at")


def test_the_TACT_actually_HOLDS_on_the_instruments_own_artifact(tmp_path, two_trees,
                                                                 monkeypatch):
    """Положительный контроль на настоящий дефект, найденный сквозным прогоном:
    артефакт не несёл `generated_at`, поэтому `measurement_due` честно отвечал
    «отметка не прочитана — мерим», объявленный такт 7 дн был ПРОЗОЙ, и дорогая
    ступень пошла бы каждый тик моста.

    Проверяется круговым ходом: записали замер → спросили снова внутри такта.
    """
    a, b = two_trees
    fake = FakeRollup({a: [row("A", ANSWERED)], b: [row("A", ANSWERED)]})
    monkeypatch.setattr(atc, "measure",
                        lambda root, **kw: _real_measure(root, fake, **kw))
    # Даты нарочно ДАЛЕКО от сегодняшней, и это часть проверки, а не вкусовщина:
    # совпади они с календарём — и тест пройдёт даже тогда, когда ступень НЕ
    # передала часы замеру (отметка легла бы от стенных часов, а разница с
    # «сегодня» всё равно вышла бы меньше такта). Мутация M38 ровно это и
    # вскрыла: тест был зелен из-за календаря, а не из-за проводки.
    first = atc.run(tmp_path, trees=[a, b], if_due=False,
                    now=dt.datetime(2029, 5, 1, tzinfo=dt.timezone.utc))
    assert first["measured"] is True
    assert first["doc"]["generated_at"].startswith("2029-05-01"), first["doc"]
    again = atc.run(tmp_path, trees=[a, b], if_due=True,
                    now=dt.datetime(2029, 5, 3, tzinfo=dt.timezone.utc))
    assert again["measured"] is False, again
    assert "прошло" in again["reason"], again


def test_a_REFUSAL_also_carries_a_stamp_so_one_refusal_does_not_break_the_tact(
        tmp_path, monkeypatch):
    """Иначе один отказ делал бы такт нечитаемым НАВСЕГДА: «не смогли прочитать,
    когда мерили» означает «мерим»."""
    def _boom(*a, **kw):
        raise atc.Unmeasured("деревьев меньше двух")
    monkeypatch.setattr(atc, "measure", _boom)
    when = dt.datetime(2029, 5, 1, tzinfo=dt.timezone.utc)
    out = atc.run(tmp_path, if_due=False, now=when)
    assert out["doc"]["generated_at"] == when.isoformat(), out["doc"]
    again = atc.run(tmp_path, if_due=True,
                    now=dt.datetime(2029, 5, 3, tzinfo=dt.timezone.utc))
    assert again["measured"] is False, again


def test_write_false_touches_nothing(tmp_path, monkeypatch):
    monkeypatch.setattr(atc, "measure",
                        lambda *a, **kw: {"status": "OK", "counts": {}, "findings": 0})
    dest = tmp_path / "data" / atc.ARTIFACT
    atc.run(tmp_path, dest=dest, write=False, if_due=False)
    assert not dest.exists()


def test_run_puts_its_artifact_under_root_data_by_default(tmp_path, monkeypatch):
    monkeypatch.setattr(atc, "measure",
                        lambda *a, **kw: {"status": "OK", "counts": {}, "findings": 0})
    out = atc.run(tmp_path, if_due=False)
    assert out["artifact"] == str(tmp_path / "data" / atc.ARTIFACT)
    assert (tmp_path / "data" / atc.ARTIFACT).is_file()


# -------------------------------------------------------------- отрисовка и коды


def test_report_of_a_refusal_says_NOTHING_about_the_acceptance_tree():
    lines = atc.report({"status": "UNMEASURED", "reason": "деревьев меньше двух"})
    assert "НЕ ИЗМЕРЕНО" in lines[0] and "деревьев меньше двух" in lines[0]
    assert any("НЕ СКАЗАНО НИЧЕГО" in ln for ln in lines), lines
    assert not any("tree_bound 0" in ln for ln in lines), lines


def test_report_prints_EVERY_verdict_including_the_empty_ones(two_trees):
    a, b = two_trees
    doc, _ = measure([a, b], {a: [row("A", ANSWERED)], b: [row("A", ANSWERED)]})
    text = "\n".join(atc.report(doc))
    for verdict in atc.VERDICTS:
        assert verdict in text, (verdict, text)


def test_the_office_rendering_names_the_subject_and_delegates_to_the_producer():
    lines = atc.format_report({"status": "UNMEASURED", "reason": "дверь молчит"})
    assert lines[0].startswith("—") and "§49" in lines[0]
    assert any("НЕ ИЗМЕРЕНО" in line for line in lines[1:]), lines


@pytest.mark.parametrize("by_tree, expected", [
    ("refuse", 2),
    ("finding", 1),
    ("clean", 0),
])
def test_exit_code_tells_the_three_outcomes_apart(tmp_path, monkeypatch, by_tree,
                                                  expected):
    a, b = tmp_path / "a", tmp_path / "b"
    a.mkdir()
    b.mkdir()
    shapes = {
        "refuse": None,
        "finding": {str(a): [row("A", ANSWERED)], str(b): [row("A", BLIND, "x")]},
        "clean": {str(a): [row("A", ANSWERED)], str(b): [row("A", ANSWERED)]},
    }
    shape = shapes[by_tree]
    if shape is None:
        def _boom(*args, **kw):
            raise atc.Unmeasured("деревьев меньше двух")
        monkeypatch.setattr(atc, "measure", _boom)
    else:
        real = atc.measure
        monkeypatch.setattr(atc, "measure", lambda root, **kw: real(
            root, rollup=FakeRollup(shape), **kw))
    rc = atc.main(["--repo-root", str(a), "--tree", str(a), "--tree", str(b),
                   "--no-write"])
    assert rc == expected, by_tree


# ------------------------------------------------------------------- проводка


def test_the_instrument_is_CALLED_by_the_bridge_stage_not_merely_written():
    """Написать прибор и не позвать его — то же, что не написать."""
    src = (_ROOT / "spa_core" / "monitoring" / "findings_bridge.py").read_text(
        encoding="utf-8")
    assert "acceptance_tree_capability" in src, "ступени моста прибор неизвестен"
    assert f"data/{atc.ARTIFACT}" in src, "артефакт не объявлен ступенью"


def test_the_office_step_renders_the_artifact_by_name():
    src = (_ROOT / "scripts" / "consume_office_reports.py").read_text(
        encoding="utf-8")
    assert atc.ARTIFACT in src, "шаг 0-офис артефакт не читает"
    assert "acceptance_tree_capability" in src, "отрисовка не делегирована прибору"


def test_the_artifact_is_declared_in_the_architecture_manifest():
    doc = json.loads((_ROOT / "architecture" / "manifest.json").read_text(
        encoding="utf-8"))
    blob = json.dumps(doc, ensure_ascii=False)
    assert f"data/{atc.ARTIFACT}" in blob, "артефакта нет в манифесте"
