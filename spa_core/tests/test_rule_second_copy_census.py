"""Перепись «одно правило — две копии»: сторож прибора, у каждой проверки обратная сторона.

Заказ **G41 п. 1** приказа владельца «Portfolio CIO», решение — ADR-417.

## Что здесь проверяется и почему именно так

Прибор отвечает на вопрос «у скольких правил есть ИСПОЛНИТЕЛЬ и СТОРОЖ,
проверяющие одно условие РАЗНЫМ кодом». Ошибиться он может в обе стороны, и
каждая сторона стоит своей проверки:

* **выдумать находку** там, где сторож честно делегирует, — если правило
  «достаёт ли исполнителя» окажется у́же настоящих дверей. Отсюда по тесту на
  КАЖДУЮ из четырёх дверей и по обратной стороне у каждой;
* **пропустить копию** — если связывать копии по одному имени (замер: 49 249
  пар, `ROOT` — 19 118) или, наоборот, требовать слишком многого.

Сцены синтетические: настоящее дерево читается ровно одним ЖИВЫМ контролем, и
тот проверяет не число находок (оно обязано убывать по мере починок), а
ПРОВЕРЯЕМОСТЬ каждой строки. Тест, требующий известной находки, покраснел бы от
её починки — это ровно тот сторож, который охраняет дефект.

Литеральных дат и номеров процессов здесь нет: часы прибора инъектируются
параметром ``now``.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import ast
import datetime as dt
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from spa_core.monitoring import rule_second_copy_census as rsc

_REPO = Path(__file__).resolve().parents[2]
#: Неподвижные часы: прибор берёт их параметром, поэтому вердикт не зависит от
#: календаря (`.claude/rules/deployment.md`, приём №1).
# FROZEN-DATE-OK: injected-clock — час передаётся в measure/run параметром now=
_NOW = dt.datetime(2000, 1, 1, tzinfo=dt.timezone.utc)


def _tree(base: Path, *, executor: str = "", guard: str = "",
          extra: dict | None = None) -> Path:
    """Минимальное дерево: исполнитель, сторож и обязательные каталоги.

    Каталоги `spa_core/` и `scripts/` создаются оба: их отсутствие — отдельный
    исход прибора (`UNMEASURED`), и смешивать его со сценой было бы нечестно.
    """
    (base / "spa_core" / "tests").mkdir(parents=True)
    (base / "scripts").mkdir(parents=True)
    (base / "scripts" / "__init__.py").write_text("", encoding="utf-8")
    if executor:
        (base / "spa_core" / "e.py").write_text(executor, encoding="utf-8")
    if guard:
        (base / "spa_core" / "tests" / "test_g.py").write_text(guard, encoding="utf-8")
    for rel, text in (extra or {}).items():
        path = base / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    return base


def _measure(base: Path) -> dict:
    return rsc.measure(base, now=_NOW)


def _rows(doc: dict) -> list:
    return doc["rows"]


class ValueIsCompared_NotJustTheName(unittest.TestCase):
    """Связывать копии по ИМЕНИ мало — это замер, а не осторожность."""

    def test_equal_constant_on_both_sides_is_a_finding(self):
        with TemporaryDirectory() as tmp:
            base = _tree(Path(tmp),
                         executor="RULE = frozenset({'new', 'backlog'})\n",
                         guard="RULE = frozenset({'new', 'backlog'})\n")
            doc = _measure(base)
        self.assertEqual(doc["counts"][rsc.CLASS_TWO_COPIES], 1)
        (row,) = _rows(doc)
        self.assertEqual(row["name"], "RULE")
        self.assertEqual(row["guard"], "spa_core/tests/test_g.py")
        self.assertEqual(row["executor"], "spa_core/e.py")

    def test_a_different_value_under_the_same_name_is_not_a_finding(self):
        """ОБРАТНАЯ СТОРОНА: совпало имя, разошлось значение ⇒ не копия правила."""
        with TemporaryDirectory() as tmp:
            base = _tree(Path(tmp),
                         executor="RULE = frozenset({'new', 'backlog'})\n",
                         guard="RULE = frozenset({'new'})\n")
            doc = _measure(base)
        self.assertEqual(_rows(doc), [])
        self.assertEqual(doc["counts"][rsc.CLASS_VALUE_DIFFERS], 1)

    def test_a_nonconstant_value_is_its_own_bin_not_a_difference(self):
        """«Сравнить было нечем» — третий исход, а не «различаются» (инв. #17).

        Здесь же положительный контроль ужесточения: по ОДНОМУ имени эта пара
        была бы находкой, и именно такими парами (`ROOT`, `main`, `run`)
        полнилась первая редакция прибора.
        """
        with TemporaryDirectory() as tmp:
            base = _tree(Path(tmp),
                         executor="from pathlib import Path\nROOT = Path(__file__).parent\n",
                         guard="from pathlib import Path\nROOT = Path(__file__).parent\n")
            doc = _measure(base)
        self.assertEqual(_rows(doc), [])
        self.assertEqual(doc["counts"][rsc.CLASS_NOT_CONSTANT], 1)
        self.assertEqual(doc["counts"][rsc.CLASS_VALUE_DIFFERS], 0)

    def test_container_constructors_stay_constant(self):
        """`frozenset({...})` есть ЗАПИСЬ множества, а не вычисление; `Path(...)` — нет."""
        self.assertEqual(rsc.const_value(ast.parse("frozenset({'a'})", mode="eval").body),
                         "frozenset({'a'})")
        self.assertIsNone(rsc.const_value(ast.parse("Path('a')", mode="eval").body))


class FourDoorsToTheExecutor(unittest.TestCase):
    """Дверь опознаётся по тому, что исполнитель НАЗВАН, а не по форме зова."""

    _SAME = "RULE = 5\n"

    def _verdict(self, guard_src: str) -> dict:
        with TemporaryDirectory() as tmp:
            base = _tree(Path(tmp), executor=self._SAME, guard=guard_src)
            return _measure(base)

    def test_plain_import_is_a_door(self):
        doc = self._verdict("import spa_core.e\nRULE = 5\n")
        self.assertEqual(_rows(doc), [])
        self.assertEqual(doc["counts"][rsc.CLASS_DELEGATES], 1)

    def test_from_package_import_module_is_a_door_and_text_alone_would_miss_it(self):
        """Положительный контроль разбора ввоза: текстового следа у этой двери НЕТ.

        `from spa_core import e` не содержит строки «spa_core.e» ни разу —
        текстовое правило объявило бы такого сторожа НЕ достающим исполнителя,
        то есть выдумало бы находку там, где делегирование честное.
        """
        src = "from spa_core import e\nRULE = 5\n"
        self.assertNotIn("spa_core.e", src)
        self.assertNotIn("spa_core/e.py", src)
        doc = self._verdict(src)
        self.assertEqual(_rows(doc), [])
        self.assertEqual(doc["counts"][rsc.CLASS_DELEGATES], 1)

    def test_a_path_literal_is_a_door(self):
        doc = self._verdict("SRC = 'spa_core/e.py'\nRULE = 5\n")
        self.assertEqual(_rows(doc), [])

    def test_a_dotted_literal_in_a_subprocess_is_a_door(self):
        doc = self._verdict("ARGV = ['python3', '-m', 'spa_core.e']\nRULE = 5\n")
        self.assertEqual(_rows(doc), [])

    def test_a_mention_of_a_DIFFERENT_module_is_not_a_door(self):
        """ОБРАТНАЯ СТОРОНА всех четырёх: дверь к соседу исполнителя не достаёт."""
        doc = self._verdict("SRC = 'spa_core/other.py'\nRULE = 5\n")
        self.assertEqual(len(_rows(doc)), 1)
        self.assertEqual(doc["counts"][rsc.CLASS_DELEGATES], 0)

    def test_imported_modules_reads_both_readings_of_from_import(self):
        tree = ast.parse("from spa_core.backtesting import tier1\n")
        names = rsc.imported_modules(tree)
        self.assertIn("spa_core.backtesting", names)
        self.assertIn("spa_core.backtesting.tier1", names)
        self.assertNotIn("spa_core.backtesting.tier2", names)


class AmbiguousExecutorIsItsOwnBin(unittest.TestCase):
    """Имя, объявленное многими исполнителями, не называет ОДНО правило."""

    def test_two_executors_of_one_name_are_not_a_finding(self):
        with TemporaryDirectory() as tmp:
            base = _tree(Path(tmp), executor="RULE = 5\n", guard="RULE = 5\n",
                         extra={"scripts/second.py": "RULE = 5\n"})
            doc = _measure(base)
        self.assertEqual(_rows(doc), [])
        self.assertEqual(doc["counts"][rsc.CLASS_AMBIGUOUS], 1)

    def test_one_executor_of_the_same_name_is(self):
        """ОБРАТНАЯ СТОРОНА: убери второго — и пара становится находкой."""
        with TemporaryDirectory() as tmp:
            base = _tree(Path(tmp), executor="RULE = 5\n", guard="RULE = 5\n")
            doc = _measure(base)
        self.assertEqual(len(_rows(doc)), 1)
        self.assertEqual(doc["counts"][rsc.CLASS_AMBIGUOUS], 0)


class CoordinateIsATopLevelPublicName(unittest.TestCase):

    def test_a_constant_inside_a_function_is_invisible(self):
        with TemporaryDirectory() as tmp:
            base = _tree(Path(tmp),
                         executor="def f():\n    RULE = 5\n    return RULE\n",
                         guard="RULE = 5\n")
            doc = _measure(base)
        self.assertEqual(_rows(doc), [])

    def test_the_same_constant_at_top_level_is_visible(self):
        """ОБРАТНАЯ СТОРОНА теста выше: различие ровно в уровне объявления."""
        with TemporaryDirectory() as tmp:
            base = _tree(Path(tmp), executor="RULE = 5\n", guard="RULE = 5\n")
            doc = _measure(base)
        self.assertEqual(len(_rows(doc)), 1)

    def test_private_names_are_not_coordinates(self):
        with TemporaryDirectory() as tmp:
            base = _tree(Path(tmp), executor="_RULE = 5\n", guard="_RULE = 5\n")
            doc = _measure(base)
        self.assertEqual(_rows(doc), [])

    def test_the_same_name_made_public_is(self):
        """ОБРАТНАЯ СТОРОНА: различие ровно в подчёркивании."""
        with TemporaryDirectory() as tmp:
            base = _tree(Path(tmp), executor="RULE = 5\n", guard="RULE = 5\n")
            doc = _measure(base)
        self.assertEqual(len(_rows(doc)), 1)

    def test_a_guard_name_starting_with_test_is_not_a_coordinate(self):
        """Отсев `test_*` живёт ТОЛЬКО на стороне сторожа, и проверяется он тут.

        Публичное имя, начинающееся с `test_`, сторона исполнителя не отсеивает
        (её отсев — про подчёркивание), поэтому без этой сцены отсев на стороне
        сторожа был бы неотличим от соседнего и батарея мутаций это показала:
        снятие отсева ВЫЖИВАЛО.
        """
        with TemporaryDirectory() as tmp:
            base = _tree(Path(tmp), executor="test_mode = 5\n", guard="test_mode = 5\n")
            doc = _measure(base)
        self.assertEqual(_rows(doc), [])

    def test_the_same_pair_without_the_test_prefix_is_a_finding(self):
        """ОБРАТНАЯ СТОРОНА: различие ровно в приставке."""
        with TemporaryDirectory() as tmp:
            base = _tree(Path(tmp), executor="mode = 5\n", guard="mode = 5\n")
            doc = _measure(base)
        self.assertEqual(len(_rows(doc)), 1)


class AccountingIsIdentical(unittest.TestCase):
    """`scanned == classified + unreadable` — вход нельзя уронить молча."""

    def test_identity_holds_on_a_clean_tree(self):
        with TemporaryDirectory() as tmp:
            base = _tree(Path(tmp), executor="RULE = 5\n", guard="RULE = 5\n")
            doc = _measure(base)
        self.assertEqual(doc["scanned"], doc["classified"] + doc["counts"]["unreadable"])
        self.assertEqual(doc["counts"]["unreadable"], 0)

    def test_an_unparsable_file_is_NAMED_not_dropped(self):
        with TemporaryDirectory() as tmp:
            base = _tree(Path(tmp), executor="RULE = 5\n", guard="RULE = 5\n",
                         extra={"scripts/broken.py": "def (\n"})
            doc = _measure(base)
        self.assertEqual(doc["counts"]["unreadable"], 1)
        (bad,) = doc["unreadable"]
        self.assertEqual(bad["file"], "scripts/broken.py")
        self.assertEqual(bad["side"], "executor")
        self.assertTrue(bad["reason"].strip(), "причина обязана быть названа")
        self.assertEqual(doc["scanned"], doc["classified"] + doc["counts"]["unreadable"])

    def test_an_unparsable_GUARD_is_named_on_its_own_side(self):
        with TemporaryDirectory() as tmp:
            base = _tree(Path(tmp), executor="RULE = 5\n", guard="RULE = 5\n",
                         extra={"spa_core/tests/test_broken.py": "def (\n"})
            doc = _measure(base)
        (bad,) = doc["unreadable"]
        self.assertEqual(bad["side"], "guard")


class ThirdOutcomeIsDistinguishable(unittest.TestCase):
    """«Не измерено» никогда не выдаётся за «чисто» (инв. #17)."""

    def test_missing_root_is_unmeasured(self):
        with TemporaryDirectory() as tmp:
            outcome = rsc.run(Path(tmp) / "нет-такого-дерева", write=False, now=_NOW)
        self.assertFalse(outcome["measured"])
        self.assertEqual(outcome["doc"]["status"], "UNMEASURED")
        self.assertIn("нет-такого-дерева", outcome["doc"]["reason"])

    def test_missing_executor_dir_is_unmeasured_not_clean(self):
        with TemporaryDirectory() as tmp:
            base = Path(tmp)
            (base / "spa_core" / "tests").mkdir(parents=True)
            (base / "spa_core" / "tests" / "test_g.py").write_text("RULE = 5\n",
                                                                   encoding="utf-8")
            outcome = rsc.run(base, write=False, now=_NOW)
        self.assertEqual(outcome["doc"]["status"], "UNMEASURED")
        self.assertIn("scripts", outcome["doc"]["reason"])

    def test_a_tree_without_guards_is_unmeasured(self):
        with TemporaryDirectory() as tmp:
            base = Path(tmp)
            (base / "spa_core").mkdir(parents=True)
            (base / "scripts").mkdir(parents=True)
            (base / "spa_core" / "e.py").write_text("RULE = 5\n", encoding="utf-8")
            outcome = rsc.run(base, write=False, now=_NOW)
        self.assertEqual(outcome["doc"]["status"], "UNMEASURED")

    def test_a_measured_clean_tree_is_CLEAN_and_says_so(self):
        """ОБРАТНАЯ СТОРОНА трёх тестов выше: измеренное чисто отличимо от них."""
        with TemporaryDirectory() as tmp:
            base = _tree(Path(tmp), executor="RULE = 5\n", guard="OTHER = 5\n")
            outcome = rsc.run(base, write=False, now=_NOW)
        self.assertTrue(outcome["measured"])
        self.assertEqual(outcome["doc"]["status"], "CLEAN")


class ExitCodesSeparateTheThreeOutcomes(unittest.TestCase):

    def test_clean_is_zero(self):
        with TemporaryDirectory() as tmp:
            base = _tree(Path(tmp), executor="RULE = 5\n", guard="OTHER = 5\n")
            self.assertEqual(rsc.main(["--root", str(base), "--no-write"]), 0)

    def test_finding_is_one(self):
        with TemporaryDirectory() as tmp:
            base = _tree(Path(tmp), executor="RULE = 5\n", guard="RULE = 5\n")
            self.assertEqual(rsc.main(["--root", str(base), "--no-write"]), 1)

    def test_unmeasured_is_two(self):
        with TemporaryDirectory() as tmp:
            self.assertEqual(
                rsc.main(["--root", str(Path(tmp) / "нет"), "--no-write"]), 2)


class SurfaceOfRenamedCopies(unittest.TestCase):
    """Переименованную копию правило имени не видит — поверхность считается отдельно."""

    def test_a_guard_touching_repo_state_without_naming_the_subject_tree_is_counted(self):
        with TemporaryDirectory() as tmp:
            base = _tree(Path(tmp), executor="RULE = 5\n",
                         guard="CARD_DIR = 'nimbalyst-local/tracker'\n")
            doc = _measure(base)
        self.assertIn("spa_core/tests/test_g.py", doc["renamed_copy_surface"])

    def test_a_guard_that_names_the_subject_tree_is_not(self):
        """ОБРАТНАЯ СТОРОНА: упомянул предмет — значит достать его МОГ."""
        with TemporaryDirectory() as tmp:
            base = _tree(Path(tmp), executor="RULE = 5\n",
                         guard="import spa_core\nCARD_DIR = 'nimbalyst-local/tracker'\n")
            doc = _measure(base)
        self.assertEqual(doc["renamed_copy_surface"], [])

    def test_a_guard_that_touches_no_repo_state_is_not(self):
        """ОБРАТНАЯ СТОРОНА вторая: не читает состояния — копии правила и нет."""
        with TemporaryDirectory() as tmp:
            base = _tree(Path(tmp), executor="RULE = 5\n", guard="X = 1 + 1\n")
            doc = _measure(base)
        self.assertEqual(doc["renamed_copy_surface"], [])


class ReportIsAnAssertion(unittest.TestCase):

    def _doc(self, rows: int) -> dict:
        return {
            "status": "FINDING" if rows else "CLEAN",
            "counts": {rsc.CLASS_TWO_COPIES: rows, rsc.CLASS_DELEGATES: 0,
                       rsc.CLASS_VALUE_DIFFERS: 0, rsc.CLASS_NOT_CONSTANT: 0,
                       rsc.CLASS_AMBIGUOUS: 0, "unreadable": 0},
            "scanned": 2, "classified": 2, "guards": 1, "executors": 1,
            "invoked_by": {"measured": True, "entry": "х"},
            "rows": [{"verdict": rsc.CLASS_TWO_COPIES, "guard": f"g{i}.py",
                      "executor": "e.py", "name": f"N{i}", "value": "5"}
                     for i in range(rows)],
            "renamed_copy_surface": [],
        }

    def test_findings_lead_and_truncation_announces_itself(self):
        lines = rsc.report(self._doc(7), max_rows=3)
        findings = [ln for ln in lines if ln.startswith("[НАХОДКА]")]
        self.assertEqual(len(findings), 3)
        self.assertTrue(any(ln.startswith("[…] показаны 3 находки из 7") for ln in lines),
                        "умолчание об укорочении и есть способ соврать усечением")

    def test_a_complete_list_does_not_announce_truncation(self):
        """ОБРАТНАЯ СТОРОНА: строка укорочения не печатается зря."""
        lines = rsc.report(self._doc(2), max_rows=3)
        self.assertFalse(any(ln.startswith("[…]") for ln in lines))

    def test_unmeasured_report_names_the_reason(self):
        lines = rsc.report({"status": "UNMEASURED", "reason": "корень не прочитан"})
        self.assertEqual(len(lines), 1)
        self.assertIn("корень не прочитан", lines[0])

    def test_unmeasured_without_a_reason_does_not_pretend_to_have_one(self):
        """ОБРАТНАЯ СТОРОНА: пустая причина не выдаётся за названную."""
        lines = rsc.report({"status": "UNMEASURED"})
        self.assertIn("причина не записана", lines[0])

    def test_office_rendering_delegates_and_marks_the_finding(self):
        doc = self._doc(1)
        plain = rsc.report(doc, max_rows=5)
        office = rsc.format_report(doc, max_rows=5)
        self.assertEqual(office[0], f"⚠️ {plain[0]}")
        self.assertEqual(office[1:], plain[1:],
                         "второй копии правила отрисовки быть не должно")

    def test_a_clean_doc_is_not_marked(self):
        doc = self._doc(0)
        self.assertEqual(rsc.format_report(doc), rsc.report(doc, max_rows=5))


class TheMeasurementIsDeterministic(unittest.TestCase):

    def test_two_runs_of_one_tree_agree_modulo_the_clock_and_the_caller(self):
        with TemporaryDirectory() as tmp:
            base = _tree(Path(tmp), executor="RULE = 5\n", guard="RULE = 5\n")
            first, second = _measure(base), _measure(base)
        for doc in (first, second):
            doc.pop("invoked_by", None)
        self.assertEqual(first, second)


class LiveControlOnTheRealTree(unittest.TestCase):
    """Единственное чтение настоящего дерева — и оно проверяет ПРОВЕРЯЕМОСТЬ.

    Требовать здесь известную находку значило бы написать сторожа, который
    краснеет от ПОЧИНКИ дефекта. Поэтому проверяется свойство, безразличное к
    числу находок: каждая напечатанная строка обязана перепроверяться по
    исходникам независимо от прибора.
    """

    @classmethod
    def setUpClass(cls) -> None:
        cls.doc = rsc.measure(_REPO, now=_NOW)

    def test_the_real_tree_is_measured_at_all(self):
        self.assertIn(self.doc["status"], ("CLEAN", "FINDING"))
        self.assertGreater(self.doc["guards"], 100)
        self.assertGreater(self.doc["executors"], 100)

    def test_accounting_identity_holds_on_the_real_tree(self):
        self.assertEqual(self.doc["scanned"],
                         self.doc["classified"] + self.doc["counts"]["unreadable"])

    def test_every_printed_row_survives_an_independent_recheck(self):
        for row in self.doc["rows"]:
            guard = (_REPO / row["guard"]).read_text(encoding="utf-8")
            executor = (_REPO / row["executor"]).read_text(encoding="utf-8")
            gv = rsc.toplevel_constants(ast.parse(guard))[row["name"]]
            ev = rsc.toplevel_constants(ast.parse(executor))[row["name"]]
            self.assertEqual(gv, ev, f"{row['name']}: значения обязаны совпадать")
            self.assertEqual(gv, row["value"])
            self.assertFalse(
                rsc.reaches(guard, rsc.imported_modules(ast.parse(guard)), row["executor"]),
                f"{row['guard']} достаёт {row['executor']} — это не находка")


if __name__ == "__main__":
    unittest.main()
