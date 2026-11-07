#!/usr/bin/env python3
"""Положительный контроль ЗАСЕВА производного имени (ADR-946, заказ G935 п. 2).

# LLM_FORBIDDEN

**Что здесь проверяется.** Ось направления вреда (ADR-945) отдавала `unmeasured`
крупнейшей причиной «результат включения уходит дальше»: пустота перечня ДОКАЗЫВАЕТ
пустоту `x` в форме `x = [… for … in NAME]`, а направление лежит у читателей `x`.
Засев переадресует вопрос им (`_direction_through_name`).

**Почему у каждой сцены есть СОСЕД с противоположным ответом.** Проба, зелёная только
на одной стороне, не отличает «прибор считает» от «прибор всегда отвечает так же» —
дословно урок ADR-913 (сторож сравнивал свои константы сам с собой). Поэтому к сцене
«тишина» приложена сцена «шум» на том же каркасе, а к каждому отказу засева — сцена,
где ровно та же форма БЕЗ помехи даёт род.

**И отдельно проверяется НАПРАВЛЕНИЕ ошибки.** Требование заказа G935 п. 2 — ошибаться
в сторону `unmeasured`, а не рода. Каждая помеха (второе связывание, мутация на месте,
параметр, `global`, `except … as`, импорт, тело класса, распаковка, бюджет) проверяется
ОТДЕЛЬНОЙ сценой и обязана дать `unmeasured` с НАЗВАННОЙ причиной.
"""

from __future__ import annotations

import ast
import unittest
from typing import List, Tuple

from spa_core.tests import _empty_collection_harm as h

NAME = "_DECLARED"


def verdicts(source: str, name: str = NAME) -> List[Tuple[str, str]]:
    """Направление для КАЖДОГО чтения `name` рода `loop` в разборе источника."""
    tree = ast.parse(source)
    parents = h._parents(tree)
    out: List[Tuple[str, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and node.id == name \
                and isinstance(node.ctx, ast.Load):
            kind, loop = h._enclosing_loop(node, parents)
            if loop is None:
                continue
            out.append(h.direction_of_one_read(node, parents))
    return out


def one(source: str, name: str = NAME) -> Tuple[str, str]:
    """Единственный вердикт; иначе падать ГРОМКО — сцена не обеспечила предпосылку."""
    got = verdicts(source, name)
    if len(got) != 1:
        raise AssertionError(
            f"сцена обязана дать РОВНО одно чтение рода `loop`, дала {len(got)}: {got}")
    return got[0]


class SeedingAnswersTheNextStep(unittest.TestCase):
    """Род берётся у ЧИТАТЕЛЕЙ производного имени, а не выдумывается."""

    def test_collected_then_looped_with_accumulation_is_fewer(self):
        verdict, why = one("""
def scan(rows):
    picked = [row for row in _DECLARED]
    findings = []
    for item in picked:
        findings.append(item)
    return findings
""")
        self.assertEqual("fewer", verdict, why)
        self.assertIn("засев `picked`", why)

    def test_the_neighbour_with_a_cutoff_predicate_is_more(self):
        """Тот же каркас, ПРОТИВОПОЛОЖНЫЙ ответ: пустое множество-исключение
        перестаёт отсекать, и находок становится БОЛЬШЕ."""
        verdict, why = one("""
def scan(markers):
    skip = [part for part in _DECLARED]
    findings = []
    for marker in markers:
        if any(part in marker for part in skip):
            continue
        findings.append(marker)
    return findings
""")
        self.assertEqual("more", verdict, why)
        self.assertIn("засев `skip`", why)

    def test_annotated_binding_is_seeded_too(self):
        verdict, why = one("""
from typing import List

def scan():
    picked: List[str] = [row for row in _DECLARED]
    out = []
    for item in picked:
        out.append(item)
    return out
""")
        self.assertEqual("fewer", verdict, why)

    def test_walrus_binding_is_seeded_too(self):
        verdict, why = one("""
def scan():
    out = []
    if (picked := [row for row in _DECLARED]):
        for item in picked:
            out.append(item)
    return out
""")
        self.assertEqual("fewer", verdict, why)

    def test_two_readers_pulling_opposite_ways_give_both(self):
        """Расхождение складывается в `both`, а не в произвольную сторону —
        то же правило, что у прямых чтений (ADR-945)."""
        verdict, why = one("""
def scan(markers):
    picked = [part for part in _DECLARED]
    findings = []
    for item in picked:
        findings.append(item)
    for marker in markers:
        if any(part in marker for part in picked):
            continue
        findings.append(marker)
    return findings
""")
        self.assertEqual("both", verdict, why)

    def test_a_chain_of_two_names_is_traced_to_the_end(self):
        verdict, why = one("""
def scan():
    first = [row for row in _DECLARED]
    second = [row for row in first]
    out = []
    for item in second:
        out.append(item)
    return out
""")
        self.assertEqual("fewer", verdict, why)
        self.assertIn("засев `second`", why)

    def test_module_scope_binding_read_inside_a_function(self):
        verdict, why = one("""
picked = [row for row in _DECLARED]

def scan():
    out = []
    for item in picked:
        out.append(item)
    return out
""")
        self.assertEqual("fewer", verdict, why)


class SeedingRefusesWhateverBreaksTheProof(unittest.TestCase):
    """Пустота `x` обязана СЛЕДОВАТЬ из пустоты перечня. Не следует ⇒ `unmeasured`."""

    def _refused(self, source: str, needle: str):
        verdict, why = one(source)
        self.assertEqual("unmeasured", verdict, why)
        self.assertIn(needle, why)
        return why

    def test_second_binding_refuses(self):
        self._refused("""
def scan(flag, rows):
    picked = [row for row in _DECLARED]
    if flag:
        picked = rows
    out = []
    for item in picked:
        out.append(item)
    return out
""", "связывается в области 2 раз(а)")

    def test_in_place_extension_refuses(self):
        self._refused("""
def scan(rows):
    picked = [row for row in _DECLARED]
    picked += rows
    out = []
    for item in picked:
        out.append(item)
    return out
""", "дополняется на месте")

    def test_in_place_mutation_refuses(self):
        self._refused("""
def scan(row):
    picked = [item for item in _DECLARED]
    picked.append(row)
    out = []
    for item in picked:
        out.append(item)
    return out
""", "мутируется на месте")

    def test_a_parameter_of_the_same_name_refuses(self):
        self._refused("""
def scan():
    picked = [row for row in _DECLARED]
    out = []
    for item in picked:
        out.append(item)

    def helper(picked):
        return len(picked)

    return out, helper
""", "параметр функции")

    def test_global_declaration_refuses(self):
        self._refused("""
def scan():
    global picked
    picked = [row for row in _DECLARED]
    out = []
    for item in picked:
        out.append(item)
    return out
""", "связывание вне области")

    def test_except_as_binding_refuses(self):
        self._refused("""
def scan(rows):
    picked = [row for row in _DECLARED]
    out = []
    for item in picked:
        out.append(item)
    try:
        rows.sort()
    except ValueError as picked:
        out.append(picked)
    return out
""", "`except … as`")

    def test_import_under_the_same_name_refuses(self):
        self._refused("""
def scan():
    import json as picked
    picked = [row for row in _DECLARED]
    out = []
    for item in picked:
        out.append(item)
    return out
""", "связывается импортом")

    def test_a_function_of_the_same_name_refuses(self):
        self._refused("""
def scan():
    picked = [row for row in _DECLARED]
    out = []
    for item in picked:
        out.append(item)

    def picked():
        return 1

    return out, picked
""", "связывается определением")

    def test_class_body_binding_refuses(self):
        self._refused("""
class Holder:
    picked = [row for row in _DECLARED]

    def scan(self):
        out = []
        for item in self.picked:
            out.append(item)
        return out
""", "ТЕЛЕ КЛАССА")

    def test_unpacking_is_not_a_name(self):
        self._refused("""
def scan(rest):
    picked, tail = [row for row in _DECLARED], rest
    out = []
    for item in picked:
        out.append(item)
    return out
""", "ИМЕНИ ему не дано")

    def test_assignment_into_an_attribute_is_not_a_name(self):
        self._refused("""
def scan(self):
    self.picked = [row for row in _DECLARED]
    out = []
    for item in self.picked:
        out.append(item)
    return out
""", "ИМЕНИ ему не дано")

    def test_no_reading_loop_in_the_scope_is_unmeasured(self):
        self._refused("""
def scan():
    picked = [row for row in _DECLARED]
    return len(picked)
""", "ни одного читающего цикла")

    def test_a_reader_whose_own_form_is_unknown_stays_unmeasured(self):
        """Засев не выдумывает род за читателя: `for … in x` без накопления в теле
        остаётся `unmeasured` и после переадресации."""
        self._refused("""
def scan(sink):
    picked = [row for row in _DECLARED]
    for item in picked:
        sink(item)
    return None
""", "рода не дало ни одно чтение")

    def test_budget_exhaustion_is_the_third_outcome_not_a_kind(self):
        """Цепочка длиннее бюджета обрывается НАЗВАННОЙ причиной. Положительный
        контроль самого бюджета: на той же цепочке с достаточным бюджетом род есть."""
        chain = """
def scan():
    n0 = [row for row in _DECLARED]
    n1 = [row for row in n0]
    n2 = [row for row in n1]
    n3 = [row for row in n2]
    n4 = [row for row in n3]
    n5 = [row for row in n4]
    n6 = [row for row in n5]
    out = []
    for item in n6:
        out.append(item)
    return out
"""
        tree = ast.parse(chain)
        parents = h._parents(tree)
        hits = [node for node in ast.walk(tree)
                if isinstance(node, ast.Name) and node.id == NAME
                and isinstance(node.ctx, ast.Load)]
        self.assertEqual(1, len(hits), "сцена обязана дать одно чтение перечня")
        starved, why_starved = h.direction_of_one_read(hits[0], parents, seeds_left=3)
        self.assertEqual("unmeasured", starved, why_starved)
        self.assertIn("ОБОРВАНО", why_starved)
        fed, why_fed = h.direction_of_one_read(hits[0], parents, seeds_left=9)
        self.assertEqual("fewer", fed, why_fed)


class DirectFormsAnswerExactlyAsBefore(unittest.TestCase):
    """Отрицательный контроль: засев не переписал ответы ADR-945 ни на одной форме."""

    def test_plain_for_with_accumulation_is_still_fewer(self):
        verdict, why = one("""
def scan():
    out = []
    for item in _DECLARED:
        out.append(item)
    return out
""")
        self.assertEqual("fewer", verdict, why)
        self.assertNotIn("засев", why)

    def test_comprehension_returned_outright_is_still_fewer(self):
        verdict, why = one("""
def scan():
    return [row for row in _DECLARED]
""")
        self.assertEqual("fewer", verdict, why)
        self.assertNotIn("засев", why)

    def test_loud_fold_is_still_not_a_subject(self):
        verdict, why = one("""
def scan():
    return max(len(row) for row in _DECLARED)
""")
        self.assertEqual("unmeasured", verdict, why)
        self.assertIn("ГРОМКО", why)

    def test_silent_fold_in_a_cutoff_branch_is_still_more(self):
        verdict, why = one("""
def scan(markers):
    findings = []
    for marker in markers:
        if any(part in marker for part in _DECLARED):
            continue
        findings.append(marker)
    return findings
""")
        self.assertEqual("more", verdict, why)
        self.assertNotIn("засев", why)

    def _chain_of(self, names: int) -> str:
        body = ["def scan():", "    n0 = [row for row in _DECLARED]"]
        for step in range(1, names):
            body.append(f"    n{step} = [row for row in n{step - 1}]")
        body += ["    out = []", f"    for item in n{names - 1}:",
                 "        out.append(item)", "    return out"]
        return "\n".join(body)

    def test_default_budget_is_the_declared_one_in_BOTH_directions(self):
        """Бюджет по умолчанию обязан БРАТЬСЯ из объявления, а не из литерала рядом.

        Паритет мерится ДВУМЯ крайностями: цепочка РОВНО в `SEED_HOPS` производных
        имён обязана дать род, а на один длиннее — ОБОРВАТЬСЯ. Одна сторона проверки
        пропустила бы и литерал поменьше (всё «оборвано» — зелено), и бюджет без
        предела (всё «род» — тоже зелено); это та же мера, которой сторож мерил бы
        свои константы сам собой (урок ADR-913).
        """
        fed, why_fed = one(self._chain_of(h.SEED_HOPS))
        self.assertEqual("fewer", fed, why_fed)
        starved, why_starved = one(self._chain_of(h.SEED_HOPS + 1))
        self.assertEqual("unmeasured", starved, why_starved)
        self.assertIn("ОБОРВАНО", why_starved)


if __name__ == "__main__":
    unittest.main()
