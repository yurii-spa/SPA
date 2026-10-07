"""Батарея АРТЕФАКТНОЙ оси переписи «предыдущий прогон» (заказ G104 п. 3, ADR-622).

Две оси-соседа считают ПАРЫ «читатель × свой же артефакт»: единица там — читатель, и
писателя спрашивают только у самокарусельных пар. Эта ось считает ФАЙЛЫ и спрашивает у
ПИСАТЕЛЯ: сколько git-tracked артефактов производится в рантайме, а обратно их не кладёт
никакая объявленная автоматика. Такой файл есть константа для любого своего читателя в
дереве, которое производителя не запускало — CI, свежий клон, новый worktree, резерв.

Авария, которую воспроизводят положительные контроли, — замер самого цикла #793:
обязательный шаг «вторая запись о деньгах» (`scripts/book_second_record.py`) из свежего
worktree доложил «7 ходов» и расхождение на T007, а на боевом дереве тем же кодом в тот
же день — «34 хода» и расхождение на T008/T034. Разным был операнд: в worktree журнал
денег есть закоммиченный канон.

Сцены НЕ переписываются — они импортируются из батареи главной оси: две копии сцены
расходятся молча, и батареи отвечали бы на разные вопросы, выглядя как одна проверка
(порядок ADR-460 — одно правило, один читатель).

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
    WORKFLOW_COMMITS_BACK,
    WORKFLOW_SILENT,
    _Scene,
)

C = census

#: Тот же читатель, но вторым артефактом он ПИШЕТ файл, которого не читает никто.
#: Нужен ровно для исхода «писателя нет, и читателя тоже нет»: без собственной сцены
#: исход проверялся бы населением главного дерева, то есть ничем.
SCENE_WRITES_AN_UNREAD_FILE = SCENE_ADR475.replace(
    "    _atomic_write(REPORT, report)",
    '''    _atomic_write(REPORT, report)
    _atomic_write(pathlib.Path("data") / "unread.json", {"rows": []})''',
)

#: Модуль-сосед, который артефакт только ЧИТАЕТ и никогда не пишет. Самокарусельной
#: парой он не является ⇒ двум осям-соседям он невидим, а этой оси обязан быть виден:
#: её единица — файл, а не пара.
NEIGHBOUR_READS_ONLY = '''
import json, pathlib
REPORT = pathlib.Path("data") / "guard_report.json"

def summarise():
    return json.loads(REPORT.read_text())
'''


#: Тот же читатель, но вторым артефактом он пишет файл, который читают ДВОЕ соседей.
#: Имя взято позже по алфавиту намеренно — см. тест про порядок печати.
SCENE_WRITES_A_POPULAR_FILE = SCENE_ADR475.replace(
    "    _atomic_write(REPORT, report)",
    '    _atomic_write(REPORT, report)\n'
    '    _atomic_write(pathlib.Path("data") / "zz.json", {"rows": []})',
)

NEIGHBOUR_READS_ZZ = NEIGHBOUR_READS_ONLY.replace("guard_report.json", "zz.json")

#: Тот же читатель, но его артефакт лежит ВНЕ `data/` — то есть вне радиуса дословной
#: команды аварии #361. Нужен ровно для того, чтобы число радиуса было ОТЛИЧИМО от числа
#: находок: в сцене по умолчанию они совпадают, и подмена условия радиуса на `True`
#: осталась бы невидимой (мутант `radius_counts_everything` её и пережил).
SCENE_OUTSIDE_THE_RADIUS = SCENE_ADR475.replace(
    'pathlib.Path("data") / "guard_report.json"', 'pathlib.Path("GUARD_REPORT.json")')


def _art(doc):
    return doc["artifact_axis"]


def _outcome_of(doc, path):
    """Исход, в который лёг именно ЭТОТ путь.

    Читается не по счётчику (счётчики совпадают у разных клеток), а по образцам плюс
    проверка, что сумма исходов равна населению: «имя не есть адрес» (ADR-465).
    """
    art = _art(doc)
    total = sum(art["outcomes"].values())
    if total != art["population"]:
        return f"form_refused:{total}!={art['population']}"
    for row in art["findings"]:
        if row["artifact"] == path:
            return C.ART_NO_WRITER_READ
    for row in art["declared"]:
        if row["artifact"] == path:
            return C.ART_WRITER_DECLARED
    name = pathlib.PurePosixPath(path).name
    for reason in art["unmeasured_reasons"]:
        if (reason.startswith("artifact_name_ambiguous_in_repo:")
                and reason.split(":")[1] == name):
            return C.ART_UNMEASURED
    return f"not_sampled:{path}"


# ──────────────────────────────────────────────────────────────────────────────
# Положительный контроль самой находки
# ──────────────────────────────────────────────────────────────────────────────

class AnArtifactWithoutADeclaredWriterIsFound(unittest.TestCase):
    """Файл производится в рантайме, его читают, обратно не кладёт никто."""

    def setUp(self):
        self.scene = _Scene(SCENE_ADR475)
        self.addCleanup(self.scene.close)
        self.doc = self.scene.measure()

    def test_the_artifact_is_named_in_the_axis(self):
        self.assertEqual(
            _outcome_of(self.doc, "data/guard_report.json"), C.ART_NO_WRITER_READ)

    def test_the_finding_names_its_writers_and_counts_its_readers(self):
        row = [r for r in _art(self.doc)["findings"]
               if r["artifact"] == "data/guard_report.json"][0]
        self.assertEqual(row["writers"], ["scripts/guard.py"])
        self.assertEqual(row["readers"], ["scripts/guard.py"])
        self.assertEqual(row["reader_count"], 1)

    def test_the_finding_under_the_accident_radius_is_its_own_number(self):
        self.assertEqual(_art(self.doc)["under_substitution_radius"], 1)

    def test_a_finding_OUTSIDE_the_radius_is_counted_as_a_finding_but_not_in_it(self):
        """Число радиуса обязано быть ОТЛИЧИМО от числа находок.

        `git checkout -- data/` — дословная команда аварии #361, и артефакт вне `data/`
        ею не подменяется (подменяется более широкой `git checkout -- .`, поэтому из
        населения не выкидывается). В сцене по умолчанию оба числа равны 1, и это
        делало подмену условия невидимой.
        """
        scene = _Scene(SCENE_OUTSIDE_THE_RADIUS,
                       track=("GUARD_REPORT.json", "data/snapshot.json"))
        self.addCleanup(scene.close)
        art = _art(scene.measure())
        self.assertEqual(art["outcomes"][C.ART_NO_WRITER_READ], 1)
        self.assertEqual([r["artifact"] for r in art["findings"]],
                         ["GUARD_REPORT.json"])
        self.assertEqual(art["under_substitution_radius"], 0)


class ADeclaredCommitterChangesTheOutcomeAndNothingElse(unittest.TestCase):
    """Контроль в ОБРАТНУЮ сторону: единственное отличие сцены — объявленный писатель."""

    def test_a_committing_workflow_moves_the_artifact_out_of_the_finding(self):
        scene = _Scene(SCENE_ADR475, workflow=WORKFLOW_COMMITS_BACK)
        self.addCleanup(scene.close)
        self.assertEqual(
            _outcome_of(scene.measure(), "data/guard_report.json"),
            C.ART_WRITER_DECLARED,
        )

    def test_without_the_commit_step_the_same_scene_is_a_finding(self):
        scene = _Scene(SCENE_ADR475, workflow=WORKFLOW_SILENT)
        self.addCleanup(scene.close)
        self.assertEqual(
            _outcome_of(scene.measure(), "data/guard_report.json"),
            C.ART_NO_WRITER_READ,
        )


# ──────────────────────────────────────────────────────────────────────────────
# Порядок ног: каждая нога несущая, и каждая исключает со СВОЕЙ причиной
# ──────────────────────────────────────────────────────────────────────────────

class ACuratedFileIsNotADefect(unittest.TestCase):
    """`data/snapshot.json` читают, но в рантайме не пишет никто — это не находка.

    Нога спрашивается ВТОРОЙ намеренно: без неё перепись объявила бы дефектом каждый
    курируемый конфиг репозитория, то есть утопила бы настоящую находку.
    """

    def test_a_file_nobody_writes_is_its_own_outcome(self):
        scene = _Scene(SCENE_ADR475)
        self.addCleanup(scene.close)
        art = _art(scene.measure())
        self.assertEqual(art["outcomes"][C.ART_NO_RUNTIME_WRITER], 1)
        self.assertNotIn("data/snapshot.json",
                         [r["artifact"] for r in art["findings"]])

    def test_the_curated_leg_is_load_bearing_not_decorative(self):
        """Снять ногу — и курируемый файл становится находкой. Проверяется ЗАМЕРОМ."""
        scene = _Scene(SCENE_ADR475)
        self.addCleanup(scene.close)
        art = _art(scene.measure())
        # Население ДВА пути, и они легли в РАЗНЫЕ исходы. Если бы нога не работала,
        # оба пути оказались бы в одном — именно так выглядела бы её потеря.
        self.assertEqual(art["population"], 2)
        self.assertEqual(art["outcomes"][C.ART_NO_WRITER_READ], 1)
        self.assertEqual(art["outcomes"][C.ART_NO_RUNTIME_WRITER], 1)


class AnUnreadArtifactIsLatentAndNotMergedIntoTheFinding(unittest.TestCase):
    """Писателя нет, но и читателя нет: вред латентен, исход свой."""

    def test_the_unread_artifact_has_its_own_outcome(self):
        scene = _Scene(
            SCENE_WRITES_AN_UNREAD_FILE,
            track=("data/guard_report.json", "data/snapshot.json", "data/unread.json"),
        )
        self.addCleanup(scene.close)
        art = _art(scene.measure())
        self.assertEqual(art["outcomes"][C.ART_NO_WRITER_UNREAD], 1)
        self.assertNotIn("data/unread.json",
                         [r["artifact"] for r in art["findings"]])

    def test_the_same_file_becomes_a_finding_once_somebody_reads_it(self):
        """Единственное отличие — появился читатель, и исход обязан отличаться."""
        reader = NEIGHBOUR_READS_ONLY.replace("guard_report.json", "unread.json")
        scene = _Scene(
            SCENE_WRITES_AN_UNREAD_FILE,
            track=("data/guard_report.json", "data/snapshot.json", "data/unread.json"),
            extra_files=(("scripts/neighbour.py", reader),),
        )
        self.addCleanup(scene.close)
        art = _art(scene.measure())
        self.assertEqual(art["outcomes"][C.ART_NO_WRITER_UNREAD], 0)
        self.assertIn("data/unread.json",
                      [r["artifact"] for r in art["findings"]])


class TheAxisJudgesTheWriterAndNotTheReader(unittest.TestCase):
    """Ось НЕ спрашивает «а заметил бы читатель» — это вопрос двух осей выше.

    Сцена `SCENE_AGE_NAMED` отличается от аварийной РОВНО тем, что читатель спрашивает
    возраст прошлого артефакта, и у главной оси исход от этого меняется. У артефактной —
    обязан НЕ меняться: писателя файлу это не добавляет.
    """

    def test_an_age_asking_reader_does_not_change_the_artifact_outcome(self):
        silent = _Scene(SCENE_ADR475)
        self.addCleanup(silent.close)
        named = _Scene(SCENE_AGE_NAMED)
        self.addCleanup(named.close)
        self.assertEqual(
            _outcome_of(silent.measure(), "data/guard_report.json"),
            _outcome_of(named.measure(), "data/guard_report.json"),
        )

    def test_the_main_axis_DOES_change_on_that_very_scene(self):
        """Контроль самого контроля: сцены действительно различимы — но ДРУГОЙ осью."""
        silent = _Scene(SCENE_ADR475)
        self.addCleanup(silent.close)
        named = _Scene(SCENE_AGE_NAMED)
        self.addCleanup(named.close)
        self.assertEqual(silent.measure()["outcomes"][C.OUT_CONST_TRUSTED], 1)
        self.assertEqual(named.measure()["outcomes"][C.OUT_CONST_NAMED], 1)


# ──────────────────────────────────────────────────────────────────────────────
# Единица населения — ПУТЬ, а не пара
# ──────────────────────────────────────────────────────────────────────────────

class TheUnitOfThePopulationIsTheFileNotThePair(unittest.TestCase):
    """Читатель, который артефакт НЕ пишет, двум осям-соседям невидим, этой — виден."""

    def setUp(self):
        self.scene = _Scene(
            SCENE_ADR475,
            extra_files=(("scripts/neighbour.py", NEIGHBOUR_READS_ONLY),),
        )
        self.addCleanup(self.scene.close)
        self.doc = self.scene.measure()

    def test_the_foreign_reader_is_counted_by_this_axis(self):
        row = [r for r in _art(self.doc)["findings"]
               if r["artifact"] == "data/guard_report.json"][0]
        self.assertIn("scripts/neighbour.py", row["readers"])
        self.assertEqual(row["reader_count"], 2)

    def test_the_foreign_reader_is_NOT_a_pair_of_the_neighbouring_axes(self):
        readers = {p for p in (
            r["reader"] for r in self.doc["findings"] + self.doc["named_sample"]
        )}
        self.assertNotIn("scripts/neighbour.py", readers)
        self.assertEqual(self.doc["population"], 1)

    def test_the_modules_handed_over_carry_the_full_read_set(self):
        """Четвёртое значение `_population` несущее: без него оси нечем считать читателей."""
        _pairs, _unparsed, _commits, modules = C._population(self.scene.root)
        by_rel = {m["rel"]: m for m in modules}
        self.assertIn("scripts/neighbour.py", by_rel)
        self.assertIn("guard_report.json", by_rel["scripts/neighbour.py"]["reads"])
        self.assertEqual(by_rel["scripts/neighbour.py"]["writes"], {})


class AnUntrackedArtifactIsOutsideThePopulation(unittest.TestCase):
    """Подменять нечем: файла в репозитории нет."""

    def test_an_untracked_artifact_is_not_in_the_axis(self):
        scene = _Scene(SCENE_ADR475, track=("data/snapshot.json",))
        self.addCleanup(scene.close)
        art = _art(scene.measure())
        self.assertEqual(art["population"], 1)
        self.assertEqual(art["outcomes"][C.ART_NO_WRITER_READ], 0)


# ──────────────────────────────────────────────────────────────────────────────
# Третий исход — ГРОМКИЙ, с названной причиной, и считается по ПУТЯМ
# ──────────────────────────────────────────────────────────────────────────────

class TheAmbiguousNameIsALoudThirdOutcome(unittest.TestCase):
    """Имя не есть адрес (ADR-465): какой из двух путей пишет модуль — неизвестно."""

    def setUp(self):
        self.scene = _Scene(
            SCENE_ADR475,
            track=("data/guard_report.json", "data/snapshot.json",
                   "landing/guard_report.json"),
        )
        self.addCleanup(self.scene.close)
        self.art = _art(self.scene.measure())

    def test_both_paths_of_one_name_are_unmeasured(self):
        self.assertEqual(self.art["outcomes"][C.ART_UNMEASURED], 2)

    def test_the_reason_is_named_and_not_merely_counted(self):
        self.assertEqual(
            sorted(self.art["unmeasured_reasons"]),
            ["artifact_name_ambiguous_in_repo:guard_report.json:2"],
        )

    def test_an_unmeasured_path_is_never_counted_as_a_finding(self):
        self.assertEqual(self.art["outcomes"][C.ART_NO_WRITER_READ], 0)

    def test_the_sum_still_equals_the_population_counted_in_paths(self):
        self.assertEqual(self.art["population"], 3)
        self.assertEqual(sum(self.art["outcomes"].values()), 3)


# ──────────────────────────────────────────────────────────────────────────────
# Форма ЗАКРЫТА, и с соседями не складывается
# ──────────────────────────────────────────────────────────────────────────────

class AnInjectedInputDoesNotBypassTheDoor(unittest.TestCase):
    """Перечень путей приходит ПАРАМЕТРОМ, и дверь чтения его не касается.

    `measure` отдаёт непустой перечень по построению (`_addressable` возвращает
    `kept or list(paths)`), поэтому проверка у двери на инъектированный вход не
    действует — ровно урок ADR-594. Раньше такой вход давал `IndexError`: прибор падал
    там, где обязан громко сказать «не измерено».
    """

    def test_a_name_without_an_address_is_a_loud_third_outcome(self):
        art = C._artifact_axis([], {"ghost.json": []}, {}, {}, {})
        self.assertEqual(art["population"], 1)
        self.assertEqual(art["outcomes"][C.ART_UNMEASURED], 1)
        self.assertEqual(sorted(art["unmeasured_reasons"]),
                         ["artifact_name_without_an_address:ghost.json"])
        self.assertEqual(art["notes"], [])
        self.assertEqual(sum(art["outcomes"].values()), art["population"])

    def test_the_unaddressed_name_is_never_a_finding(self):
        art = C._artifact_axis([], {"ghost.json": []}, {}, {}, {})
        self.assertEqual(art["outcomes"][C.ART_NO_WRITER_READ], 0)
        self.assertEqual(art["findings"], [])


class TheArtifactOutcomeFormIsClosed(unittest.TestCase):

    def setUp(self):
        self.scene = _Scene(SCENE_ADR475)
        self.addCleanup(self.scene.close)
        self.doc = self.scene.measure()

    def test_every_declared_outcome_is_present_even_at_zero(self):
        self.assertEqual(sorted(_art(self.doc)["outcomes"]),
                         sorted(C.ARTIFACT_OUTCOMES))

    def test_the_sum_equals_the_population(self):
        art = _art(self.doc)
        self.assertEqual(sum(art["outcomes"].values()), art["population"])
        self.assertEqual(art["notes"], [])

    def test_the_axis_does_not_enter_the_sums_of_its_neighbours(self):
        art = _art(self.doc)
        self.assertNotEqual(art["population"], self.doc["population"])
        self.assertEqual(sum(self.doc["outcomes"].values()), self.doc["population"])
        host = self.doc["host_axis"]
        self.assertEqual(sum(host["outcomes"].values()), host["population"])

    def test_the_three_outcome_vocabularies_do_not_collide(self):
        """Имя исхода одной оси не имеет права быть именем исхода другой."""
        self.assertFalse(set(C.OUTCOMES) & set(C.ARTIFACT_OUTCOMES))
        self.assertFalse(set(C.HOST_OUTCOMES) & set(C.ARTIFACT_OUTCOMES))

    def test_the_order_declared_is_the_order_of_the_legs(self):
        self.assertEqual(C.ARTIFACT_OUTCOMES[0], C.ART_UNMEASURED)
        self.assertEqual(C.ARTIFACT_OUTCOMES[1], C.ART_NO_RUNTIME_WRITER)
        self.assertEqual(C.ARTIFACT_OUTCOMES[-1], C.ART_NO_WRITER_READ)

    def test_the_axis_declares_its_own_order_number(self):
        self.assertEqual(_art(self.doc)["order"], "G104.3")


# ──────────────────────────────────────────────────────────────────────────────
# Код возврата: три РАЗЛИЧИМЫХ ответа
# ──────────────────────────────────────────────────────────────────────────────

class TheReturnCodeSeparatesThreeAnswers(unittest.TestCase):

    def setUp(self):
        self.scene = _Scene(SCENE_ADR475)
        self.addCleanup(self.scene.close)
        self.doc = self.scene.measure()

    def test_an_artifact_finding_alone_does_not_raise_the_code(self):
        """Лекарств у клетки три, и у дорогих — у владельца: красный навсегда учит гасить."""
        self.assertEqual(_art(self.doc)["outcomes"][C.ART_NO_WRITER_READ], 1)
        self.assertEqual(self.doc["outcomes"][C.OUT_CONST_TRUSTED], 1)
        # Код здесь 1 из-за ГЛАВНОЙ оси. Вклад артефактной проверяется отдельно ниже.
        self.assertEqual(C.verdict(self.doc), C.RC_FINDING)

    def test_an_artifact_finding_without_a_main_finding_keeps_the_code_at_zero(self):
        doc = dict(self.doc)
        doc["outcomes"] = dict(doc["outcomes"])
        doc["outcomes"][C.OUT_CONST_TRUSTED] = 0
        self.assertEqual(_art(doc)["outcomes"][C.ART_NO_WRITER_READ], 1)
        self.assertEqual(C.verdict(doc), C.RC_MEASURED)

    def test_the_ambiguous_name_raises_the_code_through_the_MAIN_axis(self):
        """Контроль разделения вкладов: двусмысленность видят ОБЕ оси, код поднимает главная.

        Без этого теста следующая проверка читалась бы как «артефактная ось код не
        поднимает», хотя на той же сцене код равен 2 — и причина была бы приписана не
        тому прибору.
        """
        scene = _Scene(
            SCENE_ADR475,
            track=("data/guard_report.json", "data/snapshot.json",
                   "landing/guard_report.json"),
        )
        self.addCleanup(scene.close)
        doc = scene.measure()
        self.assertEqual(doc["outcomes"][C.OUT_UNMEASURED], 1)
        self.assertEqual(_art(doc)["outcomes"][C.ART_UNMEASURED], 2)
        self.assertEqual(C.verdict(doc), C.RC_UNMEASURED)

    def test_an_unmeasured_path_of_the_artifact_axis_alone_does_not_raise_the_code(self):
        """Это свойство ДЕРЕВА (два файла одного имени), а не провал прибора.

        Вклад главной оси снят с дорожки намеренно: предмет проверки — политика
        `verdict` в отношении АРТЕФАКТНОЙ оси, и смешивать её с соседней нельзя.
        """
        scene = _Scene(
            SCENE_ADR475,
            track=("data/guard_report.json", "data/snapshot.json",
                   "landing/guard_report.json"),
        )
        self.addCleanup(scene.close)
        doc = scene.measure()
        doc = dict(doc, outcomes={**doc["outcomes"], C.OUT_UNMEASURED: 0,
                                  C.OUT_CONST_TRUSTED: 0})
        self.assertEqual(_art(doc)["outcomes"][C.ART_UNMEASURED], 2)
        self.assertTrue(_art(doc)["unmeasured_reasons"])
        self.assertEqual(C.verdict(doc), C.RC_MEASURED)

    def test_a_refused_artifact_form_DOES_raise_the_code(self):
        doc = dict(self.doc)
        doc["artifact_axis"] = dict(_art(self.doc), notes=["сумма != населению"])
        self.assertEqual(C.verdict(doc), C.RC_UNMEASURED)

    def test_a_document_without_the_axis_is_not_measured(self):
        doc = {k: v for k, v in self.doc.items() if k != "artifact_axis"}
        self.assertEqual(C.verdict(doc), C.RC_UNMEASURED)


# ──────────────────────────────────────────────────────────────────────────────
# Ось печатается там, где цикл её читает
# ──────────────────────────────────────────────────────────────────────────────

class TheAxisIsPrintedWhereTheCycleReadsIt(unittest.TestCase):

    def setUp(self):
        self.scene = _Scene(SCENE_ADR475)
        self.addCleanup(self.scene.close)
        self.doc = self.scene.measure()
        self.text = C.format_report(self.doc)

    def test_the_report_carries_the_axis_and_its_counters(self):
        self.assertIn("артефактная ось (заказ G104 п. 3)", self.text)
        for name in C.ARTIFACT_OUTCOMES:
            self.assertIn(name, self.text)

    def test_the_finding_is_printed_with_its_path(self):
        self.assertIn("data/guard_report.json", self.text)
        self.assertIn("ПИСАТЕЛЯ НЕ ОБЪЯВЛЕНО", self.text)

    def test_a_missing_axis_is_reported_as_unmeasured_not_omitted(self):
        doc = {k: v for k, v in self.doc.items() if k != "artifact_axis"}
        self.assertIn("[НЕ ИЗМЕРЕНО] артефактная ось", C.format_report(doc))

    def test_the_finding_list_is_sampled_and_the_remainder_is_a_number(self):
        rows = [{"artifact": f"data/a{i}.json", "writers": ["w.py"],
                 "readers": ["r.py"], "reader_count": 1}
                for i in range(C.ARTIFACT_SAMPLE + 3)]
        doc = dict(self.doc)
        doc["artifact_axis"] = dict(_art(self.doc), findings=rows,
                                    population=len(rows), outcomes={
                                        **_art(self.doc)["outcomes"],
                                        C.ART_NO_WRITER_READ: len(rows),
                                        C.ART_NO_RUNTIME_WRITER: 0,
                                    })
        text = C.format_report(doc)
        self.assertIn("… ещё 3 артефакт(ов)", text)
        self.assertNotIn("data/a12.json", text)

    def test_the_findings_are_ordered_by_the_number_of_readers(self):
        """Порядок печати — часть утверждения: дороже всего клетка с многими читателями.

        Печатается только образец, поэтому порядок решает, ВИДНА ли дорогая клетка
        вообще. Сортировка по имени поставила бы `data/a*.json` впереди клетки с 85
        читателями.
        """
        rows = [{"artifact": "data/zz_many.json", "writers": ["w.py"],
                 "readers": [f"r{i}.py" for i in range(9)], "reader_count": 9},
                {"artifact": "data/aa_one.json", "writers": ["w.py"],
                 "readers": ["r.py"], "reader_count": 1}]
        axis = C._artifact_axis([], {}, {}, {}, {})
        axis = dict(axis, findings=sorted(
            rows, key=lambda r: (-r["reader_count"], r["artifact"])))
        text = C.format_report(dict(self.doc, artifact_axis=axis))
        self.assertLess(text.index("data/zz_many.json"), text.index("data/aa_one.json"))

    def test_the_axis_itself_orders_what_it_returns(self):
        """Та же претензия, но к ПРИБОРУ, а не к печати: порядок приходит из оси.

        Сцена обязана нести РАЗЛИЧИМОСТЬ, а не только исход: имя дорогой клетки взято
        ПОЗЖЕ по алфавиту (`zz.json` против `guard_report.json`), иначе сортировка по
        имени дала бы тот же порядок и подмена ключа осталась бы невидимой.
        """
        scene = _Scene(
            SCENE_WRITES_A_POPULAR_FILE,
            track=("data/guard_report.json", "data/snapshot.json", "data/zz.json"),
            extra_files=(("scripts/peer_one.py", NEIGHBOUR_READS_ZZ),
                         ("scripts/peer_two.py", NEIGHBOUR_READS_ZZ)),
        )
        self.addCleanup(scene.close)
        findings = _art(scene.measure())["findings"]
        self.assertEqual([(r["artifact"], r["reader_count"]) for r in findings],
                         [("data/zz.json", 2), ("data/guard_report.json", 1)])

    def test_the_non_addable_warning_is_printed_and_not_merely_meant(self):
        self.assertIn("складыванию НЕ подлежит", self.text)

    def test_the_narrowness_of_the_axis_is_printed_in_the_report(self):
        """Известный член исхода, у которого расхождение покраснеет, НАЗВАН."""
        self.assertIn("architecture/manifest.json", self.text)
        self.assertIn("fill_agent_passports.py", self.text)


if __name__ == "__main__":
    unittest.main()
