"""Батарея прибора `spa_core/tests/_census_call_multiplier.py` (ADR-1056).

Каждая сцена — ОДНОРАЗОВАЯ и названа в докстроке; живое дерево спрашивается
ОТДЕЛЬНО и с ИЗВЕСТНЫМ членом по обе стороны (форма ADR-1041/1043), иначе прибор
вышел бы новым членом класса, который сам же и мерит.

Положительный контроль у каждого утверждения — в обе стороны: у формы множителя
есть сцена, где он ЕСТЬ, и сцена, где его НЕТ, и обе на НАСТОЯЩЕМ приборе.
"""
from __future__ import annotations

import ast
import json
import tempfile
import unittest
from pathlib import Path

from spa_core.tests import _census_call_multiplier as m

_REPO = Path(__file__).resolve().parents[2]
_BASELINE = _REPO / "spa_core/tests/census_call_multiplier_baseline.json"

#: Объявление сцены: имя модуля и функции, которые сцены выдают за дорогие.
_DECLARED = {"thing_census.sweep": {"runner_file_s": 999.0, "runner_run": "scene",
                                    "host_s": None, "measured_at": "scene",
                                    "cheap_when": None}}
_CHEAP_DOOR = {"thing_census.sweep": {"runner_file_s": 999.0, "runner_run": "scene",
                                      "host_s": None, "measured_at": "scene",
                                      "cheap_when": {"kwarg": "sweep", "value": False}}}

_IMPORT = "from pkg import thing_census\n"


def _verdict(body: str, declared=None):
    """Разбор ОДНОГО класса сцены настоящим прибором."""
    tree = ast.parse(_IMPORT + body)
    aliases = m.module_aliases(tree)
    classes = [n for n in ast.walk(tree) if isinstance(n, ast.ClassDef)]
    assert len(classes) == 1, "сцена обязана нести РОВНО один класс"
    return m.class_payers(classes[0], declared or _DECLARED, aliases)


class TheFormOfTheMultiplierIsMeasured(unittest.TestCase):

    def test_two_tests_calling_the_census_each_are_multiplied(self):
        """Сцена аварии: дорогой зов в теле КАЖДОГО теста."""
        out = _verdict(
            "class C:\n"
            "    def test_one(self):\n"
            "        thing_census.sweep()\n"
            "    def test_two(self):\n"
            "        thing_census.sweep()\n")
        self.assertEqual(out["outcome"], m.MULTIPLIED, out["why"])
        self.assertEqual(out["payers"], ["test_one", "test_two"])

    def test_the_same_call_in_setUpClass_is_paid_once(self):
        """Обратная сторона той же сцены — и ровно это есть выход."""
        out = _verdict(
            "class C:\n"
            "    @classmethod\n"
            "    def setUpClass(cls):\n"
            "        cls.doc = thing_census.sweep()\n"
            "    def test_one(self):\n"
            "        self.doc\n"
            "    def test_two(self):\n"
            "        self.doc\n")
        self.assertEqual(out["outcome"], m.ONCE, out["why"])
        self.assertTrue(out["via_class_setup"])

    def test_the_call_in_setUp_is_paid_by_EVERY_test_not_once(self):
        """``setUp`` — не ``setUpClass``: он зовётся на КАЖДЫЙ тест, поэтому цену
        не делит. Спутать их значило бы объявить дорогой класс дешёвым."""
        out = _verdict(
            "class C:\n"
            "    def setUp(self):\n"
            "        self.doc = thing_census.sweep()\n"
            "    def test_one(self):\n"
            "        self.doc\n"
            "    def test_two(self):\n"
            "        self.doc\n")
        self.assertEqual(out["outcome"], m.MULTIPLIED, out["why"])
        self.assertFalse(out["via_class_setup"],
                         "setUp классовой подготовкой не является")

    def test_a_lazy_class_cache_does_NOT_remove_the_multiplier(self):
        """Главный урок ADR-1056: кэш выставляется ПОСЛЕ возврата, а по сроку
        возврата нет — значит каждый тест платит полную цену снова."""
        out = _verdict(
            "class C:\n"
            "    _c = None\n"
            "    @classmethod\n"
            "    def _live(cls):\n"
            "        if cls._c is None:\n"
            "            cls._c = thing_census.sweep()\n"
            "        return cls._c\n"
            "    def test_one(self):\n"
            "        self._live()\n"
            "    def test_two(self):\n"
            "        self._live()\n")
        self.assertEqual(out["outcome"], m.MULTIPLIED, out["why"])
        self.assertEqual(out["payers"], ["test_one", "test_two"],
                         "зов через помощника обязан ДОСТИГАТЬСЯ — иначе ленивый "
                         "кэш прятал бы ровно тот класс, ради которого прибор "
                         "написан")

    def test_one_single_caller_is_not_a_multiplier(self):
        """Один платящий тест множителем не является: ошибаться в сторону
        находки прибор обязан на ДВУХ, а не на одном."""
        out = _verdict(
            "class C:\n"
            "    def test_one(self):\n"
            "        thing_census.sweep()\n"
            "    def test_two(self):\n"
            "        pass\n")
        self.assertEqual(out["outcome"], m.ONCE, out["why"])

    def test_a_class_that_never_calls_it_is_not_called_not_zero(self):
        """`not_called` и `unmeasured` — РАЗНЫЕ ответы (инв. #17)."""
        out = _verdict(
            "class C:\n"
            "    def test_one(self):\n"
            "        pass\n")
        self.assertEqual(out["outcome"], m.NOT_CALLED, out["why"])
        self.assertNotEqual(out["outcome"], m.UNMEASURED)

    def test_the_cheap_door_of_the_instrument_is_honoured(self):
        """Зов, ЯВНО открывший дешёвую дверь прибора, дорогим не считается —
        иначе правило краснело бы на семи зовах с `sweep_readers=False`."""
        body = ("class C:\n"
                "    def test_one(self):\n"
                "        thing_census.sweep(sweep=False)\n"
                "    def test_two(self):\n"
                "        thing_census.sweep(sweep=False)\n")
        self.assertEqual(_verdict(body, _CHEAP_DOOR)["outcome"], m.NOT_CALLED)
        # Положительный контроль двери: БЕЗ объявления дешёвой двери тот же
        # текст обязан быть находкой, иначе проверка ничего не измеряет.
        self.assertEqual(_verdict(body, _DECLARED)["outcome"], m.MULTIPLIED)

    def test_a_call_that_leaves_the_cheap_door_shut_is_still_expensive(self):
        """Дешёвая дверь объявлена, но зов её не открыл."""
        out = _verdict(
            "class C:\n"
            "    def test_one(self):\n"
            "        thing_census.sweep()\n"
            "    def test_two(self):\n"
            "        thing_census.sweep(sweep=True)\n", _CHEAP_DOOR)
        self.assertEqual(out["outcome"], m.MULTIPLIED, out["why"])


class ThePrecisionOfTheAxisIsMeasured(unittest.TestCase):

    def test_a_prose_mention_of_the_name_is_not_a_call(self):
        """Подстрокой прибор не проходит (ADR-333): спрашивается узел зова."""
        out = _verdict(
            "class C:\n"
            "    def test_one(self):\n"
            "        note = 'thing_census.sweep()'\n"
            "        assert note\n"
            "    def test_two(self):\n"
            "        assert 'thing_census.sweep' not in ''\n")
        self.assertEqual(out["outcome"], m.NOT_CALLED, out["why"])

    def test_a_foreign_module_with_the_same_function_name_is_not_ours(self):
        """Ось — МОДУЛЬ плюс функция, а не имя функции: иначе любой чужой
        `whatever.sweep()` читался бы объявленной переписью."""
        tree = ast.parse("from pkg import other_census\n"
                         "class C:\n"
                         "    def test_one(self):\n"
                         "        other_census.sweep()\n"
                         "    def test_two(self):\n"
                         "        other_census.sweep()\n")
        cls = [n for n in ast.walk(tree) if isinstance(n, ast.ClassDef)][0]
        out = m.class_payers(cls, _DECLARED, m.module_aliases(tree))
        self.assertEqual(out["outcome"], m.NOT_CALLED, out["why"])

    def test_an_alias_of_the_declared_module_is_still_found(self):
        """`import ... as km` — живая форма ввоза во всём наборе."""
        tree = ast.parse("from pkg import thing_census as tc\n"
                         "class C:\n"
                         "    def test_one(self):\n"
                         "        tc.sweep()\n"
                         "    def test_two(self):\n"
                         "        tc.sweep()\n")
        cls = [n for n in ast.walk(tree) if isinstance(n, ast.ClassDef)][0]
        out = m.class_payers(cls, _DECLARED, m.module_aliases(tree))
        self.assertEqual(out["outcome"], m.MULTIPLIED, out["why"])

    def test_a_bare_name_call_is_not_a_call_of_the_declared_module(self):
        """Выжившая мутация M12 (цикл #1195): голое имя `sweep()` метки модуля не
        имеет ВОВСЕ, и подставить её значило бы вернуть сравнение по подстроке —
        любой местный помощник с тем же именем читался бы объявленной переписью."""
        out = _verdict(
            "class C:\n"
            "    def test_one(self):\n"
            "        sweep()\n"
            "    def test_two(self):\n"
            "        sweep()\n")
        self.assertEqual(out["outcome"], m.NOT_CALLED, out["why"])
        self.assertIsNone(m._call_label(
            ast.parse("sweep()").body[0].value),
            "голый зов обязан не иметь метки, а не получать выдуманную")

    def test_a_name_that_was_never_imported_is_not_our_subject(self):
        """Имя слева от точки не ввезено — вердикта о нём прибор не выносит."""
        tree = ast.parse("class C:\n"
                         "    def test_one(self):\n"
                         "        thing_census.sweep()\n"
                         "    def test_two(self):\n"
                         "        thing_census.sweep()\n")
        cls = [n for n in ast.walk(tree) if isinstance(n, ast.ClassDef)][0]
        out = m.class_payers(cls, _DECLARED, m.module_aliases(tree))
        self.assertEqual(out["outcome"], m.NOT_CALLED, out["why"])


class AnUnreadableFileIsTheThirdOutcome(unittest.TestCase):

    def test_a_broken_file_is_unmeasured_with_a_named_reason_not_zero(self):
        with tempfile.TemporaryDirectory(prefix="ccm_") as tmp:
            root = Path(tmp)
            (root / "spa_core/tests").mkdir(parents=True)
            (root / "spa_core/tests/test_broken.py").write_text(
                "class C:\n    def test_one(self):\n        'unterminated",
                encoding="utf-8")
            doc = m.census(root=root, declared=_DECLARED)
        self.assertEqual(doc["tally"][m.UNMEASURED], 1, doc["rows"])
        self.assertEqual(doc["files_unread"], 1)
        row = doc["rows"][0]
        self.assertTrue(row["why"].strip(), "причина пуста — это и есть ноль "
                                            "вместо третьего исхода")
        self.assertEqual(row["outcome"], m.UNMEASURED)

    def test_an_absent_root_is_not_a_clean_pass(self):
        """Каталога нет ⇒ строк нет, и это НЕ «множителя нет»: tally пуст,
        и вызывающий обязан различить пустоту от замера."""
        with tempfile.TemporaryDirectory(prefix="ccm_") as tmp:
            doc = m.census(root=Path(tmp), declared=_DECLARED)
        self.assertEqual(doc["rows"], [])
        self.assertEqual(sum(doc["tally"].values()), 0)


class TheLiveTreeIsMeasuredAndKnownMembersAreShown(unittest.TestCase):
    """ЖИВОЕ дерево + ИЗВЕСТНЫЙ член по обе стороны (форма ADR-1041/1043).

    Зов живого дерева стои́т в ТЕЛЕ теста намеренно: форма пробы ищет его только
    в области `test_*` (урок замера #1195 — ровно та дверь, о которую споткнулся
    перенос в `setUpClass`, см. ADR-1056 и `census_call_multiplier_baseline.json`).
    Цена зова измерена и мала: разбор AST тест-каталогов, секунды, а не минуты, —
    поэтому своего множителя этот класс не создаёт.
    """

    def test_the_live_census_names_the_known_member_on_each_side(self):
        doc = m.census(root=_REPO)
        rows = {f"{r['file']}::{r['class']}": r for r in doc["rows"]}
        cheap = ("spa_core/tests/test_subscript_silencer.py"
                 "::TheRepoPopulationIsMeasured")
        dear = ("spa_core/tests/test_known_member_probe_census.py"
                "::TheLiveTreeIsMeasuredAndKnownMembersAreShown")
        self.assertIn(cheap, rows, "известный ДЕШЁВЫЙ член не найден — замер, не "
                                   "нашедший известного члена, мерой не является")
        self.assertEqual(rows[cheap]["outcome"], m.ONCE,
                         "зов этого класса стои́т в setUpClass — цена ×1")
        self.assertIn(dear, rows, "известный ДОРОГОЙ член не найден")
        self.assertEqual(rows[dear]["outcome"], m.MULTIPLIED,
                         "этот класс зовёт перепись из тела каждого теста — "
                         "множитель 3, и он объявлен в базе")
        self.assertEqual(doc["files_unread"], 0,
                         "файлов не прочитано — ответ о дереве НЕ ПОЛОН")


class TheBaselineOnlyShrinks(unittest.TestCase):

    def test_no_multiplied_class_appeared_outside_the_declaration(self):
        declared = set(json.loads(_BASELINE.read_text(encoding="utf-8"))["members"])
        measured = {f"{r['file']}::{r['class']}" for r in m.census(root=_REPO)["rows"]
                    if r["outcome"] == m.MULTIPLIED}
        new = sorted(measured - declared)
        self.assertEqual(
            new, [],
            "дорогая перепись зовётся из тела КАЖДОГО теста в НОВОМ классе: "
            f"{new}. Выход — ОДИН зов на класс либо дешевле сама перепись, а НЕ "
            "строка в spa_core/tests/census_call_multiplier_baseline.json "
            "(инв. #16) и НЕ подъём --timeout")
        self.assertLessEqual(len(measured), len(declared),
                             "база класса может только УМЕНЬШАТЬСЯ")

    def test_every_declared_member_names_its_blocker(self):
        """Строка базы без НАЗВАННОЙ причины — это дописывание, а не объявление."""
        base = json.loads(_BASELINE.read_text(encoding="utf-8"))
        for name, row in base["members"].items():
            with self.subTest(member=name):
                self.assertTrue(row.get("blocker"), name)
                self.assertGreater(len(row.get("why_not_fixed", "")), 80, name)

    def test_the_declaration_names_only_classes_that_exist(self):
        base = json.loads(_BASELINE.read_text(encoding="utf-8"))
        for name in base["members"]:
            rel, _, cls = name.partition("::")
            with self.subTest(member=name):
                path = _REPO / rel
                self.assertTrue(path.exists(), f"файла нет: {rel}")
                tree = ast.parse(path.read_text(encoding="utf-8"))
                names = {n.name for n in ast.walk(tree)
                         if isinstance(n, ast.ClassDef)}
                self.assertIn(cls, names, f"класса нет в {rel}")


class TheThresholdIsNotTheWayOut(unittest.TestCase):

    def test_the_declared_timeout_matches_the_control_workflow(self):
        """Порог живёт в воркфлоу; копия здесь обязана с ним СОВПАДАТЬ, иначе
        множитель переводится в секунды по выдуманному числу."""
        flow = (_REPO / ".github/workflows/ci-control.yml").read_text(encoding="utf-8")
        self.assertIn(f"--timeout={m.RUNNER_TIMEOUT_S}", flow,
                      "порог воркфлоу разошёлся с объявленным в приборе: "
                      "поднимать его ЗАПРЕЩЕНО (инв. #16), а молча разойтись "
                      "значит считать множитель по чужому числу")


if __name__ == "__main__":
    unittest.main()
