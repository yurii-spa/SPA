"""Контроль сводного замера §49 приказа «Portfolio CIO» (`scripts/cio_acceptance_rollup.py`).

Каждый тест здесь — положительный контроль на конкретный способ соврать, а не
украшение (`.claude/rules/deployment.md`, «Проверка сторожа сторожей»). Сводка
из тринадцати вердиктов опасна ровно одним: она производит КРАСИВОЕ ЧИСЛО, и
любая тихая подстановка внутри неё («критерий без мерки посчитали нулём»,
«раздел не разобрался — взяли что нашли», «две пробы на критерии — взяли
первую») даёт число, неотличимое по форме от честного.

Литеральных дат в файле нет: у сводки нет понятия свежести, и заводить его
фикстурой значило бы поставить бомбу на пустом месте (то же правило, раздел про
время). Литеральных pid нет по той же причине.
"""

from __future__ import annotations

import os
import subprocess
import sys

import pytest

_REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(_REPO, "scripts"))

import cio_acceptance_rollup as rollup  # noqa: E402

from spa_core.monitoring.card_acceptance import (  # noqa: E402
    NOT_SATISFIED,
    PROBES,
    SATISFIED,
    UNMEASURED,
    probe_tree_inputs,
    probes_by_s49_criterion,
    run_probe,
)

CARD_REL = rollup.CARD_REL


# --------------------------------------------------------------------------
# Сцена: одноразовый репозиторий с карточкой. Имя ветки — ВХОД (`git init -b`),
# а не умолчание хоста: `init.defaultBranch` на Маке даёт `main`, а на
# `ubuntu-latest` — `master`, и тест, назвавший потом `origin/main`, был бы
# зелён здесь и красен в CI (`.claude/rules/deployment.md`, GIT-ОКРУЖЕНИЕ).
# --------------------------------------------------------------------------
BRANCH = "main"

SECTION = """49. Acceptance criteria
Работа считается выполненной только когда доказано следующее.
Architecture
Portfolio-level decision owner существует.
Economics
Решения используют net expected return, а не raw APY.
No regression
Existing risk/security/architecture tests проходят.


⸻


50. Definition of Done
"""


def _card(section: str = SECTION, preamble: str = "преамбула") -> str:
    return ("---\ntitle: \"TASK\"\nstatus: in-progress\n---\n\n"
            "## Задание\n\n" + preamble + "\n\n\n⸻\n\n\n" + section)


def _scene(tmp_path, *, section: str = SECTION, ref_section: str | None = None,
           edit_outside_section: bool = False):
    """Репозиторий с карточкой; рабочая копия может отличаться от закоммиченной.

    Возврат — корень дерева. Три состояния сцены, и все три нужны:

    * ничего не задано — рабочая копия == `HEAD` == `ref`, сравнение копий
      ТАВТОЛОГИЧНО (урок ADR-504: совпадение тут гарантировано по построению);
    * `edit_outside_section` — файл правлен ВНЕ §49: сравнение настоящее,
      население обязано совпасть;
    * `ref_section` — правлен САМ §49: копии дают разное население, и это
      `unmeasured`, а не «возьмём ту, что под рукой».
    """
    root = tmp_path / "repo"
    (root / os.path.dirname(CARD_REL)).mkdir(parents=True)
    subprocess.run(["git", "init", "-b", BRANCH], cwd=root, check=True,
                   capture_output=True)
    subprocess.run(["git", "config", "user.email", "t@t"], cwd=root, check=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=root, check=True)
    (root / CARD_REL).write_text(_card(ref_section or section), encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=root, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "card"], cwd=root, check=True,
                   capture_output=True)
    if ref_section is not None or edit_outside_section:
        (root / CARD_REL).write_text(
            _card(section, "преамбула, дописанная в рабочем дереве"),
            encoding="utf-8")
    return str(root)


def _fixed(verdict: str, detail: str = "фикстура"):
    def runner(spec, **kw):
        return verdict, detail
    return runner


# --------------------------------------------------------------------------
# 1. Разбор населения: число критериев — ЗАМЕР, а не литерал
# --------------------------------------------------------------------------

def test_population_is_read_from_the_card_not_from_a_literal():
    names = rollup.parse_s49_criteria(_card())
    assert names == ["Architecture", "Economics", "No regression"]


def test_the_live_order_still_carries_thirteen_criteria():
    """Обратная сторона предыдущего: разбор работает на НАСТОЯЩЕЙ карточке.

    Число `13` здесь — не предмет проверки, а свидетель того, что разбор не
    развалился на живом тексте: тест упадёт и если критериев станет 12, и если
    14, и это ВЕРНО — состав приёмки владельца менять молча нельзя.
    """
    path = os.path.join(_REPO, CARD_REL)
    if not os.path.isfile(path):
        pytest.fail(f"карточка приказа {CARD_REL} в дереве отсутствует — "
                    f"население НЕ ИЗМЕРЕНО, и выдать это за успех нельзя")
    names = rollup.parse_s49_criteria(open(path, encoding="utf-8").read())
    assert len(names) == 13, names
    assert names[0] == "Architecture" and names[-1] == "No regression"


@pytest.mark.parametrize("section,needle", [
    ("совсем другой текст\n", "не найден"),
    (SECTION + "\n" + SECTION, "встречается 2 раз"),
    ("49. Acceptance criteria\nтолько описание.\nи ещё одно.\n",
     "нет НИ ОДНОГО заголовка"),
    ("49. Acceptance criteria\nвводная.\nArchitecture\nописание.\nEconomics\n",
     "остался без описания"),
    # Мутация M01 (цикл #723) пережила первую редакцию батареи: ни одна фикстура
    # не доводила разбор до ПЕРВОГО отказа — «здесь ждали заголовок, а пришло
    # описание». Ровно эта форма и есть «разбор, умеющий пропустить непонятное»:
    # лишняя строка описания сдвинула бы чередование, и следующий заголовок
    # прочёлся бы как описание — население молча стало бы короче.
    ("49. Acceptance criteria\nвводная.\nArchitecture\nописание.\n"
     "лишняя строка описания.\nEconomics\nописание.\n",
     "ожидалась заголовком критерия"),
    ("49. Acceptance criteria\nвводная.\nArchitecture\nEconomics\nописание.\n",
     "нет строки описания"),
    ("49. Acceptance criteria\nвводная.\nArchitecture\nописание.\n"
     "Architecture\nещё описание.\n", "объявлен в §49 дважды"),
])
def test_a_broken_section_is_unmeasured_with_a_named_reason(section, needle):
    """Разбор, умеющий «пропустить непонятное», врал бы ТИХО: тут он обязан падать."""
    with pytest.raises(rollup.Unmeasured) as exc:
        rollup.parse_s49_criteria(_card(section))
    assert needle in str(exc.value), str(exc.value)


def test_an_empty_section_is_not_a_clean_pass():
    with pytest.raises(rollup.Unmeasured) as exc:
        rollup.parse_s49_criteria(_card("49. Acceptance criteria\n\n\n⸻\n"))
    assert "зелено по построению" in str(exc.value)


# --------------------------------------------------------------------------
# 2. Сводка: третий исход — исход, а не ноль
# --------------------------------------------------------------------------

def test_a_criterion_without_a_probe_is_unmeasured_never_satisfied(tmp_path,
                                                                   monkeypatch):
    monkeypatch.setattr(rollup, "probes_by_s49_criterion", lambda: {})
    report = rollup.measure(_scene(tmp_path), ref=BRANCH,
                            probe_runner=_fixed(SATISFIED))
    assert report["counts"][UNMEASURED] == 3
    assert report["counts"][SATISFIED] == 0
    for row in report["rows"]:
        assert row["probe"] is None
        assert "в реестре НЕТ" in row["detail"]


def test_every_member_of_the_population_gets_exactly_one_verdict(tmp_path,
                                                                 monkeypatch):
    """Сумма троек обязана СХОДИТЬСЯ с населением: иначе число теряет смысл."""
    monkeypatch.setattr(rollup, "probes_by_s49_criterion",
                        lambda: {"Architecture": ["p1"], "Economics": ["p2"]})
    report = rollup.measure(_scene(tmp_path), ref=BRANCH,
                            probe_runner=_fixed(NOT_SATISFIED))
    assert sum(report["counts"].values()) == report["population"] == 3
    assert report["counts"][NOT_SATISFIED] == 2
    assert report["counts"][UNMEASURED] == 1


def test_a_probe_verdict_is_taken_as_is_and_not_softened(tmp_path, monkeypatch):
    monkeypatch.setattr(rollup, "probes_by_s49_criterion",
                        lambda: {"Architecture": ["p1"]})
    report = rollup.measure(_scene(tmp_path), ref=BRANCH,
                            probe_runner=_fixed(NOT_SATISFIED, "поломка названа"))
    row = next(r for r in report["rows"] if r["criterion"] == "Architecture")
    assert row["verdict"] == NOT_SATISFIED
    assert row["detail"] == "поломка названа"


def test_two_probes_on_one_criterion_is_a_collision_not_a_silent_pick(tmp_path,
                                                                      monkeypatch):
    monkeypatch.setattr(rollup, "probes_by_s49_criterion",
                        lambda: {"Architecture": ["p1", "p2"]})
    report = rollup.measure(_scene(tmp_path), ref=BRANCH,
                            probe_runner=_fixed(SATISFIED))
    row = next(r for r in report["rows"] if r["criterion"] == "Architecture")
    assert row["verdict"] == UNMEASURED
    assert row["probe"] is None
    assert "p1, p2" in row["detail"]


def test_a_declaration_pointing_outside_the_population_is_named(tmp_path,
                                                                monkeypatch):
    """Проба, объявившая критерий, которого у приказа НЕТ, обязана быть названа.

    Молчание о ней читалось бы как «этот критерий меряют где-то ещё».
    """
    monkeypatch.setattr(rollup, "probes_by_s49_criterion",
                        lambda: {"Architecture": ["p1"], "Выдумка": ["p9"]})
    report = rollup.measure(_scene(tmp_path), ref=BRANCH,
                            probe_runner=_fixed(SATISFIED))
    assert report["orphan_declarations"] == {"Выдумка": ["p9"]}
    assert report["population"] == 3


# --------------------------------------------------------------------------
# 3. Две копии карточки: расхождение населения — «не измерено»
# --------------------------------------------------------------------------

def test_copies_disagreeing_on_the_population_refuse(tmp_path):
    other = SECTION.replace("Economics\nРешения используют net expected return, "
                            "а не raw APY.\n", "")
    with pytest.raises(rollup.Unmeasured) as exc:
        rollup.read_population(_scene(tmp_path, section=other,
                                      ref_section=SECTION), ref=BRANCH)
    assert "РАЗНОЕ население" in str(exc.value)


def test_a_tautological_comparison_says_so_out_loud(tmp_path):
    """Урок ADR-504: согласие копий при `HEAD == ref` гарантировано ПО ПОСТРОЕНИЮ.

    Прибор обязан напечатать, что вопрос не задавался, а не выдать совпадение за
    наблюдение.
    """
    got = rollup.read_population(_scene(tmp_path), ref=BRANCH)
    assert "ТАВТОЛОГИЧНО" in got["comparison"]
    assert got["criteria"] == ["Architecture", "Economics", "No regression"]


def test_a_real_comparison_says_so_too(tmp_path):
    """Файл правлен ⇒ совпадение §49 есть НАБЛЮДЕНИЕ, а не следствие построения."""
    got = rollup.read_population(
        _scene(tmp_path, edit_outside_section=True), ref=BRANCH)
    assert "состоялось" in got["comparison"]
    assert "правлен" in got["comparison"]
    assert got["criteria"] == ["Architecture", "Economics", "No regression"]


def test_no_copy_at_all_is_unmeasured(tmp_path):
    root = tmp_path / "bare"
    root.mkdir()
    with pytest.raises(rollup.Unmeasured) as exc:
        rollup.read_population(str(root), ref=BRANCH)
    assert "НИ ИЗ ОДНОЙ копии" in str(exc.value)


# --------------------------------------------------------------------------
# 4. Коды возврата: «не измерено» никогда не выдаётся за «чисто»
# --------------------------------------------------------------------------

def test_exit_two_when_there_is_no_rollup_at_all(tmp_path, capsys):
    root = tmp_path / "bare"
    root.mkdir()
    code = rollup.main(["--repo-root", str(root), "--ref", BRANCH])
    assert code == 2
    assert "НЕ ИЗМЕРЕНО" in capsys.readouterr().out


@pytest.mark.parametrize("verdict,expected", [
    (SATISFIED, 0), (NOT_SATISFIED, 1), (UNMEASURED, 1)])
def test_exit_code_follows_the_tally(tmp_path, monkeypatch, verdict, expected):
    monkeypatch.setattr(rollup, "probes_by_s49_criterion",
                        lambda c={}: {"Architecture": ["p1"], "Economics": ["p2"],
                                      "No regression": ["p3"]})
    monkeypatch.setattr(rollup, "run_probe", _fixed(verdict))
    code = rollup.main(["--repo-root", _scene(tmp_path), "--ref", BRANCH])
    assert code == expected


def test_a_single_unmeasured_criterion_denies_the_green(tmp_path, monkeypatch):
    """Двенадцать зелёных и один неизмеренный — это НЕ «выполнено»."""
    def runner(spec, **kw):
        return (UNMEASURED, "нечем") if spec == "p2" else (SATISFIED, "ок")
    monkeypatch.setattr(rollup, "probes_by_s49_criterion",
                        lambda: {"Architecture": ["p1"], "Economics": ["p2"],
                                 "No regression": ["p3"]})
    monkeypatch.setattr(rollup, "run_probe", runner)
    assert rollup.main(["--repo-root", _scene(tmp_path), "--ref", BRANCH]) == 1


# --------------------------------------------------------------------------
# 5. Дерево замера доходит до пробы теми входами, которые она объявила —
#    и то, ЧТО дошло, печатается, а не подразумевается
# --------------------------------------------------------------------------

def test_the_measured_tree_reaches_the_probe_by_declared_inputs(tmp_path,
                                                                monkeypatch):
    seen: dict = {}

    def runner(spec, **kw):
        seen.update(kw)
        return SATISFIED, "ок"

    monkeypatch.setattr(rollup, "probes_by_s49_criterion",
                        lambda: {"Architecture": ["p1"]})
    monkeypatch.setattr(rollup, "probe_tree_inputs",
                        lambda name: ("repo_root", "data_dir"))
    report = rollup.measure(_scene(tmp_path), ref=BRANCH, measure_tree="/somewhere",
                            probe_runner=runner)
    assert seen == {"repo_root": "/somewhere",
                    "data_dir": os.path.join("/somewhere", "data")}
    row = next(r for r in report["rows"] if r["criterion"] == "Architecture")
    assert row["tree_inputs_reached"] == ["repo_root", "data_dir"]


def test_a_probe_that_takes_no_tree_input_says_the_tree_did_not_reach_it(
        tmp_path, monkeypatch):
    """Половина инъекции — та же бомба: молчать об этом нельзя."""
    monkeypatch.setattr(rollup, "probes_by_s49_criterion",
                        lambda: {"Architecture": ["p1"]})
    monkeypatch.setattr(rollup, "probe_tree_inputs", lambda name: ())
    report = rollup.measure(_scene(tmp_path), ref=BRANCH, measure_tree="/somewhere",
                            probe_runner=_fixed(SATISFIED))
    row = next(r for r in report["rows"] if r["criterion"] == "Architecture")
    assert row["tree_inputs_reached"] == []


def test_a_split_tree_measurement_says_so_and_can_never_be_green(tmp_path,
                                                                 monkeypatch):
    """Сборный замер — вердикт НИ ОБ ОДНОМ существующем дереве.

    Форма нужна: только ею предъявляется разрыв «поверхности в одном дереве,
    артефакты в другом» (ADR-152, `landing/` в прод-дерево не синхронизируется).
    Но зелёным она быть не имеет права — иначе «всё выполнено» стало бы
    утверждением о системе, которой нет.
    """
    monkeypatch.setattr(rollup, "probes_by_s49_criterion",
                        lambda: {"Architecture": ["p1"], "Economics": ["p2"],
                                 "No regression": ["p3"]})
    monkeypatch.setattr(rollup, "run_probe", _fixed(SATISFIED))
    root = _scene(tmp_path)
    report = rollup.measure(root, ref=BRANCH, measure_tree="/surfaces",
                            data_dir="/elsewhere/data")
    assert report["split_tree"] is True
    assert report["counts"][SATISFIED] == 3
    assert rollup.main(["--repo-root", root, "--ref", BRANCH,
                        "--measure-tree", "/surfaces",
                        "--data-dir", "/elsewhere/data"]) == 1


def test_a_data_dir_that_matches_the_tree_is_not_a_split(tmp_path, monkeypatch):
    """Обратная сторона: тот же каталог, названный явно, разрывом НЕ является."""
    monkeypatch.setattr(rollup, "probes_by_s49_criterion",
                        lambda: {"Architecture": ["p1"], "Economics": ["p2"],
                                 "No regression": ["p3"]})
    monkeypatch.setattr(rollup, "run_probe", _fixed(SATISFIED))
    root = _scene(tmp_path)
    report = rollup.measure(root, ref=BRANCH, measure_tree="/t",
                            data_dir=os.path.join("/t", "data"))
    assert report["split_tree"] is False
    assert rollup.main(["--repo-root", root, "--ref", BRANCH,
                        "--measure-tree", "/t",
                        "--data-dir", os.path.join("/t", "data")]) == 0


def test_a_data_dir_alone_reaches_only_the_data_input(tmp_path, monkeypatch):
    """`--data-dir` без `--measure-tree`: `repo_root` пробе НЕ подсовывается."""
    seen: dict = {}

    def runner(spec, **kw):
        seen.update(kw)
        return SATISFIED, "ок"

    monkeypatch.setattr(rollup, "probes_by_s49_criterion",
                        lambda: {"Architecture": ["p1"]})
    monkeypatch.setattr(rollup, "probe_tree_inputs",
                        lambda name: ("repo_root", "data_dir"))
    report = rollup.measure(_scene(tmp_path), ref=BRANCH, data_dir="/d",
                            probe_runner=runner)
    assert seen == {"repo_root": None, "data_dir": "/d"}
    row = next(r for r in report["rows"] if r["criterion"] == "Architecture")
    assert row["tree_inputs_reached"] == ["data_dir"]


def test_without_a_measure_tree_the_reach_question_is_not_asked(tmp_path,
                                                                monkeypatch):
    """`None` ≠ `[]`: «не спрашивали» и «спросили, не дошло» — разные ответы."""
    monkeypatch.setattr(rollup, "probes_by_s49_criterion",
                        lambda: {"Architecture": ["p1"]})
    report = rollup.measure(_scene(tmp_path), ref=BRANCH,
                            probe_runner=_fixed(SATISFIED))
    row = next(r for r in report["rows"] if r["criterion"] == "Architecture")
    assert row["tree_inputs_reached"] is None


# --------------------------------------------------------------------------
# 6. Объявление у пробы: реестр, а не список рядом
# --------------------------------------------------------------------------

def test_declarations_are_read_from_the_registry_not_from_a_side_list():
    declared = probes_by_s49_criterion()
    assert declared == {"Architecture": ["portfolio_decision_owner_covers_capital"],
                        "Economics": ["economics_net_return_dominates_keep"],
                        # Заказ G95 п. 1, ADR-508: вторая привязка §49 уехала из прозы
                        # в поле. Снимок обновлён НЕ для того, чтобы погасить падение:
                        # предикат этого теста И ЕСТЬ живой реестр (см. его имя), и
                        # новая строка здесь — предмет утверждения, а не помеха ему.
                        "Persistence": ["persistence_advantage_outlives_horizon"],
                        # Заказ G96 п. 1, ADR-510: третья привязка, тем же порядком
                        # и по той же причине — снимок и есть живой реестр.
                        "Risk": ["risk_policy_unbypassable_in_executed_states"],
                        # ADR-511: четвёртая привязка, тем же порядком и по той же
                        # причине — снимок и есть живой реестр.
                        "Anti-churn": ["book_does_not_oscillate_between_opportunities"],
                        # ADR-513: ПЕРВАЯ привязка цены WORDING — тем же
                        # порядком и по той же причине; конституция при этом
                        # приведена к канонической форме, иначе читателю сводки
                        # осталось бы угадывать, о каком критерии речь.
                        "Costs": ["costs_are_accounted_for_in_the_decision"],
                        # ADR-514: ВТОРАЯ привязка цены WORDING — тем же
                        # порядком и по той же причине. Правка снимка намеренна
                        # и обоснована (инв. #16): предикат этого теста И ЕСТЬ
                        # живой реестр объявлений, поэтому новая строка здесь —
                        # предмет утверждения, а не способ погасить падение.
                        # Конституция приведена к канонической форме тем же
                        # пушем; сверх привязки цикл сделал ЗАМЕРОМ саму
                        # претензию прибора о линейности целевой функции — до
                        # него она была напечатанной строкой.
                        "Marginal return":
                            ["marginal_return_size_changes_expected_yield"],
                        # ADR-512: ПЯТАЯ и последняя привязка цены TRANSCRIPTION,
                        # тем же порядком и по той же причине — предикат этого
                        # теста И ЕСТЬ живой реестр объявлений (см. его имя), и
                        # новая строка здесь предмет утверждения, а не способ
                        # погасить падение (инв. #16: правка намеренна, причина
                        # названа здесь и записана в журнал цикла).
                        "Pre-trade safety":
                            ["trade_is_rechecked_immediately_before_execution"],
                        # ADR-515: ТРЕТЬЯ и последняя привязка цены WORDING —
                        # тем же порядком и по той же причине. Правка снимка
                        # намеренна и обоснована (инв. #16): предикат этого
                        # теста И ЕСТЬ живой реестр объявлений, поэтому новая
                        # строка здесь — предмет утверждения, а не способ
                        # погасить падение. Конституция приведена к канонической
                        # форме тем же пушем; сверх привязки цикл СПЕРВА измерил
                        # покрытие решающей поверхности — до него зелёный ответ
                        # прибора был утверждением о населении из двух
                        # субъектов, не сверенном ни с одной книгой.
                        "Determinism":
                            ["determinism_recomputation_is_reproducible"],
                        "No regression": ["no_regression_tests_pass"],
                        "Owner visibility": ["owner_visibility_numbers_delivered"]}


def test_every_declared_criterion_exists_in_the_live_order():
    """Объявление, указывающее МИМО §49 живого приказа, — дефект объявления."""
    path = os.path.join(_REPO, CARD_REL)
    if not os.path.isfile(path):
        pytest.fail(f"карточка приказа {CARD_REL} отсутствует — сверить объявления "
                    f"НЕ С ЧЕМ; это не «чисто»")
    names = set(rollup.parse_s49_criteria(open(path, encoding="utf-8").read()))
    stray = sorted(set(probes_by_s49_criterion()) - names)
    assert not stray, f"объявлены критерии, которых в §49 нет: {stray}"


def test_a_probe_losing_its_registration_loses_its_declaration(monkeypatch):
    """Обход идёт по РЕЕСТРУ: мёртвая ссылка не имеет права числиться мерой."""
    trimmed = {k: v for k, v in PROBES.items()
               if k != "portfolio_decision_owner_covers_capital"}
    monkeypatch.setattr("spa_core.monitoring.card_acceptance.PROBES", trimmed)
    assert "Architecture" not in probes_by_s49_criterion()


def test_declaration_values_that_are_not_names_are_ignored(monkeypatch):
    def fake(arg):  # pragma: no cover — тело не исполняется
        return SATISFIED, ""
    fake.s49_criterion = "   "
    monkeypatch.setattr("spa_core.monitoring.card_acceptance.PROBES",
                        dict(PROBES, fake=fake))
    assert "   " not in probes_by_s49_criterion()
    assert "" not in probes_by_s49_criterion()


# --------------------------------------------------------------------------
# 7. Проводка `run_probe`: чужое дерево доходит ТОЛЬКО до объявивших его
# --------------------------------------------------------------------------

def test_run_probe_passes_a_tree_only_to_probes_that_declared_it(monkeypatch):
    seen: list = []

    def taking_both(arg, *, repo_root=None, data_dir=None):
        seen.append(("both", repo_root, data_dir))
        return SATISFIED, "ок"

    def taking_none(arg):
        seen.append(("none",))
        return SATISFIED, "ок"

    monkeypatch.setattr("spa_core.monitoring.card_acceptance.PROBES",
                        {"both": taking_both, "none": taking_none})
    run_probe("both", repo_root="/r", data_dir="/d")
    run_probe("none", repo_root="/r", data_dir="/d")
    assert seen == [("both", "/r", "/d"), ("none",)]


def test_probe_tree_inputs_reports_the_truth_for_the_real_registry():
    assert probe_tree_inputs("portfolio_decision_owner_covers_capital") == (
        "repo_root", "data_dir")
    assert probe_tree_inputs("no_regression_tests_pass") == ("repo_root",)
    assert probe_tree_inputs("нет такой пробы") == ()


def test_run_probe_stays_fail_closed_when_a_probe_explodes(monkeypatch):
    def boom(arg, *, repo_root=None):
        raise RuntimeError("дверь заклинило")

    monkeypatch.setattr("spa_core.monitoring.card_acceptance.PROBES", {"boom": boom})
    verdict, detail = run_probe("boom", repo_root="/r")
    assert verdict == UNMEASURED
    assert "дверь заклинило" in detail


# --------------------------------------------------------------------------
# 7. Цена «НЕ ИЗМЕРЕНО» (заказ G93 п. 1, ADR-506)
#
# Сводка ADR-505 печатала десять одинаковых `НЕ ИЗМЕРЕНО`, и читались они как
# десять одинаковых дыр. Это неверно, и разница между ними и есть ответ: у одних
# артефакт уже живёт и объявлен — не хватает ОДНОГО поля; у других артефакта нет
# вовсе — не хватает РЕШЕНИЯ. Тесты ниже стерегут ровно эту неслитность плюс два
# свойства проводки: цена не смеет трогать вердикты и не смеет молчать.
# --------------------------------------------------------------------------

import datetime as _dt  # noqa: E402
import json as _json  # noqa: E402

from spa_core.monitoring import s49_criterion_price as _price  # noqa: E402
from spa_core.monitoring import s49_verdict_addressee as addressee_meter  # noqa: E402

# FROZEN-DATE-OK: injected-clock — якорь передаётся замеру входом (`now=_NOW`),
# а отметка артефакта выводится из него же; стенные часы здесь не спрашиваются.
_NOW = _dt.datetime(2026, 9, 29, 12, 0, tzinfo=_dt.timezone.utc)


def _with_constitution(root: str, *, notes: str | None, artifact_age_h=None):
    """Дописать сцене конституцию и (по желанию) живой артефакт."""
    manifest_dir = os.path.join(root, os.path.dirname(_price.MANIFEST_REL))
    os.makedirs(manifest_dir, exist_ok=True)
    entry = {"path": "data/econ_census.json", "producer": "com.spa.x",
             "consumers": ["orchestrator_protocol"], "slo_hours": 12,
             "status": "active"}
    if notes is not None:
        entry["notes"] = notes
    with open(os.path.join(root, _price.MANIFEST_REL), "w", encoding="utf-8") as fh:
        _json.dump({"artifacts": [entry]}, fh)
    data_dir = os.path.join(root, "data")
    os.makedirs(data_dir, exist_ok=True)
    if artifact_age_h is not None:
        stamp = (_NOW - _dt.timedelta(hours=artifact_age_h)).isoformat()
        with open(os.path.join(data_dir, "econ_census.json"), "w",
                  encoding="utf-8") as fh:
            _json.dump({"generated_at": stamp}, fh)
    return data_dir


def _row(report, criterion):
    return next(r for r in report["rows"] if r["criterion"] == criterion)


def _no_declarations(monkeypatch):
    """Сцена цены обязана САМА решать, у кого мерки нет.

    Цена отвечает на вопрос «чего не хватает, чтобы мерка появилась», и осмыслен он
    ровно у критерия БЕЗ пробы. Взять этот отбор из ЖИВОГО реестра значило бы
    сделать предпосылку сцены фактом окружения: цикл #725 объявил пробу мерой
    `Economics`, и пять сцен разом перестали мерить то, о чём написаны, — по
    причине, к их предмету не относящейся. Ровно тот класс, что у календаря, у
    номера процесса и у git-окружения (`.claude/rules/deployment.md`): предпосылка
    обязана быть ВХОДОМ. Обратная сторона закреплена отдельно —
    `test_a_criterion_that_HAS_a_probe_is_not_priced`.
    """
    monkeypatch.setattr(rollup, "probes_by_s49_criterion", lambda: {})


def test_a_criterion_without_a_probe_gets_a_named_price(tmp_path, monkeypatch):
    _no_declarations(monkeypatch)
    root = _scene(tmp_path)
    data_dir = _with_constitution(root, notes="Критерий §49 `Economics` приказа",
                                  artifact_age_h=1.0)
    report = rollup.measure(root, ref=BRANCH, data_dir=data_dir, measure_tree=root,
                            probe_runner=_fixed(SATISFIED), now=_NOW)
    price = _row(report, "Economics")["price"]
    assert price["price"] == _price.TRANSCRIPTION
    assert price["artifact"] == "data/econ_census.json"


def test_a_stale_artifact_turns_the_price_into_the_producers(tmp_path, monkeypatch):
    """Артефакт, которого нет в такте, не дешевеет оттого, что он объявлен."""
    _no_declarations(monkeypatch)
    root = _scene(tmp_path)
    data_dir = _with_constitution(root, notes="Критерий §49 `Economics` приказа",
                                  artifact_age_h=99.0)
    report = rollup.measure(root, ref=BRANCH, data_dir=data_dir, measure_tree=root,
                            probe_runner=_fixed(SATISFIED), now=_NOW)
    assert _row(report, "Economics")["price"]["price"] == _price.PRODUCER


def test_a_criterion_nobody_bound_costs_a_decision(tmp_path, monkeypatch):
    _no_declarations(monkeypatch)
    root = _scene(tmp_path)
    data_dir = _with_constitution(root, notes="заметка без ссылки на раздел",
                                  artifact_age_h=1.0)
    report = rollup.measure(root, ref=BRANCH, data_dir=data_dir, measure_tree=root,
                            probe_runner=_fixed(SATISFIED), now=_NOW)
    assert _row(report, "Economics")["price"]["price"] == _price.DECISION


def test_a_criterion_that_HAS_a_probe_is_not_priced(tmp_path, monkeypatch):
    """Цена отвечает «чего не хватает, чтобы мерка появилась» — у критерия с
    пробой этот вопрос не стои́т, и его причина уже названа своей строкой.
    Приписать ему цену привязки значило бы ответить не на тот вопрос.
    """
    root = _scene(tmp_path)
    data_dir = _with_constitution(root, notes="Критерий §49 `Economics` приказа",
                                  artifact_age_h=1.0)
    monkeypatch.setattr(rollup, "probes_by_s49_criterion",
                        lambda: {"Economics": ["какая-то_проба"]})
    monkeypatch.setattr(rollup, "probe_tree_inputs", lambda spec: ["repo_root"])
    report = rollup.measure(root, ref=BRANCH, data_dir=data_dir, measure_tree=root,
                            probe_runner=_fixed(UNMEASURED), now=_NOW)
    row = _row(report, "Economics")
    assert row["verdict"] == UNMEASURED
    assert row.get("price") is None
    assert row.get("priceable") is not True
    # И в СЧЁТЕ его тоже быть не должно: цена, посчитанная и не показанная,
    # всё равно попадает в итоговую строку и завышает её.
    assert sum(report["price_counts"].values()) == 2  # Architecture, No regression


def test_an_unreadable_constitution_says_so_and_leaves_verdicts_alone(tmp_path, monkeypatch):
    """Цены нет ⇒ строка об этом ОБЯЗАНА быть: пустой столбец читается как ноль.

    И обратная сторона: отказ ЦЕНЫ не смеет трогать вердикты — они сняты другим
    прибором и остаются верны.
    """
    _no_declarations(monkeypatch)
    bare = _scene(tmp_path)
    blind = rollup.measure(bare, ref=BRANCH, measure_tree=bare,
                           probe_runner=_fixed(SATISFIED), now=_NOW)
    assert blind["price_problem"] and "manifest" in blind["price_problem"]
    assert blind["price_counts"] is None

    # Обратная сторона: та же сцена С конституцией. Вердикты обязаны совпасть
    # до последнего — иначе цена влияет на приёмку, а она не вправе.
    seeing = _scene(tmp_path / "second", )
    _with_constitution(seeing, notes="Критерий §49 `Economics` приказа",
                       artifact_age_h=1.0)
    lit = rollup.measure(seeing, ref=BRANCH, measure_tree=seeing,
                         probe_runner=_fixed(SATISFIED), now=_NOW)
    assert lit["price_problem"] is None and lit["price_counts"]
    assert blind["counts"] == lit["counts"]
    assert ([(r["criterion"], r["verdict"]) for r in blind["rows"]]
            == [(r["criterion"], r["verdict"]) for r in lit["rows"]])


def test_the_price_problem_reaches_the_printout(tmp_path, capsys):
    root = _scene(tmp_path)
    rollup.main(["--repo-root", root, "--ref", BRANCH, "--measure-tree", root])
    assert "ЦЕНА НЕ НАЗВАНА НИ У ОДНОГО" in capsys.readouterr().out


def test_the_price_is_measured_about_the_measured_tree_not_the_card_tree(tmp_path, monkeypatch):
    """Сводка про одно дерево с ценой про другое — два ответа под одним заголовком.

    Деревья здесь РАЗНЫЕ намеренно: карточка живёт в одном, конституция и живые
    артефакты — в другом. Совпадающие деревья сделали бы этот контроль зелёным
    по построению (урок ADR-504), и подмена `measure_tree` на `repo_root`
    прошла бы незамеченной.
    """
    _no_declarations(monkeypatch)
    card_tree = _scene(tmp_path)
    measured = str(tmp_path / "measured")
    os.makedirs(measured)
    data_dir = _with_constitution(measured,
                                  notes="Критерий §49 `Economics` приказа",
                                  artifact_age_h=1.0)
    report = rollup.measure(card_tree, ref=BRANCH, measure_tree=measured, now=_NOW,
                            probe_runner=_fixed(SATISFIED))
    assert report["price_tree"] == measured
    assert report["price_data_dir"] == data_dir
    assert _row(report, "Economics")["price"]["price"] == _price.TRANSCRIPTION


def test_an_orphan_binding_reaches_the_report_and_the_printout(tmp_path, capsys):
    root = _scene(tmp_path)
    _with_constitution(root, notes="Критерий §49 `Forecast accuracy` приказа",
                       artifact_age_h=1.0)
    rollup.main(["--repo-root", root, "--ref", BRANCH, "--measure-tree", root])
    out = capsys.readouterr().out
    assert "привязка МИМО населения" in out and "Forecast accuracy" in out


def test_an_unparsed_mention_reaches_the_printout(tmp_path, capsys):
    root = _scene(tmp_path)
    _with_constitution(root, notes="см. §49 приказа где-то там", artifact_age_h=1.0)
    rollup.main(["--repo-root", root, "--ref", BRANCH, "--measure-tree", root])
    assert "НЕРАЗОБРАННОЙ формой" in capsys.readouterr().out


def test_the_price_never_changes_the_exit_code(tmp_path):
    """Цена — ответ о том, ЧЕГО не хватает; вердикт о приказе выносит не она."""
    root = _scene(tmp_path)
    _with_constitution(root, notes="Критерий §49 `Economics` приказа",
                       artifact_age_h=1.0)
    assert rollup.main(["--repo-root", root, "--ref", BRANCH,
                        "--measure-tree", root]) == 1


# --------------------------------------------------------------------------
# 7a. `tree_inputs_reached` выводится ИЗ ПЕРЕДАННОГО, а не из второй копии мерки
#     (заказ G92 п. 1, ADR-542)
#
# Класс: отчёт о достижимости считался ВТОРЫМ выражением, знавшим ровно два
# имени входа («`repo_root` — дерево, иначе — данные»). Третий вход реестра
# (`tracker_dir`) эта ветка объявила бы дошедшим, НЕ передав его: условие
# `data_dir or measure_tree` истинно всегда, когда мы в этой ветке. Поле
# существует ровно затем, чтобы не врать о достижимости (ADR-220: две копии
# одной мерки расходятся молча).
# --------------------------------------------------------------------------

def test_a_probe_declaring_the_tracker_dir_actually_receives_it(tmp_path,
                                                                monkeypatch):
    seen: dict = {}

    def runner(spec, **kw):
        seen.update(kw)
        return SATISFIED, "ок"

    monkeypatch.setattr(rollup, "probes_by_s49_criterion",
                        lambda: {"Architecture": ["p1"]})
    monkeypatch.setattr(rollup, "probe_tree_inputs",
                        lambda name: ("repo_root", "tracker_dir"))
    report = rollup.measure(_scene(tmp_path), ref=BRANCH, measure_tree="/somewhere",
                            probe_runner=runner)
    assert seen == {"repo_root": "/somewhere",
                    "tracker_dir": os.path.join("/somewhere", rollup.TRACKER_REL)}
    row = next(r for r in report["rows"] if r["criterion"] == "Architecture")
    assert row["tree_inputs_reached"] == ["repo_root", "tracker_dir"]


def test_reach_never_names_an_input_that_was_not_passed(tmp_path, monkeypatch):
    """Положительный контроль аварии: отчёт не вправе обогнать передачу.

    `--data-dir` без `--measure-tree`: `tracker_dir` вывести НЕ из чего, и
    достижимым он называться не смеет. Вторая копия мерки назвала бы его дошедшим
    (её `else`-ветка отдавала `data_dir or measure_tree`), не передав ничего.
    """
    seen: dict = {}

    def runner(spec, **kw):
        seen.update(kw)
        return SATISFIED, "ок"

    monkeypatch.setattr(rollup, "probes_by_s49_criterion",
                        lambda: {"Architecture": ["p1"]})
    monkeypatch.setattr(rollup, "probe_tree_inputs",
                        lambda name: ("repo_root", "tracker_dir"))
    report = rollup.measure(_scene(tmp_path), ref=BRANCH, data_dir="/d",
                            probe_runner=runner)
    assert seen == {"repo_root": None, "tracker_dir": None}
    row = next(r for r in report["rows"] if r["criterion"] == "Architecture")
    assert row["tree_inputs_reached"] == []


def test_an_input_outside_the_registry_is_never_offered(tmp_path, monkeypatch):
    """Обратная сторона: предлагается только объявленное реестром.

    Без этой пары «предлагаем всё, что знаем» было бы неотличимо от «предлагаем
    объявленное», и проба упала бы по сигнатуре — то есть `unmeasured` вместо
    вердикта, молча.
    """
    seen: dict = {}

    def runner(spec, **kw):
        seen.update(kw)
        return SATISFIED, "ок"

    monkeypatch.setattr(rollup, "probes_by_s49_criterion",
                        lambda: {"Architecture": ["p1"]})
    monkeypatch.setattr(rollup, "probe_tree_inputs", lambda name: ("data_dir",))
    rollup.measure(_scene(tmp_path), ref=BRANCH, measure_tree="/somewhere",
                   probe_runner=runner)
    assert seen == {"data_dir": os.path.join("/somewhere", "data")}


# --------------------------------------------------------------------------
# 7. АДРЕСАТ вердикта (заказ G95 п. 3): «НЕ ВЫПОЛНЕН» обязан называть, за кем
#    починка. Девять отказов без адресата читались как девять долгов агента,
#    хотя `Economics` лежал вопросом владельцу с 27.09 (замер 2026-10-04).
#    Сам прибор и его пять исходов — `test_s49_verdict_addressee.py`; здесь
#    закрепляется ПРОВОДКА: что он позван, чем он позван и что его отказ не
#    уносит с собой вердикты.
#
#    Сцена уже несёт непустую очередь: карточка приказа лежит в том же каталоге
#    `nimbalyst-local/tracker/`, поэтому прибор здесь не отказывает, а честно
#    отвечает `NONE` у всех трёх — дословно состояние, которое заказ и называет.
# --------------------------------------------------------------------------

def _with_queue(root: str, cards: dict[str, str]) -> None:
    """Положить карточки в очередь сцены и ЗАКОММИТИТЬ их (очередь живёт на ref)."""
    tracker = os.path.join(root, rollup.TRACKER_REL)
    os.makedirs(tracker, exist_ok=True)
    for card_id, text in cards.items():
        with open(os.path.join(tracker, f"{card_id}.md"), "w", encoding="utf-8") as fh:
            fh.write(text)
    subprocess.run(["git", "add", "-A"], cwd=root, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "queue"], cwd=root, check=True,
                   capture_output=True)


def _owner_card(declares: str | None, status: str = "needs-owner",
                ctype: str = "owner-decision") -> str:
    head = (f"---\ntrackerStatus:\n  type: {ctype}\ntitle: \"вопрос\"\n"
            f"status: {status}\n")
    if declares is not None:
        head += f"{addressee_meter.FIELD}: {declares}\n"
    return head + "---\n\n## Что случилось и почему это важно\n\nтело\n"


def test_the_scene_queue_starts_with_nobody_addressed(tmp_path, monkeypatch):
    """Предпосылка сцены — ЗАМЕР: без неё «адресат появился» не с чем сравнить."""
    monkeypatch.setattr(rollup, "probes_by_s49_criterion", lambda: {"Economics": ["p1"]})
    report = rollup.measure(_scene(tmp_path), ref=BRANCH,
                            probe_runner=_fixed(NOT_SATISFIED, "отказ"))
    assert report["addressee_counts"][addressee_meter.NONE] == 3
    assert report["addressee_counts"][addressee_meter.OWNER_OPEN] == 0


def test_the_addressee_of_each_row_is_named_from_the_queue(tmp_path, monkeypatch):
    monkeypatch.setattr(rollup, "probes_by_s49_criterion",
                        lambda: {"Economics": ["p1"], "Architecture": ["p2"]})
    root = _scene(tmp_path)
    _with_queue(root, {"own-economics": _owner_card("Economics"),
                       "own-silent": _owner_card(None)})
    report = rollup.measure(root, ref=BRANCH,
                            probe_runner=_fixed(NOT_SATISFIED, "отказ"))
    assert _row(report, "Economics")["addressee"]["kind"] == addressee_meter.OWNER_OPEN
    assert [c["card"] for c in _row(report, "Economics")["addressee"]["cards"]] \
        == ["own-economics"]
    # Обратная сторона: критерий, которого карточка не объявляла, адресата НЕ
    # получает — иначе «адресат назван» было бы свойством наличия очереди.
    assert _row(report, "Architecture")["addressee"]["kind"] == addressee_meter.NONE


def test_the_answer_counts_only_refusals_and_only_unaddressed_ones(tmp_path,
                                                                   monkeypatch):
    """Ответ заказа — число, и оно считается по `not_satisfied`, а не по населению."""
    monkeypatch.setattr(rollup, "probes_by_s49_criterion",
                        lambda: {"Economics": ["p1"], "Architecture": ["p2"],
                                 "No regression": ["p3"]})
    root = _scene(tmp_path)
    _with_queue(root, {"own-economics": _owner_card("Economics")})

    def runner(spec, **kw):
        # `No regression` ВЫПОЛНЕН и адресата не имеет — в ответ попасть не
        # должен: вопрос заказа про отказы, и смешать это значило бы назвать
        # долгом пройденный критерий.
        return (SATISFIED, "ок") if spec == "p3" else (NOT_SATISFIED, "отказ")

    report = rollup.measure(root, ref=BRANCH, probe_runner=runner)
    assert report["unaddressed_not_satisfied"] == ["Architecture"]
    assert report["counts"][NOT_SATISFIED] == 2
    assert report["addressee_counts"][addressee_meter.OWNER_OPEN] == 1


def test_a_closed_card_does_not_count_as_an_addressee_in_the_rollup(tmp_path,
                                                                    monkeypatch):
    monkeypatch.setattr(rollup, "probes_by_s49_criterion", lambda: {"Economics": ["p1"]})
    root = _scene(tmp_path)
    _with_queue(root, {"own-economics": _owner_card("Economics", status="ingested")})
    report = rollup.measure(root, ref=BRANCH,
                            probe_runner=_fixed(NOT_SATISFIED, "отказ"))
    assert _row(report, "Economics")["addressee"]["kind"] == addressee_meter.OWNER_CLOSED
    # Закрытая карточка адресатом не является: ответ уже дан, и «НЕ ВЫПОЛНЕН»
    # рядом с ним — отдельная находка, а не ожидание владельца.
    assert "Economics" in report["unaddressed_not_satisfied"]


def test_a_refused_addressee_says_so_and_leaves_verdicts_alone(tmp_path, monkeypatch):
    """Отказ адресата гасит СТОЛБЕЦ, а не сводку — и обязан быть НАЗВАН.

    Положительный контроль подмены «не измерено» ответом: без строки отчёта
    отсутствующий столбец читается как «адресата ни у кого нет», а это другой
    ответ, и чинится он другим. Отказ подаётся подменой прибора, а не калечением
    сцены: ЧЕМ именно очередь бывает непрочитана — предмет его собственного
    набора (`test_s49_verdict_addressee.py`), здесь предмет — проводка.
    """
    monkeypatch.setattr(rollup, "probes_by_s49_criterion", lambda: {"Economics": ["p1"]})

    def refuse(*a, **kw):
        raise addressee_meter.Unmeasured("очередь не прочитана (контроль)")

    monkeypatch.setattr(addressee_meter, "measure", refuse)
    report = rollup.measure(_scene(tmp_path), ref=BRANCH,
                            probe_runner=_fixed(NOT_SATISFIED, "отказ"))
    assert "контроль" in (report["addressee_problem"] or "")
    assert report["addressee_counts"] is None
    assert report["unaddressed_not_satisfied"] is None
    assert _row(report, "Economics")["verdict"] == NOT_SATISFIED
    assert "addressee" not in _row(report, "Economics")


def test_the_queue_is_read_from_the_instrument_tree_not_from_measure_tree(
        tmp_path, monkeypatch):
    """`measure_tree` — субъект вердиктов, а не адрес очереди.

    Очередь живёт на ref и читается из дерева прибора. Если бы адрес очереди
    брался из `measure_tree`, сводка про прод-дерево читала бы ЕГО карточки —
    а они по построению отстают от origin (ADR-152), и названный адресат
    оказался бы адресатом другой очереди.
    """
    seen: dict = {}
    real = addressee_meter.measure

    def spy(criteria, **kw):
        seen.update(kw)
        return real(criteria, **kw)

    monkeypatch.setattr(rollup, "probes_by_s49_criterion", lambda: {"Economics": ["p1"]})
    monkeypatch.setattr(addressee_meter, "measure", spy)
    root = _scene(tmp_path)
    _with_queue(root, {"own-economics": _owner_card("Economics")})
    report = rollup.measure(root, ref=BRANCH, measure_tree=str(tmp_path / "elsewhere"),
                            probe_runner=_fixed(NOT_SATISFIED, "отказ"))
    assert seen["tracker_dir"] == os.path.join(root, rollup.TRACKER_REL)
    assert _row(report, "Economics")["addressee"]["kind"] == addressee_meter.OWNER_OPEN


def test_the_printed_report_names_the_addressee_and_the_answer(tmp_path, monkeypatch,
                                                               capsys):
    """Поле в отчёте, которого не видно в печати, читателю сводки не помогает."""
    monkeypatch.setattr(rollup, "probes_by_s49_criterion",
                        lambda: {"Economics": ["p1"], "Architecture": ["p2"]})
    root = _scene(tmp_path)
    _with_queue(root, {"own-economics": _owner_card("Economics")})
    monkeypatch.setattr(rollup, "run_probe", _fixed(NOT_SATISFIED, "отказ"))
    rollup.main(["--repo-root", root, "--ref", BRANCH])
    out = capsys.readouterr().out
    assert "own-economics" in out
    assert addressee_meter.OWNER_OPEN in out
    # Число ответа печатается И называет, КОГО не хватает.
    assert "ОТВЕТ G95 п. 3" in out and "Architecture" in out


def test_the_printed_report_names_an_undelivered_declaration(tmp_path, monkeypatch,
                                                             capsys):
    """Объявление, лежащее только в дереве, обязано быть НАЗВАНО недоставленным."""
    monkeypatch.setattr(rollup, "probes_by_s49_criterion", lambda: {"Economics": ["p1"]})
    root = _scene(tmp_path)
    tracker = os.path.join(root, rollup.TRACKER_REL)
    with open(os.path.join(tracker, "own-draft.md"), "w", encoding="utf-8") as fh:
        fh.write(_owner_card("Economics"))  # НЕ коммитим: на ref его нет
    monkeypatch.setattr(rollup, "run_probe", _fixed(NOT_SATISFIED, "отказ"))
    rollup.main(["--repo-root", root, "--ref", BRANCH])
    out = capsys.readouterr().out
    assert addressee_meter.TREE_ONLY in out
    # И в ответ заказа он НЕ попадает как названный адресат.
    assert "Economics" in out.split("ОТВЕТ G95 п. 3")[1]


# --------------------------------------------------------------------------
# Три состояния достижимости — ТРИ РАЗНЫЕ строки в печати, а не два
#
# Добавлено циклом #765. Строка `tag` в печати существовала без единого теста,
# и мутация `reach is None` → `reach is not None` ВЫЖИВАЛА на зелёной батарее
# из 80 тестов — мутант как раз и нашёлся тем, что остался на диске в дереве
# умершего цикла (ADR-555). Поля отчёта тремя исходами проверены выше; здесь
# проверяется, что до ЧИТАТЕЛЯ доходят все три, а «не измерено» не выдаётся за
# «измерено и пусто» (инв. #17) в самой печати.
# --------------------------------------------------------------------------

_REACHED = "дерево замера дошло входами"
_NOT_REACHED = "дерево замера НЕ дошло"


def test_the_printout_says_nothing_about_reach_when_no_tree_was_offered(
        tmp_path, monkeypatch, capsys):
    """Дерева не предлагали ⇒ о достижимости НЕ СКАЗАНО НИЧЕГО."""
    monkeypatch.setattr(rollup, "probes_by_s49_criterion", lambda: {"Economics": ["p1"]})
    monkeypatch.setattr(rollup, "probe_tree_inputs", lambda name: ("repo_root",))
    monkeypatch.setattr(rollup, "run_probe", _fixed(SATISFIED, "ок"))
    rollup.main(["--repo-root", _scene(tmp_path), "--ref", BRANCH])
    out = capsys.readouterr().out
    assert _REACHED not in out
    assert _NOT_REACHED not in out


def test_the_printout_says_the_tree_did_not_reach_a_probe_that_takes_nothing(
        tmp_path, monkeypatch, capsys):
    """Дерево предложили, проба входов не объявила ⇒ сказано «НЕ дошло»."""
    monkeypatch.setattr(rollup, "probes_by_s49_criterion", lambda: {"Economics": ["p1"]})
    monkeypatch.setattr(rollup, "probe_tree_inputs", lambda name: ())
    monkeypatch.setattr(rollup, "run_probe", _fixed(SATISFIED, "ок"))
    rollup.main(["--repo-root", _scene(tmp_path), "--ref", BRANCH,
                 "--measure-tree", str(tmp_path)])
    out = capsys.readouterr().out
    assert _NOT_REACHED in out
    assert _REACHED not in out


def test_the_printout_names_the_inputs_that_actually_reached_the_probe(
        tmp_path, monkeypatch, capsys):
    """Вход дошёл ⇒ он НАЗВАН по имени, а не подразумевается."""
    monkeypatch.setattr(rollup, "probes_by_s49_criterion", lambda: {"Economics": ["p1"]})
    monkeypatch.setattr(rollup, "probe_tree_inputs", lambda name: ("repo_root",))
    monkeypatch.setattr(rollup, "run_probe", _fixed(SATISFIED, "ок"))
    rollup.main(["--repo-root", _scene(tmp_path), "--ref", BRANCH,
                 "--measure-tree", str(tmp_path)])
    out = capsys.readouterr().out
    assert f"{_REACHED}: repo_root" in out
    assert _NOT_REACHED not in out


# --------------------------------------------------------------------------
# 8. ПЕЧАТЬ столбца адресата — пять ветвей, и каждая жила без контроля
#
# Добавлено циклом #765 по замеру мутаций: в проводке адресата выжило ПЯТЬ
# мутантов, и все пятеро — идиома запасного значения (`… or []`, `… or '?'`)
# в ПЕЧАТИ. Флип `or` → `and` там тих по построению: цикл просто не исполняется,
# предупреждение не печатается, sha подменяется вопросительным знаком — и ни
# один тест этого не замечал, потому что проверялось НАЛИЧИЕ сводки, а не то,
# что в ней сказано. Отчёт о наблюдении, которого не видно читателю, и есть
# «не измерено, выданное за ответ» (инв. #17).
# --------------------------------------------------------------------------

def test_the_printout_names_the_sha_of_the_queue_it_read(tmp_path, monkeypatch,
                                                         capsys):
    """«Сверено с очередью» без sha читалось бы как «сверено со свежайшей»."""
    monkeypatch.setattr(rollup, "probes_by_s49_criterion", lambda: {"Economics": ["p1"]})
    root = _scene(tmp_path)
    _with_queue(root, {"own-economics": _owner_card("Economics")})
    monkeypatch.setattr(rollup, "run_probe", _fixed(NOT_SATISFIED, "отказ"))
    sha = subprocess.run(["git", "rev-parse", BRANCH], cwd=root, check=True,
                         capture_output=True, text=True).stdout.strip()
    rollup.main(["--repo-root", root, "--ref", BRANCH])
    # Строка адресата, а не вывод целиком: sha той же очереди печатает и
    # сравнение копий выше, и «sha где-то есть» прошло бы при подменённом
    # столбце — проверять надо ТУ строку, которая про адресата (замер #765).
    line = next(l for l in capsys.readouterr().out.split("\n")
                if "адресат мерен по очереди" in l)
    assert sha[:9] in line


def test_the_printout_names_a_draft_declaration_standing_beside_a_named_addressee(
        tmp_path, monkeypatch, capsys):
    """Адресат назван на ref — недоставленный черновик всё равно печатается РЯДОМ."""
    monkeypatch.setattr(rollup, "probes_by_s49_criterion", lambda: {"Economics": ["p1"]})
    root = _scene(tmp_path)
    _with_queue(root, {"own-economics": _owner_card("Economics")})
    tracker = os.path.join(root, rollup.TRACKER_REL)
    with open(os.path.join(tracker, "own-draft.md"), "w", encoding="utf-8") as fh:
        fh.write(_owner_card("Economics"))  # НЕ коммитим: на ref его нет
    monkeypatch.setattr(rollup, "run_probe", _fixed(NOT_SATISFIED, "отказ"))
    rollup.main(["--repo-root", root, "--ref", BRANCH])
    out = capsys.readouterr().out
    assert addressee_meter.OWNER_OPEN in out
    assert "own-draft" in out and "только в рабочем дереве" in out


def test_the_printout_says_an_unknown_status_leaves_openness_unmeasured(
        tmp_path, monkeypatch, capsys):
    """Статус вне словарности ⇒ «открыт ли вопрос» НЕ ИЗМЕРЕНО, и это сказано."""
    monkeypatch.setattr(rollup, "probes_by_s49_criterion", lambda: {"Economics": ["p1"]})
    root = _scene(tmp_path)
    _with_queue(root, {"own-weird": _owner_card("Economics", status="полузакрыт")})
    monkeypatch.setattr(rollup, "run_probe", _fixed(NOT_SATISFIED, "отказ"))
    rollup.main(["--repo-root", root, "--ref", BRANCH])
    out = capsys.readouterr().out
    assert "вне объявленной словарности" in out and "НЕ ИЗМЕРЕНО" in out
    assert "own-weird" in out


def test_the_printout_names_a_declaration_past_the_population(tmp_path, monkeypatch,
                                                              capsys):
    """Объявление критерия, которого в §49 нет, — находка, а не тишина."""
    monkeypatch.setattr(rollup, "probes_by_s49_criterion", lambda: {"Economics": ["p1"]})
    root = _scene(tmp_path)
    _with_queue(root, {"own-ghost": _owner_card("Такого критерия нет")})
    monkeypatch.setattr(rollup, "run_probe", _fixed(NOT_SATISFIED, "отказ"))
    rollup.main(["--repo-root", root, "--ref", BRANCH])
    out = capsys.readouterr().out
    assert "МИМО населения" in out and "own-ghost" in out


def test_the_printout_names_a_queue_problem_instead_of_swallowing_it(
        tmp_path, monkeypatch, capsys):
    """Блочная форма объявления теряется разбором — и это печатается ВСЛУХ."""
    monkeypatch.setattr(rollup, "probes_by_s49_criterion", lambda: {"Economics": ["p1"]})
    root = _scene(tmp_path)
    block = ("---\ntrackerStatus:\n  type: owner-decision\ntitle: \"вопрос\"\n"
             f"status: needs-owner\n{addressee_meter.FIELD}:\n  - Economics\n"
             "---\n\n## Что случилось и почему это важно\n\nтело\n")
    _with_queue(root, {"own-block": block})
    monkeypatch.setattr(rollup, "run_probe", _fixed(NOT_SATISFIED, "отказ"))
    rollup.main(["--repo-root", root, "--ref", BRANCH])
    out = capsys.readouterr().out
    assert "очередь:" in out and "own-block" in out
