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


#: Минимальные «пороги RiskPolicy» для синтетической сцены. Число 0.07 выбрано
#: так, чтобы НЕ совпасть ни с одним значением сцен: иначе всякая находка
#: уезжала бы владельцем, и сцена мерила бы не то, ради чего написана.
_POLICY = "MAX_DRAWDOWN = 0.07\n"


def _tree(base: Path, *, executor: str = "", guard: str = "",
          extra: dict | None = None) -> Path:
    """Минимальное дерево: исполнитель, сторож и обязательные каталоги.

    Каталоги `spa_core/` и `scripts/` создаются оба: их отсутствие — отдельный
    исход прибора (`UNMEASURED`), и смешивать его со сценой было бы нечестно.
    """
    (base / "spa_core" / "tests").mkdir(parents=True)
    (base / "scripts").mkdir(parents=True)
    (base / "scripts" / "__init__.py").write_text("", encoding="utf-8")
    # Пороги RiskPolicy — предпосылка КАЖДОЙ сцены: без них прибор отвечает
    # `UNMEASURED` (право чинить спрашивается до переписи). Сцена, забывшая их,
    # мерила бы отказ, а не свой предмет.
    (base / "spa_core" / "risk").mkdir(parents=True, exist_ok=True)
    (base / "spa_core" / "risk" / "policy.py").write_text(
        _POLICY if extra is None or "spa_core/risk/policy.py" not in extra else "",
        encoding="utf-8")
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


class RiskPolicyThresholdsAreReadOrTheRunRefuses(unittest.TestCase):
    """Право чинить спрашивается ПЕРВЫМ — и «не прочитано» не есть «нет совпадений»."""

    def test_field_defaults_of_a_dataclass_are_thresholds_too(self):
        with TemporaryDirectory() as tmp:
            base = _tree(Path(tmp), extra={
                "spa_core/risk/policy.py": (
                    "from dataclasses import dataclass\n"
                    "TOP = 0.40\n"
                    "@dataclass\n"
                    "class RiskConfig:\n"
                    "    min_cash_pct: float = 0.05\n"
                    "    label: str = 'v1.0'\n"
                    "    flag: bool = True\n"
                )})
            got = rsc.risk_policy_thresholds(base)
        self.assertEqual(got.get("0.05"), ["min_cash_pct"],
                         "умолчание поля датакласса — тоже порог")
        self.assertEqual(got.get("0.4"), ["TOP"])
        self.assertNotIn("'v1.0'", got, "строка порогом не является")
        self.assertNotIn("True", got, "флаг порогом не является")

    def test_one_number_declared_twice_names_BOTH(self):
        """Обратная сторона: назвать первое имя значило бы приписать чужой смысл."""
        with TemporaryDirectory() as tmp:
            base = _tree(Path(tmp), extra={
                "spa_core/risk/policy.py": "A = 0.05\nB = 0.05\n"})
            got = rsc.risk_policy_thresholds(base)
        self.assertEqual(got["0.05"], ["A", "B"])

    def test_unreadable_policy_is_the_third_outcome_not_an_empty_set(self):
        with TemporaryDirectory() as tmp:
            base = Path(tmp)
            (base / "spa_core" / "tests").mkdir(parents=True)
            (base / "scripts").mkdir(parents=True)
            with self.assertRaises(rsc.NotMeasured):
                rsc.risk_policy_thresholds(base)

    def test_a_whole_run_without_policy_reports_UNMEASURED(self):
        """Население ЧИТАЕТСЯ целиком, нет только порогов — отказ обязан назвать ИХ.

        Сцена собирается руками, а не ``_tree``: та пороги кладёт всегда, и
        отказ, который здесь меряется, был бы недостижим.
        """
        with TemporaryDirectory() as tmp:
            base = Path(tmp)
            (base / "spa_core" / "tests").mkdir(parents=True)
            (base / "scripts").mkdir(parents=True)
            (base / "spa_core" / "e.py").write_text("X = 1\n", encoding="utf-8")
            (base / "spa_core" / "tests" / "test_g.py").write_text("X = 1\n",
                                                                   encoding="utf-8")
            out = rsc.run(base, dest=base / "out.json", write=False, now=_NOW)
        self.assertEqual(out["doc"]["status"], "UNMEASURED")
        self.assertIn("RiskPolicy", out["doc"]["reason"])

    def test_the_population_root_refusal_still_comes_FIRST(self):
        """Обратная сторона порядка: нет корня населения ⇒ отказ называет ЕГО."""
        with TemporaryDirectory() as tmp:
            base = Path(tmp)
            (base / "spa_core" / "tests").mkdir(parents=True)
            (base / "spa_core" / "tests" / "test_g.py").write_text("X = 1\n",
                                                                   encoding="utf-8")
            out = rsc.run(base, dest=base / "out.json", write=False, now=_NOW)
        self.assertEqual(out["doc"]["status"], "UNMEASURED")
        self.assertNotIn("RiskPolicy", out["doc"]["reason"])


class WitnessOfASharedSubject(unittest.TestCase):
    """Свидетель односторонний, и граница слова обязана быть."""

    def test_dotted_tail_of_two_links_is_a_witness(self):
        self.assertEqual(
            rsc.subject_witness("см. `owner_queue.queue.set_status` — отказывает там",
                                "spa_core/owner_queue/queue.py"),
            "owner_queue.queue")

    def test_file_name_is_a_witness(self):
        self.assertEqual(
            rsc.subject_witness("# must match baseanalytics_migration_summary.py",
                                "scripts/baseanalytics_migration_summary.py"),
            "baseanalytics_migration_summary.py")

    def test_a_NEIGHBOUR_is_not_a_witness(self):
        """`orchestrator_queue.py` назван — значит назван СОСЕД, а не `queue.py`."""
        self.assertIsNone(
            rsc.subject_witness("python3 scripts/orchestrator_queue.py probe",
                                "spa_core/owner_queue/queue.py"))

    def test_a_longer_name_is_not_a_witness_either(self):
        self.assertIsNone(rsc.subject_witness("queue.python", "x/queue.py"))

    def test_silence_is_not_a_witness(self):
        self.assertIsNone(rsc.subject_witness("random.Random(SEED)",
                                              "spa_core/backtesting/tier1/monte_carlo.py"))


class RemedyFormIsMeasured(unittest.TestCase):
    """Три формы + третий исход, и порядок ветвей проверен отдельно."""

    ROW = {"verdict": rsc.CLASS_TWO_COPIES, "guard": "tests/test_g.py",
           "executor": "spa_core/e.py", "name": "N", "value": "0.05"}

    def test_witness_at_the_guard_gives_import(self):
        got = rsc.classify_remedy(dict(self.ROW), guard_text="про spa_core.e рядом",
                                  executor_text="", thresholds={})
        self.assertEqual(got["remedy"], rsc.REMEDY_IMPORT)
        self.assertEqual(got["witness_side"], "guard")

    def test_witness_at_the_executor_counts_too(self):
        got = rsc.classify_remedy(dict(self.ROW), guard_text="",
                                  executor_text="сверено с tests/test_g.py",
                                  thresholds={})
        self.assertEqual(got["remedy"], rsc.REMEDY_IMPORT)
        self.assertEqual(got["witness_side"], "executor")

    def test_no_witness_is_UNPROVEN_not_coincidence(self):
        got = rsc.classify_remedy(dict(self.ROW), guard_text="", executor_text="",
                                  thresholds={})
        self.assertEqual(got["remedy"], rsc.REMEDY_UNPROVEN)
        self.assertIn("НЕ ДОКАЗАН", got["remedy_evidence"])

    def test_owner_subject_wins_EVEN_WHEN_a_witness_exists(self):
        """Порядок ветвей и есть предмет теста: право чинить раньше способа."""
        got = rsc.classify_remedy(dict(self.ROW), guard_text="про spa_core.e рядом",
                                  executor_text="", thresholds={"0.05": ["min_cash_pct"]})
        self.assertEqual(got["remedy"], rsc.REMEDY_OWNER)
        self.assertEqual(got["owner_threshold_names"], ["min_cash_pct"])

    def test_every_colliding_threshold_is_named(self):
        got = rsc.classify_remedy(dict(self.ROW), guard_text="", executor_text="",
                                  thresholds={"0.05": ["a", "b", "c"]})
        for name in ("a", "b", "c"):
            self.assertIn(f"`{name}`", got["remedy_evidence"])

    def test_unreadable_side_is_its_own_outcome(self):
        got = rsc.classify_remedy(dict(self.ROW), guard_text=None, executor_text="",
                                  thresholds={})
        self.assertEqual(got["remedy"], rsc.REMEDY_UNREADABLE)
        self.assertIn("guard", got["remedy_evidence"])


class RemedyCountsAreAccountedFor(unittest.TestCase):
    """Каждая находка несёт форму, и сумма форм равна числу находок."""

    def test_findings_carry_a_remedy_and_the_sums_agree(self):
        with TemporaryDirectory() as tmp:
            base = _tree(Path(tmp),
                         executor="import os\nSEED = 42\n",
                         guard="SEED = 42\n")
            doc = _measure(base)
        findings = [r for r in doc["rows"] if r["verdict"] == rsc.CLASS_TWO_COPIES]
        self.assertTrue(findings)
        for row in findings:
            self.assertIn(row["remedy"], rsc._REMEDY_CLASSES)
            self.assertTrue(row["remedy_evidence"])
        self.assertEqual(sum(doc["remedy_counts"].values()), len(findings))

    def test_a_named_executor_moves_the_pair_out_of_unproven(self):
        """Обратная сторона той же сцены: одно упоминание меняет вердикт формы."""
        with TemporaryDirectory() as tmp:
            base = _tree(Path(tmp),
                         executor="import os\nSEED = 42\n",
                         # Свидетель ИМЕНЕМ ФАЙЛА: точечный хвост `spa_core.e`
                         # у двузвенного пути есть сама дверь, и пара ушла бы
                         # из находок ещё до разбора форм.
                         guard="# сверено с e.py\nSEED = 42\n")
            doc = _measure(base)
        row = [r for r in doc["rows"] if r["verdict"] == rsc.CLASS_TWO_COPIES][0]
        self.assertEqual(row["remedy"], rsc.REMEDY_IMPORT)

    def test_report_prints_the_remedy_and_says_so_when_it_is_absent(self):
        with TemporaryDirectory() as tmp:
            base = _tree(Path(tmp),
                         executor="import os\nSEED = 42\n",
                         guard="SEED = 42\n")
            doc = _measure(base)
        text = "\n".join(rsc.report(doc))
        self.assertIn("[ФОРМА ПОЧИНКИ]", text)
        self.assertIn(rsc.REMEDY_UNPROVEN, text)
        doc.pop("remedy_counts")
        self.assertIn("НЕ ИЗМЕРЕНА", "\n".join(rsc.report(doc)))


class TheTwoGuardsFixedByThisOrderHoldNoCopy(unittest.TestCase):
    """Исход заказа G42 п. 1 — у починенных сторожей имя ОДНО, а не равное.

    Проверяется тождество объекта, а не равенство значений: равные копии
    выглядят точно так же и разойдутся при первой же правке одной из сторон.
    """

    def test_acceptance_ratchet_uses_the_queue_own_statuses(self):
        from spa_core.owner_queue import queue as q
        from spa_core.tests import test_inbox_acceptance_ratchet as ratchet
        self.assertIs(ratchet.INTAKE_STATUSES, q.INTAKE_STATUSES)

    def test_baseanalytics_guard_asks_the_executor_for_the_phases(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "_bac_guard", _REPO / "tests" / "test_baseanalytics_complete.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        self.assertIs(mod.PHASE_1, mod._summary.PHASE_1)
        self.assertIs(mod.PHASE_2, mod._summary.PHASE_2)
        self.assertIs(mod.PHASE_3, mod._summary.PHASE_3)


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
