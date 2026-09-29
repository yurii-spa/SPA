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
