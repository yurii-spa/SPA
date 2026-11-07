#!/usr/bin/env python3
"""Ось НАПРАВЛЕНИЯ вреда пустого перечня (ADR-945, цикл #1064, заказ G934 п. 4).

# LLM_FORBIDDEN

**Что здесь проверяется.** `survived` стенда ADR-944 означает РОВНО «пустоту не
заметил ни один собственный тест модуля» — и НЕ означает «молча усиливает». Ось
направления отвечает на другой вопрос: станет находок МЕНЬШЕ (тишина) или БОЛЬШЕ
(шум) от того, что перечень опустел. Оба состояния — дефекты, но лечатся разным.

**У каждой пробы СОСЕД с ПРОТИВОПОЛОЖНЫМ ответом** — иначе проба доказывает только,
что прибор умеет печатать одно слово: `any` против `all` · отсечка против накопления ·
`not` против его отсутствия · `min` (громко) против `any` (тихо) · собранное
отдаваемое против собранного уходящего дальше.
"""

from __future__ import annotations

import ast
import textwrap
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from spa_core.tests import _empty_collection_harm as ech


def _read(code: str, name: str) -> tuple:
    """Разбирает сцену и отдаёт (исход, причина) для ПЕРВОГО чтения имени внутри цикла.

    Строка объявления из поиска исключается: объявление само себя не читает.
    """
    source = textwrap.dedent(code)
    tree = ast.parse(source)
    parents = ech._parents(tree)
    declared = {
        node.lineno
        for stmt in tree.body
        if isinstance(stmt, ast.Assign)
        for node in stmt.targets
        if isinstance(node, ast.Name) and node.id == name
    }
    hits = [
        node for node in ast.walk(tree)
        if isinstance(node, ast.Name) and node.id == name and node.lineno not in declared
    ]
    if not hits:
        raise AssertionError(f"сцена не содержит чтения {name!r} вне объявления")
    return ech.direction_of_one_read(hits[0], parents)


class DirectionOfOneRead(unittest.TestCase):
    """Род ОДНОГО чтения. Каждая пара — положительный контроль в обе стороны."""

    def test_for_loop_that_accumulates_means_FEWER(self):
        outcome, why = _read("""
            NAMES = ("a", "b")
            def run():
                out = []
                for item in NAMES:
                    out.append(item)
                return out
        """, "NAMES")
        self.assertEqual("fewer", outcome, why)
        self.assertIn("витков НОЛЬ", why)

    def test_for_loop_that_only_validates_is_UNMEASURED(self):
        """СОСЕД предыдущей: тело не накапливает ⇒ чего станет меньше, из формы не
        следует. Назвать это `fewer` значило бы выдумать направление."""
        outcome, why = _read("""
            NAMES = ("a", "b")
            def run():
                for item in NAMES:
                    validate(item)
        """, "NAMES")
        self.assertEqual("unmeasured", outcome, why)
        self.assertIn("без накопления", why)

    def test_any_under_a_cutoff_means_MORE(self):
        """Дословная форма `presence_as_observation_census._SKIP_PARTS`: `any` над
        пустым ложен ⇒ отсечка НЕ срабатывает ⇒ сквозь неё проходит БОЛЬШЕ."""
        outcome, why = _read("""
            SKIP = ("/tmp/", "/build/")
            def run(paths):
                out = []
                for path in paths:
                    if any(part in path for part in SKIP):
                        continue
                    out.append(path)
                return out
        """, "SKIP")
        self.assertEqual("more", outcome, why)
        self.assertIn("cutoff", why)

    def test_negated_any_under_a_cutoff_means_FEWER(self):
        """СОСЕД: то же `any`, та же отсечка, добавлено `not` — и ответ
        ПРОТИВОПОЛОЖНЫЙ: над пустым отсечка срабатывает ВСЕГДА, сквозь неё не
        проходит НИЧЕГО. Полярность несущая, а не оговорка."""
        outcome, why = _read("""
            KEEP = ("/src/", "/lib/")
            def run(paths):
                out = []
                for path in paths:
                    if not any(part in path for part in KEEP):
                        continue
                    out.append(path)
                return out
        """, "KEEP")
        self.assertEqual("fewer", outcome, why)

    def test_all_under_a_cutoff_means_FEWER(self):
        """СОСЕД по свёртке: `all` над пустым ИСТИНЕН ⇒ отсечка срабатывает всегда.
        Сложить `any` и `all` в одну таблицу значило бы ответить наоборот."""
        outcome, why = _read("""
            RULES = ("a", "b")
            def run(rows):
                out = []
                for row in rows:
                    if all(rule in row for rule in RULES):
                        continue
                    out.append(row)
                return out
        """, "RULES")
        self.assertEqual("fewer", outcome, why)

    def test_any_guarding_a_finding_means_FEWER(self):
        """Та же свёртка, но ветка НАКАПЛИВАЕТ находку, а не исключает элемент ⇒
        направление ПРОТИВОПОЛОЖНО отсечке: находка не добавится никогда."""
        outcome, why = _read("""
            BAD = ("err", "fail")
            def run(rows):
                findings = []
                for row in rows:
                    if any(mark in row for mark in BAD):
                        findings.append(row)
                return findings
        """, "BAD")
        self.assertEqual("fewer", outcome, why)
        self.assertIn("accumulates", why)

    def test_all_guarding_a_finding_means_MORE(self):
        """СОСЕД предыдущей: `all` над пустым истинен ⇒ находка добавится ВСЕГДА."""
        outcome, why = _read("""
            NEEDED = ("a", "b")
            def run(rows):
                findings = []
                for row in rows:
                    if all(mark in row for mark in NEEDED):
                        findings.append(row)
                return findings
        """, "NEEDED")
        self.assertEqual("more", outcome, why)

    def test_two_arms_with_different_accumulators_mean_BOTH(self):
        """Дословная форма `failure_cause_census._FOREIGN`. ADR-944 назвал её родом
        «больше» — замер даёт `both`: у `if` ДВЕ ветки, накопители в них РАЗНЫЕ, и
        пустота двигает их в ПРОТИВОПОЛОЖНЫЕ стороны. Свести к одному роду значило бы
        потерять ровно то, ради чего ось заведена (урок ADR-943)."""
        outcome, why = _read("""
            FOREIGN = ("site-packages", "/usr/")
            def run(lines):
                mine, foreign = [], 0
                for line in lines:
                    if any(mark in line for mark in FOREIGN) or line.startswith("/"):
                        foreign += 1
                    else:
                        mine.append(line)
                return mine, foreign
        """, "FOREIGN")
        self.assertEqual("both", outcome, why)
        self.assertIn("fewer", why)
        self.assertIn("more", why)

    def test_or_chain_is_climbed_because_substitution_is_MONOTONE(self):
        """`and` рядом с `or`: подстановка константы вместо ОДНОГО операнда двигает
        «срабатывает ли ветка» РОВНО в одну сторону, поэтому значения соседних
        операндов знать не нужно."""
        outcome, why = _read("""
            SKIP = ("a", "b")
            def run(rows):
                out = []
                for row in rows:
                    if any(m in row for m in SKIP) and row.ready:
                        continue
                    out.append(row)
                return out
        """, "SKIP")
        self.assertEqual("more", outcome, why)

    def test_a_non_monotone_wrapper_is_UNMEASURED(self):
        """СОСЕД предыдущей: `== True` монотонности не сохраняет — подъём ОБРЫВАЕТСЯ
        третьим исходом, а не угадывает сторону."""
        outcome, why = _read("""
            SKIP = ("a", "b")
            def run(rows):
                out = []
                for row in rows:
                    if (any(m in row for m in SKIP)) == row.flag:
                        continue
                    out.append(row)
                return out
        """, "SKIP")
        self.assertEqual("unmeasured", outcome, why)
        self.assertIn("условием не является", why)

    def test_a_loud_fold_is_UNMEASURED_not_a_direction(self):
        """`min` над пустым поднимает ValueError: пустота замечена ГРОМКО, предмета
        нет. СОСЕД — та же форма с `any`, у которой ответ есть."""
        loud, why_loud = _read("""
            SIZES = (1, 2)
            def run():
                return min(size for size in SIZES)
        """, "SIZES")
        self.assertEqual("unmeasured", loud, why_loud)
        self.assertIn("ГРОМКО", why_loud)
        quiet, why_quiet = _read("""
            SIZES = (1, 2)
            def run(rows):
                out = []
                for row in rows:
                    if any(size > row for size in SIZES):
                        continue
                    out.append(row)
                return out
        """, "SIZES")
        self.assertEqual("more", quiet, why_quiet)

    def test_a_filter_predicate_follows_its_polarity(self):
        """Включающий фильтр включения против исключающего — ответы
        ПРОТИВОПОЛОЖНЫЕ при одной свёртке."""
        including, why_in = _read("""
            HINTS = ("tol", "eps")
            def run(names):
                return [n for n in names if any(h in n for h in HINTS)]
        """, "HINTS")
        self.assertEqual("fewer", including, why_in)
        excluding, why_ex = _read("""
            HINTS = ("tol", "eps")
            def run(names):
                return [n for n in names if not any(h in n for h in HINTS)]
        """, "HINTS")
        self.assertEqual("more", excluding, why_ex)

    def test_a_collected_comprehension_that_escapes_is_UNMEASURED(self):
        """Собранное, ушедшее дальше: меньше собранных элементов означает МЕНЬШЕ
        находок, если это находки, и БОЛЬШЕ — если это множество-исключение.
        Направление решает СЛЕДУЮЩИЙ шаг, и выдумывать его здесь значило бы вернуть
        «два бита под одним именем»."""
        outcome, why = _read("""
            KEYS = ("a", "b")
            def run():
                known = [k.upper() for k in KEYS]
                return check(known)
        """, "KEYS")
        self.assertEqual("unmeasured", outcome, why)
        self.assertIn("уходит дальше", why)

    def test_a_collected_comprehension_handed_straight_out_is_FEWER(self):
        """СОСЕД предыдущей: собранное ОТДАЁТСЯ сразу — следующего шага нет, и
        направление определено."""
        returned, why_ret = _read("""
            KEYS = ("a", "b")
            def run():
                return [k.upper() for k in KEYS]
        """, "KEYS")
        self.assertEqual("fewer", returned, why_ret)
        appended, why_app = _read("""
            KEYS = ("a", "b")
            def run(out):
                out.extend([k.upper() for k in KEYS])
        """, "KEYS")
        self.assertEqual("fewer", appended, why_app)


class BranchEffect(unittest.TestCase):
    """Род ветки. Отсечка имеет ПРИОРИТЕТ над накоплением — это выбор, и он измерим."""

    @staticmethod
    def _body(code: str):
        return ast.parse(textwrap.dedent(code)).body[0].body  # type: ignore[attr-defined]

    def test_every_answer_is_a_declared_member(self):
        """Объявление `BRANCH_EFFECTS` ЧИТАЕТСЯ — и опустошить его молча нельзя:
        проба требует членства И непустоты самого объявления (противоядие класса,
        которому посвящён модуль)."""
        self.assertTrue(ech.BRANCH_EFFECTS, "перечень родов ветки ПУСТ")
        scenes = ("if x:\n    continue", "if x:\n    out.append(1)", "if x:\n    pass")
        answers = {ech.branch_effect(self._body(code)) for code in scenes}
        self.assertEqual(set(ech.BRANCH_EFFECTS), answers,
                         "сцены обязаны покрыть КАЖДЫЙ объявленный род ветки")

    def test_a_pruning_branch_that_also_exits_is_a_CUTOFF(self):
        """Дословная ветка `_SKIP_PARTS`: `dirnames[:] = []` + `continue`. Подрезка
        похожа на накопление (`NAME[k] =`), но элемент до пути находок не доходит ни
        при каком содержимом ветки ⇒ род её отсечка, а не «и то и другое»."""
        self.assertEqual("cutoff", ech.branch_effect(
            self._body("if skip:\n    dirnames[:] = []\n    continue")))

    def test_an_accumulating_branch_without_an_exit_ACCUMULATES(self):
        self.assertEqual("accumulates", ech.branch_effect(
            self._body("if bad:\n    findings.append(row)")))

    def test_a_return_with_a_value_is_not_a_cutoff(self):
        """`return build_finding()` элемент не исключает — он находку ОТДАЁТ. СОСЕД
        — `return None`, который исключает."""
        self.assertEqual("none", ech.branch_effect(
            self._body("if bad:\n    return build_finding(row)")))
        self.assertEqual("cutoff", ech.branch_effect(
            self._body("if bad:\n    return None")))


class DirectionOfADeclaration(unittest.TestCase):
    """Свод по объявлению: роды чтений СКЛАДЫВАЮТСЯ, расхождение даёт `both`."""

    def setUp(self):
        self._tmp = TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)

    def _row(self, rel: str, name: str, lines):
        return {"module": rel, "name": name, "lineno": 1, "form": "tuple",
                "reads": {"loop": [f"{rel}:{n}" for n in lines]}}

    def test_two_reads_pointing_opposite_ways_give_BOTH(self):
        rel = "scene.py"
        (self.root / rel).write_text(textwrap.dedent("""\
            MARKS = ("a", "b")
            def quiet(rows):
                out = []
                for row in rows:
                    if any(m in row for m in MARKS):
                        out.append(row)
                return out
            def noisy(rows):
                out = []
                for row in rows:
                    if any(m in row for m in MARKS):
                        continue
                    out.append(row)
                return out
        """))
        result = ech.direction([self._row(rel, "MARKS", (5, 11))], root=self.root)
        self.assertEqual("both", result["rows"][0]["direction"], result["rows"][0]["why"])
        self.assertEqual({"fewer": 0, "more": 0, "both": 1, "unmeasured": 0}, result["tally"])

    def test_one_unmeasured_read_does_not_lock_a_measured_sibling(self):
        """`unmeasured` у ОТДЕЛЬНОГО чтения род объявления не запирает — иначе одна
        неразобранная форма объявляла бы неизвестным направление, уже измеренное
        соседним чтением."""
        rel = "scene.py"
        (self.root / rel).write_text(textwrap.dedent("""\
            MARKS = ("a", "b")
            def measured(rows):
                out = []
                for row in rows:
                    if any(m in row for m in MARKS):
                        continue
                    out.append(row)
                return out
            def murky():
                known = [m.upper() for m in MARKS]
                return check(known)
        """))
        result = ech.direction([self._row(rel, "MARKS", (5, 10))], root=self.root)
        self.assertEqual("more", result["rows"][0]["direction"], result["rows"][0]["why"])

    def test_an_unreadable_reader_is_UNMEASURED_with_a_named_reason(self):
        """Третий исход ГРОМКИЙ: файл, который не разобран, мог нести ЛЮБОЕ чтение,
        и «направления нет» из этого не следует (инв. #17)."""
        rel = "broken.py"
        (self.root / rel).write_text("def f(:\n    pass\n")
        result = ech.direction([self._row(rel, "MARKS", (1,))], root=self.root)
        self.assertEqual("unmeasured", result["rows"][0]["direction"])
        self.assertIn(rel, result["unparsable_readers"])
        self.assertTrue(any("НЕ РАЗОБРАН" in w for w in result["rows"][0]["why"]))

    def test_a_declaration_with_no_loop_read_is_UNMEASURED(self):
        result = ech.direction([{"module": "x.py", "name": "N", "lineno": 1,
                                 "reads": {"loop": []}}], root=self.root)
        self.assertEqual("unmeasured", result["rows"][0]["direction"])
        self.assertTrue(any("ось к объявлению не относится" in w
                            for w in result["rows"][0]["why"]))

    def test_the_tally_declares_exactly_the_four_outcomes(self):
        """Своё объявление тоже обязано иметь читателя непустоты: опустошить
        `DIRECTION_OUTCOMES` молча нельзя."""
        self.assertTrue(ech.DIRECTION_OUTCOMES, "перечень исходов ПУСТ")
        result = ech.direction([], root=self.root)
        self.assertEqual(set(ech.DIRECTION_OUTCOMES), set(result["tally"]))
        self.assertEqual(("fewer", "more", "both", "unmeasured"), ech.DIRECTION_OUTCOMES)

    def test_the_truth_table_over_empty_is_declared_and_not_empty(self):
        """`any` → False · `all` → True · `sum` → 0. Громкие свёртки сюда не входят:
        склеить тихую и громкую пустоту значило бы потерять единственное свойство,
        которым они различаются."""
        self.assertTrue(ech.TRUTH_OVER_EMPTY, "таблица истинности ПУСТА")
        self.assertEqual({"any": False, "all": True, "sum": False}, ech.TRUTH_OVER_EMPTY)
        self.assertEqual(set(ech.SILENT_FOLDS), set(ech.TRUTH_OVER_EMPTY))
        self.assertFalse(set(ech.LOUD_FOLDS) & set(ech.TRUTH_OVER_EMPTY))


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
