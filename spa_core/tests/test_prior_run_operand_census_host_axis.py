"""Батарея ХОСТОВОЙ оси переписи «предыдущий прогон» (заказ G104 п. 2, ADR-621).

Главная ось (ADR-524, `test_prior_run_operand_census.py`) спрашивает про CI, где
прошлого прогона нет вовсе. Эта ось — про ту же пару на РАБОЧЕЙ машине, где файл на
диске есть результат прошлого прогона, ПОКА его не подменит закоммиченный канон.

Авария, которую воспроизводят положительные контроли, — цикл #361: `git checkout --
data/`, набранная для одноразового дерева и выполненная в боевом, откатила 116 файлов
на три недели (`.claude/rules/deployment.md` п. 4). Ни один сторож об этом не сказал.

Сцены НЕ переписываются: они импортируются из батареи главной оси. Две копии сцены
расходятся молча, и тогда батареи отвечали бы на разные вопросы, выглядя как одна
проверка (порядок ADR-460 — одно правило, один читатель).

Часов в приборе нет ВОВСЕ ⇒ литеральных дат в батарее нет по построению, `FROZEN-DATE-OK`
не нужен. Литеральных pid нет: прибор ни одного процесса не спрашивает.
"""

from __future__ import annotations

import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

from spa_core.monitoring import prior_run_operand_census as census  # noqa: E402
from spa_core.tests.test_prior_run_operand_census import (  # noqa: E402
    SCENE_ADR475,
    SCENE_AGE_NAMED,
    SCENE_PARITY,
    SCENE_VALIDATOR,
    WORKFLOW_CALLS_READER,
    WORKFLOW_SILENT,
    _Scene,
)

C = census

#: Воркфлоу, который КОММИТИТ артефакт обратно и при этом читателя НЕ зовёт. Без второго
#: условия сцена ушла бы в ГЛАВНУЮ ось (читатель достижим из CI), и исход хостовой оси
#: проверить было бы нечем.
WORKFLOW_COMMITS_BACK_WITHOUT_THE_READER = """
name: carry
on: [push]
jobs:
  carry:
    permissions:
      contents: write
    steps:
      - run: python3 scripts/other_tool.py
      - run: git commit -am "carry data/guard_report.json forward"
"""


def _host(doc):
    return doc["host_axis"]


def _only_nonzero(host):
    """Единственный ненулевой хостовый исход — плюс проверка, что сумма равна населению."""
    nonzero = [name for name, count in host["outcomes"].items() if count]
    total = sum(host["outcomes"].values())
    if total != host["population"]:
        return f"form_refused:{total}!={host['population']}"
    return nonzero[0] if len(nonzero) == 1 else f"ambiguous:{nonzero}"


# ──────────────────────────────────────────────────────────────────────────────
# Положительный контроль самой аварии #361
# ──────────────────────────────────────────────────────────────────────────────

class TheAccidentOfCycle361IsFoundSilentOnTheHost(unittest.TestCase):
    """Пара, которая молча примет канон за прошлый прогон, обязана находиться.

    Сцена — ДОСЛОВНАЯ форма аварии ADR-475 (решение о мире против живого наблюдения,
    возраст прошлого артефакта не спрашивается), но читателя не зовёт ни одна джоба.
    То есть на хосте он работает, в CI его нет — ровно население хостовой оси.
    """

    def test_the_silent_pair_is_named(self):
        scene = _Scene(SCENE_ADR475, workflow=WORKFLOW_SILENT)
        self.addCleanup(scene.close)
        host = _host(scene.measure())
        self.assertEqual(host["population"], 1, host)
        self.assertEqual(_only_nonzero(host), C.HOST_SILENTLY_TRUSTS, host)
        self.assertEqual(
            [row["reader"] for row in host["silent"]], ["scripts/guard.py"], host,
        )

    def test_the_same_pair_in_ci_belongs_to_the_other_axis_and_not_to_this_one(self):
        """Контроль в ОБРАТНУЮ сторону: одна буква сцены — джоба — и оси меняются.

        Без него «население 1» читалось бы как свойство прибора, а не как ответ на
        вопрос «кого эта ось вообще считает».
        """
        scene = _Scene(SCENE_ADR475, workflow=WORKFLOW_CALLS_READER)
        self.addCleanup(scene.close)
        doc = scene.measure()
        self.assertEqual(_host(doc)["population"], 0, doc)
        self.assertEqual(_host(doc)["outcomes"][C.HOST_SILENTLY_TRUSTS], 0, doc)
        self.assertEqual(doc["outcomes"][C.OUT_CONST_TRUSTED], 1, doc)


class AskingTheAgeIsMeasuredAndNotMerelyDeclared(unittest.TestCase):
    """Нога «спрошен ли возраст» обязана УМЕТЬ срабатывать на хостовой оси.

    Это положительный контроль измеренного НУЛЯ: живое дерево даёт
    ``host_notices_by_age = 0``, и без этого теста ноль был бы неотличим от мёртвой
    ноги, которая не срабатывает никогда (инв. #17 — «измерено и равно нулю» ≠ «не
    измерено»).
    """

    def test_the_age_asking_reader_changes_the_host_outcome(self):
        scene = _Scene(SCENE_AGE_NAMED, workflow=WORKFLOW_SILENT)
        self.addCleanup(scene.close)
        host = _host(scene.measure())
        self.assertEqual(host["population"], 1, host)
        self.assertEqual(_only_nonzero(host), C.HOST_NOTICES_BY_AGE, host)
        self.assertEqual(host["outcomes"][C.HOST_SILENTLY_TRUSTS], 0, host)


class TheParityIdiomNoticesTheSubstitutionByConstruction(unittest.TestCase):
    """Читатель, сверяющий закоммиченную копию с ПЕРЕСБОРКОЙ, подмену увидит."""

    def test_parity_is_its_own_host_outcome(self):
        scene = _Scene(SCENE_PARITY, workflow=WORKFLOW_SILENT)
        self.addCleanup(scene.close)
        host = _host(scene.measure())
        self.assertEqual(host["population"], 1, host)
        self.assertEqual(_only_nonzero(host), C.HOST_PARITY, host)
        self.assertEqual(
            [row["why"] for row in host["noticed_sample"]], [C.HOST_PARITY], host,
        )


class TheValidatorIsExcludedWithANamedReasonAndNotCountedAsSilent(unittest.TestCase):
    """Проверка документа решения о мире не принимает — исключается, а не вменяется."""

    def test_no_decision_is_an_excluded_outcome_with_a_reason(self):
        scene = _Scene(
            SCENE_VALIDATOR,
            workflow=WORKFLOW_SILENT,
            track=("board.json",),
        )
        self.addCleanup(scene.close)
        host = _host(scene.measure())
        self.assertEqual(host["population"], 1, host)
        self.assertEqual(_only_nonzero(host), C.HOST_NO_DECISION, host)
        self.assertEqual(
            [row["why"] for row in host["excluded_sample"]], [C.HOST_NO_DECISION], host,
        )
        self.assertEqual(host["silent"], [], host)


class ADeclaredWriterMakesTheCanonARecentRun(unittest.TestCase):
    """Если автоматика кладёт артефакт обратно, канон есть наблюдение на шаг старше."""

    def test_committed_back_is_not_a_silent_pair(self):
        scene = _Scene(
            SCENE_ADR475,
            workflow=WORKFLOW_COMMITS_BACK_WITHOUT_THE_READER,
        )
        self.addCleanup(scene.close)
        host = _host(scene.measure())
        self.assertEqual(host["population"], 1, host)
        self.assertEqual(_only_nonzero(host), C.HOST_CANON_IS_A_RECENT_RUN, host)

    def test_without_the_commit_step_the_same_scene_is_silent(self):
        """Контроль в обратную сторону: рвём ровно одно звено — шаг коммита."""
        scene = _Scene(
            SCENE_ADR475,
            workflow=WORKFLOW_COMMITS_BACK_WITHOUT_THE_READER.replace(
                '      - run: git commit -am "carry data/guard_report.json forward"\n',
                "",
            ),
        )
        self.addCleanup(scene.close)
        host = _host(scene.measure())
        self.assertEqual(_only_nonzero(host), C.HOST_SILENTLY_TRUSTS, host)


class AnUntrackedArtifactIsNotInTheHostPopulation(unittest.TestCase):
    """Подменять нечем: файла в репозитории нет, значит канона нет тоже."""

    def test_untracked_pair_is_outside_the_axis(self):
        scene = _Scene(SCENE_ADR475, workflow=WORKFLOW_SILENT, track=())
        self.addCleanup(scene.close)
        doc = scene.measure()
        self.assertEqual(_host(doc)["population"], 0, doc)
        # и это НЕ «чисто»: сам факт отсутствия остаётся виден главной осью
        self.assertEqual(doc["outcomes"][C.OUT_NOT_IN_CI], 1, doc)


# ──────────────────────────────────────────────────────────────────────────────
# Форма исхода и три различимых ответа
# ──────────────────────────────────────────────────────────────────────────────

class TheHostOutcomeFormIsClosed(unittest.TestCase):
    """Сумма равна населению, перечень исходов ЗАКРЫТ, каждый ноль объявлен."""

    def test_every_declared_outcome_is_present_even_at_zero(self):
        scene = _Scene(SCENE_ADR475, workflow=WORKFLOW_SILENT)
        self.addCleanup(scene.close)
        host = _host(scene.measure())
        self.assertEqual(tuple(host["outcomes"]), C.HOST_OUTCOMES, host)
        self.assertEqual(sum(host["outcomes"].values()), host["population"], host)

    def test_the_axis_does_not_enter_the_main_sum(self):
        """Две оси — две суммы. Слияние сделало бы оба числа непроверяемыми."""
        scene = _Scene(SCENE_ADR475, workflow=WORKFLOW_SILENT)
        self.addCleanup(scene.close)
        doc = scene.measure()
        self.assertEqual(sum(doc["outcomes"].values()), doc["population"], doc)
        self.assertNotIn(C.HOST_SILENTLY_TRUSTS, doc["outcomes"])
        self.assertEqual(doc["notes"], [], doc)

    def test_the_host_names_and_the_main_names_do_not_collide(self):
        self.assertEqual(set(C.HOST_OUTCOMES) & set(C.OUTCOMES), set())


class TheAmbiguousNameIsALoudThirdOutcome(unittest.TestCase):
    """Имя лежит по двум НЕ-фикстурным путям ⇒ адреса не знаем, и это сказано громко."""

    def test_two_real_paths_of_one_name_are_unmeasured_with_a_reason(self):
        scene = _Scene(
            SCENE_ADR475,
            workflow=WORKFLOW_SILENT,
            track=(
                "data/guard_report.json",
                "data/snapshot.json",
                "landing/src/data/guard_report.json",
            ),
        )
        self.addCleanup(scene.close)
        host = _host(scene.measure())
        self.assertEqual(host["outcomes"][C.HOST_UNMEASURED], 1, host)
        self.assertEqual(host["outcomes"][C.HOST_SILENTLY_TRUSTS], 0, host)
        reasons = list(host["unmeasured_reasons"])
        self.assertTrue(
            any(r.startswith("artifact_name_ambiguous_in_repo:") for r in reasons),
            reasons,
        )

    def test_a_fixture_is_not_a_second_address(self):
        """Замер 07.10: ТРИ пары были объявлены «не измерено» фикстурой.

        `tests/fixtures/golive_status.json` — вход теста, а не второй адрес
        `data/golive_status.json`. Без этого сужения прибор выдумывал неоднозначность,
        то есть выдавал «не измерено» там, где измерять было что.
        """
        scene = _Scene(
            SCENE_ADR475,
            workflow=WORKFLOW_SILENT,
            track=(
                "data/guard_report.json",
                "data/snapshot.json",
                "tests/fixtures/guard_report.json",
            ),
        )
        self.addCleanup(scene.close)
        host = _host(scene.measure())
        self.assertEqual(host["outcomes"][C.HOST_UNMEASURED], 0, host)
        self.assertEqual(_only_nonzero(host), C.HOST_SILENTLY_TRUSTS, host)

    def test_the_narrowing_never_turns_tracked_into_absent(self):
        """Если ВСЕ пути имени фикстурные, перечень остаётся исходным.

        Иначе «отслеживается» молча превратилось бы в «в CI отсутствует» — другой
        исход и другая беда (ADR-524 развёл их намеренно).
        """
        self.assertEqual(
            C._addressable(["tests/fixtures/a.json"]), ["tests/fixtures/a.json"],
        )
        self.assertEqual(
            C._addressable(["data/a.json", "tests/fixtures/a.json"]), ["data/a.json"],
        )


class TheReturnCodeSeparatesThreeAnswers(unittest.TestCase):
    """Код возврата: находка · измерено · НЕ ИЗМЕРЕНО — и хостовая ось в этом участвует."""

    def test_a_silent_host_pair_alone_does_not_raise_the_code(self):
        """РЕШЕНИЕ с названной причиной, а не недосмотр.

        На хосте файл на диске есть прошлый прогон; вред возникает только от команды,
        запрещённой правилом доставки. Красный навсегда приучил бы гасить прибор.
        """
        scene = _Scene(SCENE_ADR475, workflow=WORKFLOW_SILENT)
        self.addCleanup(scene.close)
        doc = scene.measure()
        self.assertEqual(_host(doc)["outcomes"][C.HOST_SILENTLY_TRUSTS], 1, doc)
        self.assertEqual(C.verdict(doc), C.RC_MEASURED, doc)

    def test_host_unmeasured_does_raise_the_code(self):
        doc = {
            "measured": True,
            "population": 0,
            "outcomes": {name: 0 for name in C.OUTCOMES},
            "notes": [],
            "host_axis": {
                "population": 1,
                "outcomes": dict(
                    {name: 0 for name in C.HOST_OUTCOMES},
                    **{C.HOST_UNMEASURED: 1},
                ),
                "notes": [],
            },
        }
        self.assertEqual(C.verdict(doc), C.RC_UNMEASURED)

    def test_a_refused_host_form_raises_the_code(self):
        doc = {
            "measured": True,
            "population": 0,
            "outcomes": {name: 0 for name in C.OUTCOMES},
            "notes": [],
            "host_axis": {
                "population": 7,
                "outcomes": {name: 0 for name in C.HOST_OUTCOMES},
                "notes": ["сумма хостовых исходов 0 != хостовому населению 7 — ОТКАЗ формы"],
            },
        }
        self.assertEqual(C.verdict(doc), C.RC_UNMEASURED)

    def test_a_document_without_the_axis_is_not_measured(self):
        """Молчание о целой оси обязано читаться как «не измерено», а не как «чисто»."""
        doc = {
            "measured": True,
            "population": 0,
            "outcomes": {name: 0 for name in C.OUTCOMES},
            "notes": [],
        }
        self.assertEqual(C.verdict(doc), C.RC_UNMEASURED)


# ──────────────────────────────────────────────────────────────────────────────
# Отчёт: число, которое никто не печатает, снимается молча
# ──────────────────────────────────────────────────────────────────────────────

class TheAxisIsPrintedWhereTheCycleReadsIt(unittest.TestCase):
    """Шаг 0-офис зовёт `format_report`; раздел, пропавший из него, невидим."""

    def test_the_report_carries_the_axis_and_its_counters(self):
        scene = _Scene(SCENE_ADR475, workflow=WORKFLOW_SILENT)
        self.addCleanup(scene.close)
        text = C.format_report(scene.measure())
        self.assertIn("хостовая ось", text)
        self.assertIn("G104", text)
        self.assertIn(C.HOST_SILENTLY_TRUSTS, text)
        self.assertIn("МОЛЧА ПРИМЕТ КАНОН", text)
        self.assertIn(C.CANON_SUBSTITUTION_RADIUS, text)

    def test_the_cost_of_the_no_decision_leg_is_printed_when_it_fires(self):
        """Самый населённый исход оси — исключающий. Его цена обязана быть названа."""
        scene = _Scene(
            SCENE_VALIDATOR, workflow=WORKFLOW_SILENT, track=("board.json",),
        )
        self.addCleanup(scene.close)
        text = C.format_report(scene.measure())
        self.assertIn("ЦЕНА ноги «решения нет»", text)
        self.assertIn("ПЕРЕПУБЛИКУЕТ", text)

    def test_a_missing_axis_is_reported_as_unmeasured_not_omitted(self):
        lines = C._host_lines({"measured": True})
        self.assertEqual(len(lines), 1, lines)
        self.assertIn("НЕ ИЗМЕРЕНО", lines[0])

    def test_the_silent_list_is_sampled_and_the_remainder_is_a_number(self):
        """Остаток называется ЧИСЛОМ, а не многоточием: иначе он исчезает из отчёта."""
        host = {
            "population": C.HOST_SILENT_SAMPLE + 3,
            "under_substitution_radius": 0,
            "outcomes": dict(
                {name: 0 for name in C.HOST_OUTCOMES},
                **{C.HOST_SILENTLY_TRUSTS: C.HOST_SILENT_SAMPLE + 3},
            ),
            "unmeasured_reasons": {},
            "silent": [
                {"reader": f"scripts/r{i}.py", "artifact": "a.json", "read_lines": [1]}
                for i in range(C.HOST_SILENT_SAMPLE + 3)
            ],
            "noticed_sample": [],
            "excluded_sample": [],
            "notes": [],
        }
        text = "\n".join(C._host_lines({"measured": True, "host_axis": host}))
        self.assertEqual(text.count("МОЛЧА ПРИМЕТ КАНОН"), C.HOST_SILENT_SAMPLE)
        self.assertIn("ещё 3 молчаливых", text)


# ──────────────────────────────────────────────────────────────────────────────
# Дефекты, найденные самим расширением
# ──────────────────────────────────────────────────────────────────────────────

class AnAnnotationWithoutAValueBindsNothing(unittest.TestCase):
    """Дефект, найденный хостовой осью: `x: int` ронял главную ногу `AttributeError`.

    Главная ось доходила до ноги на ЧЕТЫРЁХ парах из 586 и формы не видела; хостовая
    привела туда двести, и прибор упал на первой же аннотации без значения. Это
    положительный контроль РЕАЛЬНОГО падения, а не гипотезы.
    """

    SCENE = SCENE_ADR475.replace(
        "def run():",
        "pending_total: int\n\n\ndef run():",
    )

    def test_the_census_survives_an_annotation_without_a_value(self):
        scene = _Scene(self.SCENE, workflow=WORKFLOW_SILENT)
        self.addCleanup(scene.close)
        host = _host(scene.measure())
        self.assertEqual(_only_nonzero(host), C.HOST_SILENTLY_TRUSTS, host)

    def test_the_leg_itself_returns_empty_for_such_a_declaration(self):
        import ast
        tree = ast.parse("import json\nx: int\n")
        resolver = C._PathResolver(tree)
        self.assertEqual(C._read_bindings(tree, "a.json", resolver), set())


class TheReachRuleHasExactlyOneCopy(unittest.TestCase):
    """Достижимость из CI спрашивается ОДИН раз на читателя.

    Прежняя редакция звала `_reader_in_ci` дважды — в главном цикле и у хостовой
    цифры рядом. Две копии одного правила расходятся молча, и тогда «население
    хостовой оси» и «исход главной оси» отвечали бы о разных парах.
    """

    def test_the_host_population_equals_the_legacy_side_number(self):
        scene = _Scene(SCENE_ADR475, workflow=WORKFLOW_SILENT)
        self.addCleanup(scene.close)
        doc = scene.measure()
        self.assertEqual(
            doc["host_only_but_git_tracked"], _host(doc)["population"], doc,
        )

    def test_the_module_calls_the_reach_rule_exactly_once(self):
        import ast
        source = pathlib.Path(C.__file__).read_text(encoding="utf-8")
        calls = [
            node for node in ast.walk(ast.parse(source))
            if isinstance(node, ast.Call)
            and getattr(node.func, "id", None) == "_reader_in_ci"
        ]
        self.assertEqual(len(calls), 1, [c.lineno for c in calls])


class TheInstrumentStillOnlyReads(unittest.TestCase):
    """Расширение не завело ни одной записи и ни одного похода в сеть."""

    def test_applied_is_false_and_no_write_primitive_appeared(self):
        import ast
        self.assertFalse(C.APPLIED)
        source = pathlib.Path(C.__file__).read_text(encoding="utf-8")
        tree = ast.parse(source)
        forbidden = {"atomic_save", "write_text", "urlopen", "requests"}
        seen = {
            name for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            for name in [C._call_name(node)]
            if name in forbidden
        }
        self.assertEqual(seen, set(), seen)


if __name__ == "__main__":
    unittest.main()
