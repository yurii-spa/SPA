"""Поведенческий зонд отсутствующего входа (заказ G46 п. 1, ADR-424).

Контроль в обе стороны у каждой проверки, а положительный контроль — на
НАСТОЯЩЕМ контуре: git-репозиторий, три сторожа разного поведения, живой
pytest в одноразовом дереве. Сторож, который не краснеет ни на одной поломке,
украшение (`positive-control-can-be-an-ornament`).

Литеральных дат нет. Живое `data/` не читается и не пишется ни одной
проверкой: все сцены — в одноразовом каталоге.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from spa_core.monitoring import absent_path_probe as probe
from spa_core.monitoring import call_sourced_input_census as csi

REPO = Path(__file__).resolve().parents[2]


def _git(root: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=str(root), check=True,
                   capture_output=True, text=True, timeout=180)


class ARowWhoseGuardChangedInTheWorkingTree(unittest.TestCase):
    """«Не спрашивали» обязано быть ЗАПИСАНО, а не выведено из пустоты.

    Одноразовое дерево несёт HEAD, поэтому у сторожа, правленого в рабочем
    дереве, спрашивать нечего: ответ был бы о другом файле. Прежняя редакция
    оставляла такую строку вовсе без поля, и «не спрашивали» читалось так же,
    как «спросили и не разобрали».
    """

    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory()
        cls.root = Path(cls._tmp.name) / "repo"
        for rel in csi.GUARD_DIRS:
            (cls.root / rel).mkdir(parents=True, exist_ok=True)
        guard = cls.root / "spa_core" / "tests" / "test_blind_guard.py"
        guard.write_text(BLIND, encoding="utf-8")
        (cls.root / "area_blind").mkdir()
        (cls.root / "area_blind" / "a.txt").write_text("x", encoding="utf-8")
        _git(cls.root, "init", "-q")
        _git(cls.root, "add", "-A")
        _git(cls.root, "-c", "user.email=probe@spa", "-c", "user.name=probe",
             "commit", "-q", "-m", "scene")
        # правка ПОСЛЕ коммита — ровно то состояние, из-за которого строка и
        # снимается с опыта
        guard.write_text(BLIND + "\n# правка рабочего дерева\n", encoding="utf-8")
        cls.doc = probe.measure(cls.root)

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def test_the_row_is_unmeasured_and_its_own_test_is_NOT_ASKED(self):
        self.assertEqual(len(self.doc["entries"]), 1, self.doc["entries"])
        entry = self.doc["entries"][0]
        self.assertEqual(entry["verdict"], probe.VERDICT_UNMEASURED)
        self.assertEqual(entry["own_test"], probe.OWN_NOT_ASKED,
                         "вопрос не задавался — и это записано значением, а "
                         "не отсутствием поля")
        self.assertEqual(self.doc["own_test_counts"][probe.OWN_NOT_ASKED], 1)
        self.assertEqual(self.doc["own_test_counts"][probe.OWN_RAN], 0,
                         "удобное умолчание «бежал» и есть подмена «не "
                         "измерено» успехом")


MANY_CASES = '''
import pytest
from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]
AREA = ROOT / "area_many"

@pytest.mark.parametrize("case", [f"случай-{i:03d}-с-достаточно-длинным-именем"
                                  for i in range(120)])
def test_walks(case):
    for item in AREA.rglob("*.txt"):
        assert item.name and case
'''


class ACollectionTooLongForTheDefaultBudget(unittest.TestCase):
    """Обрезанный вывод — НЕ ответ «такого теста нет» (находка #643).

    Общая проводка прогонов хранит хвост в 2000 знаков. Сбор одного
    параметризованного теста даёт ВОСЕМЬДЕСЯТ ОДНУ строку, и на живом
    населении так пропал `test_declared_schema_matches_the_live_producer`:
    перечень обрезался, совпадений не находилось, и зонд отвечал «не тест»
    про тест, который в ту же минуту исправно бежал.
    """

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        (self.root / "spa_core" / "tests").mkdir(parents=True)
        (self.root / "area_many").mkdir()
        (self.root / "area_many" / "a.txt").write_text("x", encoding="utf-8")
        self.addCleanup(self._tmp.cleanup)

    def test_all_of_a_long_collection_is_read_not_its_tail(self):
        rel = "spa_core/tests/test_many_cases.py"
        (self.root / rel).write_text(MANY_CASES, encoding="utf-8")
        ids = probe.own_test_ids(self.root, rel, "test_walks")
        self.assertIsNotNone(ids, "сбор ответил — перечень обязан быть прочитан")
        self.assertEqual(len(ids), 120,
                         "перечень прочитан целиком, а не хвостом бюджета")
        self.assertGreater(sum(len(i) for i in ids), 2000,
                           "сцена обязана ПРЕВОСХОДИТЬ умолчание проводки, "
                           "иначе проверка верна по построению")
        self.assertEqual(probe.own_test_state(self.root, rel, "test_walks"),
                         probe.OWN_RAN)


class TheDeclaredCountGuardsTheParsedList(unittest.TestCase):
    """Число собранного объявляет сам pytest, и перечень обязан с ним сойтись."""

    def test_a_short_list_against_a_bigger_declared_count_is_unknown(self):
        out = ("g.py::test_a\n"
               "g.py::test_b\n"
               "\n5/9 tests collected (4 deselected) in 0.10s\n")
        self.assertIsNone(probe._collected_ids(out, "g.py"),
                          "перечень короче объявленного — вывод обрезан")

    def test_a_matching_list_is_returned(self):
        out = ("g.py::test_a\n"
               "g.py::test_b\n"
               "\n2/9 tests collected (7 deselected) in 0.10s\n")
        self.assertEqual(probe._collected_ids(out, "g.py"),
                         ["g.py::test_a", "g.py::test_b"])

    def test_no_tests_collected_is_an_empty_list_not_unknown(self):
        out = "\nno tests collected (9 deselected) in 0.10s\n"
        self.assertEqual(probe._collected_ids(out, "g.py"), [],
                         "«ничего не подошло» — ответ сбора, а не молчание")

    def test_an_output_without_the_summary_is_unknown(self):
        self.assertIsNone(probe._collected_ids("g.py::test_a\n", "g.py"),
                          "сводки нет ⇒ сверять не с чем ⇒ не измерено")

    def test_the_SAME_summary_with_an_error_is_unknown_not_empty(self):
        """Сбор, умерший ошибкой, печатает ту же сводку «no tests collected».

        Различает их только приписка «, 1 error» — и без неё поломка файла
        снимала бы строку с учёта под видом ответа «такого теста нет».
        """
        self.assertEqual(
            probe._collected_ids("\nno tests collected (9 deselected) in 0.1s\n",
                                 "g.py"), [])
        self.assertIsNone(
            probe._collected_ids("\nno tests collected, 1 error in 0.04s\n",
                                 "g.py"))


class AFileWhoseCollectionFAILS(unittest.TestCase):
    """Сбор не ответил — это третий исход, а не «такого теста нет» (инв. #17).

    Разница существенная: «нет такого теста» снимает строку с учёта
    (`not_addressable`), а «сбор упал» обязан оставить её НА учёте
    (`unknown`). Слить их значило бы гасить вопрос поломкой файла.
    """

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        (self.root / "spa_core" / "tests").mkdir(parents=True)
        self.addCleanup(self._tmp.cleanup)

    def test_a_collection_error_is_unknown_not_not_addressable(self):
        rel = "spa_core/tests/test_broken_collect.py"
        (self.root / rel).write_text(
            "import a_module_that_certainly_does_not_exist_here\n"
            "def test_walks():\n    assert True\n", encoding="utf-8")
        self.assertIsNone(probe.own_test_ids(self.root, rel, "test_walks"),
                          "сбор не ответил — перечня адресов НЕТ, и пустым "
                          "списком это не притворяется")
        self.assertEqual(probe.own_test_state(self.root, rel, "test_walks"),
                         probe.OWN_UNKNOWN)

    def test_the_same_file_without_the_broken_import_answers(self):
        """Обратная сторона: дело в поломке сбора, а не в самой сцене."""
        rel = "spa_core/tests/test_ok_collect.py"
        (self.root / rel).write_text(
            "def test_walks():\n    assert True\n", encoding="utf-8")
        self.assertEqual(probe.own_test_ids(self.root, rel, "test_walks"),
                         [f"{rel}::test_walks"])
        self.assertEqual(probe.own_test_state(self.root, rel, "test_walks"),
                         probe.OWN_RAN)


class TheTallyOfTheOwnTestQuestion(unittest.TestCase):
    """Счёт состояний спрашивается без прогона — иначе умолчание неизмеримо."""

    def test_a_row_WITHOUT_the_field_counts_as_not_asked_not_as_ran(self):
        own, _ = probe.own_test_tally([{"verdict": probe.VERDICT_UNMEASURED}])
        self.assertEqual(own[probe.OWN_NOT_ASKED], 1)
        self.assertEqual(own[probe.OWN_RAN], 0,
                         "удобное умолчание «бежал» и есть подмена «не "
                         "измерено» успехом")

    def test_an_unknown_value_is_counted_as_unknown_not_dropped(self):
        own, _ = probe.own_test_tally([{"own_test": "выдумка"}])
        self.assertEqual(own[probe.OWN_UNKNOWN], 1)
        self.assertEqual(sum(own.values()), 1, "строка не теряется молча")

    def test_the_cut_by_verdict_counts_only_the_skipped(self):
        _, by_verdict = probe.own_test_tally([
            {"own_test": probe.OWN_SKIPPED, "verdict": probe.VERDICT_REFUSES},
            {"own_test": probe.OWN_RAN, "verdict": probe.VERDICT_REFUSES},
        ])
        self.assertEqual(by_verdict[probe.VERDICT_REFUSES], 1)


class TheReportOfTheOwnTestQuestion(unittest.TestCase):
    """Отсутствие числа обязано читаться как отсутствие, а не как ноль."""

    def test_a_ledger_without_the_counts_says_NOT_MEASURED(self):
        lines = probe.report({"status": "MEASURED", "counts": {}, "entries": []})
        joined = "\n".join(lines)
        self.assertIn("[СВОЙ ТЕСТ] НЕ ИЗМЕРЕНО", joined)
        self.assertNotIn("[ПРОПУЩЕН ПРИ ДРУГОМ ИСХОДЕ]", joined)

    def test_a_ledger_with_the_counts_names_them(self):
        lines = probe.report({
            "status": "MEASURED", "counts": {}, "entries": [],
            "own_test_counts": {probe.OWN_RAN: 3, probe.OWN_SKIPPED: 2,
                                probe.OWN_NOT_ADDRESSABLE: 1,
                                probe.OWN_UNKNOWN: 0, probe.OWN_NOT_ASKED: 4},
            "own_skipped_by_verdict": {probe.VERDICT_REFUSES: 2}})
        joined = "\n".join(lines)
        self.assertIn("не спрашивали 4", joined)
        self.assertIn("[ПРОПУЩЕН ПРИ ДРУГОМ ИСХОДЕ] 2 строк(и)", joined)

    def test_zero_skipped_elsewhere_is_said_out_loud_not_omitted(self):
        """Ноль — ответ, и он обязан быть напечатан: молчание читалось бы как «не мерили»."""
        lines = probe.report({
            "status": "MEASURED", "counts": {}, "entries": [],
            "own_test_counts": {st: 0 for st in probe.OWN_STATES},
            "own_skipped_by_verdict": {probe.VERDICT_ALREADY_SKIPPED: 5}})
        joined = "\n".join(lines)
        self.assertIn("[ПРОПУЩЕН ПРИ ДРУГОМ ИСХОДЕ] 0 строк(и)", joined)
        self.assertIn("ленивое правило совпало с замером", joined)

    def test_not_asked_is_a_separate_state_from_unknown(self):
        """«Не спрашивали» и «спросили, ответа не разобрали» — разные состояния (инв. #17)."""
        self.assertNotEqual(probe.OWN_NOT_ASKED, probe.OWN_UNKNOWN)
        self.assertIn(probe.OWN_NOT_ASKED, probe.OWN_STATES)


class Fingerprint(unittest.TestCase):
    """Отпечаток обязан замечать СОСТАВ каталога, а не только байты файла."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)

    def test_a_missing_path_has_no_fingerprint_and_an_empty_dir_has_one(self):
        """«Каталога нет» и «каталог есть и пуст» — разные состояния (инв. #17)."""
        empty = self.root / "empty"
        empty.mkdir()
        self.assertIsNone(probe.fingerprint(self.root / "нет"))
        self.assertIsNotNone(probe.fingerprint(empty))

    def test_a_changed_file_changes_the_fingerprint(self):
        item = self.root / "a.txt"
        item.write_text("один", encoding="utf-8")
        before = probe.fingerprint(item)
        item.write_text("другой", encoding="utf-8")
        self.assertNotEqual(before, probe.fingerprint(item))

    def test_a_removed_or_renamed_neighbour_changes_a_directory_fingerprint(self):
        area = self.root / "area"
        area.mkdir()
        (area / "a.txt").write_text("x", encoding="utf-8")
        (area / "b.txt").write_text("y", encoding="utf-8")
        before = probe.fingerprint(area)
        (area / "b.txt").rename(area / "c.txt")
        self.assertNotEqual(before, probe.fingerprint(area),
                            "переименование соседа обязано быть видно")
        (area / "c.txt").unlink()
        self.assertNotEqual(before, probe.fingerprint(area))

    def test_the_same_content_gives_the_same_fingerprint(self):
        for name in ("one", "two"):
            area = self.root / name
            area.mkdir()
            (area / "a.txt").write_text("x", encoding="utf-8")
        self.assertEqual(probe.fingerprint(self.root / "one"),
                         probe.fingerprint(self.root / "two"))


class BlockingReasons(unittest.TestCase):
    """Почему путь унести нельзя — и это РАЗНЫЕ причины, а не одна."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tree = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)
        (self.tree / "spa_core" / "tests").mkdir(parents=True)
        (self.tree / "spa_core" / "tests" / "test_g.py").write_text("x = 1\n",
                                                                    encoding="utf-8")
        (self.tree / "area").mkdir()

    def _row(self, path: str) -> dict:
        return {"path": path, "guard": "spa_core/tests/test_g.py"}

    def test_the_tree_root_cannot_be_carried_away(self):
        self.assertIn("КОРЕНЬ", probe._blocking_reason(self.tree, self._row(".")))

    def test_a_path_containing_the_guard_cannot_be_carried_away(self):
        self.assertIn("СОДЕРЖИТ", probe._blocking_reason(self.tree, self._row("spa_core")))

    def test_an_absent_path_has_nothing_to_carry(self):
        self.assertIn("нет в одноразовом дереве",
                      probe._blocking_reason(self.tree, self._row("нет-такого")))

    def test_an_occupied_destination_is_refused(self):
        (self.tree / ("area" + probe.MOVED_SUFFIX)).mkdir()
        self.assertIn("занято", probe._blocking_reason(self.tree, self._row("area")))

    def test_a_clean_case_is_not_blocked(self):
        self.assertIsNone(probe._blocking_reason(self.tree, self._row("area")),
                          "иначе все причины были бы истинны по построению")


class VerdictFromTheRun(unittest.TestCase):
    """Исход прогона → вердикт. Порядок вопросов существен."""

    def _entry(self, **extra) -> dict:
        row = {"path": "area", "scope": "test_walks", "absent_passed": None}
        row.update(extra)
        return row

    def test_green_with_the_same_count_is_blindness(self):
        entry = probe._verdict(self._entry(absent_passed=3), 0, "3 passed in 0.1s", 3)
        self.assertEqual(entry["verdict"], probe.VERDICT_VACUOUS)

    def test_green_with_fewer_passed_is_an_announcement(self):
        entry = probe._verdict(self._entry(absent_passed=0),
                               0, "3 skipped in 0.1s", 3)
        self.assertEqual(entry["verdict"], probe.VERDICT_ANNOUNCES)

    def test_red_is_a_refusal_and_the_failing_names_are_kept(self):
        out = ("FAILED spa_core/tests/test_g.py::T::test_walks - нет каталога\n"
               "1 failed in 0.1s")
        entry = probe._verdict(self._entry(absent_passed=0), 1, out, 3)
        self.assertEqual(entry["verdict"], probe.VERDICT_REFUSES)
        self.assertEqual(entry["failed_tests"],
                         ["spa_core/tests/test_g.py::T::test_walks"])
        self.assertTrue(entry["consumer_is_red"])

    def test_a_neighbour_going_red_is_recorded_as_such(self):
        out = ("FAILED spa_core/tests/test_g.py::T::test_other - что-то\n"
               "1 failed in 0.1s")
        entry = probe._verdict(self._entry(absent_passed=0), 1, out, 3)
        self.assertEqual(entry["verdict"], probe.VERDICT_REFUSES)
        self.assertFalse(entry["consumer_is_red"],
                         "покраснел сосед, а не потребитель входа")

    def test_a_broken_collection_is_NOT_a_refusal(self):
        """Унос сломал сцену — вердикта о слепоте нет.

        Обратный порядок вопросов записал бы поломку сбора тестов в «сторож
        заметил отсутствие», то есть выдумал бы исправность.
        """
        entry = probe._verdict(self._entry(absent_passed=0),
                               1, "1 error in 0.1s", 3)
        self.assertEqual(entry["verdict"], probe.VERDICT_SCENE)

    def test_pytest_collecting_nothing_is_not_a_verdict_either(self):
        entry = probe._verdict(self._entry(), 5, "no tests ran in 0.01s", 3)
        self.assertEqual(entry["verdict"], probe.VERDICT_SCENE)

    def test_a_timeout_is_not_measured_and_not_green(self):
        entry = probe._verdict(self._entry(), -1, "не уложился", 3)
        self.assertEqual(entry["verdict"], probe.VERDICT_UNMEASURED)

    def test_an_unparsed_summary_is_not_measured(self):
        entry = probe._verdict(self._entry(absent_passed=None),
                               0, "совсем другое", 3)
        self.assertEqual(entry["verdict"], probe.VERDICT_UNMEASURED)


class StaticAgreement(unittest.TestCase):

    def test_a_door_expecting_refusal_agrees_with_a_refusal(self):
        self.assertTrue(probe.agreement(
            {"static_door": csi.DOOR_REFUSES, "verdict": probe.VERDICT_REFUSES}))

    def test_no_door_disagrees_with_a_refusal(self):
        self.assertFalse(probe.agreement(
            {"static_door": csi.DOOR_NONE, "verdict": probe.VERDICT_REFUSES}))

    def test_a_broken_scene_is_not_compared_at_all(self):
        for verdict in (probe.VERDICT_SCENE, probe.VERDICT_UNMEASURED):
            self.assertIsNone(probe.agreement(
                {"static_door": csi.DOOR_NONE, "verdict": verdict}),
                "засчитать статике ненаблюдённый вердикт нельзя")


class PopulationAndSample(unittest.TestCase):

    ROWS = [{"key": f"k{i}", "present_here": csi.PRESENT_YES} for i in range(5)] + \
           [{"key": "gone", "present_here": csi.PRESENT_NO}]

    def test_only_live_paths_enter_the_population(self):
        self.assertEqual(len(probe.population(self.ROWS)), 5)

    def test_the_sample_is_reproducible_by_its_named_seed(self):
        first = [r["key"] for r in probe.select(self.ROWS, sample=3)]
        second = [r["key"] for r in probe.select(self.ROWS, sample=3)]
        self.assertEqual(first, second)
        self.assertEqual(len(first), 3)

    def test_without_a_sample_the_whole_population_is_taken(self):
        self.assertEqual(len(probe.select(self.ROWS, sample=None)), 5)


BLIND = '''
from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]
AREA = ROOT / "area_blind"

def test_walks():
    for item in AREA.rglob("*.txt"):
        assert item.name
'''

LOUD = '''
from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]
AREA = ROOT / "area_loud"

def test_walks():
    assert AREA.is_dir(), "входа нет — сторож отказывается"
    for item in AREA.rglob("*.txt"):
        assert item.name
'''

REBUILDS = '''
from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]
AREA = ROOT / "area_rebuilt"

def test_walks():
    AREA.mkdir(exist_ok=True)
    (AREA / "made.txt").write_text("сделано прогоном", encoding="utf-8")
    for item in AREA.rglob("*.txt"):
        assert item.name
'''


#: Сторож, чей СОБСТВЕННЫЙ тест пропущен ещё до опыта. Условие пропуска
#: указывает на ДРУГОЙ путь (гитигнореный, отсутствующий), а не на тот,
#: который уносит зонд, — ровно так устроены настоящие случаи
#: (`skipif(not (ROOT / "data" / "aggressive_lab").exists())`). Второй тест в
#: файле нужен, чтобы база была зелёной и непустой: строку с нулём прошедших
#: зонд отказывается мерить раньше.
SKIPPED = '''
import pytest
from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]
AREA = ROOT / "area_skipped"

def test_unrelated_and_always_green():
    assert True

@pytest.mark.skipif(not (ROOT / "nightly_artefacts").exists(),
                    reason="ночные артефакты гитигнорены и здесь отсутствуют")
def test_walks():
    for item in AREA.rglob("*.txt"):
        assert item.name
'''

#: Сторож, чей СОБСТВЕННЫЙ тест пропущен, а СОСЕД по файлу при уносе пути
#: краснеет. До заказа G48 п. 2 вопрос «бежал ли тест этой строки» такой
#: строке не задавался ВОВСЕ: исход опыта — `refuses_absent`, а он «заведомо
#: означает, что тест бежал». Означает он другое — что заговорил кто-то в этом
#: файле. Строка получает чужой вердикт, и в дереве, где условие пропуска
#: ложно, отвечать за неё будет некому.
LOUD_BUT_SKIPPED = '''
import pytest
from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]
AREA = ROOT / "area_loud_skipped"

def test_neighbour_refuses():
    assert AREA.is_dir(), "входа нет — краснеет СОСЕД, а не сама строка"

@pytest.mark.skipif(not (ROOT / "nightly_artefacts").exists(),
                    reason="ночные артефакты гитигнорены и здесь отсутствуют")
def test_walks():
    for item in AREA.rglob("*.txt"):
        assert item.name
'''


#: Сторож, чей тест — МЕТОД ВНУТРИ КЛАССА и притом пропущен. До цикла #643
#: вопрос задавался селектором `файл::имя`, которым метод класса НЕ
#: адресуется: pytest печатает «no tests ran» и выходит КОДОМ 0, а зонд читал
#: это как «имя тестом не является». На живом населении так было помечено
#: 29 строк из 47, и исход `already_skipped` для классовых тестов был
#: недостижим по построению.
CLASS_SKIPPED = '''
import unittest
from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]
AREA = ROOT / "area_class_skipped"

class TestInAClass(unittest.TestCase):
    def test_unrelated_and_always_green(self):
        self.assertTrue(True)

    @unittest.skipIf(not (ROOT / "nightly_artefacts").exists(),
                     "ночные артефакты гитигнорены и здесь отсутствуют")
    def test_walks(self):
        for item in AREA.rglob("*.txt"):
            self.assertTrue(item.name)
'''


class ARealContour(unittest.TestCase):
    """Настоящий контур: git-репозиторий, три сторожа, живой pytest."""

    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory()
        cls.root = Path(cls._tmp.name) / "repo"
        for rel in csi.GUARD_DIRS:
            (cls.root / rel).mkdir(parents=True, exist_ok=True)
        tests = cls.root / "spa_core" / "tests"
        for name, body in (("test_blind_guard.py", BLIND),
                           ("test_loud_guard.py", LOUD),
                           ("test_rebuilding_guard.py", REBUILDS),
                           ("test_skipped_guard.py", SKIPPED),
                           ("test_loud_but_skipped_guard.py", LOUD_BUT_SKIPPED),
                           ("test_class_skipped_guard.py", CLASS_SKIPPED)):
            (tests / name).write_text(body, encoding="utf-8")
        for area in ("area_blind", "area_loud", "area_rebuilt",
                     "area_skipped", "area_loud_skipped", "area_class_skipped"):
            (cls.root / area).mkdir()
            (cls.root / area / "a.txt").write_text("исходное", encoding="utf-8")
        _git(cls.root, "init", "-q")
        _git(cls.root, "add", "-A")
        _git(cls.root, "-c", "user.email=probe@spa", "-c", "user.name=probe",
             "commit", "-q", "-m", "scene")
        cls.before = {
            name: probe.fingerprint(cls.root / name)
            for name in ("area_blind", "area_loud", "area_rebuilt",
                         "area_skipped", "area_loud_skipped",
                         "area_class_skipped")}
        cls.guard_shas = {
            path.name: probe.fingerprint(path) for path in tests.glob("*.py")}
        cls.doc = probe.measure(cls.root)
        cls.by_guard = {Path(str(e.get("guard"))).name: e
                        for e in cls.doc["entries"]}

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def test_the_measurement_did_not_abort(self):
        self.assertEqual(self.doc["status"], "MEASURED",
                         self.doc.get("aborted_reason") or "")
        self.assertEqual(len(self.doc["entries"]), 6)

    def test_the_blind_guard_stays_green_and_says_nothing(self):
        entry = self.by_guard["test_blind_guard.py"]
        self.assertEqual(entry["verdict"], probe.VERDICT_VACUOUS, entry["evidence"])
        self.assertEqual(entry["baseline_passed"], 1)
        self.assertEqual(entry["absent_passed"], 1)

    def test_the_loud_guard_goes_red_and_its_own_test_is_named(self):
        entry = self.by_guard["test_loud_guard.py"]
        self.assertEqual(entry["verdict"], probe.VERDICT_REFUSES, entry["evidence"])
        self.assertTrue(entry["failed_tests"])
        self.assertTrue(entry["consumer_is_red"])

    def test_a_guard_that_REBUILDS_its_input_is_recorded_and_the_tree_survives(self):
        """Положительный контроль на аварию 19.09.

        Сторож завёл унесённый каталог заново И ПОЛОЖИЛ В НЕГО ФАЙЛ. Возврат
        `rename` поверх непустого каталога падает, и первая редакция зонда на
        этом оборвала весь замер. Сцена воспроизводит аварию буквально.
        """
        entry = self.by_guard["test_rebuilding_guard.py"]
        self.assertTrue(entry["path_recreated_by_run"],
                        "сторож создал свой вход — это наблюдение, а не помеха")
        self.assertEqual(entry["verdict"], probe.VERDICT_VACUOUS, entry["evidence"])

    def test_a_guard_whose_own_test_is_SKIPPED_is_not_called_blind(self):
        """Обе стороны одного различия, и в этом весь смысл проверки.

        Пропущенный тест и вырожденный проход дают ОДИН И ТОТ ЖЕ признак:
        счёт `passed` по файлу не меняется ни до уноса пути, ни после. До
        цикла #642 зонд звал слепыми обоих — и четыре строки из девяти находок
        ADR-424 оказались пропущенными тестами, а не слепыми сторожами.
        """
        skipped = self.by_guard["test_skipped_guard.py"]
        self.assertEqual(skipped["verdict"], probe.VERDICT_ALREADY_SKIPPED,
                         skipped["evidence"])
        self.assertEqual(skipped["own_test"], probe.OWN_SKIPPED)
        self.assertEqual(skipped["baseline_passed"], skipped["absent_passed"],
                         "признак у пропуска и у слепоты ОДИН — на нём и "
                         "ловились четыре строки")
        self.assertIn("ПРОПУЩЕН", skipped["evidence"])

        blind = self.by_guard["test_blind_guard.py"]
        self.assertEqual(blind["verdict"], probe.VERDICT_VACUOUS,
                         "обратная сторона: настоящая слепота обязана остаться "
                         "находкой, иначе новый исход проглотил бы весь класс")
        self.assertEqual(blind["own_test"], probe.OWN_RAN)

    def test_a_test_that_is_a_METHOD_of_a_class_is_addressed_not_disowned(self):
        """Находка цикла #643, и обе её стороны.

        Прежний селектор `файл::имя` метод класса не адресует: pytest выходит
        КОДОМ 0 со словами «no tests ran», и зонд читал это как «имя тестом не
        является». Тогда ответ «не тест» выдавался там, где тест есть, а весь
        исход `already_skipped` для классовых тестов был недостижим.
        """
        entry = self.by_guard["test_class_skipped_guard.py"]
        self.assertEqual(entry["own_test"], probe.OWN_SKIPPED, entry["evidence"])
        self.assertEqual(entry["verdict"], probe.VERDICT_ALREADY_SKIPPED,
                         entry["evidence"])

        guard = "spa_core/tests/test_class_skipped_guard.py"
        self.assertEqual(
            probe.own_test_ids(self.root, guard, "test_walks"),
            [f"{guard}::TestInAClass::test_walks"],
            "адрес СПРОШЕН у pytest, а не собран второй копией правила")
        self.assertEqual(
            probe.own_test_ids(self.root, guard, "test_that_does_not_exist"), [],
            "обратная сторона: «такого теста нет» — ответ сбора, а не молчание")

    def test_the_name_is_matched_as_a_SEGMENT_not_as_a_substring(self):
        """`test_walks` и `test_unrelated_and_always_green` живут в одном файле."""
        guard = "spa_core/tests/test_class_skipped_guard.py"
        ids = probe.own_test_ids(self.root, guard, "test_unrelated")
        self.assertEqual(ids, [], "подстрока адресом не является")

    def test_the_collection_is_cached_per_guard_AND_per_name(self):
        """Кеш — не украшение: строк у одного файла бывает несколько.

        Ключ — ПАРА (сторож, имя), а не один сторож: вывод сбора сужен по
        имени, и общий на файл ключ отдал бы второй строке чужой перечень.
        """
        cache: dict = {}
        guard = "spa_core/tests/test_class_skipped_guard.py"
        first = probe.own_test_ids(self.root, guard, "test_walks", cache=cache)
        self.assertIn(f"{guard}::test_walks", cache)
        self.assertNotIn(guard, cache, "ключом файла перечень не адресуется")
        cache[f"{guard}::test_walks"] = []          # подменяем ответ сбора
        second = probe.own_test_ids(self.root, guard, "test_walks", cache=cache)
        self.assertTrue(first)
        self.assertEqual(second, [], "второй раз сбор не звался — взят кеш")
        other = probe.own_test_ids(self.root, guard,
                                   "test_unrelated_and_always_green", cache=cache)
        self.assertTrue(other, "чужое имя чужим кешем не отвечает")

    def test_a_row_whose_verdict_never_ran_is_not_compared_with_the_static_door(self):
        """«Тест не звали» — не наблюдение о двери, и согласием считаться не может."""
        self.assertIsNone(probe.agreement(
            {"verdict": probe.VERDICT_ALREADY_SKIPPED, "static_door": "no_door"}))
        self.assertIsNotNone(probe.agreement(
            {"verdict": probe.VERDICT_VACUOUS, "static_door": "no_door"}))

    def test_the_census_does_not_carry_already_skipped_as_a_blindness_verdict(self):
        overlay = csi.behaviour_of(
            {"key": "k", "guard_sha": "s"},
            {"k": {"key": "k", "guard_sha": "s",
                   "verdict": probe.VERDICT_ALREADY_SKIPPED,
                   "evidence": "пропущен"}}, None)
        self.assertIsNone(overlay["behaviour"],
                          "«тест не звали» вердиктом о слепоте не является")

    def test_a_scope_that_is_not_a_test_is_a_third_outcome_not_a_run(self):
        """Неадресуемое имя обязано называться, а не выдаваться за «бежал»."""
        self.assertEqual(
            probe.own_test_state(self.root, "spa_core/tests/test_blind_guard.py",
                                 "_helper_that_is_not_a_test"),
            probe.OWN_NOT_ADDRESSABLE)
        self.assertEqual(
            probe.own_test_state(self.root, "spa_core/tests/test_blind_guard.py", ""),
            probe.OWN_NOT_ADDRESSABLE)
        self.assertEqual(
            probe.own_test_state(self.root, "spa_core/tests/test_blind_guard.py",
                                 "test_walks"),
            probe.OWN_RAN)

    def test_the_question_is_put_to_EVERY_row_not_only_to_the_vacuous_ones(self):
        """Заказ G48 п. 2: ленивый вопрос заменён замером по всему населению.

        Обратная сторона проверки — не «поле есть у пяти строк», а «поле есть
        у строк С РАЗНЫМИ исходами»: прежняя редакция тоже дала бы поле, но
        ровно у одного исхода, и число «сколько ещё строк пропущено» не
        существовало бы вовсе.
        """
        states = {Path(str(e.get("guard"))).name: e.get("own_test")
                  for e in self.doc["entries"]}
        self.assertNotIn(None, states.values(), states)
        verdicts_asked = {
            e.get("verdict") for e in self.doc["entries"]
            if e.get("own_test") != probe.OWN_NOT_ASKED}
        self.assertGreater(len(verdicts_asked), 1, verdicts_asked)
        self.assertIn(probe.VERDICT_REFUSES, verdicts_asked,
                      "у красневшего сторожа вопрос прежде не задавался вовсе")
        counts = self.doc["own_test_counts"]
        self.assertEqual(sum(counts.values()), len(self.doc["entries"]),
                         "перепись состояний обязана покрывать всё население")
        self.assertEqual(set(counts), set(probe.OWN_STATES))

    def test_a_refusal_produced_by_a_NEIGHBOUR_is_named_and_a_real_one_is_not(self):
        """Обе стороны: чужой вердикт назван, свой — нет."""
        borrowed = self.by_guard["test_loud_but_skipped_guard.py"]
        self.assertEqual(borrowed["verdict"], probe.VERDICT_REFUSES,
                         borrowed["evidence"])
        self.assertEqual(borrowed["own_test"], probe.OWN_SKIPPED,
                         "тест самой строки пропущен — краснел сосед по файлу")
        self.assertFalse(borrowed["consumer_is_red"])

        own = self.by_guard["test_loud_guard.py"]
        self.assertEqual(own["own_test"], probe.OWN_RAN)
        self.assertTrue(own["consumer_is_red"])

        named = {c["guard"] for c in self.doc["refusal_credited_to_neighbour"]}
        self.assertTrue(any("loud_but_skipped" in g for g in named), named)
        self.assertFalse(any(g.endswith("test_loud_guard.py") for g in named),
                         "сторож, чей СОБСТВЕННЫЙ тест покраснел, чужим "
                         "вердиктом не живёт — иначе находка проглотила бы класс")
        self.assertIsNotNone(
            borrowed["static_agrees"],
            "чужой вердикт остаётся ВЕРДИКТОМ: снять такую строку со сравнения "
            "со статикой значило бы уменьшить население молча — ровно тот "
            "класс, который заказ G48 п. 3 велит мерить, а не заводить")
        self.assertFalse(any(g.endswith("test_skipped_guard.py") for g in named),
                         "строка, у которой сторож ПРОМОЛЧАЛ, чужого вердикта "
                         "не получала — ей вердикта не произвёл никто, и это "
                         "уже сказано исходом `already_skipped`")

    def test_the_number_asked_by_the_order_is_counted_per_verdict(self):
        """«Сколько строк с ДРУГИМ исходом тоже пропущены» — это число, не проза."""
        by_verdict = self.doc["own_skipped_by_verdict"]
        self.assertEqual(by_verdict[probe.VERDICT_ALREADY_SKIPPED], 2,
                         "вырожденный проход с пропуском переименован в исход — "
                         "и у теста-ФУНКЦИИ, и у теста-МЕТОДА класса")
        self.assertEqual(by_verdict[probe.VERDICT_REFUSES], 1,
                         "а вот ЭТУ строку прежнее правило не спрашивало")
        self.assertEqual(by_verdict[probe.VERDICT_VACUOUS], 0,
                         "после переименования в `already_skipped` под "
                         "вырожденным проходом пропусков не остаётся")

    def test_every_carried_path_came_back_byte_for_byte(self):
        for name, before in self.before.items():
            self.assertEqual(probe.fingerprint(self.root / name), before,
                             f"путь `{name}` вернулся не тем, чем был")

    def test_the_probe_never_edits_the_guard_source(self):
        """Главное отличие от соседнего зонда — и оно ИЗМЕРЯЕТСЯ."""
        tests = self.root / "spa_core" / "tests"
        for path in tests.glob("*.py"):
            self.assertEqual(probe.fingerprint(path), self.guard_shas[path.name])

    def test_the_static_door_is_compared_with_the_run(self):
        compared = [e for e in self.doc["entries"] if e["static_agrees"] is not None]
        self.assertTrue(compared, "сравнения не было — контроль вхолостую")
        self.assertEqual(self.doc["static_compared"], len(compared))

    def test_the_report_is_not_vacuous_on_a_real_document(self):
        lines = probe.report(self.doc)
        self.assertGreaterEqual(len(lines), 5)
        self.assertTrue(any("СОЗДАЛ СВОЙ ВХОД" in line for line in lines))

    def test_run_writes_the_ledger_and_names_its_producer(self):
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / "ledger.json"
            outcome = probe.run(self.root, dest=dest, limit=1)
            self.assertTrue(outcome["measured"])
            doc = json.loads(dest.read_text(encoding="utf-8"))
            self.assertEqual(doc["generated_by"], probe.PRODUCER)

    def test_the_ledger_verdict_overrides_the_static_door_in_the_census(self):
        """Право на вердикт даёт ПРОГОН — и перепись обязана это читать."""
        rows = csi.measure(self.root)["rows"]
        blind = next(r for r in rows if r["guard"].endswith("test_blind_guard.py"))
        ledger = {e["key"]: e for e in self.doc["entries"]}
        overlay = csi.behaviour_of(blind, ledger, None)
        self.assertEqual(overlay["behaviour"], probe.VERDICT_VACUOUS)
        self.assertTrue(csi.is_finding(dict(blind, **overlay)))

    def test_a_ledger_taken_from_another_edition_of_the_guard_is_DROPPED(self):
        rows = csi.measure(self.root)["rows"]
        blind = next(r for r in rows if r["guard"].endswith("test_blind_guard.py"))
        ledger = {e["key"]: dict(e, guard_sha="другая-редакция")
                  for e in self.doc["entries"]}
        overlay = csi.behaviour_of(blind, ledger, None)
        self.assertIsNone(overlay["behaviour"])
        self.assertIn("ДРУГОЙ редакции", overlay["behaviour_evidence"])

    def test_scene_destroyed_is_not_carried_into_the_census_as_a_verdict(self):
        overlay = csi.behaviour_of(
            {"key": "k", "guard_sha": "s"},
            {"k": {"key": "k", "guard_sha": "s", "verdict": probe.VERDICT_SCENE,
                   "evidence": "сцена"}}, None)
        self.assertIsNone(overlay["behaviour"],
                          "«унос сломал сцену» вердиктом о слепоте не является")


class TheInstrumentRunsFromTheCommandLine(unittest.TestCase):

    def test_exit_code_two_when_the_tree_is_not_a_repository(self):
        with tempfile.TemporaryDirectory() as tmp:
            proc = subprocess.run(
                [sys.executable, "-m", "spa_core.monitoring.absent_path_probe",
                 "--root", tmp, "--no-write"],
                cwd=str(REPO), capture_output=True, text=True, timeout=300)
            self.assertEqual(proc.returncode, 2,
                             "«не измерено» обязано выходить своим кодом, а не нулём")
            self.assertIn("НЕ ИЗМЕРЕНО", proc.stdout)


class TheExitCodeKeepsTheThreeOutcomesApart(unittest.TestCase):
    """Код возврата — то место, где различие читает ЗОВУЩИЙ скрипт (инв. #17).

    Прежняя редакция `main()` читала `(doc.get("counts") or {}).get(...)`:
    журнал без поля давал пусто, пусто — ложь, ложь — код 0. «Поля нет» и
    «находок ноль» выходили одним и тем же успехом. Контроль здесь в обе
    стороны: полный журнал с нулём обязан дать 0, урезанный — 2.
    """

    def _main_with(self, doc: dict) -> tuple[int, str]:
        import contextlib
        import io
        original = probe.run
        probe.run = lambda *a, **k: {"doc": doc, "path": None}   # noqa: ARG005
        self.addCleanup(lambda: setattr(probe, "run", original))
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            code = probe.main(["--no-write"])
        return code, buf.getvalue()

    def _measured(self, **over) -> dict:
        doc = {"status": "MEASURED", "question": "q", "order": "G46",
               "population": 0, "probed": 0, "findings": 0,
               "counts": {probe.VERDICT_VACUOUS: 0, probe.VERDICT_UNMEASURED: 0},
               "static_compared": 0, "static_disagrees": 0, "static_by_kind": {},
               "path_recreated_by_run": [], "stale_disposable_trees": [],
               "entries": [], "what_it_does_not_prove": []}
        doc.update(over)
        return doc

    def test_a_complete_journal_with_zero_findings_exits_clean(self):
        code, _ = self._main_with(self._measured())
        self.assertEqual(code, 0, "измеренный ноль обязан выходить нулём")

    def test_a_journal_without_counts_is_not_measured_and_never_exits_clean(self):
        doc = self._measured()
        del doc["counts"]
        code, out = self._main_with(doc)
        self.assertEqual(code, 2, "отсутствие наблюдения кодом 0 не выдаётся")
        self.assertIn("НЕ ИЗМЕРЕНО", out)
        self.assertIn("counts", out, "пропавшее поле обязано быть НАЗВАНО")

    def test_a_journal_without_findings_is_not_measured_either(self):
        doc = self._measured()
        del doc["findings"]
        code, out = self._main_with(doc)
        self.assertEqual(code, 2)
        self.assertIn("findings", out)

    def test_a_findings_field_of_the_wrong_kind_is_absence_not_a_number(self):
        code, out = self._main_with(self._measured(findings="девять"))
        self.assertEqual(code, 2, "мусор в поле замером не является")
        self.assertIn("findings", out)

    def test_findings_above_zero_still_exits_one(self):
        code, _ = self._main_with(self._measured(findings=9))
        self.assertEqual(code, 1, "находки обязаны выходить кодом 1")

    def test_unmeasured_rows_alone_also_exit_one(self):
        code, _ = self._main_with(self._measured(
            counts={probe.VERDICT_VACUOUS: 0, probe.VERDICT_UNMEASURED: 3}))
        self.assertEqual(code, 1, "непомеренные строки — не благополучие")


if __name__ == "__main__":
    unittest.main()
