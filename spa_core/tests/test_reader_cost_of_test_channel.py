"""Цена читателей канала ТЕСТА и их замыкание на ступень — заказ G70 п. 1.

ADR-447 объявил цену этих читателей неизмеримой ПО ПРИЧИНЕ: «прогон pytest
изнутри ступени породил бы вложенный прогон». Причина — утверждение о
МЕХАНИЗМЕ, и замера у неё не было ни одного. Набор проверяет ровно это: что
причина теперь МЕРИТСЯ (двумя независимыми свидетелями), что цена делится на
ТОТ ЖЕ такт, и что каждый третий исход отличим от рабочих.

У каждого утверждения есть обратная сторона: «уложились» ↔ «не уложились» ↔
«слишком близко»; «замыкания не наблюдено» ↔ «наблюдено» ↔ «не измерено»;
«свидетели согласны» ↔ «спорят» ↔ «неполны»; «прогон не заводился» ↔ «прогон
не измерен» — и ни один из двух не есть ноль.

FROZEN-DATE-OK: injected-clock — литеральных дат в наборе нет вовсе; ни одно
утверждение не зависит от календаря, а цена меряется часами `time.monotonic`
внутри самого прибора и в тестах ИНЪЕКТИРУЕТСЯ подставным прогонщиком.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

from spa_core.monitoring import rule_second_copy_census as mod
from spa_core.monitoring.rule_second_copy_census import (
    BUDGET_DOES_NOT_FIT,
    BUDGET_FITS,
    BUDGET_TOO_CLOSE,
    BUDGET_UNMEASURED,
    CENSUS_MODULE,
    CHILD_RAN_GREEN,
    CHILD_RAN_RED,
    CHILD_REFUSED_NESTED,
    CHILD_UNMEASURED,
    PRODUCER,
    RECURSION_NOT_OBSERVED,
    RECURSION_OBSERVED,
    RECURSION_UNMEASURED,
    REENTRY_ENV,
    REQUIRED_COST_MARGIN,
    STEP_ENTRYPOINTS,
    reader_cost_of_test_channel,
)

#: Такт стенда. Не копия боевого числа: стенд объявляет СВОЙ манифест, и
#: тест на том и стои́т, что бюджет ЧИТАЕТСЯ у объявителя, а не зашит.
STAND_TACT_S = 1000.0


def _stand(tmp: Path, *, tact: str = f"interval:{int(STAND_TACT_S)}s") -> Path:
    """Наименьшее дерево: манифест с производителем артефакта переписи."""
    (tmp / "architecture").mkdir(parents=True, exist_ok=True)
    (tmp / "architecture" / "manifest.json").write_text(json.dumps({
        "agents": [{"label": "com.spa.stand", "schedule": tact,
                    "produces": [{"artifact": mod.BUDGET_ARTIFACT}]}]
    }), encoding="utf-8")
    return tmp


def _harm(*readers: dict) -> dict:
    return {"readers": list(readers)}


def _reader(rel: str, *, decides: bool = True) -> dict:
    return {"file": rel,
            "decides_on_moved": ([{"field": "by_name"}] if decides else [])}


#: Корень дерева, из которого ввозится сам прибор. Дочернему процессу его
#: надо НАЗВАТЬ: `sys.path[0]` у запущенного ПО ПУТИ скрипта — каталог
#: скрипта, а не текущий каталог (урок `.claude/rules/deployment.md`), и
#: дочерний прогон во временном дереве иначе не нашёл бы `spa_core` вовсе.
_REPO_ROOT = Path(mod.__file__).resolve().parents[2]


def _env_reaching_the_repo(**extra) -> dict:
    env = dict(os.environ)
    existing = env.get("PYTHONPATH")
    env["PYTHONPATH"] = (f"{_REPO_ROOT}{os.pathsep}{existing}" if existing
                         else str(_REPO_ROOT))
    env.update(extra)
    return env


def _runner(**per_file):
    """Подставной прогонщик: файл → готовая строка замера."""
    def run(root, rel):
        return dict(per_file[rel])
    return run


def _unnested():
    """Снять признаки вложенности, чтобы пройти НЕ-отказной путь, и НАЗВАТЬ
    дочернему процессу корень дерева: прогонщик копирует `os.environ`, а
    временное дерево `spa_core` само не содержит.

    Помощник живёт на уровне модуля (цикл #669), потому что его зовут ДВА
    набора: `RealRunnerTests` и `ThirdOutcomeUnderFailureTests`. Вторая копия
    этого правила была бы ровно тем классом, который перепись ищет у других.
    Поведение не менялось ни на строку — сменилось только место.
    """
    saved = (os.environ.pop("PYTEST_CURRENT_TEST", None),
             os.environ.get("PYTHONPATH"))
    os.environ.pop(REENTRY_ENV, None)
    os.environ["PYTHONPATH"] = _env_reaching_the_repo()["PYTHONPATH"]
    return saved


def _renested(saved):
    current, pythonpath = saved
    if current is not None:
        os.environ["PYTEST_CURRENT_TEST"] = current
    if pythonpath is None:
        os.environ.pop("PYTHONPATH", None)
    else:
        os.environ["PYTHONPATH"] = pythonpath


def _row(cost, *, outcome=CHILD_RAN_GREEN, recursion=RECURSION_NOT_OBSERVED,
         reentries=0, exit_code=0, file="spa_core/tests/test_a.py"):
    return {"file": file, "cost_s": cost, "exit_code": exit_code,
            "reentries": reentries, "recursion": recursion,
            "outcome": outcome, "why": "стенд"}


class PopulationTests(unittest.TestCase):
    """Население — ВЫВОД соседа, а не список имён в коде."""

    def test_only_test_channel_readers_deciding_on_a_moved_field_are_taken(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = _stand(Path(tmp))
            doc = reader_cost_of_test_channel(
                root,
                _harm(_reader("spa_core/tests/test_a.py"),
                      _reader("spa_core/monitoring/coder.py"),
                      _reader("spa_core/tests/test_b.py", decides=False)),
                {"total_cost_s": 1.0},
                run_file=_runner(**{"spa_core/tests/test_a.py": _row(2.0)}))
        self.assertEqual(doc["population"], ["spa_core/tests/test_a.py"])

    def test_a_code_channel_reader_is_not_in_the_population(self):
        """Обратная сторона: канал КОДА этой координатой не считается."""
        with tempfile.TemporaryDirectory() as tmp:
            root = _stand(Path(tmp))
            doc = reader_cost_of_test_channel(
                root, _harm(_reader("spa_core/monitoring/coder.py")),
                {"total_cost_s": 1.0}, run_file=_runner())
        self.assertEqual(doc["population"], [])
        self.assertEqual(doc["verdict"], BUDGET_UNMEASURED)

    def test_empty_population_is_unmeasured_with_a_named_reason_not_fits(self):
        """Пустое население — НЕ «уложились»: делить нечего, и это сказано."""
        with tempfile.TemporaryDirectory() as tmp:
            root = _stand(Path(tmp))
            doc = reader_cost_of_test_channel(root, _harm(), {"total_cost_s": 1.0},
                                           run_file=_runner())
        self.assertEqual(doc["status"], "UNMEASURED")
        self.assertIn("делить нечего", doc["budget_refused"])

    def test_missing_neighbour_is_unmeasured_not_an_empty_population(self):
        """Соседа нет ⇒ «не из чего вывести», а не «читателей нет»."""
        with tempfile.TemporaryDirectory() as tmp:
            root = _stand(Path(tmp))
            doc = reader_cost_of_test_channel(root, None, {"total_cost_s": 1.0},
                                           run_file=_runner())
        self.assertEqual(doc["verdict"], BUDGET_UNMEASURED)
        self.assertIn("НЕ «читателей", doc["reason"])


class BudgetTests(unittest.TestCase):
    """Сумма делится на ТОТ ЖЕ такт, и порог объявлен ДО замера."""

    def _doc(self, cost, prior, *, tact=f"interval:{int(STAND_TACT_S)}s"):
        with tempfile.TemporaryDirectory() as tmp:
            root = _stand(Path(tmp), tact=tact)
            return reader_cost_of_test_channel(
                root, _harm(_reader("spa_core/tests/test_a.py")),
                ({"total_cost_s": prior} if prior is not None else None),
                run_file=_runner(**{"spa_core/tests/test_a.py": _row(cost)}))

    def test_a_comfortable_sum_fits(self):
        doc = self._doc(10.0, 20.0)
        self.assertEqual(doc["combined_cost_s"], 30.0)
        self.assertEqual(doc["budget_s"], STAND_TACT_S)
        self.assertEqual(doc["verdict"], BUDGET_FITS)
        self.assertGreaterEqual(doc["margin"], REQUIRED_COST_MARGIN)

    def test_a_sum_over_the_tact_does_not_fit(self):
        """Обратная сторона «уложились»."""
        doc = self._doc(900.0, 200.0)
        self.assertEqual(doc["verdict"], BUDGET_DOES_NOT_FIT)
        self.assertEqual(doc["status"], "CRITICAL")

    def test_a_sum_inside_the_tact_but_under_the_margin_is_too_close(self):
        """Третий вердикт: влезает, но запаса нет — решать НЕЛЬЗЯ."""
        doc = self._doc(100.0, 100.0)
        self.assertEqual(doc["verdict"], BUDGET_TOO_CLOSE)
        self.assertLess(doc["margin"], REQUIRED_COST_MARGIN)

    def test_the_tact_is_read_from_the_declarer_not_copied(self):
        """Другой интервал в манифесте даёт другой бюджет — копии числа нет."""
        doc = self._doc(10.0, 20.0, tact="interval:2000s")
        self.assertEqual(doc["budget_s"], 2000.0)

    def test_an_unreadable_tact_is_unmeasured_not_a_fit(self):
        doc = self._doc(10.0, 20.0, tact="cron:daily")
        self.assertEqual(doc["verdict"], BUDGET_UNMEASURED)
        self.assertIsNone(doc["margin"])

    def test_a_missing_prior_cost_makes_the_sum_unmeasured_not_the_channel_cost(self):
        """Цена пересчёта не измерена ⇒ суммы НЕТ. Подставить цену канала
        значило бы ответить не на тот вопрос: такт у них общий."""
        doc = self._doc(10.0, None)
        self.assertEqual(doc["total_cost_s"], 10.0)
        self.assertIsNone(doc["combined_cost_s"])
        self.assertEqual(doc["verdict"], BUDGET_UNMEASURED)

    def test_a_non_positive_sum_is_unmeasured_not_an_infinite_margin(self):
        doc = self._doc(0.0, 0.0)
        self.assertEqual(doc["verdict"], BUDGET_UNMEASURED)
        self.assertIn("не положительна", doc["budget_refused"])


class RecursionOutcomeTests(unittest.TestCase):
    """Замыкание: наблюдено · не наблюдено · НЕ ИЗМЕРЕНО — три разных исхода."""

    def _doc(self, row):
        with tempfile.TemporaryDirectory() as tmp:
            root = _stand(Path(tmp))
            return reader_cost_of_test_channel(
                root, _harm(_reader("spa_core/tests/test_a.py")),
                {"total_cost_s": 1.0},
                run_file=_runner(**{"spa_core/tests/test_a.py": row}))

    def test_no_marks_at_a_run_that_happened_is_not_observed(self):
        doc = self._doc(_row(2.0, reentries=0))
        self.assertEqual(doc["counts"]["recursion_not_observed"], 1)
        self.assertEqual(doc["counts"]["recursion_observed"], 0)

    def test_marks_at_a_run_that_happened_is_observed_and_a_finding(self):
        """Обратная сторона: замыкание ЕСТЬ — причина ADR-447 подтверждается."""
        doc = self._doc(_row(2.0, reentries=3, recursion=RECURSION_OBSERVED))
        self.assertEqual(doc["counts"]["recursion_observed"], 1)
        kinds = {f["kind"] for f in doc["findings"]}
        self.assertIn("test_channel_closes_on_own_step", kinds)
        self.assertNotIn("refusal_reason_refuted_by_measurement", kinds)

    def test_a_run_that_never_happened_is_unmeasured_not_not_observed(self):
        """Отказ от вложенности отметок не даёт ПО ПОСТРОЕНИЮ: его ноль —
        третий исход, а не «замыкания нет»."""
        doc = self._doc({"file": "spa_core/tests/test_a.py", "cost_s": None,
                         "exit_code": None, "reentries": None,
                         "recursion": RECURSION_UNMEASURED,
                         "outcome": CHILD_REFUSED_NESTED, "why": "стенд"})
        self.assertEqual(doc["counts"]["recursion_unmeasured"], 1)
        self.assertEqual(doc["counts"]["recursion_not_observed"], 0)
        self.assertEqual(doc["counts"]["refused_nested"], 1)
        self.assertEqual(doc["verdict"], BUDGET_UNMEASURED)

    def test_refused_and_unmeasured_are_counted_apart(self):
        """«Прогон не заводился» ≠ «прогон не измерен»: разные события."""
        doc = self._doc({"file": "spa_core/tests/test_a.py", "cost_s": None,
                         "exit_code": None, "reentries": None,
                         "recursion": RECURSION_UNMEASURED,
                         "outcome": CHILD_UNMEASURED, "why": "инструмента нет"})
        self.assertEqual(doc["counts"]["unmeasured"], 1)
        self.assertEqual(doc["counts"]["refused_nested"], 0)


class FindingTests(unittest.TestCase):
    """Находка о причине отказа — только когда её ОПРОВЕРГ замер."""

    def _doc(self, rows, prior=1.0, tact=f"interval:{int(STAND_TACT_S)}s"):
        with tempfile.TemporaryDirectory() as tmp:
            root = _stand(Path(tmp), tact=tact)
            readers = [_reader(r["file"]) for r in rows]
            return reader_cost_of_test_channel(
                root, _harm(*readers), {"total_cost_s": prior},
                run_file=_runner(**{r["file"]: r for r in rows}))

    def test_refusal_reason_is_refuted_when_nothing_closes_and_the_sum_fits(self):
        doc = self._doc([_row(2.0, file="spa_core/tests/test_a.py"),
                         _row(3.0, file="spa_core/tests/test_b.py")])
        kinds = {f["kind"] for f in doc["findings"]}
        self.assertIn("refusal_reason_refuted_by_measurement", kinds)

    def test_the_reason_is_not_refuted_when_the_sum_does_not_fit(self):
        """Обратная сторона: замыкания нет, но по карману НЕ было."""
        doc = self._doc([_row(2000.0, file="spa_core/tests/test_a.py")])
        kinds = {f["kind"] for f in doc["findings"]}
        self.assertNotIn("refusal_reason_refuted_by_measurement", kinds)

    def test_the_reason_is_not_refuted_while_one_reader_stays_unmeasured(self):
        """Один неизмеренный файл — и опровержения НЕТ: «не измерено» не есть
        «не замыкается»."""
        doc = self._doc([_row(2.0, file="spa_core/tests/test_a.py"),
                         {"file": "spa_core/tests/test_b.py", "cost_s": None,
                          "exit_code": None, "reentries": None,
                          "recursion": RECURSION_UNMEASURED,
                          "outcome": CHILD_UNMEASURED, "why": "стенд"}])
        kinds = {f["kind"] for f in doc["findings"]}
        self.assertNotIn("refusal_reason_refuted_by_measurement", kinds)

    def test_a_red_reader_is_a_finding_and_its_price_is_still_measured(self):
        doc = self._doc([_row(2.0, outcome=CHILD_RAN_RED, exit_code=1,
                              file="spa_core/tests/test_a.py")])
        kinds = {f["kind"] for f in doc["findings"]}
        self.assertIn("test_channel_reader_is_red", kinds)
        self.assertEqual(doc["total_cost_s"], 2.0)

    def test_a_green_reader_raises_no_red_finding(self):
        doc = self._doc([_row(2.0, file="spa_core/tests/test_a.py")])
        kinds = {f["kind"] for f in doc["findings"]}
        self.assertNotIn("test_channel_reader_is_red", kinds)


class StaticWitnessTests(unittest.TestCase):
    """Второй свидетель — разбор текста, и его СОБСТВЕННАЯ слепота названа."""

    def _file(self, tmp: Path, body: str, rel="spa_core/tests/test_x.py"):
        path = tmp / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(textwrap.dedent(body), encoding="utf-8")
        return rel

    def test_an_attribute_call_of_the_step_is_seen(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            rel = self._file(root, f"""
                from {CENSUS_MODULE.rsplit('.', 1)[0]} import \\
                    {CENSUS_MODULE.rsplit('.', 1)[1]} as m
                def test_x():
                    m.measure(None)
            """)
            self.assertIs(mod._static_reaches_step(root, rel)["reaches"], True)

    def test_a_named_import_of_the_step_is_seen(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            rel = self._file(root, f"""
                from {CENSUS_MODULE} import measure
                def test_x():
                    measure(None)
            """)
            self.assertIs(mod._static_reaches_step(root, rel)["reaches"], True)

    def test_importing_the_module_without_calling_the_step_is_not_reaching(self):
        """Обратная сторона: ввоз есть, ступени нет. Зов ОДНОЙ координаты
        ступенью не является."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            rel = self._file(root, f"""
                from {CENSUS_MODULE} import report
                def test_x():
                    report({{}})
            """)
            self.assertIs(mod._static_reaches_step(root, rel)["reaches"], False)

    def test_a_missing_file_is_unmeasured_not_false(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = mod._static_reaches_step(Path(tmp), "nope/test_x.py")
        self.assertIsNone(out["reaches"])
        self.assertIn("нет в дереве", out["why"])

    def test_an_unparseable_file_is_unmeasured_not_false(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            rel = self._file(root, "def broken(:\n")
            out = mod._static_reaches_step(root, rel)
        self.assertIsNone(out["reaches"])

    def test_the_witness_sees_one_level_of_repo_imports(self):
        """Глубина 1 объявлена и работает: ступень за ввезённым модулем видна."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "spa_core" / "helpers").mkdir(parents=True)
            (root / "spa_core" / "helpers" / "mid.py").write_text(
                f"from {CENSUS_MODULE} import measure\n"
                "def go():\n    return measure(None)\n", encoding="utf-8")
            rel = self._file(root, """
                from spa_core.helpers import mid
                def test_x():
                    mid.go()
            """)
            self.assertIs(mod._static_reaches_step(root, rel)["reaches"], True)

    def test_the_witness_is_blind_past_its_declared_depth(self):
        """Слепота КОСВЕННОГО свидетеля названа, а не подразумевается."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "spa_core" / "helpers").mkdir(parents=True)
            (root / "spa_core" / "helpers" / "far.py").write_text(
                f"from {CENSUS_MODULE} import measure\n"
                "def go():\n    return measure(None)\n", encoding="utf-8")
            (root / "spa_core" / "helpers" / "mid.py").write_text(
                "from spa_core.helpers import far\n"
                "def go():\n    return far.go()\n", encoding="utf-8")
            rel = self._file(root, """
                from spa_core.helpers import mid
                def test_x():
                    mid.go()
            """)
            self.assertIs(mod._static_reaches_step(root, rel)["reaches"], False)


class WitnessAgreementTests(unittest.TestCase):
    """Согласие свидетелей · спор · неполнота — три состояния, и спор есть
    ПРЕДМЕТ, а не шум."""

    def _doc(self, tmp: Path, body: str, row: dict):
        rel = "spa_core/tests/test_x.py"
        path = tmp / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(textwrap.dedent(body), encoding="utf-8")
        _stand(tmp)
        return reader_cost_of_test_channel(
            tmp, _harm(_reader(rel)), {"total_cost_s": 1.0},
            run_file=_runner(**{rel: dict(row, file=rel)}))

    def test_both_witnesses_saying_no_agree(self):
        with tempfile.TemporaryDirectory() as tmp:
            doc = self._doc(Path(tmp), "def test_x():\n    pass\n", _row(2.0))
        self.assertEqual(doc["counts"]["witnesses_agree"], 1)

    def test_text_says_yes_and_observation_says_no_is_a_disagreement_finding(self):
        with tempfile.TemporaryDirectory() as tmp:
            doc = self._doc(Path(tmp), f"""
                from {CENSUS_MODULE} import measure
                def test_x():
                    measure(None)
            """, _row(2.0))
        self.assertEqual(doc["counts"]["witnesses_disagree"], 1)
        self.assertIn("recursion_witnesses_disagree",
                      {f["kind"] for f in doc["findings"]})

    def test_an_unmeasured_observation_leaves_the_witnesses_incomplete(self):
        """Неполнота — НЕ согласие и НЕ спор."""
        with tempfile.TemporaryDirectory() as tmp:
            doc = self._doc(Path(tmp), "def test_x():\n    pass\n",
                            {"cost_s": None, "exit_code": None,
                             "reentries": None,
                             "recursion": RECURSION_UNMEASURED,
                             "outcome": CHILD_REFUSED_NESTED, "why": "стенд"})
        self.assertEqual(doc["counts"]["witnesses_incomplete"], 1)
        self.assertEqual(doc["counts"]["witnesses_agree"], 0)


class ReentryNoteTests(unittest.TestCase):
    """Отметка входа — НАБЛЮДЕНИЕ, и у него есть положительный контроль."""

    def test_the_note_is_silent_when_the_process_was_not_marked(self):
        saved = os.environ.pop(REENTRY_ENV, None)
        try:
            mod._reentry_note("measure")      # побочного действия быть не должно
        finally:
            if saved is not None:
                os.environ[REENTRY_ENV] = saved

    def test_the_note_writes_one_line_per_entry_when_marked(self):
        with tempfile.TemporaryDirectory() as tmp:
            ledger = Path(tmp) / "reentry.log"
            os.environ[REENTRY_ENV] = str(ledger)
            try:
                mod._reentry_note("measure")
                mod._reentry_note("measure")
            finally:
                os.environ.pop(REENTRY_ENV, None)
            lines = [ln for ln in ledger.read_text(encoding="utf-8").splitlines()
                     if ln]
        self.assertEqual(len(lines), 2)
        self.assertTrue(all(str(os.getpid()) in ln for ln in lines))

    def test_a_child_that_ENTERS_the_step_leaves_a_mark(self):
        """ПОЛОЖИТЕЛЬНЫЙ КОНТРОЛЬ наблюдения: без него «отметок ноль» было бы
        украшением — ноль, который не умеет становиться единицей."""
        with tempfile.TemporaryDirectory() as tmp:
            ledger = Path(tmp) / "reentry.log"
            script = Path(tmp) / "child.py"
            script.write_text(
                "from pathlib import Path\n"
                f"from {CENSUS_MODULE} import measure, NotMeasured\n"
                "try:\n"
                "    measure(Path('/definitely/not/a/tree'))\n"
                "except NotMeasured:\n"
                "    pass\n", encoding="utf-8")
            env = _env_reaching_the_repo(**{REENTRY_ENV: str(ledger)})
            proc = subprocess.run([sys.executable, str(script)],
                                  capture_output=True, text=True, timeout=300,
                                  env=env)
            self.assertEqual(proc.returncode, 0, proc.stderr)
            marks = [ln for ln in ledger.read_text(encoding="utf-8").splitlines()
                     if ln]
        self.assertEqual(len(marks), 1)

    def test_a_child_that_only_IMPORTS_leaves_no_mark(self):
        """Обратная сторона контроля: ввоз ступенью не является."""
        with tempfile.TemporaryDirectory() as tmp:
            ledger = Path(tmp) / "reentry.log"
            ledger.write_text("", encoding="utf-8")
            script = Path(tmp) / "child.py"
            script.write_text(f"import {CENSUS_MODULE}\n", encoding="utf-8")
            env = _env_reaching_the_repo(**{REENTRY_ENV: str(ledger)})
            proc = subprocess.run([sys.executable, str(script)],
                                  capture_output=True, text=True, timeout=300,
                                  env=env)
            self.assertEqual(proc.returncode, 0, proc.stderr)
            marks = [ln for ln in ledger.read_text(encoding="utf-8").splitlines()
                     if ln]
        self.assertEqual(marks, [])


class ToolPresenceTests(unittest.TestCase):
    """Наличие инструмента — ОТДЕЛЬНЫЙ вопрос, и задаётся он отдельно."""

    def test_the_probe_answers_with_a_verdict_and_a_reason(self):
        present, why = mod._pytest_available()
        self.assertIs(present, True)
        self.assertTrue(why)

    def test_a_missing_tool_is_none_or_false_never_a_zero_cost(self):
        saved = sys.executable
        try:
            sys.executable = "/definitely/not/a/python"
            present, why = mod._pytest_available()
        finally:
            sys.executable = saved
        self.assertIsNot(present, True)
        self.assertTrue(why)


class RealRunnerTests(unittest.TestCase):
    """Настоящий прогонщик: отказы и НЕ-отказ. Инъекция прячет разбор входа,
    поэтому сам прогонщик проверяется своим кодом, а не подставным."""

    def test_the_runner_refuses_inside_pytest_and_says_why(self):
        """Причина ADR-447 ВЕРНА для этого зова — и теперь она ИЗМЕРЕНА."""
        self.assertIn("PYTEST_CURRENT_TEST", os.environ)
        out = mod._run_test_file(Path("."), "spa_core/tests/test_a.py")
        self.assertEqual(out["outcome"], CHILD_REFUSED_NESTED)
        self.assertIn("вложенн", out["why"])
        self.assertIsNone(out["cost_s"])

    def test_the_runner_refuses_inside_a_marked_child_first(self):
        os.environ[REENTRY_ENV] = "/tmp/never-written"
        try:
            out = mod._run_test_file(Path("."), "spa_core/tests/test_a.py")
        finally:
            os.environ.pop(REENTRY_ENV, None)
        self.assertEqual(out["outcome"], CHILD_REFUSED_NESTED)
        self.assertIn("второго уровня", out["why"])

    _unnested = staticmethod(_unnested)
    _renested = staticmethod(_renested)

    def test_the_runner_prices_a_real_child_and_observes_no_closure(self):
        saved = self._unnested()
        try:
            with tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                rel = "test_tiny.py"
                (root / rel).write_text("def test_ok():\n    assert True\n",
                                        encoding="utf-8")
                out = mod._run_test_file(root, rel, timeout=300)
        finally:
            self._renested(saved)
        self.assertEqual(out["outcome"], CHILD_RAN_GREEN)
        self.assertGreater(out["cost_s"], 0)
        self.assertEqual(out["recursion"], RECURSION_NOT_OBSERVED)
        self.assertEqual(out["reentries"], 0)

    def test_a_failing_child_is_priced_and_marked_red(self):
        """Обратная сторона: красный читатель цену всё равно имеет."""
        saved = self._unnested()
        try:
            with tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                rel = "test_tiny.py"
                (root / rel).write_text("def test_no():\n    assert False\n",
                                        encoding="utf-8")
                out = mod._run_test_file(root, rel, timeout=300)
        finally:
            self._renested(saved)
        self.assertEqual(out["outcome"], CHILD_RAN_RED)
        self.assertNotEqual(out["exit_code"], 0)
        self.assertGreater(out["cost_s"], 0)

    def test_a_child_that_ENTERS_the_step_is_observed_by_the_runner(self):
        """ПОЛОЖИТЕЛЬНЫЙ КОНТРОЛЬ всей проводки наблюдения: прогонщик обязан
        УМЕТЬ увидеть замыкание, иначе его `not_observed` — украшение."""
        saved = self._unnested()
        try:
            with tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                rel = "test_tiny.py"
                (root / rel).write_text(
                    "from pathlib import Path\n"
                    f"from {CENSUS_MODULE} import measure, NotMeasured\n"
                    "def test_enters():\n"
                    "    try:\n"
                    "        measure(Path('/definitely/not/a/tree'))\n"
                    "    except NotMeasured:\n"
                    "        pass\n", encoding="utf-8")
                out = mod._run_test_file(root, rel, timeout=300)
        finally:
            self._renested(saved)
        self.assertEqual(out["recursion"], RECURSION_OBSERVED)
        self.assertGreaterEqual(out["reentries"], 1)

    def test_a_missing_file_is_unmeasured_not_a_zero_price(self):
        saved = self._unnested()
        try:
            with tempfile.TemporaryDirectory() as tmp:
                out = mod._run_test_file(Path(tmp), "nope/test_x.py")
        finally:
            self._renested(saved)
        self.assertEqual(out["outcome"], CHILD_UNMEASURED)
        self.assertIsNone(out["cost_s"])


class _FrozenClock:
    """Часы, которые НЕ ИДУТ. Всё остальное — настоящий `time`.

    Инъекция здесь обязательна и заменить её нечем: «неположительная цена»
    достижима только тогда, когда часы соврали, а настоящие часы врать по
    заказу не умеют. Объект делегирует всё, кроме `monotonic`, чтобы подмена
    меняла ровно одно свойство — предмет замера, а не окружение целиком.
    """

    def __init__(self, real, at=1000.0):
        self._real, self._at = real, at

    def monotonic(self):
        return self._at

    def __getattr__(self, name):
        return getattr(self._real, name)


class ThirdOutcomeUnderFailureTests(unittest.TestCase):
    """Три исхода, у которых обратной стороны НЕ БЫЛО (замер цикла #669).

    Батарея мутаций цикла #668 оставила ровно трёх выживших, и все три —
    одного класса: код честно разводит «не измерено» и «измерено», а ни один
    тест этого не требует. Выжившая мутация значит, что утверждение держится
    на прозе автора; проверяется здесь именно ОНА, координата в координату:

    * ``if reentries is None`` → ``if False`` — нечитаемый журнал отметок
      прочёлся бы как «замыкания не наблюдено». Это fail-OPEN: тише красного
      теста и потому опаснее.
    * ``if proc.returncode != 0`` → ``if False`` — сломанный (а не
      отсутствующий) pytest объявился бы исправным. Соседний тест мерил
      только ветку ИСКЛЮЧЕНИЯ (`sys.executable` не существует), и ветка
      «инструмент есть, но отвечает ненулевым» не была пройдена ни разу —
      ровно та подмена «с другой стороны», о которой предупреждает
      `.claude/rules/deployment.md`.
    * ``if cost <= 0`` → ``if False`` — ноль секунд выдался бы за цену.
    """

    def test_a_ledger_the_child_destroyed_is_unmeasured_not_not_observed(self):
        """Журнал отметок пропал ⇒ замыкание НЕ ИЗМЕРЕНО, и причина названа.

        Журнал рушит сам дочерний прогон — это настоящее событие, а не
        подмена чтения: так ветка проходится тем же кодом, каким её пройдёт
        авария.
        """
        saved = _unnested()
        try:
            with tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                rel = "test_tiny.py"
                (root / rel).write_text(
                    "import os, pathlib\n"
                    "def test_destroys_the_ledger():\n"
                    f"    pathlib.Path(os.environ[{REENTRY_ENV!r}]).unlink()\n",
                    encoding="utf-8")
                out = mod._run_test_file(root, rel, timeout=300)
        finally:
            _renested(saved)
        self.assertEqual(out["outcome"], CHILD_RAN_GREEN)
        self.assertGreater(out["cost_s"], 0)        # цена ИЗМЕРЕНА
        self.assertIsNone(out["reentries"])         # отметки — НЕТ
        self.assertEqual(out["recursion"], RECURSION_UNMEASURED)
        self.assertTrue(out.get("reentry_unreadable"),
                        "причина, по которой журнал не прочитан, обязана "
                        "доехать до читателя строки, а не осесть в словаре, "
                        "который никто не возвращает")
        self.assertIn("НЕ ПРОЧИТАН", out["why"])

    def test_a_readable_ledger_still_reads_as_not_observed(self):
        """Обратная сторона предыдущего: целый журнал с нулём отметок — это
        «не наблюдено», а вовсе не «не измерено». Без этой пары проверка
        выше была бы выполнима подменой всех нулей на `unmeasured`."""
        saved = _unnested()
        try:
            with tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                rel = "test_tiny.py"
                (root / rel).write_text("def test_ok():\n    assert True\n",
                                        encoding="utf-8")
                out = mod._run_test_file(root, rel, timeout=300)
        finally:
            _renested(saved)
        self.assertEqual(out["reentries"], 0)
        self.assertEqual(out["recursion"], RECURSION_NOT_OBSERVED)
        self.assertIsNone(out.get("reentry_unreadable"))

    def test_a_tool_that_answers_non_zero_is_absent_not_present(self):
        """Инструмент ЕСТЬ, но отвечает ненулевым ⇒ `False`, не `True`.

        Сосед подставляет несуществующий путь и проходит ветку исключения;
        сломанный инструмент — другое событие и другая ветка.
        """
        with tempfile.TemporaryDirectory() as tmp:
            shim = Path(tmp) / "python-that-answers-badly"
            shim.write_text("#!/bin/sh\nexit 3\n", encoding="utf-8")
            shim.chmod(0o755)
            saved = sys.executable
            try:
                sys.executable = str(shim)
                present, why = mod._pytest_available()
            finally:
                sys.executable = saved
        self.assertIs(present, False)
        self.assertIn("3", why)

    def test_a_broken_tool_makes_the_price_unmeasured_at_the_caller(self):
        """Тот же вопрос у ПОТРЕБИТЕЛЯ: сломанный инструмент обязан дать
        третий исход, а не цену прогона, который на самом деле мерил чужой
        код возврата."""
        saved = _unnested()
        try:
            with tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                rel = "test_tiny.py"
                (root / rel).write_text("def test_ok():\n    assert True\n",
                                        encoding="utf-8")
                shim = root / "python-that-answers-badly"
                shim.write_text("#!/bin/sh\nexit 3\n", encoding="utf-8")
                shim.chmod(0o755)
                saved_exe = sys.executable
                try:
                    sys.executable = str(shim)
                    out = mod._run_test_file(root, rel, timeout=300)
                finally:
                    sys.executable = saved_exe
        finally:
            _renested(saved)
        self.assertEqual(out["outcome"], CHILD_UNMEASURED)
        self.assertIsNone(out["cost_s"])
        self.assertIn("инструмента нет", out["why"])

    def test_a_clock_that_does_not_advance_is_unmeasured_not_a_zero_price(self):
        """Ноль секунд ценой не является — и прогон при этом СОСТОЯЛСЯ.

        Проверяется обе половины: цена не измерена (`cost_s is None`), но код
        возврата дочернего прогона записан. Слить их значило бы выдать
        «мерить не получилось» за «прогона не было».
        """
        saved = _unnested()
        real_time = mod.time
        try:
            with tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                rel = "test_tiny.py"
                (root / rel).write_text("def test_ok():\n    assert True\n",
                                        encoding="utf-8")
                mod.time = _FrozenClock(real_time)
                try:
                    out = mod._run_test_file(root, rel, timeout=300)
                finally:
                    mod.time = real_time
        finally:
            _renested(saved)
        self.assertEqual(out["outcome"], CHILD_UNMEASURED)
        self.assertIsNone(out["cost_s"])
        self.assertEqual(out["exit_code"], 0)
        self.assertIn("не положительная", out["why"])

    def test_the_frozen_clock_is_not_inert(self):
        """Контроль самой подмены: с настоящими часами тот же прогон даёт
        ЦЕНУ. Без этой строки предыдущий тест был бы выполним прибором,
        который не меряет вовсе."""
        saved = _unnested()
        try:
            with tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                rel = "test_tiny.py"
                (root / rel).write_text("def test_ok():\n    assert True\n",
                                        encoding="utf-8")
                out = mod._run_test_file(root, rel, timeout=300)
        finally:
            _renested(saved)
        self.assertEqual(out["outcome"], CHILD_RAN_GREEN)
        self.assertGreater(out["cost_s"], 0)


class WiringTests(unittest.TestCase):
    """Проводка: ключ в документе, секция в отчёте, имя модуля ВЫВЕДЕНО."""

    def test_the_census_module_name_is_derived_from_the_producer_path(self):
        """Набранное рядом имя было бы второй копией пути — тем самым
        классом, который перепись ищет у других."""
        self.assertEqual(CENSUS_MODULE, PRODUCER[:-3].replace("/", "."))
        text = Path(mod.__file__).read_text(encoding="utf-8")
        self.assertNotIn(f'"{CENSUS_MODULE}"', text)

    def test_measure_calls_the_coordinate_and_stores_it_under_its_own_key(self):
        source = Path(mod.__file__).read_text(encoding="utf-8")
        self.assertIn("test_channel_cost = reader_cost_of_test_channel(", source)
        self.assertIn('"reader_cost_of_test_channel": test_channel_cost,', source)

    def test_measure_marks_its_own_entry_before_any_refusal(self):
        """Отметка стои́т ДО проверки корня: вопрос «замкнулся ли прогон» не
        зависит от того, довела ли ступень работу до конца."""
        source = Path(mod.__file__).read_text(encoding="utf-8")
        head = source.split("def measure(", 1)[1]
        note = head.index('_reentry_note("measure")')
        refusal = head.index("корень дерева не прочитан")
        self.assertLess(note, refusal)

    def test_the_report_prints_the_section(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = _stand(Path(tmp))
            coord = reader_cost_of_test_channel(
                root, _harm(_reader("spa_core/tests/test_a.py")),
                {"total_cost_s": 1.0},
                run_file=_runner(**{"spa_core/tests/test_a.py": _row(2.0)}))
        lines = mod.report({"reader_cost_of_test_channel": coord})
        self.assertTrue(any("[ЦЕНА КАНАЛА ТЕСТА]" in ln for ln in lines))
        self.assertTrue(any("[ЦЕНА КАНАЛА ТЕСТА · УЧЁТ]" in ln for ln in lines))

    def test_the_section_speaks_when_the_coordinate_is_absent(self):
        """Ключа нет ⇒ «НЕ ИЗМЕРЕНА», а не молчание."""
        lines = mod.report({})
        self.assertTrue(any("[ЦЕНА КАНАЛА ТЕСТА] НЕ ИЗМЕРЕНА" in ln
                            for ln in lines))

    def test_the_section_is_not_nested_under_the_neighbouring_coordinate(self):
        """Секция вынесена ЗА блок цены пересчёта: вложенная в его `else`, она
        молчала бы ровно там, где цена пересчёта не измерена."""
        with tempfile.TemporaryDirectory() as tmp:
            root = _stand(Path(tmp))
            coord = reader_cost_of_test_channel(
                root, _harm(_reader("spa_core/tests/test_a.py")),
                {"total_cost_s": 1.0},
                run_file=_runner(**{"spa_core/tests/test_a.py": _row(2.0)}))
        lines = mod.report({
            "recompute_cost_budget": {"verdict": BUDGET_UNMEASURED,
                                      "budget_refused": "стенд"},
            "reader_cost_of_test_channel": coord})
        self.assertTrue(any("[ЦЕНА ПЕРЕСЧЁТА] НЕ ИЗМЕРЕНА" in ln
                            for ln in lines))
        self.assertTrue(any("[ЦЕНА КАНАЛА ТЕСТА] канал" in ln for ln in lines))

    def test_the_step_entrypoints_are_the_names_of_the_step(self):
        for name in STEP_ENTRYPOINTS:
            self.assertTrue(callable(getattr(mod, name)))

    def test_no_production_callable_is_named_like_a_test(self):
        """Своя находка на доставке: функция прибора, названная `test_*`,
        СОБИРАЕТСЯ pytest как тест у каждого, кто её ввозит, и падает на
        «fixture 'root' not found» — красный набор из-за ИМЕНИ, а не из-за
        поведения. Первая редакция этой координаты звалась ровно так."""
        import ast as _ast
        tree = _ast.parse(Path(mod.__file__).read_text(encoding="utf-8"))
        named = [node.name for node in tree.body
                 if isinstance(node, (_ast.FunctionDef, _ast.AsyncFunctionDef))
                 and node.name.startswith("test")]
        self.assertEqual(named, [])

    def test_the_coordinate_is_advisory(self):
        """Порога не вводится, вердикта переписи координата не меняет."""
        with tempfile.TemporaryDirectory() as tmp:
            root = _stand(Path(tmp))
            doc = reader_cost_of_test_channel(
                root, _harm(_reader("spa_core/tests/test_a.py")),
                {"total_cost_s": 1.0},
                run_file=_runner(**{"spa_core/tests/test_a.py": _row(2.0)}))
        self.assertIs(doc["applied"], False)
        self.assertEqual(doc["order"], "G70.1")


if __name__ == "__main__":
    unittest.main()
