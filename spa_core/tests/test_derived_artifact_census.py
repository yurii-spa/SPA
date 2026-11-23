#!/usr/bin/env python3
"""Контроль прибора и пробы класса «производный артефакт уехал без перемера».

Заказ G1061 п. 2 приказа владельца «Portfolio CIO», карточка
`inbox-izmerit-naselenie-klassa-proizvodnyi-art` (ADR-1074).

КАЖДЫЙ ТЕСТ ЗДЕСЬ — ПОЛОЖИТЕЛЬНЫЙ КОНТРОЛЬ НА НАСТОЯЩУЮ НАХОДКУ
─────────────────────────────────────────────────────────────────────────────
Проверка, никогда не видевшая настоящей поломки, — украшение
(`.claude/rules/deployment.md` § «Проверка сторожа сторожей»). Поломки, которые
воспроизводятся ниже, все ИЗМЕРЕНЫ 23.11 на `origin/main` 2fc564a0e:

* **`ast.walk(tree)` в поверхности.** Число «652» заказа G1061 снято наивным
  совпадением по ИМЕНИ МЕТОДА, и 547 из 653 файлов попали в поверхность через
  обход СИНТАКСИЧЕСКОГО дерева, каталогов не перечисляющий вовсе. Прибор,
  считающий метод по имени, отвечает на вопрос «как называется метод».
* **Маркер сцены спрашивался ОДИН раз.** `with tempfile.TemporaryDirectory()
  as td` даёт получателя `td`, и в ЕГО тексте маркера нет — маркер живёт в
  привязке. Первая редакция записала 130 таких зовов в «НЕ РАЗОБРАН», то есть
  завысила вилку на РАЗОБРАННОМ материале.
* **Третий исход нулём не считается** (инв. #17): неразобранный путь обязан
  давать НЕНУЛЕВОЙ код, а нечитаемое НАЗВАННОЕ дерево — код 2, а не молчаливый
  возврат к дереву прибора.

Время, номера процессов и git-окружение здесь не спрашиваются ни одной дверью:
прибор статический, а сцены строятся в одноразовых каталогах. Литеральных дат в
файле нет вовсе — значит и бомбы календаря нет по построению.
"""
from __future__ import annotations

import importlib.util
import pathlib
import sys
import tempfile
import unittest

REPO = pathlib.Path(__file__).resolve().parents[2]
CENSUS = REPO / "scripts" / "derived_artifact_census.py"


def _load():
    spec = importlib.util.spec_from_file_location("spa_dac_test", CENSUS)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules["spa_dac_test"] = mod
    spec.loader.exec_module(mod)
    return mod


def _scene(root: pathlib.Path, name: str, body: str) -> pathlib.Path:
    tests = root / "spa_core" / "tests"
    tests.mkdir(parents=True, exist_ok=True)
    path = tests / f"test_{name}.py"
    path.write_text(body, encoding="utf-8")
    return path


class TheMeasureIsNotTheMethodName(unittest.TestCase):
    """`ast.walk` каталогов не перечисляет — и это измеренная находка, не вкус."""

    def test_ast_walk_does_not_enter_the_surface(self):
        mod = _load()
        with tempfile.TemporaryDirectory(prefix="dac_t1_") as d:
            root = pathlib.Path(d)
            _scene(root, "ast_only",
                   "import ast\n"
                   "def test_x():\n"
                   "    assert list(ast.walk(ast.parse('x = 1')))\n")
            census = mod.measure_surface(root)
        self.assertEqual(len(census.entries), 0,
                         "обход синтаксического дерева попал в поверхность каталогов — "
                         "это дефект, давший «652» в заказе G1061")

    def test_an_aliased_ast_import_does_not_enter_the_surface_either(self):
        """`import ast as _ast` — тот же не-путь под другим именем (20 зовов)."""
        mod = _load()
        with tempfile.TemporaryDirectory(prefix="dac_t2_") as d:
            root = pathlib.Path(d)
            _scene(root, "ast_alias",
                   "import ast as _ast\n"
                   "def test_x():\n"
                   "    assert list(_ast.walk(_ast.parse('x = 1')))\n")
            census = mod.measure_surface(root)
        self.assertEqual(len(census.entries), 0,
                         "псевдоним не-пути прошёл в поверхность: проверка смотрит на "
                         "имя получателя, а не на то, чем он является")

    def test_a_real_directory_walk_DOES_enter_the_surface(self):
        """Обратная половина: мера, не видящая настоящего обхода, бесполезна."""
        mod = _load()
        with tempfile.TemporaryDirectory(prefix="dac_t3_") as d:
            root = pathlib.Path(d)
            (root / "spa_core" / "analytics").mkdir(parents=True)
            _scene(root, "os_walk",
                   "import os, pathlib\n"
                   "def test_x():\n"
                   "    root = pathlib.Path(__file__).resolve().parents[2]\n"
                   "    assert list(os.walk(root / 'spa_core' / 'analytics'))\n")
            census = mod.measure_surface(root)
        self.assertEqual(len(census.entries), 1)
        self.assertEqual(census.entries[0].kind, mod.SOURCE_DIR)
        self.assertEqual(census.entries[0].source_dirs, ["spa_core/analytics"])


class TheFourLabelsAreDistinguishable(unittest.TestCase):
    """Совпади любые два ярлыка — прибор мерит не то, что объявляет."""

    def _kind(self, mod, name: str, body: str):
        with tempfile.TemporaryDirectory(prefix="dac_k_") as d:
            root = pathlib.Path(d)
            _scene(root, name, body)
            census = mod.measure_surface(root)
            self.assertEqual(len(census.entries), 1, f"сцена {name}: поверхность не одна")
            return census.entries[0].kind, census.code

    def test_source_state_sandbox_and_unresolved_are_four_different_answers(self):
        mod = _load()
        source, _ = self._kind(mod, "src",
                               "import pathlib\n"
                               "def test_x():\n"
                               "    r = pathlib.Path(__file__).resolve().parents[2]\n"
                               "    assert list((r / 'spa_core' / 'analytics').glob('*.py'))\n")
        state, _ = self._kind(mod, "state",
                              "import pathlib\n"
                              "def test_x():\n"
                              "    r = pathlib.Path(__file__).resolve().parents[2]\n"
                              "    assert list((r / 'data').glob('*.json'))\n")
        sandbox, _ = self._kind(mod, "sand",
                                "import pathlib, tempfile\n"
                                "def test_x():\n"
                                "    with tempfile.TemporaryDirectory() as td:\n"
                                "        assert not list(pathlib.Path(td).glob('*'))\n")
        unresolved, code = self._kind(mod, "unres",
                                      "def test_x(fixture_dir):\n"
                                      "    assert list(fixture_dir.glob('*.py'))\n")
        self.assertEqual(
            [source, state, sandbox, unresolved],
            [mod.SOURCE_DIR, mod.STATE_DIR, mod.SANDBOX, mod.UNRESOLVED],
            "четыре ярлыка не различимы — ответ прибора зависит не от того, что он мерит")
        self.assertNotEqual(code, 0,
                            "НЕ РАЗОБРАННЫЙ путь дал код 0: третий исход неотличим от "
                            "«чисто», и это ровно предмет инв. #17")

    def test_the_sandbox_marker_is_asked_at_EVERY_step_not_only_the_first(self):
        """Привязка `as td` несёт маркер, а получатель `td` — нет (130 зовов)."""
        mod = _load()
        kind, _ = self._kind(mod, "bound_sandbox",
                             "import pathlib, tempfile\n"
                             "def test_x():\n"
                             "    with tempfile.TemporaryDirectory() as td:\n"
                             "        here = pathlib.Path(td) / 'sub'\n"
                             "        here.mkdir()\n"
                             "        assert not list(here.glob('*'))\n")
        self.assertEqual(kind, mod.SANDBOX,
                         "сцена, чей маркер живёт в привязке, записана в «НЕ РАЗОБРАН» — "
                         "вилка населения завышена на разобранном материале")

    def test_a_TemporaryDirectory_dot_name_receiver_is_a_sandbox(self):
        """`self.tmp.name` — путь каталога сцены, и так написаны 75 зовов набора."""
        mod = _load()
        kind, _ = self._kind(mod, "dot_name",
                             "import pathlib, tempfile, unittest\n"
                             "class T(unittest.TestCase):\n"
                             "    def setUp(self):\n"
                             "        self.tmp = tempfile.TemporaryDirectory()\n"
                             "        self.dir = pathlib.Path(self.tmp.name) / 'tracker'\n"
                             "        self.dir.mkdir()\n"
                             "    def test_x(self):\n"
                             "        assert not list(self.dir.glob('*.md'))\n")
        self.assertEqual(kind, mod.SANDBOX)


class TheThirdOutcomeIsNotZero(unittest.TestCase):
    """Инв. #17: измерено · измерено и равно нулю · НЕ ИЗМЕРЕНО — три исхода."""

    def test_an_unreadable_NAMED_tree_refuses_with_code_2(self):
        mod = _load()
        import contextlib, io
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            code = mod.main(["--repo-root", str(REPO / "net-takogo-dereva-kontrol"), "--surface"])
        self.assertEqual(code, 2,
                         "нечитаемое НАЗВАННОЕ дерево не дало кода 2 — прибор молча вернулся "
                         "к своему дереву, и читатель не узнает, о чьём дереве ему ответили")

    def test_an_empty_tests_directory_is_unmeasured_not_a_clean_zero(self):
        mod = _load()
        with tempfile.TemporaryDirectory(prefix="dac_empty_") as d:
            root = pathlib.Path(d)
            (root / "spa_core" / "tests").mkdir(parents=True)
            with self.assertRaises(mod.NotMeasured):
                mod.measure_surface(root)

    def test_the_default_tree_is_PRINTED_not_silent(self):
        """Умолчание печатается: молча подставить дерево хуже ошибки."""
        mod = _load()
        import contextlib, io
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            root = mod._resolve_root(None)
        self.assertIn(str(root), err.getvalue())
        self.assertIn("НЕ НАЗВАН", err.getvalue())


class TheProbeMeasuresTheOutcomeNotTheProse(unittest.TestCase):
    """Проба приёмки: зелена на целом контуре, красна на каждом порванном звене."""

    def _probe(self, repo_root):
        from spa_core.monitoring import card_acceptance as ca
        return ca.PROBES["derived_artifact_class_population_named"](
            None, repo_root=str(repo_root))

    @staticmethod
    def _full_scene(root: pathlib.Path) -> None:
        """Одноразовое дерево с ПРИБОРОМ, ОБЪЯВЛЕНИЕМ и живой поверхностью."""
        import json
        import shutil
        (root / "scripts").mkdir(parents=True, exist_ok=True)
        shutil.copy2(CENSUS, root / "scripts" / CENSUS.name)
        tests = root / "spa_core" / "tests"
        tests.mkdir(parents=True, exist_ok=True)
        (root / "spa_core" / "analytics").mkdir(parents=True, exist_ok=True)
        _scene(root, "guard_of_a_derived_artifact",
               "import pathlib\n"
               "def test_x():\n"
               "    r = pathlib.Path(__file__).resolve().parents[2]\n"
               "    assert list((r / 'spa_core' / 'analytics').glob('*.py'))\n")
        mod = _load()
        # Известные члены класса обязаны быть В ПРЕДМЕТЕ — иначе форма
        # опровергнута и число предмета населением класса не является.
        for known in mod.KNOWN_MEMBERS:
            name = pathlib.PurePosixPath(known).name[len("test_"):-len(".py")]
            _scene(root, name,
                   "import pathlib\n"
                   "def test_x():\n"
                   "    r = pathlib.Path(__file__).resolve().parents[2]\n"
                   "    assert list((r / 'spa_core' / 'analytics').glob('*.py'))\n")
        counts = mod.measure_surface(root).counts
        (root / "scripts" / "derived_artifact_baseline.json").write_text(json.dumps({
            "measured_at": "scene", "tree": "scene", "counts": counts,
            "unresolved_is_not_zero": True,
            "members": [{"path": "spa_core/tests/test_guard_of_a_derived_artifact.py",
                         "enumerated_dir": "spa_core/analytics",
                         "needs": "delivery_gate",
                         "reason": "сцена: сторож производного артефакта"}],
        }, ensure_ascii=False), encoding="utf-8")

    def test_the_probe_is_green_on_a_whole_circuit(self):
        from spa_core.monitoring import card_acceptance as ca
        with tempfile.TemporaryDirectory(prefix="dac_whole_") as d:
            root = pathlib.Path(d)
            self._full_scene(root)
            status, why = self._probe(root)
        self.assertEqual(status, ca.SATISFIED, why)

    def test_a_missing_declaration_is_not_satisfied(self):
        from spa_core.monitoring import card_acceptance as ca
        with tempfile.TemporaryDirectory(prefix="dac_nodecl_") as d:
            root = pathlib.Path(d)
            self._full_scene(root)
            (root / "scripts" / "derived_artifact_baseline.json").unlink()
            status, why = self._probe(root)
        self.assertEqual(status, ca.NOT_SATISFIED, why)
        self.assertIn("объявления нет", why)

    def test_a_declaration_that_DRIFTED_from_the_live_measurement_is_not_satisfied(self):
        """Объявление, которому нечем состариться вместе с деревом, есть проза."""
        from spa_core.monitoring import card_acceptance as ca
        import json
        with tempfile.TemporaryDirectory(prefix="dac_drift_") as d:
            root = pathlib.Path(d)
            self._full_scene(root)
            decl = root / "scripts" / "derived_artifact_baseline.json"
            doc = json.loads(decl.read_text(encoding="utf-8"))
            doc["counts"][_load().SOURCE_DIR] += 7
            decl.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
            status, why = self._probe(root)
        self.assertEqual(status, ca.NOT_SATISFIED, why)
        self.assertIn("РАЗОШЛОСЬ", why)

    def test_a_member_without_a_needs_from_the_closed_vocabulary_is_not_satisfied(self):
        from spa_core.monitoring import card_acceptance as ca
        import json
        with tempfile.TemporaryDirectory(prefix="dac_needs_") as d:
            root = pathlib.Path(d)
            self._full_scene(root)
            decl = root / "scripts" / "derived_artifact_baseline.json"
            doc = json.loads(decl.read_text(encoding="utf-8"))
            doc["members"][0]["needs"] = "пожалуй, что-нибудь"
            decl.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
            status, why = self._probe(root)
        self.assertEqual(status, ca.NOT_SATISFIED, why)
        self.assertIn("вне словаря", why)

    def test_a_member_with_needs_but_no_reason_is_not_satisfied(self):
        from spa_core.monitoring import card_acceptance as ca
        import json
        with tempfile.TemporaryDirectory(prefix="dac_reason_") as d:
            root = pathlib.Path(d)
            self._full_scene(root)
            decl = root / "scripts" / "derived_artifact_baseline.json"
            doc = json.loads(decl.read_text(encoding="utf-8"))
            doc["members"][0]["reason"] = "   "
            decl.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
            status, why = self._probe(root)
        self.assertEqual(status, ca.NOT_SATISFIED, why)
        self.assertIn("причина НЕТ", why)

    def test_a_declaration_denying_the_third_outcome_is_not_satisfied(self):
        from spa_core.monitoring import card_acceptance as ca
        import json
        with tempfile.TemporaryDirectory(prefix="dac_third_") as d:
            root = pathlib.Path(d)
            self._full_scene(root)
            decl = root / "scripts" / "derived_artifact_baseline.json"
            doc = json.loads(decl.read_text(encoding="utf-8"))
            doc["unresolved_is_not_zero"] = False
            decl.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
            status, why = self._probe(root)
        self.assertEqual(status, ca.NOT_SATISFIED, why)

    def test_an_instrument_that_counts_ast_walk_is_UNMEASURED_not_green(self):
        """Нулевая проба: НАСТОЯЩАЯ находка #1218 в её НАСТОЯЩЕМ месте.

        Прибор лишается вопроса о получателе — ровно та редакция, что дала «652».
        Проба обязана ответить `unmeasured`: прибор, не ловящий свою аварию,
        печатает «✅» и ничего не утверждает.
        """
        from spa_core.monitoring import card_acceptance as ca
        with tempfile.TemporaryDirectory(prefix="dac_zero_") as d:
            root = pathlib.Path(d)
            self._full_scene(root)
            tool = root / "scripts" / CENSUS.name
            src = tool.read_text(encoding="utf-8")
            broken = src.replace(
                "NON_PATH_RECEIVERS = frozenset({\"ast\",",
                "NON_PATH_RECEIVERS = frozenset({\"_never_a_receiver_1218\",", 1)
            self.assertNotEqual(broken, src, "якорь мутации не найден — контроль не состоялся")
            tool.write_text(broken, encoding="utf-8")
            status, why = self._probe(root)
        self.assertEqual(status, ca.UNMEASURED, why)
        self.assertIn("ast.walk", why)

    def test_an_instrument_without_the_surface_door_is_UNMEASURED(self):
        """Дыра покрытия, найденная #1202 и #1217: подать прибор БЕЗ двери разбора."""
        from spa_core.monitoring import card_acceptance as ca
        with tempfile.TemporaryDirectory(prefix="dac_nodoor_") as d:
            root = pathlib.Path(d)
            self._full_scene(root)
            tool = root / "scripts" / CENSUS.name
            src = tool.read_text(encoding="utf-8")
            tool.write_text(src.replace("def measure_surface(", "def _measure_surface_renamed(", 1),
                            encoding="utf-8")
            status, why = self._probe(root)
        self.assertEqual(status, ca.UNMEASURED, why)
        self.assertIn("measure_surface", why)

    def test_an_absent_instrument_is_not_satisfied_not_a_silent_pass(self):
        from spa_core.monitoring import card_acceptance as ca
        with tempfile.TemporaryDirectory(prefix="dac_notool_") as d:
            root = pathlib.Path(d)
            self._full_scene(root)
            (root / "scripts" / CENSUS.name).unlink()
            status, why = self._probe(root)
        self.assertEqual(status, ca.NOT_SATISFIED, why)

    def test_a_form_that_LOSES_a_known_member_is_not_satisfied(self):
        """Форма, потерявшая известного члена, ОПРОВЕРГНУТА — замер #1218.

        «Тест САМ перечисляет каталог» теряла 2 из 3 артефактов, у которых класс
        уже найден поимённо: оба перечисляют через помощника. При такой форме
        число предмета есть ответ о поверхности, которой перепись не видела.
        """
        from spa_core.monitoring import card_acceptance as ca
        with tempfile.TemporaryDirectory(prefix="dac_lost_") as d:
            root = pathlib.Path(d)
            self._full_scene(root)
            mod = _load()
            victim = sorted(mod.KNOWN_MEMBERS)[0]
            (root / victim).unlink()
            status, why = self._probe(root)
        self.assertEqual(status, ca.NOT_SATISFIED, why)
        self.assertIn("ОПРОВЕРГНУТА", why)

    def test_the_probe_refuses_an_argument(self):
        from spa_core.monitoring import card_acceptance as ca
        status, why = ca.PROBES["derived_artifact_class_population_named"]("spa_core/x.py")
        self.assertEqual(status, ca.UNMEASURED, why)


if __name__ == "__main__":
    unittest.main()
