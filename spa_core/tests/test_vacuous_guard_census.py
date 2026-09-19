"""Перепись вырожденных сторожей: у каждой проверки обратная сторона.

Заказ **G44 п. 1** приказа владельца «Portfolio CIO», решение — ADR-420.

## Почему сцены именно такие

Перепись может ошибиться в обе стороны, и опасна одна: назвать исправным
сторожа, который на пустом входе зеленеет. Поэтому каждая сцена идёт парой —
что прибор НАЗЫВАЕТ и чего он НЕ называет:

* роль имени: перечень-вход против списка исключений (опустошить второй значит
  сделать сторожа СТРОЖЕ, и населением он не является);
* пустой литерал обязан сохранять РОД: `[]` вместо `frozenset()` менял бы ещё
  и тип, и краснота говорила бы о типе, а не о пустоте;
* дверь без правки исходника: в теле цикла-потребителя (путь ИМЕННО этого
  перечня) против «где-то в модуле» (может относиться к соседнему);
* приписывание красноты: упал потребитель перечня или сосед — во втором случае
  потребитель остался вырожденным, и краснота защитой не является;
* журнал зонда протухает В БЕЗОПАСНУЮ сторону: другой sha сторожа возвращает
  строку в `unmeasured`, то есть НА учёт.

Литеральных дат здесь нет: часы прибора инъектируются параметром ``now``.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import ast
import datetime as dt
import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import List, Optional
from unittest import mock

from spa_core.monitoring import vacuous_guard_census as vgc

#: Неподвижные часы: прибор берёт их параметром.
# FROZEN-DATE-OK: injected-clock — час передаётся в measure/run параметром now=
_NOW = dt.datetime(2000, 1, 1, tzinfo=dt.timezone.utc)


def _tree(src: str) -> ast.Module:
    return ast.parse(src)


class RoleSeparatesAnInputFromAnExclusionList(unittest.TestCase):
    """Вход — это «где смотреть». Список исключений входом не является."""

    def test_a_name_iterated_is_an_input(self):
        role = vgc.enumeration_role(
            _tree("D = ('a',)\nfor x in D:\n    print(x)\n"), "D")
        self.assertEqual(role, vgc.ROLE_ITERATED)
        self.assertIn(role, vgc.INPUT_ROLES)

    def test_a_name_passed_to_a_call_is_an_input(self):
        role = vgc.enumeration_role(_tree("D = ('a',)\nassert len(D) == 1\n"), "D")
        self.assertEqual(role, vgc.ROLE_PASSED)
        self.assertIn(role, vgc.INPUT_ROLES)

    def test_a_membership_only_name_is_NOT_in_the_population(self):
        """ОБРАТНАЯ СТОРОНА: опустошить список исключений — сделать СТРОЖЕ."""
        role = vgc.enumeration_role(
            _tree("ALLOW = ('a',)\ndef f(x):\n    return x in ALLOW\n"), "ALLOW")
        self.assertEqual(role, vgc.ROLE_MEMBERSHIP)
        self.assertNotIn(role, vgc.INPUT_ROLES)

    def test_a_get_call_is_membership_not_an_input(self):
        role = vgc.enumeration_role(
            _tree("M = {'a': 1}\ndef f(k):\n    return M.get(k)\n"), "M")
        self.assertEqual(role, vgc.ROLE_MEMBERSHIP)

    def test_iteration_wins_over_membership_when_both_are_present(self):
        """Старшинство — предмет: `for d in D` рядом с `x in D` есть ВХОД."""
        role = vgc.enumeration_role(
            _tree("D = ('a',)\nfor d in D:\n    pass\ndef f(x):\n    return x in D\n"),
            "D")
        self.assertEqual(role, vgc.ROLE_ITERATED)

    def test_a_name_never_loaded_is_named_so(self):
        self.assertEqual(vgc.enumeration_role(_tree("D = ('a',)\n"), "D"),
                         vgc.ROLE_UNREAD)


class TheEmptyLiteralKeepsTheKIND(unittest.TestCase):
    """Подставить `[]` вместо `frozenset()` значило бы менять ещё и тип."""

    def test_each_container_kind_gets_its_own_empty(self):
        self.assertEqual(vgc.empty_literal("('a', 'b')"), "()")
        self.assertEqual(vgc.empty_literal("['a']"), "[]")
        self.assertEqual(vgc.empty_literal("{'a'}"), "set()")
        self.assertEqual(vgc.empty_literal("frozenset({'a'})"), "frozenset()")
        self.assertEqual(vgc.empty_literal("{'a': 1}"), "{}")

    def test_a_container_written_as_a_CONSTRUCTOR_is_parsed_too(self):
        """Иначе `frozenset({...})` выпадал бы из населения МОЛЧА (19 констант)."""
        self.assertEqual(vgc.empty_literal("frozenset({'a'})"), "frozenset()")
        self.assertEqual(vgc.enumeration_value("frozenset({'a'})"), frozenset({"a"}))
        self.assertEqual(vgc.empty_literal("tuple(['a'])"), "()")

    def test_a_call_that_is_NOT_a_container_constructor_is_not_parsed(self):
        """ОБРАТНАЯ СТОРОНА: `Path(...)` значением перечня не является."""
        parsed, _ = vgc.literal_of("Path('x')")
        self.assertFalse(parsed)
        self.assertIsNone(vgc.enumeration_value("Path('x')"))

    def test_parsed_and_the_value_are_SEPARATE_answers(self):
        """`None` — законное значение; слить его с «не разобрано» нельзя."""
        self.assertEqual(vgc.literal_of("None"), (True, None))
        self.assertEqual(vgc.literal_of("some_name"), (False, None))

    def test_a_non_container_has_no_empty_of_the_same_kind(self):
        """ОБРАТНАЯ СТОРОНА: третий исход, а не подстановка наугад."""
        self.assertIsNone(vgc.empty_literal("42"))
        self.assertIsNone(vgc.empty_literal("Path(__file__)"))


class EmptinessAndPopulationAreDifferentQUESTIONS(unittest.TestCase):
    """Слить их значило бы сделать «не применилось» неотличимым от «применилось»."""

    def test_a_nonempty_string_collection_is_population(self):
        self.assertEqual(vgc.enumeration_value("('a',)"), ("a",))

    def test_an_empty_collection_is_NOT_population(self):
        """Опустошать нечего — вердикт был бы о сегодняшнем состоянии, не о классе."""
        self.assertIsNone(vgc.enumeration_value("()"))

    def test_a_collection_of_numbers_is_not_an_enumeration_of_places(self):
        self.assertIsNone(vgc.enumeration_value("(1, 2)"))

    def test_is_empty_literal_answers_the_OTHER_question(self):
        self.assertTrue(vgc.is_empty_literal("()"))
        self.assertFalse(vgc.is_empty_literal("('a',)"))
        self.assertFalse(vgc.is_empty_literal(None))
        self.assertFalse(vgc.is_empty_literal("42"))


class TheDoorToEmptinessIsMeasuredNotAssumed(unittest.TestCase):
    """«Пустота достижима без правки» — утверждение, у него есть улика."""

    SRC = ("D = ('a',)\n"
           "def test_x():\n"
           "    for d in D:\n"
           "        base = ROOT / d\n"
           "        if not base.exists():\n"
           "            continue\n")

    def test_a_silent_skip_on_a_missing_path_is_named(self):
        found = vgc.silently_skips_absent(_tree(self.SRC))
        self.assertIsNotNone(found)
        self.assertIn("exists()", found)

    def test_a_branch_that_DOES_something_is_not_a_door(self):
        """ОБРАТНАЯ СТОРОНА: `if not p.exists(): raise` — отказ, а не пропуск."""
        src = ("def f(p):\n"
               "    if not p.exists():\n"
               "        raise AssertionError('нет каталога')\n")
        self.assertIsNone(vgc.silently_skips_absent(_tree(src)))

    def test_the_door_inside_the_consumer_loop_is_distinguished(self):
        tree = _tree(self.SRC)
        loops = vgc.consumer_loops(tree, "D")
        self.assertEqual(len(loops), 1)
        self.assertIsNotNone(vgc.silently_skips_absent(tree, within=loops[0]))

    def test_a_door_belonging_to_a_NEIGHBOUR_is_not_inside_our_loop(self):
        """Дверь по модулю может относиться к соседнему перечню — это слабее."""
        src = ("D = ('a',)\n"
               "OTHER = ('b',)\n"
               "def test_x():\n"
               "    for d in D:\n"
               "        assert d\n"
               "def test_y():\n"
               "    for o in OTHER:\n"
               "        p = ROOT / o\n"
               "        if not p.exists():\n"
               "            continue\n")
        tree = _tree(src)
        self.assertIsNotNone(vgc.silently_skips_absent(tree))
        loops = vgc.consumer_loops(tree, "D")
        self.assertIsNone(vgc.silently_skips_absent(tree, within=loops[0]))


class WhoReadsTheNameDecidesWhoseREDNESSCounts(unittest.TestCase):
    SRC = ("D = ('a',)\n"
           "DERIVED = [x.upper() for x in D]\n"
           "def _helper():\n"
           "    return list(D)\n"
           "def test_consumer():\n"
           "    assert list(D)\n"
           "def test_neighbour():\n"
           "    assert len(DERIVED) == 1\n")

    def test_tests_helpers_and_module_level_are_separated(self):
        tests, helpers, module_level = vgc.loaders_of(_tree(self.SRC), "D")
        self.assertEqual(tests, {"test_consumer"})
        self.assertEqual(helpers, {"_helper"})
        self.assertTrue(module_level, "включение на уровне модуля тоже читает имя")

    def test_a_failing_consumer_is_refuses_empty(self):
        row = {"consumer_tests": ["test_consumer"], "name": "D"}
        verdict, attribution = vgc._attribute(
            row, {"failed_tests": ["tests/t.py::test_consumer"]})
        self.assertEqual(verdict, vgc.VERDICT_REFUSES)
        self.assertEqual(attribution, vgc.ATTRIBUTION_DIRECT)

    def test_a_failing_NEIGHBOUR_leaves_the_consumer_vacuous(self):
        """Чужая краснота защитой не является — отдельный вердикт, не оттенок."""
        row = {"consumer_tests": ["test_consumer"], "name": "D"}
        verdict, attribution = vgc._attribute(
            row, {"failed_tests": ["tests/t.py::test_neighbour"]})
        self.assertEqual(verdict, vgc.VERDICT_ELSEWHERE)
        self.assertEqual(attribution, vgc.ATTRIBUTION_NONE)

    def test_without_a_named_consumer_attribution_is_NOT_invented(self):
        """Имя читает помощник — какой тест потребитель, статикой не решается."""
        row = {"consumer_tests": [], "name": "D"}
        verdict, attribution = vgc._attribute(
            row, {"failed_tests": ["tests/t.py::test_neighbour"]})
        self.assertEqual(verdict, vgc.VERDICT_REFUSES)
        self.assertEqual(attribution, vgc.ATTRIBUTION_HELPER)

    def test_an_EMPTY_list_of_fallen_does_not_name_a_culprit(self):
        """Выжившая мутация батареи: без имён упавших «упал потребитель» есть
        ВЫДУМКА, а не приписывание. Исход обязан остаться неприписанным."""
        row = {"consumer_tests": ["test_consumer"], "name": "D"}
        verdict, attribution = vgc._attribute(row, {"failed_tests": []})
        self.assertEqual(verdict, vgc.VERDICT_REFUSES)
        self.assertEqual(attribution, vgc.ATTRIBUTION_HELPER,
                         "имён нет ⇒ виновный НЕ назван")
        self.assertNotEqual(attribution, vgc.ATTRIBUTION_DIRECT)
        # и то же самое, когда поля нет вовсе
        self.assertEqual(vgc._attribute(row, {})[1], vgc.ATTRIBUTION_HELPER)

    def test_a_parametrised_test_id_is_matched_by_its_name(self):
        row = {"consumer_tests": ["test_consumer"], "name": "D"}
        verdict, _ = vgc._attribute(
            row, {"failed_tests": ["tests/t.py::test_consumer[case-1]"]})
        self.assertEqual(verdict, vgc.VERDICT_REFUSES)


class TheProbeLedgerExpiresTOWARDSTheBooks(unittest.TestCase):
    """Протухшая запись не молчит — она перестаёт отвечать."""

    ROW = {"key": "tests/t.py|D", "guard": "tests/t.py", "name": "D",
           "value": "('a',)", "guard_sha": "abc", "consumer_tests": ["test_x"]}

    def test_a_matching_entry_gives_the_verdict(self):
        out = vgc._verdict(dict(self.ROW),
                           {"tests/t.py|D": {"guard_sha": "abc", "value": "('a',)",
                                             "verdict": vgc.VERDICT_VACUOUS,
                                             "evidence": "зелен"}}, None)
        self.assertEqual(out["verdict"], vgc.VERDICT_VACUOUS)

    def test_a_different_guard_sha_returns_the_row_to_the_books(self):
        out = vgc._verdict(dict(self.ROW),
                           {"tests/t.py|D": {"guard_sha": "OTHER", "value": "('a',)",
                                             "verdict": vgc.VERDICT_VACUOUS}}, None)
        self.assertEqual(out["verdict"], vgc.VERDICT_UNMEASURED)
        self.assertIn("ДРУГОМУ sha", out["evidence"])

    def test_a_missing_entry_is_unmeasured_with_the_ledger_reason(self):
        out = vgc._verdict(dict(self.ROW), {}, "журнала зонда нет")
        self.assertEqual(out["verdict"], vgc.VERDICT_UNMEASURED)
        self.assertIn("журнала зонда нет", out["evidence"])

    def test_an_outcome_never_comes_without_a_reason(self):
        out = vgc._verdict(dict(self.ROW), {}, None)
        self.assertTrue(out["evidence"], "исход без основания — не исход")


class ACensusOverARealTree(unittest.TestCase):
    """Маленькое дерево целиком: население, роли, двери, отчёт."""

    def _stand(self, tmp: str) -> Path:
        root = Path(tmp)
        (root / "tests").mkdir()
        (root / "tests" / "test_input.py").write_text(
            "from pathlib import Path\n"
            "ROOT = Path(__file__).resolve().parent.parent\n"
            "SCAN_DIRS = ('pkg_a', 'pkg_b')\n"
            "def test_scan():\n"
            "    for d in SCAN_DIRS:\n"
            "        base = ROOT / d\n"
            "        if not base.exists():\n"
            "            continue\n"
            "        assert base.is_dir()\n", encoding="utf-8")
        (root / "tests" / "test_allowlist.py").write_text(
            "ALLOW = ('clock.py',)\n"
            "def test_allow():\n"
            "    assert 'clock.py' in ALLOW\n", encoding="utf-8")
        return root

    def test_population_counts_inputs_and_names_the_excluded(self):
        with TemporaryDirectory() as tmp:
            doc = vgc.measure(self._stand(tmp), now=_NOW)
        self.assertEqual(doc["inputs"], 1, "список исключений в население не входит")
        self.assertEqual(doc["roles"][vgc.ROLE_MEMBERSHIP], 1,
                         "исключённое обязано быть СОСЧИТАНО, а не пропасть молча")
        self.assertEqual(doc["empty_reachable_without_edit"], 1)
        self.assertEqual(doc["door_inside_consumer_loop"], 1)

    def test_without_a_probe_ledger_every_row_is_unmeasured_not_clean(self):
        with TemporaryDirectory() as tmp:
            doc = vgc.measure(self._stand(tmp), now=_NOW)
        self.assertEqual(doc["counts"][vgc.VERDICT_UNMEASURED], doc["inputs"])
        self.assertEqual(doc["status"], "MEASURED")
        self.assertIn("журнала зонда нет", doc["probe_ledger_reason"])
        text = "\n".join(vgc.report(doc))
        self.assertIn("остаются НЕ ИЗМЕРЕНЫ, а не исправны", text)

    def test_a_vacuous_row_turns_the_status_CRITICAL(self):
        with TemporaryDirectory() as tmp:
            root = self._stand(tmp)
            rows = vgc.measure(root, now=_NOW)["rows"]
            ledger = root / vgc.PROBE_LEDGER
            ledger.parent.mkdir(parents=True, exist_ok=True)
            ledger.write_text(json.dumps({"entries": [
                {"key": rows[0]["key"], "guard_sha": rows[0]["guard_sha"],
                 "value": rows[0]["value"], "verdict": vgc.VERDICT_VACUOUS,
                 "evidence": "зелен с пустым перечнем"}]}), encoding="utf-8")
            doc = vgc.measure(root, now=_NOW)
        self.assertEqual(doc["status"], "CRITICAL")
        self.assertEqual(doc["counts"][vgc.VERDICT_VACUOUS], 1)
        self.assertEqual(doc["vacuous_and_reachable"], 1)
        self.assertIn("[vacuous_pass]", "\n".join(vgc.report(doc)))

    def test_the_clock_is_an_INPUT_not_the_wall(self):
        with TemporaryDirectory() as tmp:
            doc = vgc.measure(self._stand(tmp), now=_NOW)
        self.assertEqual(doc["generated_at"], _NOW.isoformat())

    def test_an_unreadable_guard_is_named_not_skipped(self):
        with TemporaryDirectory() as tmp:
            root = self._stand(tmp)
            (root / "tests" / "test_broken.py").write_text(
                "D = ('a',\ndef oops(:\n", encoding="utf-8")
            doc = vgc.measure(root, now=_NOW)
        self.assertEqual(len(doc["unreadable"]), 1)
        self.assertIn("[НЕ ИЗМЕРЕНО]", "\n".join(vgc.report(doc)))


class TheCensusCanFillTheLedgerITSelfAndOnlyWhenASKED(unittest.TestCase):
    """Прибор, которого никто не зовёт, — файл. Но зов зонда стои́т прогонов."""

    def test_the_probe_flag_delegates_to_the_probe(self):
        from spa_core.monitoring import vacuous_guard_probe
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "tests").mkdir()
            (root / "tests" / "test_x.py").write_text(
                "D = ('a',)\ndef test_x():\n    assert list(D)\n", encoding="utf-8")
            with mock.patch.object(vacuous_guard_probe, "run",
                                   return_value={"doc": {"status": "MEASURED",
                                                         "probed": 1}}) as called:
                vgc.main(["--root", str(root), "--no-write", "--probe", "3"])
        self.assertEqual(called.call_count, 1)
        self.assertEqual(called.call_args.kwargs["sample"], 3)

    def test_without_the_flag_the_probe_is_NOT_called(self):
        """ОБРАТНАЯ СТОРОНА: иначе шестичасовой агент платил бы часами прогонов."""
        from spa_core.monitoring import vacuous_guard_probe
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "tests").mkdir()
            (root / "tests" / "test_x.py").write_text(
                "D = ('a',)\ndef test_x():\n    assert list(D)\n", encoding="utf-8")
            with mock.patch.object(vacuous_guard_probe, "run") as called:
                vgc.main(["--root", str(root), "--no-write"])
        self.assertEqual(called.call_count, 0)


class TheInstrumentRefusesRatherThanGuesses(unittest.TestCase):
    def test_a_missing_root_is_the_third_outcome_with_a_reason(self):
        with TemporaryDirectory() as tmp:
            out = vgc.run(Path(tmp) / "no-such-tree", write=False, now=_NOW)
        self.assertFalse(out["measured"])
        self.assertEqual(out["doc"]["status"], "UNMEASURED")
        self.assertIn("корень дерева не прочитан", out["doc"]["reason"])
        self.assertIn("НЕ ИЗМЕРЕНО", "\n".join(vgc.report(out["doc"])))

    def test_the_exit_code_separates_unmeasured_from_a_finding(self):
        with TemporaryDirectory() as tmp:
            self.assertEqual(vgc.main(["--root", str(Path(tmp) / "nope"),
                                       "--no-write"]), 2)

    def test_a_tree_without_a_single_guard_is_the_third_outcome_too(self):
        """Ввезённый читатель населения отказывает — исход обязан быть НАШИМ."""
        with TemporaryDirectory() as tmp:
            (Path(tmp) / "tests").mkdir()
            with self.assertRaises(vgc.NotMeasured):
                vgc.measure(Path(tmp), now=_NOW)
            out = vgc.run(Path(tmp), write=False, now=_NOW)
        self.assertFalse(out["measured"])
        self.assertIn("ни одного файла-сторожа", out["doc"]["reason"])

    def test_the_reverse_sides_are_published_with_the_document(self):
        """Прибор без названных границ читается как всеведущий."""
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "tests").mkdir()
            (root / "tests" / "test_x.py").write_text(
                "D = ('a',)\ndef test_x():\n    assert list(D)\n", encoding="utf-8")
            doc = vgc.measure(root, now=_NOW)
        self.assertTrue(doc["what_it_does_not_prove"])
        self.assertTrue(any("membership_only" in s
                            for s in doc["what_it_does_not_prove"]))


if __name__ == "__main__":  # pragma: no cover
    unittest.main()


class BatterySurvivorsOfCycle638(unittest.TestCase):
    """Сцены, закрывающие ВЫЖИВШИХ батареи мутаций цикла #638.

    Каждая сцена — не придирка, а дыра, которую батарея нашла в унаследованном
    наборе: мутация проходила, и НИ ОДИН тест не краснел.
    """

    def _stand(self, tmp: str, *, door: str = "exists") -> Path:
        root = Path(tmp)
        (root / "tests").mkdir()
        (root / "tests" / "test_input.py").write_text(
            "from pathlib import Path\n"
            "ROOT = Path(__file__).resolve().parent.parent\n"
            "SCAN_DIRS = ('pkg_a', 'pkg_b')\n"
            "def test_scan():\n"
            "    for d in SCAN_DIRS:\n"
            "        base = ROOT / d\n"
            f"        if not base.{door}():\n"
            "            continue\n"
            "        assert base.is_dir()\n", encoding="utf-8")
        return root

    def _with_verdict(self, root: Path, verdict: str,
                      failed: Optional[List[str]] = None) -> dict:
        """Журнал зонда в его НАСТОЯЩЕЙ форме.

        Зонд пишет сырой вердикт И ИМЕНА упавших тестов; кому приписать
        красноту, решает перепись. Поэтому сцена подаёт то, что подаёт зонд, а
        не готовый ответ — иначе она проверяла бы саму себя.
        """
        rows = vgc.measure(root, now=_NOW)["rows"]
        ledger = root / vgc.PROBE_LEDGER
        ledger.parent.mkdir(parents=True, exist_ok=True)
        entry = {"key": rows[0]["key"], "guard_sha": rows[0]["guard_sha"],
                 "value": rows[0]["value"], "verdict": verdict,
                 "evidence": "сцена"}
        if failed is not None:
            entry["failed_tests"] = failed
        ledger.write_text(json.dumps({"entries": [entry]}), encoding="utf-8")
        return vgc.measure(root, now=_NOW)

    # --- выживший №4: у четвёртого вердикта не было ПОСЛЕДСТВИЯ -------------
    def test_refuses_elsewhere_COUNTS_as_a_finding_not_only_as_a_label(self):
        """Батарея: `FINDING_VERDICTS` без `VERDICT_ELSEWHERE` — все зелены.

        Приписывание было проверено, а СЛЕДСТВИЕ — нет: чужая краснота обязана
        краснить перепись, иначе вердикт есть ярлык без последствий.
        """
        self.assertIn(vgc.VERDICT_ELSEWHERE, vgc.FINDING_VERDICTS)
        with TemporaryDirectory() as tmp:
            # зонд увидел красноту, но упал СОСЕД, а не потребитель `SCAN_DIRS`
            doc = self._with_verdict(
                self._stand(tmp), vgc.VERDICT_REFUSES,
                failed=["tests/test_input.py::test_neighbour"])
        self.assertEqual(doc["counts"][vgc.VERDICT_ELSEWHERE], 1)
        self.assertEqual(doc["status"], "CRITICAL",
                         "сторож, покрасневший НЕ ТЕМ тестом, остался вырожден")
        self.assertIn("[refuses_elsewhere]", "\n".join(vgc.report(doc)))

    def test_refuses_empty_alone_does_NOT_turn_the_status_critical(self):
        """Обратная сторона: упал САМ потребитель ⇒ отказ, а не находка."""
        with TemporaryDirectory() as tmp:
            doc = self._with_verdict(
                self._stand(tmp), vgc.VERDICT_REFUSES,
                failed=["tests/test_input.py::test_scan"])
        self.assertEqual(doc["counts"][vgc.VERDICT_REFUSES], 1)
        self.assertEqual(doc["counts"][vgc.VERDICT_ELSEWHERE], 0)
        self.assertEqual(doc["status"], "MEASURED")

    # --- выживший №6: «не измерено» сливалось с «отказал» -------------------
    def test_the_unmeasured_label_is_DISTINCT_from_every_verdict(self):
        """Батарея: `VERDICT_UNMEASURED = "refuses_empty"` — все зелены.

        Слить их значило бы читать «не измерено» как «сторож отказал» — ровно
        подмена исходов, запрещённая инв. #17, и подмена в ОПАСНУЮ сторону.
        """
        verdicts = (vgc.VERDICT_VACUOUS, vgc.VERDICT_REFUSES,
                    vgc.VERDICT_ELSEWHERE)
        self.assertNotIn(vgc.VERDICT_UNMEASURED, verdicts)
        self.assertEqual(len(set(vgc.VERDICTS)), len(vgc.VERDICTS),
                         "ярлыки вердиктов обязаны быть попарно различны")
        self.assertNotIn(vgc.VERDICT_UNMEASURED, vgc.FINDING_VERDICTS,
                         "«не измерено» не есть находка — оно третий исход")

    def test_an_unmeasured_row_is_counted_apart_and_clears_nothing(self):
        with TemporaryDirectory() as tmp:
            doc = self._with_verdict(self._stand(tmp), vgc.VERDICT_UNMEASURED)
        self.assertEqual(doc["counts"][vgc.VERDICT_UNMEASURED], 1)
        self.assertEqual(doc["counts"][vgc.VERDICT_REFUSES], 0,
                         "«не измерено» засчиталось как отказ — подмена исхода")
        self.assertEqual(doc["counts"][vgc.VERDICT_VACUOUS], 0)

    # --- выживший №8: дверь искалась только по exists() ---------------------
    def test_every_existence_method_opens_the_door_not_only_exists(self):
        """Батарея: `_EXISTENCE_METHODS` сузили до `{"exists"}` — все зелены.

        `if not base.is_dir(): continue` даёт ту же пустоту, что и `exists()`;
        видеть одну форму и не видеть двух других значит занижать подкласс, где
        вред не гипотетичен.
        """
        for method in sorted(vgc._EXISTENCE_METHODS):
            with self.subTest(method=method), TemporaryDirectory() as tmp:
                doc = vgc.measure(self._stand(tmp, door=method), now=_NOW)
                self.assertEqual(
                    doc["empty_reachable_without_edit"], 1,
                    f"дверь `if not ….{method}(): continue` не опознана")
                self.assertEqual(doc["door_inside_consumer_loop"], 1)

    def test_a_method_that_is_NOT_an_existence_check_is_not_a_door(self):
        """Обратная сторона: иначе дверью стала бы любая отрицаемая проверка."""
        with TemporaryDirectory() as tmp:
            doc = vgc.measure(self._stand(tmp, door="is_symlink"), now=_NOW)
        self.assertEqual(doc["empty_reachable_without_edit"], 0)


class TheExitCodeKeepsTheThreeOutcomesApart(unittest.TestCase):
    """Код возврата — то место, где различие читает ЗОВУЩИЙ скрипт (инв. #17).

    До цикла #642 `main()` читал `doc.get("counts") or {}`: поля нет ⇒ пусто ⇒
    ложь ⇒ код 0. «Поля нет» и «находок ноль» выходили одним и тем же успехом, и
    зовущему различить их было нечем. Контроль здесь в ОБЕ стороны: полный
    артефакт с нулём обязан дать 0, урезанный — 2 с названным полем.
    """

    def _main_with(self, doc: dict):
        import contextlib
        import io
        for name, stub in (("run", lambda *a, **k: {"doc": doc, "path": None}),
                           ("report", lambda *a, **k: [])):
            original = getattr(vgc, name)
            setattr(vgc, name, stub)
            self.addCleanup(lambda n=name, o=original: setattr(vgc, n, o))
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            code = vgc.main(["--no-write"])
        return code, buf.getvalue()

    def test_a_complete_artifact_with_zero_findings_exits_clean(self):
        code, _ = self._main_with({"status": "MEASURED", "counts": {v: 0 for v in vgc.FINDING_VERDICTS} | {vgc.VERDICT_UNMEASURED: 0}})
        self.assertEqual(code, 0, "измеренный ноль обязан выходить нулём")

    def test_an_artifact_without_counts_is_not_measured_and_never_exits_clean(self):
        code, out = self._main_with({"status": "MEASURED"})
        self.assertEqual(code, 2, "отсутствие наблюдения кодом 0 не выдаётся")
        self.assertIn("НЕ ИЗМЕРЕНО", out)
        self.assertIn("counts", out, "пропавшее поле обязано быть НАЗВАНО")

    def test_counts_of_the_wrong_kind_is_absence_not_an_empty_tally(self):
        code, out = self._main_with({"status": "MEASURED", "counts": "ноль"})
        self.assertEqual(code, 2, "мусор в поле замером не является")
        self.assertIn("НЕ ИЗМЕРЕНО", out)

    def test_a_finding_still_exits_one(self):
        code, _ = self._main_with({"status": "MEASURED", "counts": {v: 0 for v in vgc.FINDING_VERDICTS} | {vgc.VERDICT_UNMEASURED: 4}})
        self.assertEqual(code, 1, "находки обязаны выходить кодом 1")

    def test_unmeasured_status_still_wins_over_the_tally(self):
        code, _ = self._main_with({"status": "UNMEASURED", "counts": {v: 0 for v in vgc.FINDING_VERDICTS} | {vgc.VERDICT_UNMEASURED: 0}})
        self.assertEqual(code, 2, "«не измерено» у всего замера кодом 0 не выдаётся")
