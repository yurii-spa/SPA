#!/usr/bin/env python3
"""ПРОВЕРКА ПРИНАДЛЕЖНОСТИ как чтение оси направления (ADR-947, цикл #1066, G936 п. 2).

# LLM_FORBIDDEN

**Что здесь проверяется.** Ось направления вреда (ADR-945) спрашивала ТОЛЬКО чтения
рода `loop`, и ADR-946 измерил, что крупнейшая причина `unmeasured` — не пробел
разбора, а эта ГРАНИЦА: «ни одного читающего цикла в области». Заказ G936 п. 2
переносит границу на ОДИН род чтения — проверку принадлежности (`item in NAME`), —
и назвал ИЗВЕСТНЫЙ член класса ДО замера: `if item in SKIP: continue` над пустым
`SKIP` не отсекает ничего ⇒ находок БОЛЬШЕ.

**У каждой пробы СОСЕД с ПРОТИВОПОЛОЖНЫМ ответом** — иначе проба доказывает лишь,
что прибор умеет печатать одно слово: `in` против `not in` · отсечка против
накопления · `not` против его отсутствия · фильтр включения против отсечки ·
принадлежность против индексации производного имени.

**И отдельно — проба на ОДНУ дверь.** Логика «чаще/реже × что делает ветка» общая у
тихой свёртки и у принадлежности; своя копия у второй двери означала бы, что две
двери расходятся МОЛЧА. Это проверяется разбором кода, а не рассуждением.
"""

from __future__ import annotations

import ast
import inspect
import textwrap
import unittest

from spa_core.tests import _empty_collection_harm as ech


def _read(code: str, name: str, index: int = 0) -> tuple:
    """(исход, причина) для index-го чтения имени вне строки его объявления."""
    tree = ast.parse(textwrap.dedent(code))
    parents = ech._parents(tree)
    declared = {
        node.lineno
        for stmt in tree.body
        if isinstance(stmt, (ast.Assign, ast.AnnAssign))
        for node in (stmt.targets if isinstance(stmt, ast.Assign) else [stmt.target])
        if isinstance(node, ast.Name) and node.id == name
    }
    hits = [
        node for node in ast.walk(tree)
        if isinstance(node, ast.Name) and node.id == name and node.lineno not in declared
    ]
    if len(hits) <= index:
        raise AssertionError(f"сцена не содержит чтения {name!r} №{index}")
    return ech.direction_of_one_read(hits[index], parents)


class TheKnownMemberOfTheClass(unittest.TestCase):
    """Член класса, НАЗВАННЫЙ заказом ДО замера. Контроль в обе стороны."""

    def test_a_skip_list_consulted_by_in_and_cut_off_means_MORE(self):
        """`if item in SKIP: continue` над ПУСТЫМ `SKIP`: не отсечён НИ ОДИН
        элемент ⇒ находок БОЛЬШЕ. Дословно форма `_SKIP_PARTS` (ADR-945), но без
        свёртки `any` — до этой двери ось отвечала о ней `unmeasured`."""
        outcome, why = _read("""
            SKIP = ("vendor", "build")
            def run(items):
                out = []
                for item in items:
                    if item in SKIP:
                        continue
                    out.append(item)
                return out
        """, "SKIP")
        self.assertEqual("more", outcome, why)
        self.assertIn("x in NAME", why)
        self.assertIn("cutoff", why)

    def test_an_allow_list_consulted_by_not_in_and_cut_off_means_FEWER(self):
        """СОСЕД с ОБРАТНОЙ полярностью: `not in` над пустым истинно ВСЕГДА ⇒
        отсечено ВСЁ ⇒ находок МЕНЬШЕ. Один и тот же скелет сцены, и ответ
        противоположный — значит ответ принадлежит оператору, а не форме."""
        outcome, why = _read("""
            ALLOW = ("a", "b")
            def run(items):
                out = []
                for item in items:
                    if item not in ALLOW:
                        continue
                    out.append(item)
                return out
        """, "ALLOW")
        self.assertEqual("fewer", outcome, why)
        self.assertIn("x not in NAME", why)


class PolarityAndBranchEffect(unittest.TestCase):
    """Четыре сочетания «оператор × что делает ветка» дают четыре разных ответа."""

    def test_in_guarding_an_accumulation_means_FEWER(self):
        outcome, why = _read("""
            WANTED = ("a",)
            def run(items):
                out = []
                for item in items:
                    if item in WANTED:
                        out.append(item)
                return out
        """, "WANTED")
        self.assertEqual("fewer", outcome, why)
        self.assertIn("accumulates", why)

    def test_not_in_guarding_an_accumulation_means_MORE(self):
        """СОСЕД предыдущей: та же ветка-накопитель, обратный оператор."""
        outcome, why = _read("""
            SEEN = ("a",)
            def run(items):
                out = []
                for item in items:
                    if item not in SEEN:
                        out.append(item)
                return out
        """, "SEEN")
        self.assertEqual("more", outcome, why)

    def test_an_explicit_not_flips_the_answer(self):
        """`if not (item in SKIP): continue` — отрицание меняет эффективную
        истинность операнда, и ответ обязан перевернуться относительно первой
        пробы этого файла."""
        outcome, why = _read("""
            SKIP = ("vendor",)
            def run(items):
                out = []
                for item in items:
                    if not (item in SKIP):
                        continue
                    out.append(item)
                return out
        """, "SKIP")
        self.assertEqual("fewer", outcome, why)

    def test_two_arms_with_opposite_accumulators_mean_BOTH(self):
        outcome, why = _read("""
            KNOWN = ("a",)
            def run(items):
                hits = []
                misses = []
                for item in items:
                    if item in KNOWN:
                        hits.append(item)
                    else:
                        misses.append(item)
                return hits, misses
        """, "KNOWN")
        self.assertEqual("both", outcome, why)

    def test_a_filter_predicate_follows_its_polarity(self):
        """Предикат ВКЛЮЧЕНИЯ, а не отсечка: `in` над пустым ложен ⇒ собрано
        меньше. Сосед — `not in` в том же месте."""
        included, why_in = _read("""
            WANTED = ("a",)
            def run(rows):
                return [row for row in rows if row in WANTED]
        """, "WANTED")
        self.assertEqual("fewer", included, why_in)
        self.assertIn("фильтре включения", why_in)
        excluded, why_out = _read("""
            BANNED = ("a",)
            def run(rows):
                return [row for row in rows if row not in BANNED]
        """, "BANNED")
        self.assertEqual("more", excluded, why_out)


class RefusalsAreNamedAndLeanToUnmeasured(unittest.TestCase):
    """Каждый отказ назван, и ни один не выдаётся за род (инв. #17)."""

    def test_a_comparison_chain_is_UNMEASURED(self):
        outcome, why = _read("""
            MIDDLE = ("a",)
            def run(items):
                out = []
                for item in items:
                    if item in MIDDLE in item:
                        continue
                    out.append(item)
                return out
        """, "MIDDLE")
        self.assertEqual("unmeasured", outcome, why)
        self.assertIn("цепочка сравнений", why)

    def test_the_name_on_the_LEFT_is_UNMEASURED(self):
        """`NAME in registry` спрашивает, не является ли сам перечень ЭЛЕМЕНТОМ
        чужого набора. Другой вопрос, и пустота его не решает."""
        outcome, why = _read("""
            GROUP = ("a",)
            def run(registry, items):
                out = []
                for item in items:
                    if GROUP in registry:
                        continue
                    out.append(item)
                return out
        """, "GROUP")
        self.assertEqual("unmeasured", outcome, why)
        self.assertIn("СЛЕВА", why)

    def test_a_non_membership_operator_is_UNMEASURED(self):
        outcome, why = _read("""
            LIMIT = ("a",)
            def run(items):
                out = []
                for item in items:
                    if item == LIMIT:
                        continue
                    out.append(item)
                return out
        """, "LIMIT")
        self.assertEqual("unmeasured", outcome, why)
        self.assertIn("принадлежностью не является", why)

    def test_a_transparent_wrapper_is_UNMEASURED_by_declared_boundary(self):
        """`item in tuple(NAME)` — пустота сохраняется обёрткой, но подъём через
        обёртки есть ОТДЕЛЬНЫЙ вопрос с НЕ ИЗМЕРЕННЫМ населением (заказ G936
        п. 3). Пройти его молча значило бы ответить о том, чего не смотрели."""
        outcome, why = _read("""
            SKIP = ("a",)
            def run(items):
                out = []
                for item in items:
                    if item in tuple(SKIP):
                        continue
                    out.append(item)
                return out
        """, "SKIP")
        self.assertEqual("unmeasured", outcome, why)
        self.assertIn("не операнд сравнения", why)

    def test_a_membership_outside_a_condition_is_UNMEASURED(self):
        """Принадлежность, чей результат присваивается имени, условием ветки не
        является: что станет с находками, из формы не следует."""
        outcome, why = _read("""
            SKIP = ("a",)
            def run(items):
                flags = []
                for item in items:
                    flag = item in SKIP
                    flags.append(flag)
                return flags
        """, "SKIP")
        self.assertEqual("unmeasured", outcome, why)
        self.assertIn("условием не является", why)

    def test_the_refusal_of_the_loop_path_still_names_itself(self):
        """Чтение, которое не перебор И не принадлежность, обязано нести ОБЕ
        причины — иначе читатель решит, что прибор смотрел только одно."""
        outcome, why = _read("""
            SIZES = ("a",)
            def run():
                return len(SIZES)
        """, "SIZES")
        self.assertEqual("unmeasured", outcome, why)
        self.assertIn("цикл над именем не поднят", why)
        self.assertIn("принадлежность", why)


class TheLoopPathKeepsPriority(unittest.TestCase):
    """Порядок НЕСУЩИЙ: сперва перебор, и только при его отсутствии — принадлежность."""

    def test_an_iterated_name_is_answered_by_the_loop_door(self):
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
        self.assertNotIn("x in NAME", why)


class TheSeedAsksTheNewKindToo(unittest.TestCase):
    """Засев производного имени (ADR-946) спрашивает и о принадлежности."""

    def test_a_derived_name_checked_by_membership_gets_a_direction(self):
        outcome, why = _read("""
            BASE = ("a", "b")
            def run(rows):
                allowed = [item for item in BASE]
                out = []
                for row in rows:
                    if row in allowed:
                        out.append(row)
                return out
        """, "BASE")
        self.assertEqual("fewer", outcome, why)
        self.assertIn("засев `allowed`", why)

    def test_a_derived_name_only_indexed_stays_UNMEASURED(self):
        """СОСЕД предыдущей: `x[k]` — индексация, и над ПУСТЫМ она поднимает
        исключение, то есть пустота замечена ГРОМКО. Род ей не выдаётся.
        Это крупнейшая оставшаяся форма замера ADR-947 (78 чтений из 184)."""
        outcome, why = _read("""
            BASE = (("a", 1),)
            def run(key):
                table = {name: value for name, value in BASE}
                return table[key]
        """, "BASE")
        self.assertEqual("unmeasured", outcome, why)
        self.assertIn("засев `table`", why)
        self.assertIn("ни одной проверки принадлежности", why)


class TheDoorIsOneAndTheVocabularyIsClosed(unittest.TestCase):
    """Объявление несёт свой контракт, а не только условие в теле (ADR-932)."""

    def test_both_forms_call_the_SAME_arm_logic(self):
        """Положительный контроль на РАСХОЖДЕНИЕ двух дверей: обе обязаны звать
        `_direction_from_condition`, и ни одна — не содержать своей копии
        разбора ветвей."""
        for func in (ech._direction_of_silent_fold, ech.direction_of_one_membership_read):
            tree = ast.parse(textwrap.dedent(inspect.getsource(func)))
            called = {
                node.func.id for node in ast.walk(tree)
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
            }
            self.assertIn("_direction_from_condition", called, func.__name__)
            self.assertNotIn("branch_effect", called,
                             f"{func.__name__} несёт СВОЮ копию разбора ветвей")

    def test_the_truth_table_over_empty_is_declared_for_both_operators(self):
        self.assertEqual({"In": False, "NotIn": True}, ech.MEMBERSHIP_TRUTH_OVER_EMPTY)
        self.assertEqual(set(ech.MEMBERSHIP_TRUTH_OVER_EMPTY),
                         set(ech.MEMBERSHIP_TEXT))

    def test_every_outcome_of_the_new_door_is_a_declared_member(self):
        scenes = (
            ("SKIP = ('a',)\ndef r(i):\n    o = []\n    for x in i:\n"
             "        if x in SKIP:\n            continue\n        o.append(x)\n    return o", "SKIP"),
            ("S = ('a',)\ndef r():\n    return len(S)", "S"),
            ("K = ('a',)\ndef r(i):\n    h = []\n    m = []\n    for x in i:\n"
             "        if x in K:\n            h.append(x)\n        else:\n"
             "            m.append(x)\n    return h, m", "K"),
        )
        seen = set()
        for code, name in scenes:
            outcome, why = _read(code, name)
            self.assertIn(outcome, ech.DIRECTION_OUTCOMES, why)
            seen.add(outcome)
        self.assertEqual({"more", "unmeasured", "both"}, seen)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
