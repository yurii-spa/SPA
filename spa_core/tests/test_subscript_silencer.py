#!/usr/bin/env python3
"""Контроль прибора громкости индексирующего чтения (ADR-949).

# LLM_FORBIDDEN

Проба устроена как положительный контроль В ОБЕ СТОРОНЫ: у каждой сцены глушитель
либо ЕСТЬ и назван, либо его НЕТ, и прибор обязан различать эти случаи, а форму, в
которой род ловимого исключения не разобран, — объявлять ТРЕТЬИМ исходом.

**Почему контроль на СЦЕНАХ, а не на члене репозитория, и это сказано вслух.**
Замер 2026-11-08 (ADR-949) дал население глушителя РОВНО НОЛЬ: ни одно из 78
индексирующих чтений в репозитории под глушителем не стои́т. Известного члена в
дереве НЕТ — значит контроль можно поставить только на сцене, и это СЛАБЕЕ контроля
на настоящем члене. Ноль заслуживает веры ровно потому, что дверь на сценах
СРАБАТЫВАЕТ: прибор, который не нашёл бы глушитель нигде и никогда, отвечал бы тем
же нулём, и отличить его от замера было бы нечем (дословный урок `pyflakes`,
`.claude/rules/deployment.md`).
"""

from __future__ import annotations

import ast
import unittest

from spa_core.tests import _empty_collection_harm as harm
from spa_core.tests import _subscript_silencer as sil


def ask(source: str, name: str = "x"):
    """Исходы прибора по ВСЕМ чтениям ``name[…]`` сцены."""
    tree = ast.parse(source)
    index = harm._parents(tree)
    return [sil.silencer_of_one_subscript(node, name, index)
            for node in ast.walk(tree)
            if isinstance(node, ast.Subscript)
            and isinstance(node.value, ast.Name) and node.value.id == name]


class SilencerIsMeasuredNotAssumed(unittest.TestCase):
    """Сцены отличаются РОВНО глушителем — значит вердикт меняет он, а не форма."""

    def test_a_read_with_no_silencer_is_loud(self):
        got = ask("def f(ks):\n x = [k for k in ks]\n return x[0]\n")
        self.assertEqual([o for o, _k, _w in got], ["loud"])
        self.assertIn("НЕ СПРАШИВАЛ", got[0][2],
                      "исход `loud` обязан нести объявленную границу в причине")

    def test_the_same_read_under_a_catching_try_is_silenced(self):
        got = ask("def f(ks, k):\n x = {a: 1 for a in ks}\n try:\n  return x[k]\n"
                  " except KeyError:\n  return None\n")
        self.assertEqual([(o, kind) for o, kind, _w in got], [("silenced", "try")])

    def test_a_bare_except_silences_too(self):
        got = ask("def f(ks):\n x = [k for k in ks]\n try:\n  return x[0]\n"
                  " except:\n  return None\n")
        self.assertEqual([(o, kind) for o, kind, _w in got], [("silenced", "try")])

    def test_a_handler_of_a_FOREIGN_kind_does_not_silence(self):
        got = ask("def f(ks):\n x = [k for k in ks]\n try:\n  return x[0]\n"
                  " except ValueError:\n  return None\n")
        self.assertEqual([o for o, _k, _w in got], ["loud"],
                         "`except ValueError` пустоту индексации не глушит")

    def test_an_OUTER_try_is_still_found_after_a_foreign_inner_one(self):
        """Подъём обязан ПРОДОЛЖАТЬСЯ после чужого обработчика — иначе вложенный
        `try` прятал бы настоящий глушитель, и ошибка шла бы в сторону `loud`."""
        got = ask("def f(ks):\n x = [k for k in ks]\n try:\n  try:\n   return x[0]\n"
                  "  except ValueError:\n   pass\n except KeyError:\n  return None\n")
        self.assertEqual([(o, kind) for o, kind, _w in got], [("silenced", "try")])

    def test_a_handler_in_a_form_the_tool_cannot_parse_is_the_THIRD_outcome(self):
        got = ask("def f(ks, E):\n x = [k for k in ks]\n try:\n  return x[0]\n"
                  " except (E[0]):\n  return None\n")
        self.assertEqual([o for o, _k, _w in got], ["unmeasured"],
                         "неразобранный род ловимого исключения ни за громкость, "
                         "ни за тишину не выдаётся (инв. #17)")

    def test_a_truthiness_guard_silences(self):
        got = ask("def f(ks):\n x = [k for k in ks]\n if x:\n  return x[0]\n")
        self.assertEqual([(o, kind) for o, kind, _w in got], [("silenced", "guard")])

    def test_a_containment_guard_silences(self):
        got = ask("def f(ks, k):\n x = {a: 1 for a in ks}\n if k in x:\n  return x[k]\n")
        self.assertEqual([(o, kind) for o, kind, _w in got], [("silenced", "guard")])

    def test_a_guard_on_a_DIFFERENT_name_does_not_silence(self):
        """Охрана чужого имени о пустоте нашего не говорит ничего."""
        got = ask("def f(ks, other, k):\n x = {a: 1 for a in ks}\n if other:\n"
                  "  return x[k]\n")
        self.assertEqual([o for o, _k, _w in got], ["loud"])

    def test_the_else_branch_of_a_try_is_NOT_its_body(self):
        """`else` у `try` обработчиками НЕ кроется — исключение уходит наружу."""
        got = ask("def f(ks):\n x = [k for k in ks]\n try:\n  pass\n"
                  " except KeyError:\n  return None\n else:\n  return x[0]\n")
        self.assertEqual([o for o, _k, _w in got], ["loud"])

    def test_every_handler_kind_declared_as_silencing_is_actually_accepted(self):
        for kind in sorted(sil.SILENCING_EXCEPTIONS):
            got = ask(f"def f(ks):\n x = [k for k in ks]\n try:\n  return x[0]\n"
                      f" except {kind}:\n  return None\n")
            self.assertEqual([(o, k) for o, k, _w in got], [("silenced", "try")],
                             f"объявленный род {kind} обязан глушить")

    def test_a_tuple_handler_is_read_through(self):
        got = ask("def f(ks):\n x = [k for k in ks]\n try:\n  return x[0]\n"
                  " except (OSError, IndexError):\n  return None\n")
        self.assertEqual([(o, kind) for o, kind, _w in got], [("silenced", "try")])


class TheRepoPopulationIsMeasured(unittest.TestCase):
    """Замер дерева зовётся ОДИН раз: он стои́т секунды, а вопросов к нему три."""

    @classmethod
    def setUpClass(cls):
        cls.result = sil.subscript_reads()

    def test_all_three_outcomes_are_distinguishable(self):
        tally = self.result["tally"]
        self.assertEqual(sorted(tally), sorted(sil.OUTCOMES),
                         "исходы обязаны быть РАЗЛИЧИМЫ (инв. #17)")
        self.assertEqual(sum(tally.values()), len(self.result["rows"]))

    def test_the_scope_of_the_measurement_is_NAMED_not_implied(self):
        scope = self.result["scope"]
        for field in ("declarations_still_unmeasured", "candidates", "subjects"):
            self.assertIn(field, scope)
            self.assertGreater(scope[field], 0, f"{field} не измерено")
        self.assertEqual(scope["declarations_still_unmeasured"],
                         self.result["axis_tally"]["unmeasured"],
                         "область обязана СОВПАДАТЬ с осью направления, а не "
                         "объявляться рядом с ней")

    def test_every_row_carries_a_named_reason(self):
        for row in self.result["rows"]:
            self.assertIn(row["loudness"], sil.OUTCOMES)
            self.assertTrue(row["why"].strip(), f"причина пуста: {row}")
            if row["loudness"] == "silenced":
                self.assertIn(row["silencer"], sil.SILENCER_KINDS)
            else:
                self.assertIsNone(row["silencer"])

    def test_the_population_of_indexing_reads_has_not_VANISHED(self):
        """Ноль чтений означал бы, что прибор перестал видеть форму вовсе, — а это
        неотличимо от «форма ушла из дерева». Замер 08.11 — 78."""
        self.assertGreater(len(self.result["rows"]), 0,
                           "индексирующих чтений не найдено НИ ОДНОГО — прибор "
                           "смотрит не туда, либо область сузилась молча")


if __name__ == "__main__":
    unittest.main()
