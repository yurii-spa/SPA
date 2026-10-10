"""Батарея к ``kin_breadth_price`` — цена ШИРИНЫ двери родни (заказ G112 п. 3, ADR-538).

Каждый положительный тест здесь проигрывает ИЗМЕРЕННЫЙ случай 10.10 (цикл #830), а не
выдуманный:

* ``ADR-156-orphan-test-runs-have-no-guard.md`` объявлен потерянным, а предмет закрыт
  как ``ADR-304-orphaned-pytest-runs-get-a-schedule-not-an-executioner.md`` — **в ТОМ ЖЕ
  каталоге**. Ось, которую назвал заказ («дерево целиком»), до него не достаёт ни при
  каком пороге; достают только набор токенов И усечение окончания.
* ``scripts/day30_review.py`` сегодня несёт вердикт ``retired_at_base`` со sha коммита
  ``d45cb4a3c`` — и ровно его расширенная дверь перебила бы подозрением ``absent_kin``,
  потому что у соседа родня спрашивается ДО списания. Это цена, которой заказ не
  предполагал.

**Контроль в обе стороны.** Мало показать, что мера находит; надо показать, что она
ОТКАЗЫВАЕТ, когда предпосылки нет: пустое население — не «цена ноль», непрочитанное
дерево — не «чисто», истинность без строки доказательства — не «ложь».

Время — ВХОД: ``now`` подаётся всем вызовам явно. Живого git здесь нет — дерево базы
подаётся читателем-входом; живого journal нет — население подаётся раскрывателем-входом.
Поэтому файл не привязан ни к календарю, ни к хосту.
"""
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from spa_core.monitoring import duplicate_subject_census as dsc  # noqa: E402
from spa_core.monitoring import kin_breadth_price as kbp  # noqa: E402

# FROZEN-DATE-OK: injected-clock — `now` подаётся в `measure()` аргументом от этого
# литерала, и ни одна ветвь прибора стенных часов не читает (все отметки отчёта
# происходят от него). Смена календаря тест не двигает. Часы на уровне модуля читать
# нельзя (сторож `test_no_import_time_clock_in_tests`), поэтому точка — литерал.
NOW = datetime(2026, 10, 10, 22, 0, 0, tzinfo=timezone.utc)

#: Разборщики имени берутся у СОСЕДА — своя копия мерила бы разницу двух разборов.
NAME_DOORS = dict(tokens=dsc._tokens, shared_prefix=dsc._shared_prefix,
                  numbered=dsc._numbered, need_tokens=dsc._KIN_TOKENS)

ADR156 = "docs/decisions/ADR-156-orphan-test-runs-have-no-guard.md"
ADR304 = ("docs/decisions/"
          "ADR-304-orphaned-pytest-runs-get-a-schedule-not-an-executioner.md")
DAY30 = "scripts/day30_review.py"
DAY30_MODULE = "spa_core/riskwire/day30_review.py"


def _scene_tree():
    """Дерево базы из ИЗМЕРЕННЫХ путей: только то, что участвует в находках."""
    return [
        ADR304,
        "docs/decisions/ADR-174-guard-subject-is-the-live-tree-not-the-tree-it-runs-from.md",
        "docs/decisions/ADR-622-which-tracked-artifacts-have-no-declared-writer.md",
        "docs/decisions/ADR-366-capital-observability-over-history.md",
        DAY30_MODULE,
        "spa_core/tests/test_day30_review_cli_contract.py",
    ]


def _findings():
    return [
        {"coordinate": ADR156, "verdict": "absent_lost"},
        {"coordinate": DAY30, "verdict": "retired_at_base"},
        {"coordinate": "docs/decisions/ADR-365-capital-observability-over-history.md",
         "verdict": "absent_kin"},
    ]


def _measure(tmp_path, *, findings=None, tree=None, neighbour=None):
    doc = neighbour if neighbour is not None else {
        "measured": True,
        "price": {"findings": _findings() if findings is None else findings},
        "base_ref": {"sha": "0" * 40, "measured": True},
    }
    return kbp.measure(tmp_path, tmp_path / "data", now=NOW,
                       census=lambda: doc,
                       tree_reader=lambda _root: _scene_tree() if tree is None else tree)


# ─────────────────────────── ГЛАВНОЕ ЧИСЛО ЗАКАЗА ───────────────────────────

def test_the_named_case_lies_in_the_same_directory_so_the_premise_is_wrong(tmp_path):
    """Посылка заказа — «прячет КАТАЛОГ» — измеренно неверна для названного случая."""
    report = _measure(tmp_path)
    assert report["measured"], report["reason"]
    named = report["named_case"]
    assert named["coordinate"] == ADR156
    assert named["candidate"] == ADR304
    assert named["same_directory"] is True, (
        "ADR-156 и ADR-304 лежат в docs/decisions/ оба — каталог НЕ прячет ничего")
    assert report["verdict"]["premise_of_the_order_holds"] is False


def test_the_axis_the_order_asked_for_does_not_reach_the_named_case(tmp_path):
    """«Дерево целиком» названный случай не достаёт — ни при каком пороге."""
    report = _measure(tmp_path)
    assert report["axes"]["whole_tree"]["reaches_named_case"] is False
    assert report["named_case"]["reached_by_the_asked_axis"] is False


def test_only_token_set_plus_stemming_reaches_the_named_case(tmp_path):
    """Достают ровно те оси, которых заказ не предполагал — и они НАЗВАНЫ."""
    report = _measure(tmp_path)
    reached = set(report["named_case"]["reached_by"])
    assert "token_set+stemmed" in reached
    assert "all_three" in reached
    # Каждая ось ПОРОЗНЬ до него не достаёт: нужны обе сразу.
    assert report["axes"]["token_set"]["reaches_named_case"] is False
    assert report["axes"]["stemmed"]["reaches_named_case"] is False


def test_the_named_case_is_not_a_rename_it_crosses_the_file_kind(tmp_path):
    """.md для .py-соседей — закрытие ПРЕДМЕТА, а не переименование координаты."""
    report = _measure(tmp_path)
    rows = report["axes"]["all_three"]["rows"]
    row = next(r for r in rows if r["coordinate"] == ADR156 and r["candidate"] == ADR304)
    assert row["truth"] == "subject_closed_elsewhere"
    assert "ADR-304" in row["evidence"]
    # Этот конкретный ряд род файла НЕ пересекает (оба .md) — пересечение считается
    # отдельным числом, и выдавать одно за другое нельзя.
    assert row["kind_crossing"] is False
    assert report["axes"]["all_three"]["subject_closed_elsewhere"] == len(
        [r for r in rows if r["truth"] == "subject_closed_elsewhere"]) == 1


# ───────────────── ЦЕНА, КОТОРОЙ ЗАКАЗ НЕ ПРЕДПОЛАГАЛ ─────────────────

def test_the_asked_axis_gains_one_candidate_and_it_preempts_evidence(tmp_path):
    """Ось заказа даёт ОДНОГО кандидата — и он перебивает доказанный вердикт."""
    report = _measure(tmp_path)
    axis = report["axes"]["whole_tree"]
    assert axis["candidates_new_vs_baseline"] == 1, axis["coordinates_gaining"]
    assert axis["coordinates_gaining"] == [DAY30]
    row = next(r for r in axis["rows"] if r["coordinate"] == DAY30)
    assert row["candidate"] == DAY30_MODULE
    assert row["truth"] == "true", "родство доказано ADR-538 ОТВЕТ 1"
    # И ровно поэтому цена отрицательна: сегодня у координаты есть sha коммита,
    # а расширенная дверь подменила бы его подозрением.
    assert row["current_verdict"] == "retired_at_base"
    assert row["would_become"] == "absent_kin"
    assert row["preempts_evidence"] is True
    assert axis["preempted_evidence"] == 1


def test_a_true_relative_still_costs_because_the_kin_door_is_asked_first(tmp_path):
    """Истинность кандидата цену не отменяет: валюта тут ПОРЯДОК, а не ложность."""
    report = _measure(tmp_path)
    axis = report["axes"]["whole_tree"]
    assert axis["verified_true"] == len(
        [r for r in axis["rows"] if r["truth"] == "true"])
    assert axis["verified_true"] == 2 and axis["verified_false"] == 0
    assert axis["preempted_evidence"] == 1, (
        "ось без единого ложного кандидата всё равно платит — это и есть находка")


def test_widening_is_not_applied_by_the_instrument(tmp_path):
    """Прибор ТОЛЬКО ЧИТАЕТ: дверь соседа он не правит (ADR-682)."""
    report = _measure(tmp_path)
    assert report["verdict"]["widening_applied"] is False
    before = dsc.kin_of(ADR156, _scene_tree())
    _measure(tmp_path)
    assert dsc.kin_of(ADR156, _scene_tree()) == before


def test_axes_price_separately_and_the_sum_is_not_a_single_axis(tmp_path):
    """Цена осей ПОРОЗНЬ: сумма комбинации строго больше каждой её части."""
    report = _measure(tmp_path)
    axes = report["axes"]
    assert axes["baseline"]["candidates_new_vs_baseline"] == 0
    assert (axes["all_three"]["candidates"]
            > max(axes["whole_tree"]["candidates"], axes["token_set"]["candidates"],
                  axes["stemmed"]["candidates"]))


def test_unverifiable_candidates_are_the_third_outcome_not_false(tmp_path):
    """Кандидат без строки доказательства — `unmeasured`, и его не считают ложным."""
    tree = _scene_tree() + ["docs/decisions/ADR-999-orphan-test-runs-of-another-subject.md"]
    report = _measure(tmp_path, tree=tree)
    rows = report["axes"]["token_set"]["rows"]
    stranger = [r for r in rows if r["candidate"].startswith("docs/decisions/ADR-999")]
    assert stranger, "сцена обязана нести незнакомца, иначе тест ничего не различает"
    assert all(r["truth"] == "unmeasured" for r in stranger)
    assert report["axes"]["token_set"]["truth_unmeasured"] == len(
        [r for r in rows if r["truth"] == "unmeasured"]), (
        "счёт «истинность не измерена» обязан совпадать с рядами ТОЧНО: под `>=` "
        "мутант, удваивающий счётчик, выживает (замер мутаций #830)")
    # И он НЕ попал в ложные: подстановка «неизвестно = ложно» завысила бы цену.
    assert all(r["truth"] != "false" for r in stranger)


def test_known_false_candidates_are_counted_as_false(tmp_path):
    """Обратная сторона: строка доказательства «не та работа» ЧИТАЕТСЯ как ложь."""
    report = _measure(tmp_path)
    rows = report["axes"]["token_set"]["rows"]
    false_rows = [r for r in rows if r["truth"] == "false"]
    assert {r["candidate"] for r in false_rows} >= {
        "docs/decisions/ADR-174-guard-subject-is-the-live-tree-not-the-tree-it-runs-from.md"}
    assert report["axes"]["token_set"]["verified_false"] == len(false_rows)


# ─────────────── ПРЕТЕНЗИЯ О ПОРЯДКЕ ДВЕРЕЙ — МЕРИТСЯ ИСХОДОМ ───────────────

def _base(paths):
    paths = set(paths)
    return {"measured": True, "reason": None, "ref": "origin/main", "sha": "deadbeef",
            "committed_at": "2026-09-28T00:00:00+00:00", "paths": paths,
            "top_level": {p.split("/")[0] for p in paths}}


def _two_sessions_on(coordinate, *, ts="2026-09-20T10:00:00+00:00"):
    """Две РАЗЛИЧНЫЕ сессии на одном предмете — предпосылка оси A соседа.

    Отметка объявления РАНЬШЕ даты базового ref намеренно: иначе первой
    срабатывает дверь «база старше объявления», и сцена не доходит до
    столкновения родни со списанием вовсе (проверено — находок ноль).
    """
    return [{"ts": ts, "session": f"cycle-{pid}", "session_pid": pid,
             "session_pid_start": "Mon Sep 28 10:00:00 2026",
             "summary": "работа", "card": "inbox-scene",
             "files": [f"/tmp/scene_{pid}/{coordinate}"]}
            for pid in (101, 202)]


def test_kin_door_preempts_the_retirement_door():
    """`KIN_PRECEDES` — претензия о СОСЕДЕ, и она проверяется его ИСХОДОМ.

    Чтение кода соседа подтвердило бы только то, что я его прочёл. Поэтому сцена
    герметична и дифференциальна: ОДНА и та же координата, у которой дверь
    списания отвечает «списана ПОЗЖЕ объявления» (то есть сильный доказанный
    вердикт ДОСТУПЕН), прогоняется через настоящий `measure_price` ДВАЖДЫ —
    с роднёй в дереве базы и без неё. Разность вердиктов и есть порядок дверей.
    """
    coordinate = "pkg/thing_one.py"
    relative = "pkg/thing_one_two.py"
    records = _two_sessions_on(coordinate)

    def retirement(_coordinate):
        return {"measured": True, "sha": "deadbeef12",
                "deleted_at": "2026-09-25T10:00:00+00:00"}

    with_kin = dsc.measure_price(records, _base({relative}), retirement=retirement)
    without_kin = dsc.measure_price(records, _base({"pkg/unrelated_name.py"}),
                                    retirement=retirement)
    got = {f["coordinate"]: f["verdict"] for f in with_kin["findings"]}
    lost = {f["coordinate"]: f["verdict"] for f in without_kin["findings"]}
    assert lost.get(coordinate) == "retired_at_base", (
        f"сцена не обеспечила ДОКАЗАННЫЙ вердикт без родни: {lost}")
    assert got.get(coordinate) == "absent_kin", (
        f"сцена не воспроизвела столкновение дверей: {got}")
    # Претензия модуля подтверждена ИСХОДОМ: родня перебивает списание.
    assert "retired_at_base" in kbp.KIN_PRECEDES
    assert relative in next(f for f in with_kin["findings"]
                            if f["coordinate"] == coordinate)["kin"]


def test_the_scene_of_the_precedence_claim_can_fail(monkeypatch):
    """Обратная сторона: встань родня ПОСЛЕ списания — тот же замер даст другое.

    Контроль самого контроля. Если бы дверь родни у соседа спрашивалась после
    списания, доказанный вердикт выжил бы — и претензия `KIN_PRECEDES` была бы
    ложной. Здесь это проигрывается подменой двери родни на пустую: вердикт
    обязан вернуться к `retired_at_base`.
    """
    coordinate = "pkg/thing_one.py"
    records = _two_sessions_on(coordinate)

    def retirement(_coordinate):
        return {"measured": True, "sha": "deadbeef12",
                "deleted_at": "2026-09-25T10:00:00+00:00"}

    monkeypatch.setattr(dsc, "kin_of", lambda *_a, **_k: [])
    got = dsc.measure_price(records, _base({"pkg/thing_one_two.py"}),
                            retirement=retirement)
    verdicts = {f["coordinate"]: f["verdict"] for f in got["findings"]}
    assert verdicts.get(coordinate) == "retired_at_base"


def test_at_base_is_not_preempted_by_kin(tmp_path):
    """Обратная сторона той же претензии: `at_base` родня НЕ перебивает."""
    assert "at_base" not in kbp.KIN_PRECEDES
    report = _measure(tmp_path, findings=[{"coordinate": DAY30, "verdict": "at_base"}])
    rows = report["axes"]["whole_tree"]["rows"]
    row = next(r for r in rows if r["coordinate"] == DAY30)
    assert row["would_become"] == "at_base"
    assert row["preempts_evidence"] is False


# ────────────────────────── ТРЕТИЙ ИСХОД ПРИБОРА ──────────────────────────

def test_empty_population_is_not_a_zero_price(tmp_path):
    report = _measure(tmp_path, findings=[])
    assert report["measured"] is False
    assert "население пусто" in report["reason"]
    assert report["axes"] is None, "цена на пустом населении не определена, а не ноль"


def test_missing_findings_section_differs_from_an_empty_one(tmp_path):
    report = _measure(tmp_path, neighbour={"measured": True, "price": {}})
    assert report["measured"] is False
    assert "НЕ ИЗМЕРЕНО" in report["reason"]
    # И это ДРУГАЯ причина, чем у пустого списка — склеить их значило бы потерять
    # различие «раздела нет» и «находок нет» (инв. #17).
    other = _measure(tmp_path, findings=[])
    assert report["reason"] != other["reason"]


def test_unmeasured_neighbour_is_carried_with_its_reason(tmp_path):
    report = _measure(tmp_path, neighbour={"measured": False, "reason": "журнал не прочитан"})
    assert report["measured"] is False
    assert "журнал не прочитан" in report["reason"]


def test_unreadable_base_tree_is_not_clean(tmp_path):
    report = _measure(tmp_path, tree=None if False else [])
    assert report["measured"] is False
    assert "пусто" in report["reason"]


def test_tree_reader_returning_none_is_named_not_swallowed(tmp_path):
    report = kbp.measure(
        tmp_path, tmp_path / "data", now=NOW,
        census=lambda: {"measured": True, "price": {"findings": _findings()}},
        tree_reader=lambda _root: None)
    assert report["measured"] is False
    assert "не прочитано" in report["reason"]


def test_a_raising_resolver_does_not_crash_the_instrument(tmp_path):
    def boom():
        raise RuntimeError("сосед упал")
    report = kbp.measure(tmp_path, tmp_path / "data", now=NOW, census=boom,
                         tree_reader=lambda _root: _scene_tree())
    assert report["measured"] is False
    assert "сосед-раскрыватель не ответил" in report["reason"]
    assert "RuntimeError" in report["reason"]


# ──────────────────────────── МЕРА САМА ПО СЕБЕ ────────────────────────────

def test_stem_is_crude_by_declaration_and_spares_short_tokens():
    """Усечение достаёт РОВНО наблюдённое расхождение и не шире."""
    assert kbp.stem("orphaned") == "orphan"   # предмет замера #830
    assert kbp.stem("orphans") == "orphan"
    # Порог длины щадит короткие намеренно: `runs` → `run` склеило бы `run`/`ru`,
    # и прирост кандидатов пришёл бы от МЕРЫ, а не от предмета.
    assert kbp.stem("runs") == "runs"
    assert kbp.stem("test") == "test"
    assert kbp.stem("no") == "no"
    # И при этом названный случай всё равно достаётся: у ADR-156/ADR-304
    # расходится ровно `orphan`/`orphaned`, а `runs` стои́т по обе стороны.
    assert "runs" in dsc._tokens("ADR-156-orphan-test-runs-have-no-guard.md")
    assert "runs" in dsc._tokens(
        "ADR-304-orphaned-pytest-runs-get-a-schedule-not-an-executioner.md")


def test_whole_tree_axis_sees_the_same_leaf_in_another_directory(tmp_path):
    """Главный предмет оси: тот же лист в ДРУГОМ каталоге."""
    found = kbp.kin_at_breadth(DAY30, [DAY30_MODULE], whole_tree=True, **NAME_DOORS)
    assert found == [DAY30_MODULE]
    # А запертая в своём каталоге дверь его отбрасывает по равенству листа.
    assert kbp.kin_at_breadth(DAY30, [DAY30_MODULE], **NAME_DOORS) == []


def test_the_coordinate_is_never_its_own_relative(tmp_path):
    assert kbp.kin_at_breadth(DAY30, [DAY30], whole_tree=True, **NAME_DOORS) == []


def test_baseline_axis_reproduces_the_neighbour_door_exactly(tmp_path):
    """Нуль отсчёта обязан совпадать с дверью соседа — иначе прирост выдуман."""
    tree = _scene_tree() + [
        "docs/decisions/ADR-365-capital-observability-over-history-extra.md"]
    for coordinate in (ADR156, DAY30,
                       "docs/decisions/ADR-365-capital-observability-over-history.md"):
        assert (kbp.kin_at_breadth(coordinate, tree, **NAME_DOORS)
                == dsc.kin_of(coordinate, tree)), coordinate


def test_ground_truth_rows_all_carry_evidence():
    """Строка без доказательства в оракуле жить не вправе."""
    for row in kbp.GROUND_TRUTH:
        assert row["truth"] in ("true", "false", "subject_closed_elsewhere"), row
        assert row["evidence"].strip(), row
        assert row["relation"].strip(), row


def test_render_names_the_third_outcome_and_the_verdict(tmp_path):
    report = _measure(tmp_path)
    text = "\n".join(kbp.render(report))
    assert "НАЗВАННЫЙ ЗАКАЗОМ СЛУЧАЙ" in text
    assert "НЕВЕРНА" in text
    assert "НЕ ДОКЛАДЫВАЕТ" in text
    # Достающие оси обязаны быть названы В СТРОКЕ НАЗВАННОГО СЛУЧАЯ. Проверять их
    # по всему тексту — ловушка подстроки (ADR-333): те же имена печатают строки
    # `[ОСЬ …]`, поэтому мутант `or`→`and`, гасивший перечень до «—», выживал.
    named_line = next(l for l in kbp.render(report) if l.startswith("[НАЗВАННЫЙ"))
    assert "token_set+stemmed" in named_line and "all_three" in named_line, named_line
    assert "—" not in named_line
    assert "дверь НЕ расширена" in text
    unmeasured = "\n".join(kbp.render(_measure(tmp_path, findings=[])))
    assert "НЕ ИЗМЕРЕНО" in unmeasured


def test_exit_code_distinguishes_three_outcomes(tmp_path, monkeypatch):
    calls = {}

    def fake_run(root=None, *, now=None):
        return {"measured": calls["measured"], "doc": calls["doc"]}

    monkeypatch.setattr(kbp, "run", fake_run)
    calls.update(measured=False, doc={"measured": False, "reason": "нет замера"})
    assert kbp.main(["--json"]) == 2
    calls.update(measured=True, doc={"measured": True, "status": "НАХОДКА"})
    assert kbp.main(["--json"]) == 1
    calls.update(measured=True, doc={"measured": True, "status": "ЧИСТО"})
    assert kbp.main(["--json"]) == 0


def test_artifact_is_left_even_for_the_third_outcome(tmp_path):
    data = tmp_path / "data"
    data.mkdir(parents=True)
    report = {"measured": False, "reason": "сцена"}
    kbp.save_artifact(report, data)
    written = json.loads((data / kbp.ARTIFACT).read_text())
    assert written["measured"] is False and written["reason"] == "сцена"


def test_status_is_a_finding_when_the_asked_axis_pays(tmp_path):
    report = _measure(tmp_path)
    assert report["status"] == "НАХОДКА"
    assert report["verdict"]["asked_axis"] == "whole_tree"
    assert report["verdict"]["asked_axis_preempts_evidence"] == 1


def test_population_counts_the_two_currencies_separately(tmp_path):
    report = _measure(tmp_path)
    pop = report["population"]
    assert pop["silenceable"] == 1   # ADR-156 absent_lost
    assert pop["evidenced"] == 1     # day30_review retired_at_base
    assert pop["findings"] == 3
    assert pop["base_paths"] == len(_scene_tree())


@pytest.mark.parametrize("flag", ["whole_tree", "token_set", "stemmed"])
def test_each_axis_flag_changes_the_measure_on_the_real_scene(flag, tmp_path):
    """Положительный контроль проводки флагов: выключенный флаг — другой ответ."""
    report = _measure(tmp_path)
    names = [name for name, flags in kbp.AXES if flags == {flag: True}]
    assert names, flag
    axis = report["axes"][names[0]]
    baseline = report["axes"]["baseline"]
    assert (axis["candidates"], axis["reaches_named_case"]) != (
        baseline["candidates"], baseline["reaches_named_case"]) or flag == "stemmed", (
        f"флаг {flag} не меняет ни одного наблюдения — проводка не измерена")


# ─────────── ЗАКРЫТО ПО СЛЕДАМ МУТАЦИЙ #830 (каждый тест убивает выжившего) ───────────

def test_injected_clock_reaches_the_stamp(tmp_path):
    """`now or _utcnow()` → `and`: отчёт брал бы СТЕННЫЕ часы при поданном `now`.

    Это и есть претензия `FROZEN-DATE-OK: injected-clock` этого файла, и до замера
    мутаций её не проверял ни один ассерт: тесты подавали `now`, но ни один не
    спрашивал, дошёл ли он до отметки.
    """
    report = _measure(tmp_path)
    assert report["generated_at"] == kbp._iso(NOW)


def test_declared_axis_flags_are_pinned_exactly():
    """Флаг КОМБИНАЦИИ был непроверен: мутант гасил ось внутри `all_three` молча."""
    assert dict(kbp.AXES) == {
        "baseline": {},
        "whole_tree": {"whole_tree": True},
        "token_set": {"token_set": True},
        "stemmed": {"stemmed": True},
        "whole_tree+token_set": {"whole_tree": True, "token_set": True},
        "token_set+stemmed": {"token_set": True, "stemmed": True},
        "all_three": {"whole_tree": True, "token_set": True, "stemmed": True},
    }
    # И порядок объявления тоже предмет: `baseline` обязан быть ПЕРВЫМ, иначе
    # «новых кандидатов» считали бы относительно расширенной оси.
    assert kbp.AXES[0][0] == "baseline"
    assert kbp.AXES[1][0] == "whole_tree", "ось заказа — вторая, её имя печатает вердикт"


def test_stem_threshold_is_pinned_at_its_boundary():
    """`len(token) > 4` → `> 5`: порог уехал бы на один знак незаметно."""
    # Пять знаков — усекается (и усечение ГРУБОЕ: «es» снимает два знака, поэтому
    # `runes` → `run`; это объявленное свойство меры, а не опечатка теста).
    assert kbp.stem("runes") == "run"
    assert kbp.stem("lines") == "lin"
    # Четыре знака и короче — не трогаются.
    assert kbp.stem("runs") == "runs"
    assert kbp.stem("need") == "need"


def test_kind_of_reads_the_last_extension_only():
    """`rsplit('.', 1)[1]` → индекс/предел: род файла брался бы не с конца."""
    assert kbp._kind_of("a/b/thing.py") == "py"
    assert kbp._kind_of("a/b/thing.test.py") == "py"
    assert kbp._kind_of("a/b/ADR-1-x.md") == "md"
    assert kbp._kind_of("a/b/Makefile") == ""


def test_kind_crossing_is_counted_when_a_py_is_matched_by_an_md():
    """Положительный контроль числа `kind_crossing` — иначе счёт мог бы врать."""
    coordinate = "spa_core/monitoring/orphan_runs.py"
    report = _measure(
        tmp_path=Path("/tmp"), findings=[{"coordinate": coordinate,
                                          "verdict": "absent_lost"}],
        tree=[ADR304])
    rows = report["axes"]["all_three"]["rows"]
    assert rows and all(r["kind_crossing"] is True for r in rows), rows
    assert report["axes"]["all_three"]["kind_crossing"] == len(rows)


def test_numbered_slug_threshold_is_measured_at_its_margin():
    """`>= min(need, len(slug))` → `>` / `max`: порог слага уехал бы на краю.

    Сцена краевая намеренно: слаг делит РОВНО три токена (порог) и ни одного
    больше. Широкий зазор прежней сцены мутанта не убивал.
    """
    mine = "docs/decisions/ADR-100-alpha-beta-gamma.md"
    exactly_three = "docs/decisions/ADR-200-alpha-beta-gamma.md"
    only_two = "docs/decisions/ADR-200-alpha-beta-delta.md"
    assert kbp.kin_at_breadth(mine, [exactly_three], **NAME_DOORS) == [exactly_three]
    assert kbp.kin_at_breadth(mine, [only_two], **NAME_DOORS) == []
    # Та же краевая раскладка обязана совпасть с дверью СОСЕДА — иначе нуль
    # отсчёта разошёлся бы с ней ровно на краю.
    assert dsc.kin_of(mine, [exactly_three]) == [exactly_three]
    assert dsc.kin_of(mine, [only_two]) == []
    # И ВТОРОЙ край — слаг КОРОЧЕ порога. Ровно он различает `min` и `max`:
    # min(3, 2) = 2 (родня есть), max(3, 2) = 3 (родни нет никогда). Без этого
    # случая мутант `min`→`max` выживал, потому что у трёхтокенного слага оба
    # ответа совпадают (замер мутаций #830).
    short = "docs/decisions/ADR-100-alpha-beta.md"
    short_kin = "docs/decisions/ADR-200-alpha-beta.md"
    assert kbp.kin_at_breadth(short, [short_kin], **NAME_DOORS) == [short_kin]
    assert dsc.kin_of(short, [short_kin]) == [short_kin]


def test_live_git_door_answers_on_a_real_repo(tmp_path):
    """Дверь без читателя-входа НЕ была исполнена ни одним тестом (замер мутаций)."""
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "one.py").write_text("# one\n")
    subprocess.run(["git", "init", "-b", "main", str(tmp_path)], check=True,
                   capture_output=True)
    subprocess.run(["git", "-C", str(tmp_path), "add", "pkg"], check=True,
                   capture_output=True)
    subprocess.run(["git", "-C", str(tmp_path), "-c", "user.email=s@s",
                    "-c", "user.name=s", "commit", "-m", "scene"], check=True,
                   capture_output=True)
    paths, why = kbp._base_paths(tmp_path)
    assert why is None and paths == ["pkg/one.py"]


def test_live_git_door_refuses_outside_a_repo(tmp_path):
    """Обратная сторона: не репозиторий ⇒ НАЗВАННАЯ причина, а не пустое дерево."""
    paths, why = kbp._base_paths(tmp_path / "not_a_repo")
    assert paths is None
    assert why and "git" in why


def test_named_case_in_another_directory_is_reported_as_such(monkeypatch, tmp_path):
    """Отрицательный контроль `same_directory`: сцена, где ответ ДОЛЖЕН быть False.

    Прежняя сцена отвечала только `True`, поэтому мутант, сравнивавший РАЗДЕЛИТЕЛИ
    вместо каталогов, выживал: «/» == «/» на любой паре.
    """
    monkeypatch.setattr(kbp, "GROUND_TRUTH", (
        {"coordinate": "scripts/alpha_beta_gamma.py",
         "candidate": "spa_core/monitoring/alpha_beta_gamma.py",
         "truth": "subject_closed_elsewhere", "relation": "сцена",
         "evidence": "сцена"},))
    report = _measure(tmp_path,
                      findings=[{"coordinate": "scripts/alpha_beta_gamma.py",
                                 "verdict": "absent_lost"}],
                      tree=["spa_core/monitoring/alpha_beta_gamma.py"])
    assert report["named_case"]["same_directory"] is False
    assert report["verdict"]["premise_of_the_order_holds"] is True
    # И ось заказа этот случай ДОСТАЁТ — иначе посылка была бы верна зря.
    assert report["axes"]["whole_tree"]["reaches_named_case"] is True


def test_unreached_named_case_alone_is_already_a_finding(monkeypatch, tmp_path):
    """`not reaches_named_case` был ЗАМАСКИРОВАН: в прежней сцене платили и другие.

    Сцена изолирует третий член: тишины нет, перебития нет, а названный случай
    ось не достаёт — вердикт обязан остаться НАХОДКОЙ.
    """
    monkeypatch.setattr(kbp, "GROUND_TRUTH", (
        {"coordinate": "docs/decisions/ADR-900-unreachable-by-name.md",
         "candidate": "docs/decisions/ADR-901-quite-different-words-here.md",
         "truth": "subject_closed_elsewhere", "relation": "сцена",
         "evidence": "сцена"},))
    report = _measure(tmp_path,
                      findings=[{"coordinate": "docs/decisions/ADR-900-unreachable-by-name.md",
                                 "verdict": "at_base"}],
                      tree=["docs/decisions/ADR-901-quite-different-words-here.md"])
    axis = report["axes"]["whole_tree"]
    assert axis["silenced"] == 0 and axis["preempted_evidence"] == 0
    assert axis["reaches_named_case"] is False
    assert report["status"] == "НАХОДКА", (
        "недостижимость названного случая САМА есть находка — заказ просил достать его")


def test_the_module_resolves_its_own_repo_root():
    """`parents[2]` → `[3]`: корень уехал бы на каталог выше МОЛЧА."""
    root = Path(kbp.__file__).resolve().parents[2]
    assert (root / "spa_core" / "monitoring" / "kin_breadth_price.py").exists()
    assert (root / "architecture" / "manifest.json").exists()


def test_json_output_stays_readable_russian(tmp_path, monkeypatch, capsys):
    """`ensure_ascii=False` и `indent=2` наблюдаемы: иначе вывод шага нечитаем."""
    doc = _measure(tmp_path)
    monkeypatch.setattr(kbp, "run", lambda root=None, *, now=None: {
        "measured": True, "doc": doc})
    assert kbp.main(["--json"]) == 1
    out = capsys.readouterr().out
    assert "\\u" not in out, "русский ушёл в \\uXXXX — вывод шага нечитаем"
    assert "НАХОДКА" in out
    first_nested = next(l for l in out.splitlines() if l.startswith("  \""))
    assert first_nested.startswith('  "'), "отступ вложенности не 2 знака"


def _office():
    """Реестр шага 0-офис — грузится ПО ПУТИ, он не пакетный модуль."""
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "c830_office", ROOT / "scripts" / "consume_office_reports.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_artifact_name_and_producer_agree_with_the_office_registry():
    """Имя артефакта и производитель — КОНТРАКТ с читателем, а не внутреннее дело.

    Мутант, переименовавший `ARTIFACT`, в батарее выживал: все её ассерты ходили
    через ту же константу. Претензия закрывается сверкой с ТЕМ, КТО ЧИТАЕТ.
    """
    office = _office()
    assert kbp.ARTIFACT in office._READ_SCHEMA, (
        f"{kbp.ARTIFACT} не объявлен реестру офиса — артефакт читался бы ВХОЛОСТУЮ")
    assert office._PRODUCER[kbp.ARTIFACT] == "spa_core/monitoring/kin_breadth_price.py"


def test_every_declared_schema_key_is_present_in_both_outcomes(tmp_path):
    """Объявленное поле, которого читатель не видит, — мёртвый свидетель (ADR-686).

    Сторож схемы офиса краснеет на ОТСУТСТВИИ объявленного ключа. Поэтому ключи
    обязаны быть и в измеренном отчёте, и в третьем исходе — ЯВНЫМ `None`, а не
    отсутствием.
    """
    office = _office()
    declared = set(office._READ_SCHEMA[kbp.ARTIFACT])
    for report in (_measure(tmp_path), _measure(tmp_path, findings=[])):
        missing = declared - set(report)
        assert not missing, f"объявлено, но не напечатано: {sorted(missing)}"


def test_the_manifest_declares_this_artifact_with_a_producer_and_an_slo():
    """Артефакт без объявленного производителя в конституции = дрейф проводки."""
    manifest = json.loads((ROOT / "architecture" / "manifest.json").read_text())
    path = f"data/{kbp.ARTIFACT}"
    rows = [a for a in manifest["artifacts"] if a.get("path") == path]
    assert len(rows) == 1, f"строк о {path} в манифесте {len(rows)}, должна быть одна"
    assert rows[0]["producer"] == "com.spa.decision_loop"
    assert rows[0]["slo_hours"] == 12
    produced = [pr for agent in manifest["agents"]
                for pr in (agent.get("produces") or [])
                if pr.get("artifact") == path]
    assert produced, "ни один агент не объявляет этот артефакт своим продуктом"


def test_ground_truth_keys_are_the_ones_the_rows_carry(tmp_path):
    """Переименуй ключ оракула — и доказательство перестанет доезжать МОЛЧА."""
    report = _measure(tmp_path)
    rows = report["axes"]["all_three"]["rows"]
    assert rows
    for row in rows:
        assert {"truth", "relation", "evidence"} <= set(row), sorted(row)
    verified = [r for r in rows if r["truth"] != "unmeasured"]
    assert verified, "сцена без ни одного доказанного ряда оракул не проверяет"
    assert all(r["evidence"] for r in verified)
    assert all(r["relation"] for r in verified)


def test_run_writes_its_artifact_under_the_given_root(tmp_path):
    """Обёртка ступени: конверт `{measured, doc}` и каталог `data` — наблюдаемы.

    `run()` — тонкий вход моста, и батарея его намеренно НЕ зовёт с умолчанием
    (это писало бы в живой `data/`). С ЗАДАННЫМ корнем он безопасен, и тогда
    проверяется то, что читает мост: конверт, имя каталога и оставленный артефакт.
    Здесь журнала нет по построению ⇒ третий исход, и он обязан ДОЕХАТЬ до файла.
    """
    (tmp_path / "data").mkdir()
    result = kbp.run(root=str(tmp_path))
    assert set(result) == {"measured", "doc"}
    assert result["measured"] is False, "журнала нет ⇒ замера нет"
    assert result["doc"]["measured"] is False
    assert result["doc"]["reason"], "третий исход без названной причины запрещён"
    written = json.loads((tmp_path / "data" / kbp.ARTIFACT).read_text())
    assert written["reason"] == result["doc"]["reason"]
    assert written["measured"] is False


def test_axis_rows_declare_their_flags(tmp_path):
    """Ключ `flags` — объявление оси в отчёте; без него читатель не знает, что мерили."""
    report = _measure(tmp_path)
    for axis, flags in kbp.AXES:
        assert report["axes"][axis]["flags"] == flags, axis
