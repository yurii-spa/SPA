"""Контроль: «НЕ ИЗМЕРЕНО» в сводке §49 — ТРИ класса, и ИТОГ обязан их развести.

Предмет — ADR-810, и авария, которую он чинит, настоящая и свежая.

**Что случилось.** Цикл #932 снял сводку §49 в одноразовом worktree, передав ей
живое `data/` прод-дерева (`--data-dir`), прочитал «ИТОГ: … НЕ ИЗМЕРЕНО 1» и
записал в ADR-809, что неизмеренным остался критерий `No regression` — «мерка
есть, а ВХОДА у неё нет», — и выписал следующему циклу заказ «чинить
производителя входа». Замер цикла #933 на том же живом `data/`: в ПРОД-дереве
этот критерий **ВЫПОЛНЕН** (`satisfied`), запись прогона свежа, производитель
работает и позван ступенью моста. Неизмеренным в прод-дереве стои́т ДРУГОЙ
критерий — `Owner visibility`.

**Почему две правды.** `no_regression_tests_pass` — единственная из тринадцати
проб, объявляющая ровно один вход дерева (`repo_root`). `--data-dir` до него не
доходит ПО ПОСТРОЕНИЮ, проба читает СВОЁ дерево (пустой worktree), не находит
отчёта переписи и честно отвечает «не измерено». Строка про это стояла в выводе
дословно — «дерево замера НЕ дошло: проба читает СВОЁ дерево». Её съела ТРОЙКА
чисел ИТОГА: «не измерено по существу» и «вердикт снят не о том дереве» в ней
были ОДНИМ числом, а чинятся они противоположным — первое мерку исправляет,
второе мерку трогать ЗАПРЕЩАЕТ и требует перемера.

Это инв. #17 этажом выше обычного: не проба выдала отсутствие наблюдения за
ноль, а СВОДКА слила два разных отсутствия в один счёт.

Каждый тест ниже — положительный контроль на конкретный способ соврать, а не
украшение (`.claude/rules/deployment.md`, «Проверка сторожа сторожей»).
Литеральных дат и pid в файле нет: у сводки нет понятия свежести, заводить его
фикстурой значило бы поставить бомбу на пустом месте.
"""

from __future__ import annotations

import ast
import os
import subprocess
import sys

import pytest

_REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(_REPO, "scripts"))

import cio_acceptance_rollup as rollup  # noqa: E402

from spa_core.monitoring.card_acceptance import (  # noqa: E402
    NOT_SATISFIED,
    SATISFIED,
    UNMEASURED,
)

CARD_REL = rollup.CARD_REL

#: Имя ветки — ВХОД сцены, а не умолчание хоста (`init.defaultBranch` даёт
#: `main` на Маке и `master` на `ubuntu-latest`): `.claude/rules/deployment.md`,
#: раздел GIT-ОКРУЖЕНИЕ.
BRANCH = "main"

SECTION = """49. Acceptance criteria
Работа считается выполненной только когда доказано следующее.
Architecture
Portfolio-level decision owner существует.
Owner visibility
Числа доходят до владельца.
No regression
Existing risk/security/architecture tests проходят.


⸻

50. Definition of Done
"""


def _scene(tmp_path) -> str:
    root = tmp_path / "repo"
    (root / os.path.dirname(CARD_REL)).mkdir(parents=True)
    subprocess.run(["git", "init", "-b", BRANCH], cwd=root, check=True,
                   capture_output=True)
    subprocess.run(["git", "config", "user.email", "t@t"], cwd=root, check=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=root, check=True)
    (root / CARD_REL).write_text(
        "---\ntitle: \"TASK\"\nstatus: in-progress\n---\n\n## Задание\n\n"
        "преамбула\n\n\n⸻\n\n\n" + SECTION, encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=root, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "card"], cwd=root, check=True,
                   capture_output=True)
    return str(root)


def _row(report: dict, name: str) -> dict:
    return next(r for r in report["rows"] if r["criterion"] == name)


def _inputs(mapping: dict):
    """Объявленные входы по имени пробы; имя вне словаря — пустой кортеж."""
    return lambda name: mapping.get(name, ())


def _verdicts(mapping: dict, default=(SATISFIED, "ок")):
    def runner(spec, **kw):
        return mapping.get(spec, default)
    return runner


# --------------------------------------------------------------------------
# 1. ВОСПРОИЗВЕДЕНИЕ АВАРИИ: форма замера ADR-809, дословно
# --------------------------------------------------------------------------

def test_the_adr_809_run_shape_is_named_as_a_wrong_tree_not_as_a_debt(
        tmp_path, monkeypatch):
    """`--data-dir` без `--measure-tree` + проба, которой нужен только `repo_root`.

    Это ровно форма прогона цикла #932. Вердикт строки остаётся `unmeasured` —
    проба и правда ничего не измерила, — но КЛАСС обязан сказать, что измеряли
    не то дерево, а не что у критерия дыра в мерке.
    """
    monkeypatch.setattr(rollup, "probes_by_s49_criterion",
                        lambda: {"Architecture": ["p_arch"],
                                 "Owner visibility": ["p_vis"],
                                 "No regression": ["p_reg"]})
    monkeypatch.setattr(rollup, "probe_tree_inputs", _inputs({
        "p_arch": ("repo_root", "data_dir"),
        "p_vis": ("repo_root", "data_dir"),
        "p_reg": ("repo_root",)}))
    report = rollup.measure(
        _scene(tmp_path), ref=BRANCH, data_dir="/prod/data",
        probe_runner=_verdicts({"p_reg": (UNMEASURED, "отчёта переписи нет")}))

    row = _row(report, "No regression")
    assert row["verdict"] == UNMEASURED
    assert row["unmeasured_class"] == rollup.UNMEASURED_TREE_NOT_REACHED
    assert report["unmeasured_classes"] == {
        rollup.UNMEASURED_IN_SUBJECT_TREE: 0,
        rollup.UNMEASURED_TREE_NOT_REACHED: 1,
        rollup.UNMEASURED_NO_MEASURE: 0}
    assert [m["criterion"] for m in report["not_about_subject_tree"]] \
        == ["No regression"]
    # Адрес починки назван: перемерять надо тем входом, который проба объявила.
    assert report["not_about_subject_tree"][0]["tree_inputs_declared"] \
        == ["repo_root"]


def test_the_same_probe_in_the_subject_tree_is_a_real_debt(tmp_path, monkeypatch):
    """Обратная сторона той же монеты, и без неё первый тест ничего не стои́т.

    Дерево замера дошло до пробы её объявленным входом, а она всё равно не
    измерила — ЭТО долг критерия, и класс обязан сказать именно так.
    """
    monkeypatch.setattr(rollup, "probes_by_s49_criterion",
                        lambda: {"Architecture": ["p_arch"],
                                 "Owner visibility": ["p_vis"],
                                 "No regression": ["p_reg"]})
    monkeypatch.setattr(rollup, "probe_tree_inputs", _inputs({
        "p_arch": ("repo_root", "data_dir"),
        "p_vis": ("repo_root", "data_dir"),
        "p_reg": ("repo_root",)}))
    report = rollup.measure(
        _scene(tmp_path), ref=BRANCH, measure_tree="/prod",
        probe_runner=_verdicts({"p_reg": (UNMEASURED, "отчёта переписи нет")}))

    assert _row(report, "No regression")["unmeasured_class"] \
        == rollup.UNMEASURED_IN_SUBJECT_TREE
    assert report["unmeasured_classes"][rollup.UNMEASURED_TREE_NOT_REACHED] == 0
    assert report["not_about_subject_tree"] == []


# --------------------------------------------------------------------------
# 2. Три класса различимы, и ни один не поглощает соседа
# --------------------------------------------------------------------------

def test_a_criterion_without_a_measure_is_its_own_class(tmp_path, monkeypatch):
    """«Мерки нет» чинится ОБЪЯВЛЕНИЕМ мерки, а не перемером и не починкой."""
    monkeypatch.setattr(rollup, "probes_by_s49_criterion", lambda: {})
    report = rollup.measure(_scene(tmp_path), ref=BRANCH, measure_tree="/prod",
                            probe_runner=_verdicts({}))
    assert {r["unmeasured_class"] for r in report["rows"]} \
        == {rollup.UNMEASURED_NO_MEASURE}
    assert report["unmeasured_classes"][rollup.UNMEASURED_NO_MEASURE] == 3
    assert report["not_about_subject_tree"] == []


def test_two_probes_on_one_criterion_is_not_counted_as_a_wrong_tree(
        tmp_path, monkeypatch):
    """Столкновение объявлений — тоже «мерки нет», и дерево тут ни при чём."""
    monkeypatch.setattr(rollup, "probes_by_s49_criterion",
                        lambda: {"Architecture": ["p1", "p2"]})
    monkeypatch.setattr(rollup, "probe_tree_inputs", _inputs({}))
    report = rollup.measure(_scene(tmp_path), ref=BRANCH, measure_tree="/prod",
                            probe_runner=_verdicts({}))
    assert _row(report, "Architecture")["unmeasured_class"] \
        == rollup.UNMEASURED_NO_MEASURE


def test_a_probe_declaring_no_tree_input_is_never_blamed_on_the_tree(
        tmp_path, monkeypatch):
    """Тонкая сторона, и ошибиться здесь значило бы спрятать настоящий долг.

    Проба, не спрашивающая дерева ни одним входом, получает `reached == []` —
    по той же форме, что и жертва аварии. Но дерево замера её ответ изменить НЕ
    МОЖЕТ, поэтому «перемерять в другом дереве» было бы ложным советом, а
    настоящий долг остался бы незамеченным. Класс обязан быть `in_subject_tree`.
    """
    monkeypatch.setattr(rollup, "probes_by_s49_criterion",
                        lambda: {"Architecture": ["p1"]})
    monkeypatch.setattr(rollup, "probe_tree_inputs", _inputs({}))
    report = rollup.measure(
        _scene(tmp_path), ref=BRANCH, measure_tree="/prod",
        probe_runner=_verdicts({"p1": (UNMEASURED, "нечего читать")}))
    row = _row(report, "Architecture")
    assert row["tree_inputs_reached"] == []       # форма та же, что у аварии
    assert row["tree_inputs_declared"] == []      # а объявления входов НЕТ
    assert row["unmeasured_class"] == rollup.UNMEASURED_IN_SUBJECT_TREE
    assert report["not_about_subject_tree"] == []


def test_without_a_measure_tree_no_divergence_is_invented(tmp_path, monkeypatch):
    """`reached is None` — дерева замера не объявляли; проба судила СВОЁ, и оно
    же есть предмет вердикта. Назвать это «не о том дереве» значило бы выдумать
    расхождение там, где его нет (`None` ≠ `[]`, тот же урок инв. #17)."""
    monkeypatch.setattr(rollup, "probes_by_s49_criterion",
                        lambda: {"Architecture": ["p1"]})
    monkeypatch.setattr(rollup, "probe_tree_inputs",
                        _inputs({"p1": ("repo_root",)}))
    report = rollup.measure(
        _scene(tmp_path), ref=BRANCH,
        probe_runner=_verdicts({"p1": (UNMEASURED, "нечего читать")}))
    row = _row(report, "Architecture")
    assert row["tree_inputs_reached"] is None
    assert row["unmeasured_class"] == rollup.UNMEASURED_IN_SUBJECT_TREE


@pytest.mark.parametrize("verdict", [SATISFIED, NOT_SATISFIED])
def test_a_measured_row_carries_the_class_question_answered_not_absent(
        tmp_path, monkeypatch, verdict):
    """У измеренной строки класс есть и равен `None` — «вопрос не стои́т».

    Отсутствие ПОЛЯ значило бы «класс не считали вовсе», и отличить это от
    «посчитали, вопрос не стои́т» было бы нечем.
    """
    monkeypatch.setattr(rollup, "probes_by_s49_criterion",
                        lambda: {"Architecture": ["p1"]})
    monkeypatch.setattr(rollup, "probe_tree_inputs", _inputs({}))
    report = rollup.measure(_scene(tmp_path), ref=BRANCH, measure_tree="/prod",
                            probe_runner=_verdicts({"p1": (verdict, "д")}))
    row = _row(report, "Architecture")
    assert "unmeasured_class" in row
    assert row["unmeasured_class"] is None


def test_the_three_classes_add_up_to_the_unmeasured_count(tmp_path, monkeypatch):
    """Сумма классов ЕСТЬ счёт «НЕ ИЗМЕРЕНО» — иначе разбор говорил бы о другом
    населении, чем ИТОГ, и два числа под одним заголовком снова разошлись бы."""
    monkeypatch.setattr(rollup, "probes_by_s49_criterion",
                        lambda: {"Architecture": ["p_arch"],
                                 "No regression": ["p_reg"]})
    monkeypatch.setattr(rollup, "probe_tree_inputs", _inputs({
        "p_arch": ("repo_root", "data_dir"),
        "p_reg": ("repo_root",)}))
    report = rollup.measure(
        _scene(tmp_path), ref=BRANCH, data_dir="/prod/data",
        probe_runner=_verdicts({"p_arch": (UNMEASURED, "нет данных"),
                                "p_reg": (UNMEASURED, "нет дерева")}))
    # Owner visibility остался без пробы ⇒ третий класс тоже населён.
    assert sum(report["unmeasured_classes"].values()) \
        == report["counts"][UNMEASURED] == 3
    assert report["unmeasured_classes"] == {
        rollup.UNMEASURED_IN_SUBJECT_TREE: 1,
        rollup.UNMEASURED_TREE_NOT_REACHED: 1,
        rollup.UNMEASURED_NO_MEASURE: 1}


# --------------------------------------------------------------------------
# 3. Разбор ДОХОДИТ ДО ЧИТАТЕЛЯ — иначе он был бы полем без читателя
# --------------------------------------------------------------------------

def test_the_breakdown_is_printed_under_the_tally(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(rollup, "probes_by_s49_criterion",
                        lambda: {"Architecture": ["p_arch"],
                                 "Owner visibility": ["p_vis"],
                                 "No regression": ["p_reg"]})
    monkeypatch.setattr(rollup, "probe_tree_inputs", _inputs({
        "p_arch": ("repo_root", "data_dir"),
        "p_vis": ("repo_root", "data_dir"),
        "p_reg": ("repo_root",)}))
    monkeypatch.setattr(rollup, "run_probe",
                        _verdicts({"p_reg": (UNMEASURED, "отчёта нет")}))
    code = rollup.main(["--repo-root", _scene(tmp_path), "--ref", BRANCH,
                        "--data-dir", "/prod/data"])
    out = capsys.readouterr().out
    assert code == 1
    assert "НЕ ИЗМЕРЕНО 1" in out
    assert "НЕ О ТОМ ДЕРЕВЕ 1" in out
    assert "ВЕРДИКТ СНЯТ НЕ О ТОМ ДЕРЕВЕ: No regression" in out
    # Совет обязан быть ПРОТИВОПОЛОЖЕН тому, который выписал ADR-809.
    assert "мерку НЕ ТРОГАТЬ" in out


def test_a_clean_subject_tree_run_says_the_residue_is_substance(
        tmp_path, monkeypatch, capsys):
    """Вторая сторона печати: когда «не о том дереве» ноль, это ВИДНО числом."""
    monkeypatch.setattr(rollup, "probes_by_s49_criterion",
                        lambda: {"Architecture": ["p_arch"],
                                 "Owner visibility": ["p_vis"],
                                 "No regression": ["p_reg"]})
    monkeypatch.setattr(rollup, "probe_tree_inputs", _inputs({
        "p_arch": ("repo_root", "data_dir"),
        "p_vis": ("repo_root", "data_dir"),
        "p_reg": ("repo_root",)}))
    monkeypatch.setattr(rollup, "run_probe",
                        _verdicts({"p_vis": (UNMEASURED, "поверхности нет")}))
    rollup.main(["--repo-root", _scene(tmp_path), "--ref", BRANCH,
                 "--measure-tree", "/prod"])
    out = capsys.readouterr().out
    assert "по существу 1 · НЕ О ТОМ ДЕРЕВЕ 0" in out
    assert "ВЕРДИКТ СНЯТ НЕ О ТОМ ДЕРЕВЕ" not in out


def test_nothing_unmeasured_prints_no_breakdown(tmp_path, monkeypatch, capsys):
    """Разбор пустого множества — шум, а не честность: его быть не должно."""
    monkeypatch.setattr(rollup, "probes_by_s49_criterion",
                        lambda: {"Architecture": ["p_arch"],
                                 "Owner visibility": ["p_vis"],
                                 "No regression": ["p_reg"]})
    monkeypatch.setattr(rollup, "probe_tree_inputs", _inputs({}))
    monkeypatch.setattr(rollup, "run_probe", _verdicts({}))
    rollup.main(["--repo-root", _scene(tmp_path), "--ref", BRANCH,
                 "--measure-tree", "/prod"])
    out = capsys.readouterr().out
    assert "из «НЕ ИЗМЕРЕНО»" not in out


# --------------------------------------------------------------------------
# 4. У правила ОДИН дом, и это меряется AST, а не глазами
# --------------------------------------------------------------------------

def test_the_class_rule_has_exactly_one_home():
    """Второе место, решающее класс, разошлось бы с первым молча (ADR-220).

    Меряется не подстрокой, а разбором: ищутся функции, ВОЗВРАЩАЮЩИЕ любую из
    трёх констант класса. Такая функция обязана быть ровно одна.
    """
    source = open(rollup.__file__, encoding="utf-8").read()
    names = {"UNMEASURED_NO_MEASURE", "UNMEASURED_TREE_NOT_REACHED",
             "UNMEASURED_IN_SUBJECT_TREE"}
    deciders = set()
    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for inner in ast.walk(node):
            if isinstance(inner, ast.Return) and isinstance(inner.value, ast.Name) \
                    and inner.value.id in names:
                deciders.add(node.name)
    assert deciders == {"unmeasured_class"}, (
        f"класс решают {sorted(deciders)} — копий правила больше одной")


def test_the_breakdown_names_every_declared_class():
    """Словарь классов и его русская расшифровка не имеют права разойтись:
    новый класс без имени печатался бы ключом либо не печатался вовсе."""
    assert set(rollup.UNMEASURED_CLASS_RU) == {
        rollup.UNMEASURED_NO_MEASURE,
        rollup.UNMEASURED_TREE_NOT_REACHED,
        rollup.UNMEASURED_IN_SUBJECT_TREE}


# --------------------------------------------------------------------------
# 5. Живой приказ: `No regression` — единственная проба с одним входом дерева,
#    и именно поэтому жертвой стала она
# --------------------------------------------------------------------------

def test_the_live_order_still_has_exactly_one_probe_unreachable_by_data_dir():
    """Замер, а не литерал: если завтра таких проб станет две, тест покраснеет
    и скажет, что поверхность класса выросла."""
    from spa_core.monitoring.card_acceptance import (
        probe_tree_inputs,
        probes_by_s49_criterion,
    )
    lonely = sorted(
        probe
        for probes in probes_by_s49_criterion().values()
        for probe in probes
        if probe_tree_inputs(probe) == ("repo_root",))
    assert lonely == ["no_regression_tests_pass"], lonely
