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


class SurvivorsOfTheMutationRunOfCycle1223(unittest.TestCase):
    """Сцены, которых НЕ БЫЛО: каждая убивает мутанта, пережившего замер #1223.

    Долг G1062 п. 7 («мутационный прогон прибора ADR-1074 не запускался») был
    закрыт циклом #1223: 20 мутаций, **убито 13, выжило 7**. Четверо выживших
    были дырами покрытия, и четыре теста ниже — ровно они. Остальные трое
    записаны там, где их место: двое — дефекты МЕРКИ (укреплены в
    `test_an_instrument_without_the_surface_door_is_UNMEASURED` и в самой пробе
    `card_acceptance`), один — ЭКВИВАЛЕНТНЫЙ мутант, доказанный замером
    (см. `test_the_pytest_fixture_branch_is_UNREACHABLE_and_that_is_measured`).
    """

    def test_a_DOTTED_non_path_receiver_does_not_enter_the_surface(self):
        """`ast.helpers.walk(tree)` — получатель точечный, корень его не путь.

        Мутация «точечный не-путь снова входит» выжила: ни одна сцена не
        подавала получателя вида `<не-путь>.<что-то>`. Ветка в приборе есть, а
        свидетеля у неё не было.
        """
        mod = _load()
        with tempfile.TemporaryDirectory(prefix="dac_dotted_") as d:
            root = pathlib.Path(d)
            _scene(root, "dotted_non_path",
                   "import ast\n"
                   "def test_x():\n"
                   "    tree = ast.parse('x = 1')\n"
                   "    assert list(ast.helpers.walk(tree))\n")
            surface = mod.measure_surface(root)
        self.assertEqual(surface.entries, [],
                         "точечный получатель, чей корень — не путь, вошёл в "
                         "поверхность: это снова мерка по ИМЕНИ МЕТОДА")

    def test_a_form_that_loses_a_known_member_gives_CODE_2_not_a_number(self):
        """Потеря известного члена обязана быть видна КОДОМ, а не только прозой.

        Мутация «форма, потерявшая известного члена, всё равно печатает число»
        выжила: вердикт `Surface.code` на этом состоянии не спрашивал никто —
        проба читает `lost_known_members` своей отдельной веткой.
        """
        mod = _load()
        with tempfile.TemporaryDirectory(prefix="dac_lost_") as d:
            root = pathlib.Path(d)
            _scene(root, "some_guard",
                   "import pathlib\n"
                   "def test_x():\n"
                   "    r = pathlib.Path(__file__).resolve().parents[2]\n"
                   "    assert list((r / 'spa_core' / 'analytics').glob('*.py'))\n")
            surface = mod.measure_surface(root)
            self.assertTrue(surface.lost_known_members,
                            "сцена не обеспечена: известные члены обязаны быть ПОТЕРЯНЫ")
            self.assertEqual(surface.code, 2,
                             "форма ОПРОВЕРГНУТА, а код не 2 — число предмета "
                             "выдавалось бы за население класса")

    def test_the_known_members_are_anchored_OUTSIDE_the_instrument(self):
        """Якорь известных членов обязан быть НЕЗАВИСИМ от самого прибора.

        Мутация «`KNOWN_MEMBERS` опустошены» выжила, и это дефект КОНТРОЛЯ, а не
        прибора: сцена пробы подкладывает членов, перечисляя `mod.KNOWN_MEMBERS`,
        поэтому пустой словарь означает «подложить нечего и проверять нечего» —
        сверка одного и того же с самим собой. Три пути названы ЗДЕСЬ, и
        опустошение словаря в приборе краснит этот тест.
        """
        mod = _load()
        self.assertEqual(set(mod.KNOWN_MEMBERS), {
            "spa_core/tests/test_untiered_census.py",
            "spa_core/tests/test_tracker_board_matches_cards.py",
            "spa_core/tests/test_adr_index_titles.py",
            # ЧЕТВЁРТЫЙ дочитан циклом #1259 (ADR-1113), и это УСИЛЕНИЕ якоря, а
            # не его ослабление (инв. #16): перечень был заморожен на трёх, член
            # найден 26.11 (ADR-1112), и прибор печатал «все 3 из 3 ВНУТРИ
            # предмета» — правду о СПИСКЕ вместо ответа о КЛАССЕ. Контроль, не
            # знающий о члене, не может быть им опровергнут.
            "spa_core/tests/test_python_git_ref_provenance.py",
        }, "перечень известных членов класса разошёлся с независимым якорем: "
           "каждый найден поимённо ПОСЛЕ того, как красное уехало на "
           "`main` (ADR-1073 · ADR-1060 · ADR-889 · ADR-1112)")
        for path, why in mod.KNOWN_MEMBERS.items():
            with self.subTest(member=path):
                self.assertTrue(str(why).strip(),
                                "у известного члена обязана быть НАЗВАННАЯ причина")

    def test_the_ONE_HOP_through_a_helper_is_what_finds_2_of_3_members(self):
        """Хоп через помощника — центральное притязание ADR-1074, и свидетеля у него не было.

        Мутация «хоп снят» выжила: форма «тест САМ перечисляет каталог» находит
        1 известного члена из 3, остальные два перечисляют каталог ЧЕРЕЗ
        ПОМОЩНИКА. Сцена ниже — ровно эта форма: тест не перечисляет ничего сам,
        каталог перечисляет ввезённый помощник репозитория.
        """
        mod = _load()
        with tempfile.TemporaryDirectory(prefix="dac_hop_") as d:
            root = pathlib.Path(d)
            helper = root / "scripts" / "zz_helper_of_the_scene.py"
            helper.parent.mkdir(parents=True, exist_ok=True)
            helper.write_text(
                "import pathlib\n"
                "def modules_on_disk():\n"
                "    r = pathlib.Path(__file__).resolve().parents[1]\n"
                "    return sorted((r / 'spa_core' / 'analytics').glob('*.py'))\n",
                encoding="utf-8")
            (root / "spa_core" / "analytics").mkdir(parents=True, exist_ok=True)
            _scene(root, "guard_through_a_helper",
                   "import importlib.util, pathlib\n"
                   "HELPER = pathlib.Path(__file__).resolve().parents[2] / 'scripts' / "
                   "'zz_helper_of_the_scene.py'\n"
                   "def test_x():\n"
                   "    spec = importlib.util.spec_from_file_location('h', HELPER)\n"
                   "    mod = importlib.util.module_from_spec(spec)\n"
                   "    spec.loader.exec_module(mod)\n"
                   "    assert mod.modules_on_disk() is not None\n")
            surface = mod.measure_surface(root)
        paths = [e.path for e in surface.entries]
        self.assertIn("spa_core/tests/test_guard_through_a_helper.py", paths,
                      "тест, перечисляющий каталог ЧЕРЕЗ ПОМОЩНИКА, не вошёл в "
                      "поверхность — именно эта форма теряет 2 известных члена из 3")

    def test_the_pytest_fixture_branch_is_UNREACHABLE_and_that_is_measured(self):
        """ЭКВИВАЛЕНТНЫЙ мутант записан как эквивалентный, а не замазан сценой.

        Мутация «фикстура pytest перестаёт быть одноразовым каталогом»
        (`if expr.id in PYTEST_TMP_FIXTURES` → `if False`) выжила, и дырой
        покрытия это НЕ является: КАЖДОЕ имя из `PYTEST_TMP_FIXTURES` ловится
        РАНЬШЕ циклом `SANDBOX_MARKERS` по тексту выражения (`tmp_path` и
        `tmpdir` дословно, `tmp_path_factory` — подстрокой `tmp_path`). Ветка
        недостижима, и её причина («фикстура pytest …») не произносится никогда.

        Тест закрепляет ИМЕННО это: выдумывать эквивалентному мутанту сцену
        значило бы получить зелёный тест, ничего не проверяющий (урок #1217).
        Станет хоть одно имя фикстуры не-подстрокой маркеров — тест покраснеет,
        и ветку надо будет либо снабдить сценой, либо снять.
        """
        mod = _load()
        for name in sorted(mod.PYTEST_TMP_FIXTURES):
            with self.subTest(fixture=name):
                caught = [m for m in mod.SANDBOX_MARKERS if m in name]
                self.assertTrue(caught, f"имя `{name}` маркерами НЕ ловится — "
                                        "ветка PYTEST_TMP_FIXTURES стала достижима, "
                                        "и ей нужна своя сцена")
        with tempfile.TemporaryDirectory(prefix="dac_fixture_") as d:
            root = pathlib.Path(d)
            _scene(root, "tmp_path_receiver",
                   "def test_x(tmp_path):\n"
                   "    assert list(tmp_path.glob('*'))\n")
            surface = _load().measure_surface(root)
        self.assertEqual([e.kind for e in surface.entries], [mod.SANDBOX])
        self.assertIn("в выражении", surface.entries[0].calls[0].reason,
                      "ярлык пришёл НЕ от маркера — значит ветка фикстур всё же "
                      "работает, и эквивалентность мутанта больше не доказана")


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
        # ADR-1078 (#1223): здесь стояло только `assertIn("measure_surface", why)`,
        # и мутация «проба не спрашивает у прибора НИ ОДНОЙ двери»
        # (`for door in ():`) ВЫЖИЛА: без переписи дверей проба падала ПОЗЖЕ, на
        # `mod.measure_surface(...)`, ловила это своим `except BaseException` и
        # возвращала текст, в котором то же слово есть СЛУЧАЙНО. Тест был зелен
        # по другой причине — поэтому спрашивается именно ВЕРДИКТ переписи
        # дверей, а не наличие слова.
        self.assertIn("нет двери", why,
                      "проба обязана назвать ОТСУТСТВИЕ ДВЕРИ, а не упасть позже "
                      "на её использовании: второе зелено и при снятой переписи")
        # Притязание об ИМЕНИ двери снимать нельзя: «нет двери» верно и о чужой
        # двери, а отказ обязан назвать ИМЕННО ту, которой нет. Два утверждения,
        # и ни одно не покрывает другое — поэтому оба, а не одно вместо другого
        # (находка цикла #1223 по предупреждению пушера о провенансе: укрепляя
        # тест, я снял слабое притязание вместо того, чтобы добавить сильное).
        self.assertIn("measure_surface", why,
                      "отказ не назвал ИМЯ отсутствующей двери — читатель не "
                      "узнает, чего именно у прибора нет")

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


class TheTwoDoorsThatTheFourthKnownMemberNeeded(unittest.TestCase):
    """Замер #1259: ни одна из двух дверей в одиночку члена 4 не возвращает.

    Поломка, которую воспроизводит КАЖДАЯ проба ниже, измерена на живом дереве
    `fbb0fa45a`: `spa_core/tests/test_python_git_ref_provenance.py` (ADR-1112)
    отсутствовал в поверхности ВОВСЕ — `_repo_helpers` отдавал `[]`, а
    `_named_source_dirs` отдавал `[]`, — при том что прибор печатал «все 3
    известных члена ВНУТРИ предмета». Правда о списке за ответ о классе.
    """

    #: Сцена четвёртого члена ДОСЛОВНО по форме: каталог на `sys.path`, ввоз
    #: помощника БАРЕ-ИМЕНЕМ, корень репозитория привязкой, перечисление — в
    #: помощнике по аргументу. Обе двери нужны одновременно.
    MEMBER4_FORM = (
        "import sys\n"
        "from pathlib import Path\n"
        "REPO = Path(__file__).resolve().parents[2]\n"
        "sys.path.insert(0, str(REPO / 'scripts'))\n"
        "from zz_tool_of_the_scene import main\n"
        "def test_x():\n"
        "    assert main(['--root', str(REPO)]) == 0\n")

    HELPER = ("import pathlib\n"
              "def python_files(root):\n"
              "    return sorted(root.rglob('*.py'))\n"
              "def main(argv):\n"
              "    return 0 if python_files(pathlib.Path(argv[1])) else 1\n")

    def _scene_of_member4(self, root: pathlib.Path) -> None:
        helper = root / "scripts" / "zz_tool_of_the_scene.py"
        helper.parent.mkdir(parents=True, exist_ok=True)
        helper.write_text(self.HELPER, encoding="utf-8")
        _scene(root, "like_member_four", self.MEMBER4_FORM)

    def test_a_helper_imported_by_BARE_NAME_after_sys_path_insert_is_found(self):
        """Дверь 1. Голова баре-ввоза каталога не называет — найти его можно

        только через каталоги, которые файл САМ положил на `sys.path`. До #1259
        поиск помощников знал лишь пунктирную форму (`scripts.x`), и помощник
        четвёртого члена был невидим.
        """
        mod = _load()
        with tempfile.TemporaryDirectory(prefix="dac_bare_") as d:
            root = pathlib.Path(d)
            self._scene_of_member4(root)
            path = root / "spa_core" / "tests" / "test_like_member_four.py"
            import ast as _ast
            tree = _ast.parse(path.read_text(encoding="utf-8"))
            res = mod._PathResolver(tree, pathlib.PurePosixPath(
                "spa_core/tests/test_like_member_four.py"))
            helpers = [h.relative_to(root).as_posix()
                       for h in mod._repo_helpers(root, tree, res)]
        self.assertIn("scripts/zz_tool_of_the_scene.py", helpers,
                      "помощник, ввезённый БАРЕ-ИМЕНЕМ после `sys.path.insert`, "
                      "не найден — хоп через него не состоится, и член класса "
                      "окажется ВНЕ поверхности молча")

    def test_sys_path_dirs_asks_the_RECEIVER_not_the_method_name(self):
        """Обратная половина двери 1: `insert` носят десятки списков.

        Совпадение по ИМЕНИ МЕТОДА — ровно тот дефект, из-за которого в
        поверхность попали 547 зовов `ast.walk` (ADR-1074). Здесь каталог
        кладётся в ОБЫЧНЫЙ список, и каталогом на пути поиска он не является.
        """
        mod = _load()
        with tempfile.TemporaryDirectory(prefix="dac_recv_") as d:
            root = pathlib.Path(d)
            (root / "scripts").mkdir(parents=True, exist_ok=True)
            _scene(root, "not_sys_path",
                   "from pathlib import Path\n"
                   "REPO = Path(__file__).resolve().parents[2]\n"
                   "bag = []\n"
                   "bag.insert(0, str(REPO / 'scripts'))\n"
                   "def test_x():\n"
                   "    assert bag\n")
            path = root / "spa_core" / "tests" / "test_not_sys_path.py"
            import ast as _ast
            tree = _ast.parse(path.read_text(encoding="utf-8"))
            res = mod._PathResolver(tree, pathlib.PurePosixPath(
                "spa_core/tests/test_not_sys_path.py"))
            dirs = [str(x) for x in mod._sys_path_dirs(root, tree, res)]
        self.assertEqual([], dirs,
                         "каталог, положенный в ОБЫЧНЫЙ список, объявлен лежащим "
                         "на `sys.path` — мерка отвечает на вопрос «как называется "
                         "метод», а не «что на пути поиска»")

    def test_the_repo_ROOT_is_a_source_dir_and_not_an_empty_path(self):
        """Дверь 2. Корень репозитория — МАКСИМАЛЬНЫЙ каталог исходников.

        До #1259 `_named_source_dirs` отбрасывал путь с пустыми `parts`, то есть
        отвечал на вопрос «назван ли ПОДКАТАЛОГ». Сторож, чей помощник
        перечисляет `REPO.rglob('*.py')`, краснеет от ЛЮБОГО нового `*.py` —
        это самый сильный член класса, и отбрасывать его значило ошибаться в
        сторону «чисто».
        """
        mod = _load()
        with tempfile.TemporaryDirectory(prefix="dac_root_") as d:
            root = pathlib.Path(d)
            self._scene_of_member4(root)
            path = root / "spa_core" / "tests" / "test_like_member_four.py"
            import ast as _ast
            tree = _ast.parse(path.read_text(encoding="utf-8"))
            res = mod._PathResolver(tree, pathlib.PurePosixPath(
                "spa_core/tests/test_like_member_four.py"))
            named = mod._named_source_dirs(root, res)
        self.assertIn(".", named,
                      "корень репозитория не назван каталогом исходников — "
                      "сторож, перечисляющий всё дерево, выпадает из предмета")

    def test_the_state_dir_is_STILL_not_a_source_dir(self):
        """Обратная половина двери 2: `data/` предметом не стало.

        Правка «пустые `parts` больше не отказ» могла снять и отсев каталога
        СОСТОЯНИЯ — тогда предмет вырос бы на сторожей, чей набор доставкой кода
        не растёт вовсе. Проба закрепляет, что отсев жив.
        """
        mod = _load()
        with tempfile.TemporaryDirectory(prefix="dac_state_") as d:
            root = pathlib.Path(d)
            (root / "data").mkdir(parents=True, exist_ok=True)
            (root / "scripts").mkdir(parents=True, exist_ok=True)
            _scene(root, "state_named",
                   "from pathlib import Path\n"
                   "REPO = Path(__file__).resolve().parents[2]\n"
                   "DATA = REPO / 'data'\n"
                   "def test_x():\n"
                   "    assert DATA.is_dir()\n")
            path = root / "spa_core" / "tests" / "test_state_named.py"
            import ast as _ast
            tree = _ast.parse(path.read_text(encoding="utf-8"))
            res = mod._PathResolver(tree, pathlib.PurePosixPath(
                "spa_core/tests/test_state_named.py"))
            named = mod._named_source_dirs(root, res)
        self.assertNotIn("data", named,
                         "каталог СОСТОЯНИЯ объявлен каталогом исходников — "
                         "доставкой кода его набор не растёт, и предмет раздулся "
                         "бы на сторожей вне класса")

    def test_BOTH_doors_are_needed_for_the_member4_form(self):
        """Несущее утверждение #1259: ни одна дверь в одиночку члена не вернёт.

        Замер на живом дереве дал это тремя редакциями (121 / 123 / 401 — член
        ВНЕ предмета у всех трёх, 412 — ВНУТРИ). Здесь то же утверждение
        закреплено сценой: у формы члена 4 отбирается по одной двери, и предмет
        обязан ПОТЕРЯТЬ файл в обоих случаях.
        """
        mod = _load()
        with tempfile.TemporaryDirectory(prefix="dac_both_") as d:
            root = pathlib.Path(d)
            self._scene_of_member4(root)
            rel = "spa_core/tests/test_like_member_four.py"

            with_both = {e.path for e in mod.measure_surface(root).subject}
            self.assertIn(rel, with_both,
                          "обе двери на месте, а член формы 4 вне предмета")

            # дверь 1 отобрана: каталоги `sys.path` не спрашиваются
            orig_sys = mod._sys_path_dirs
            try:
                mod._sys_path_dirs = lambda *a, **k: []
                без_двери1 = {e.path for e in mod.measure_surface(root).subject}
            finally:
                mod._sys_path_dirs = orig_sys
            self.assertNotIn(rel, без_двери1,
                             "без двери 1 член формы 4 ВСЁ ЕЩЁ в предмете — "
                             "значит проба закрепляет не ту дверь")

            # дверь 2 отобрана: корень репозитория снова отбрасывается
            orig_named = mod._named_source_dirs
            try:
                mod._named_source_dirs = (
                    lambda r, res: [x for x in orig_named(r, res) if x != "."])
                без_двери2 = {e.path for e in mod.measure_surface(root).subject}
            finally:
                mod._named_source_dirs = orig_named
            self.assertNotIn(rel, без_двери2,
                             "без двери 2 член формы 4 ВСЁ ЕЩЁ в предмете — "
                             "значит корень репозитория был не нужен")

    def test_the_INERT_plant_boundary_is_PRINTED_not_left_in_prose(self):
        """Граница зонда обязана быть в ОТЧЁТЕ, а не только в докстринге.

        Замер #1259 на четвёртом члене: инертный зонд оставил предмет храповика
        на 80, содержательный довёл до 81. Значит «не предмет» у такого сторожа
        есть ответ О ЗОНДЕ. Читатель отчёта обязан это видеть — иначе он примет
        ответ о зонде за ответ о классе.
        """
        mod = _load()
        empty = mod.Differential(root="/nowhere", entries=[])
        text = mod.render_differential(empty)
        self.assertIn("ЗОНД ИНЕРТЕН", text,
                      "граница зонда в отчёте не напечатана")
        self.assertIn("80", mod.PLANTED_INERT,
                      "у границы зонда нет ЗАМЕРА — осторожность вместо числа")

    def test_an_already_red_guard_is_not_called_not_a_subject(self):
        """Премиса дифференциала: «красен ДО» — третий исход, а не «не предмет».

        Четвёртый член класса красен на чистом `main` (долг храповика 80 против
        базы 50 — ADR-1112 назвал это верным), и дифференциал по нему дал
        `already_red`. Прочитать это как «не предмет» значило бы объявить
        члена класса не-членом по причине, к классу не относящейся.
        """
        mod = _load()
        kind, why = mod._classify("failed=1,passed=47", "failed=1,passed=47")
        self.assertEqual(mod.ALREADY_RED, kind)
        self.assertNotEqual(mod.NOT_SUBJECT, kind,
                            "красный ДО подкладывания объявлен «не предметом»")
        self.assertIn("зелёным", why,
                      "причина не называет недоступную премису")


class TheInertPlantBoundaryIsNowASKEDNotOnlyNAMED(unittest.TestCase):
    """Заказ G1103 п. 3, цикл #1612 — направление 2 карточки класса ADR-1127.

    ЧТО ИЗМЕРЕНО И ПОЧЕМУ ЭТО НАХОДКА. Граница `PLANTED_INERT` названа верно и
    напечатана СВОДКОЙ отчёта — но вердикт КАЖДОЙ записи `not_subject` читался
    «вердикт тот же», а `Differential.code` отдавал на таком наборе **0**, то
    есть «предмета нет». Для сторожа, чей предмет решает СОДЕРЖИМОЕ набора, это
    «не измерено, выданное за ответ» (инв. #17): ровно та форма, из-за которой
    #1259 и нашёл границу (на ADR-1112 инертный зонд 80→80, содержательный
    80→81). Направление 2 карточки опирается на это число, поэтому сужение
    предмета инертным зондом было бы сужением в сторону «чисто».

    Второй зонд содержателен ПО ПОСТРОЕНИЮ, а не угадан: донором берётся файл,
    который в ЭТОМ ЖЕ каталоге уже лежит и сторожем уже ПРИНЯТ, и меняется у
    него РОВНО ОДНО — имя.
    """

    # ── донор: отбор ДЕТЕРМИНИРОВАН и фильтры РАБОТАЮТ ──────────────────────
    def test_the_donor_is_the_first_eligible_by_name_and_the_filters_BITE(self):
        """КАЖДЫЙ непригодный декой стои́т ПЕРЕД верным ответом — иначе снятие
        соответствующего фильтра ответа не меняет и мутация ВЫЖИВАЕТ зелёной
        (форма «выжившая мутация — дыра СЦЕНЫ», одиннадцать циклов подряд).
        Порядок имён здесь — несущая часть мерки, а не оформление.

        Наивные реализации, которые сцена РАЗЛИЧАЕТ, и каждая своим декоем:
          * фильтра расширения нет → отдала бы `a_alien.txt`;
          * фильтра пустого файла нет → отдала бы `b_empty.py`;
          * предела размера нет → отдала бы `c_huge.json`;
          * отбор не по первому имени (последний) → отдала бы `e_later.py`;
          * «предпочесть `.py`» → отдала бы `e_later.py`.
        """
        mod = _load()
        with tempfile.TemporaryDirectory(prefix="dac_donor_") as d:
            box = pathlib.Path(d)
            (box / "a_alien.txt").write_text("не то расширение\n", encoding="utf-8")
            (box / "b_empty.py").write_text("", encoding="utf-8")
            # ⚠️ РАЗМЕР ЗАДАН АБСОЛЮТНЫМ ЧИСЛОМ, а не от `COPY_DONOR_MAX_BYTES`.
            # Первая редакция писала `COPY_DONOR_MAX_BYTES + 10`, и сцена читала
            # МУТИРОВАННУЮ константу: поднятие предела делало файл ровно настолько
            # же крупнее, ответ не менялся, и мутация «предел вчетверо выше»
            # ВЫЖИЛА зелёной (прогон 1 цикла #1612). Сцена, берущая мерку у
            # предмета измерения, тавтологична по построению.
            self.assertLessEqual(
                mod.COPY_DONOR_MAX_BYTES, 300_000,
                "объявленный предел донора вырос выше того, на котором стои́т эта "
                "сцена — поднимать его можно только вместе с перемером сцены")
            (box / "c_huge.json").write_text("{}" + " " * 300_001, encoding="utf-8")
            (box / "d_right.md").write_text("# донор\n", encoding="utf-8")
            (box / "e_later.py").write_text("X = 1\n", encoding="utf-8")
            donor, note = mod._copy_donor(box)
            self.assertIsNotNone(donor, f"донор не найден при двух пригодных: {note}")
            self.assertEqual("d_right.md", donor.name,
                             "отбор донора не детерминирован по имени либо фильтры не кусают")
            self.assertEqual("d_right.md", note,
                             "выбранный донор НЕ ПЕЧАТАЕТСЯ — замер нечем воспроизвести")

    def test_the_prober_own_plant_can_NOT_be_the_donor(self):
        """Копия СВОЕГО зонда содержательной не является — она тот же зонд."""
        mod = _load()
        with tempfile.TemporaryDirectory(prefix="dac_self_") as d:
            box = pathlib.Path(d)
            (box / f"{mod.PLANTED_STEM}.py").write_text(mod.PLANTED_PY, encoding="utf-8")
            (box / f"{mod.PLANTED_STEM}{mod.COPY_SUFFIX_MARK}.md").write_text(
                "x\n", encoding="utf-8")
            donor, note = mod._copy_donor(box)
            self.assertIsNone(donor,
                              f"донором стал собственный зонд прибора: {donor}")
            self.assertIn("НЕ ИЗ ЧЕГО", note,
                          "причина «донора нет» не названа — тихое «не предмет»")

    def test_no_donor_is_a_THIRD_outcome_and_NOT_code_zero(self):
        """«Содержательный зонд построить не из чего» ≠ «предмета нет»."""
        mod = _load()
        only_copy = mod.Differential(root="/nowhere", entries=[
            mod.DiffEntry("spa_core/tests/test_x.py", "pkg", mod.COPY_UNMEASURED,
                          reason="донора нет"),
        ])
        self.assertEqual(2, only_copy.code,
                         "НЕ ИЗМЕРЕНО содержательным зондом дало код, неотличимый от "
                         "«измерено и равно нулю» — предмет инв. #17")
        measured_zero = mod.Differential(root="/nowhere", entries=[
            mod.DiffEntry("spa_core/tests/test_x.py", "pkg", mod.NOT_SUBJECT,
                          reason="оба зонда"),
        ])
        self.assertEqual(0, measured_zero.code,
                         "ИЗМЕРЕННЫЙ ноль стал неотличим от «не измерено» — ошибка в "
                         "ОБРАТНУЮ сторону, и она тоже ложь")

    # ── уборка обязана видеть ОБА зонда ────────────────────────────────────
    def test_the_cleanup_sweeps_the_COPY_probe_too(self):
        """Уборка, видящая один зонд, печатала бы «чисто» про грязное дерево."""
        mod = _load()
        with tempfile.TemporaryDirectory(prefix="dac_clean_") as d:
            root = pathlib.Path(d)
            pkg = root / "spa_core" / "analytics"
            pkg.mkdir(parents=True)
            (pkg / f"{mod.PLANTED_STEM}.py").write_text("x = 1\n", encoding="utf-8")
            (pkg / f"{mod.PLANTED_STEM}{mod.COPY_SUFFIX_MARK}.py").write_text(
                "y = 1\n", encoding="utf-8")
            removed = mod.clean_planted(root)
            self.assertEqual(2, len(removed),
                             f"уборка сняла не оба зонда: {removed}")
            self.assertFalse(
                list(pkg.glob(f"{mod.PLANTED_STEM}*")),
                "копия зонда осталась в дереве, а уборка отчиталась")

    # ── ОТЧЁТ называет и границу, и то, что её СПРОСИЛИ ────────────────────
    def test_the_report_says_the_boundary_was_ASKED_of_every_candidate(self):
        mod = _load()
        text = mod.render_differential(mod.Differential(root="/nowhere", entries=[]))
        self.assertIn("ЗОНД ИНЕРТЕН", text, "граница зонда не напечатана")
        self.assertIn("СПРОШЕНА", text,
                      "отчёт не говорит, что границу СПРОСИЛИ у каждого кандидата — "
                      "читатель примет ответ о зонде за ответ о классе")
        self.assertIn("КОПИЯ", text, "второй зонд в отчёте не назван")

    # ── НЕСУЩАЯ ПРОБА: воспроизводит замер #1259 ОБЩИМ правилом ────────────
    def test_a_CONTENT_judging_guard_is_resolved_by_the_COPY_and_NOT_by_the_inert_plant(self):
        """Дословная форма замера #1259: инертный зонд 80→80, содержательный 80→81.

        Сцена — сторож, который перечисляет каталог и считает в нём файлы,
        НЕСУЩИЕ маркер. Инертный зонд растит ЧИСЛО файлов и маркера не несёт ⇒
        вердикт не двигается, и прибор без второго зонда сказал бы «не предмет».
        Копия существующего члена маркер несёт ПО ПОСТРОЕНИЮ ⇒ сторож краснеет,
        и он ЕСТЬ член класса.

        Контроль в ОБЕ стороны: второй сторож той же сцены судит НАБОР по именам
        (`len(list(...))`), его инертный зонд разрешает, и второй прогон у него
        не нужен — «не предмет» у него ИЗМЕРЕН.
        """
        mod = _load()
        with tempfile.TemporaryDirectory(prefix="dac_e2e_") as d:
            root = pathlib.Path(d)
            pkg = root / "spa_core" / "analytics"
            pkg.mkdir(parents=True)
            (pkg / "m_one.py").write_text('MARKER = "derived-marker"\n', encoding="utf-8")

            content_guard = (
                "import pathlib\n"
                "def test_content():\n"
                "    r = pathlib.Path(__file__).resolve().parents[2]\n"
                "    pkg = r / 'spa_core' / 'analytics'\n"
                "    carry = [p for p in pkg.glob('*.py')\n"
                "             if 'derived-marker' in p.read_text(encoding='utf-8')]\n"
                "    assert len(carry) == 1, carry\n")
            set_guard = (
                "import pathlib\n"
                "def test_set():\n"
                "    r = pathlib.Path(__file__).resolve().parents[2]\n"
                "    pkg = r / 'spa_core' / 'analytics'\n"
                "    assert len(list(pkg.glob('*.py'))) >= 1\n")
            _scene(root, "content_guard", content_guard)
            _scene(root, "set_guard", set_guard)

            surface = mod.measure_surface(root)
            paths = {e.path for e in surface.subject}
            self.assertEqual(
                {"spa_core/tests/test_content_guard.py", "spa_core/tests/test_set_guard.py"},
                paths, f"сцена не легла в предмет поверхности: {paths}")

            diff = mod.measure_differential(root, surface, timeout=240)
            got = {e.path: e for e in diff.entries}
            self.assertEqual([], diff.leftovers, f"зонд не снят: {diff.leftovers}")
            # Спрашивается ДЕРЕВО, а не счётчик прибора: `leftovers` пополняется
            # лишь при ошибке снятия, поэтому забытый `unlink` оставил бы файл
            # МОЛЧА — «дерево чисто» стало бы утверждением без наблюдения.
            self.assertEqual(
                [], sorted(q.name for q in pkg.glob(f"{mod.PLANTED_STEM}*")),
                "подложенный файл остался в перечисляемом каталоге, а счётчик "
                "`leftovers` пуст — доставка увезла бы байты, которых никто не писал")

            content = got["spa_core/tests/test_content_guard.py"]
            self.assertEqual(
                mod.SUBJECT, content.kind,
                "сторож, судящий СОДЕРЖИМОЕ набора, объявлен «не предметом» — "
                f"инертный зонд ответил о себе: {content.reason}")
            self.assertIn("КОПИЯ", content.reason,
                          "предмет найден не вторым зондом — проба не о нём")

            s = got["spa_core/tests/test_set_guard.py"]
            self.assertEqual(
                mod.NOT_SUBJECT, s.kind,
                f"сторож, судящий НАБОР, назван предметом: {s.reason}")
            self.assertIn("СОДЕРЖАТЕЛЬНОГО", s.reason,
                          "«не предмет» поставлен без второго зонда — то есть "
                          "по-прежнему есть ответ о зонде, а не о стороже")


class TheDirectoryOfTheVerdictIsOBSERVEDOrItIsNotAnAnswer(unittest.TestCase):
    """Заказ G1103 п. 3, цикл #1612 — ВТОРАЯ находка того же прогона, и она глубже.

    ЗАМЕР НА ИЗВЕСТНОМ ЧЛЕНЕ. Дифференциал по ЧЕТЫРЁМ известным членам класса дал
    «не предмет» ДВУМ записям, и одна из них — `test_adr_index_titles` (ADR-889,
    колонка реестра решений). Причина не в содержимом зонда: у этого файла
    поверхность разобрала РОВНО ОДИН каталог — `docs/journal`, — а членство его
    класса стои́т на `docs/decisions`. Зонд лёг в каталог, которого сторож не
    судит, и «вердикт тот же» оказался ответом о КАТАЛОГЕ.

    ПОЧЕМУ ЭТО СВОЙСТВО МЕРЫ, А НЕ СЛУЧАЙ. Половина хопа `_helper_calls` ставит
    каталог, который ИМЕНУЕТ тест, на зов помощника, перечисляющего каталог ИЗ
    АРГУМЕНТА, и прибор сам говорит вслух: «названный каталог может и не дойти до
    помощника». Для ПОВЕРХНОСТИ это верная ошибка в сторону большей; для ВЕРДИКТА
    дифференциала — нет. Замер #1612 по всему предмету: из **1966** привязок
    каталога **1815** (92,3 %) происходят из этой ветки-догадки, через помощника с
    РАЗОБРАННЫМ каталогом — 84, прямым зовом — 67.
    """

    def _tree(self, box: pathlib.Path) -> pathlib.Path:
        pkg = box / "spa_core" / "analytics"
        pkg.mkdir(parents=True)
        return pkg

    def test_a_GUESSED_directory_gives_the_THIRD_outcome_and_a_nonzero_code(self):
        """Сцена дословно повторяет форму известного члена: каталог ИМЕНУЕТ тест,
        перечисляет помощник по аргументу, и вердикт не двигается."""
        mod = _load()
        with tempfile.TemporaryDirectory(prefix="dac_guess_") as d:
            root = pathlib.Path(d)
            pkg = self._tree(root)
            (pkg / "m_one.py").write_text("X = 1\n", encoding="utf-8")
            helpers = root / "scripts"
            helpers.mkdir()
            (helpers / "helper_enum.py").write_text(
                "import pathlib\n"
                "def names(where):\n"
                "    return sorted(p.name for p in pathlib.Path(where).glob('*.py'))\n",
                encoding="utf-8")
            _scene(root, "guessed_dir",
                   "import pathlib, sys\n"
                   "REPO = pathlib.Path(__file__).resolve().parents[2]\n"
                   "sys.path.insert(0, str(REPO / 'scripts'))\n"
                   "PKG = REPO / 'spa_core' / 'analytics'\n"
                   "import helper_enum\n"
                   "def test_x():\n"
                   "    # вердикт НЕ зависит от набора: сторож спрашивает тип ответа\n"
                   "    assert isinstance(helper_enum.names(PKG), list)\n")
            surface = mod.measure_surface(root)
            entry = next(e for e in surface.subject
                         if e.path == "spa_core/tests/test_guessed_dir.py")
            self.assertEqual(
                mod.ORIGIN_GUESS, entry.dir_origin("spa_core/analytics"),
                "каталог, названный тестом и перечисляемый помощником ПО АРГУМЕНТУ, "
                "объявлен НАБЛЮДЁННЫМ — ось происхождения не работает")

            diff = mod.measure_differential(root, surface, timeout=240)
            got = {(e.path, e.enumerated_dir): e for e in diff.entries}
            e = got[("spa_core/tests/test_guessed_dir.py", "spa_core/analytics")]
            self.assertEqual(
                mod.GUESSED_DIR_UNMEASURED, e.kind,
                f"«вердикт тот же» на ДОГАДАННОМ каталоге выдан за ответ о стороже: "
                f"{e.kind} / {e.reason}")
            self.assertNotEqual(
                0, diff.code,
                "третий исход дал код 0 — «не измерено» снова неотличимо от "
                "«измерено и равно нулю» (инв. #17)")

    def test_an_OBSERVED_directory_is_NOT_downgraded_to_unmeasured(self):
        """Контроль в ОБРАТНУЮ сторону: ось не имеет права глушить всё подряд.

        Прямой зов каталога — НАБЛЮДЕНИЕ, и «не предмет» на нём остаётся
        вердиктом. Ось, объявляющая неизмеримым и наблюдённый каталог, сделала бы
        дифференциал бесполезным — это было бы «осторожность вместо мерки».
        """
        mod = _load()
        with tempfile.TemporaryDirectory(prefix="dac_obs_") as d:
            root = pathlib.Path(d)
            pkg = self._tree(root)
            (pkg / "m_one.py").write_text("X = 1\n", encoding="utf-8")
            _scene(root, "observed_dir",
                   "import pathlib\n"
                   "def test_x():\n"
                   "    r = pathlib.Path(__file__).resolve().parents[2]\n"
                   "    assert isinstance(list((r / 'spa_core' / 'analytics').glob('*.py')), list)\n")
            surface = mod.measure_surface(root)
            entry = next(e for e in surface.subject
                         if e.path == "spa_core/tests/test_observed_dir.py")
            self.assertEqual(mod.ORIGIN_OBSERVED,
                             entry.dir_origin("spa_core/analytics"),
                             "прямой зов каталога объявлен ДОГАДКОЙ")
            diff = mod.measure_differential(root, surface, timeout=240)
            e = next(x for x in diff.entries
                     if x.path == "spa_core/tests/test_observed_dir.py")
            self.assertEqual(mod.NOT_SUBJECT, e.kind,
                             f"наблюдённый каталог понижен до «не измерено»: {e.reason}")
            self.assertEqual(0, diff.code,
                             "измеренный ноль дал ненулевой код — ошибка в обратную сторону")

    def test_an_observation_OVERRIDES_a_guess_for_the_same_directory(self):
        """Тот же каталог и догадкой, и прямым зовом ⇒ зонд ляжет по наблюдению."""
        mod = _load()
        with tempfile.TemporaryDirectory(prefix="dac_both_") as d:
            root = pathlib.Path(d)
            pkg = self._tree(root)
            (pkg / "m_one.py").write_text("X = 1\n", encoding="utf-8")
            helpers = root / "scripts"; helpers.mkdir()
            (helpers / "helper_enum.py").write_text(
                "import pathlib\n"
                "def names(where):\n"
                "    return sorted(p.name for p in pathlib.Path(where).glob('*.py'))\n",
                encoding="utf-8")
            _scene(root, "both_origins",
                   "import pathlib, sys\n"
                   "REPO = pathlib.Path(__file__).resolve().parents[2]\n"
                   "sys.path.insert(0, str(REPO / 'scripts'))\n"
                   "PKG = REPO / 'spa_core' / 'analytics'\n"
                   "import helper_enum\n"
                   "def test_x():\n"
                   "    assert isinstance(helper_enum.names(PKG), list)\n"
                   "    assert isinstance(list(PKG.glob('*.py')), list)\n")
            surface = mod.measure_surface(root)
            entry = next(e for e in surface.subject
                         if e.path == "spa_core/tests/test_both_origins.py")
            self.assertEqual(
                mod.ORIGIN_OBSERVED, entry.dir_origin("spa_core/analytics"),
                "наблюдение НЕ перебило догадку — прибор отказался бы отвечать там, "
                "где сторож каталог действительно перечисляет")

    def test_no_donor_reaches_the_THIRD_outcome_THROUGH_measure_differential(self):
        """Мутация M15 ВЫЖИЛА на первом прогоне — и это была дыра СЦЕНЫ.

        Проба `test_no_donor_is_a_THIRD_outcome_and_NOT_code_zero` собирает
        `DiffEntry` руками и проверяет СВОЙСТВО `code`, а не ПРОВОДКУ: подмена
        ярлыка внутри `measure_differential` её не касалась. Форма «выжившая
        мутация — дыра сцены» подтвердилась двенадцатый раз подряд (#1202, #1217,
        #1267, #1270…#1273, #1275, #1277, #1612). Выжившую записывают и чинят
        МЕРКОЙ: сцена ниже доводит путь «донора нет» до вердикта сквозь прибор.

        Каталог НАБЛЮДЁН (прямой зов) — иначе ответ перехватила бы ось догадки, и
        сцена снова меряла бы не то.
        """
        mod = _load()
        with tempfile.TemporaryDirectory(prefix="dac_nodonor_") as d:
            root = pathlib.Path(d)
            pkg = self._tree(root)
            # ни одного файла с пригодным расширением — донора построить НЕ ИЗ ЧЕГО
            (pkg / "only_alien.txt").write_text("не то расширение\n", encoding="utf-8")
            _scene(root, "nodonor_dir",
                   "import pathlib\n"
                   "def test_x():\n"
                   "    r = pathlib.Path(__file__).resolve().parents[2]\n"
                   "    pkg = r / 'spa_core' / 'analytics'\n"
                   "    carry = [p for p in pkg.glob('*.py')\n"
                   "             if 'derived-marker' in p.read_text(encoding='utf-8')]\n"
                   "    assert len(carry) == 0, carry\n")
            surface = mod.measure_surface(root)
            diff = mod.measure_differential(root, surface, timeout=240)
            e = next(x for x in diff.entries
                     if x.path == "spa_core/tests/test_nodonor_dir.py")
            self.assertEqual(
                mod.COPY_UNMEASURED, e.kind,
                f"«содержательный зонд построить не из чего» выдано за ответ: "
                f"{e.kind} / {e.reason}")
            self.assertIn("НЕ ИЗ ЧЕГО", e.reason, "причина третьего исхода не названа")
            self.assertEqual(2, diff.code,
                             "третий исход прошёл сквозь прибор с кодом «чисто»")


class TheVERDICTAlsoNeedsItsKnownMemberControl(unittest.TestCase):
    """Зеркало `Surface.lost_known_members`, которого у ВЕРДИКТА не было.

    Замер #1612 на живом дереве: `test_adr_index_titles` (ADR-889, колонка
    реестра решений) приходит `not_subject` ПРИ ОБОИХ зондах и при НАБЛЮДЁННОМ
    каталоге — потому что поверхность разобрала у него ровно один каталог
    (`docs/journal`), а членство класса стои́т на `docs/decisions`. То есть
    остаётся ТРЕТЬЯ причина ложного «не предмета», которой ни один зонд не
    лечит: зонд ложится не туда, куда смотрит сторож СВОЕГО класса.

    Пока это так, `ПРЕДМЕТ N` есть НИЖНЯЯ ГРАНИЦА, и прибор обязан говорить это
    вслух. Контроль, которого нет, зелен ПО ПОСТРОЕНИЮ (урок ADR-1113).
    """

    def test_a_known_member_called_not_a_subject_REFUTES_the_measure(self):
        mod = _load()
        known = next(iter(mod.KNOWN_MEMBERS))
        refuted = mod.Differential(root="/nowhere", entries=[
            mod.DiffEntry(known, "docs/journal", mod.NOT_SUBJECT, reason="оба зонда"),
        ])
        self.assertEqual({known: mod.KNOWN_MEMBERS[known]}, refuted.refuted_known_members,
                         "известный член, названный «не предметом», мерку не опроверг")
        self.assertEqual(2, refuted.code,
                         "опровергнутая мерка отдала код, который читается как вердикт")
        text = mod.render_differential(refuted)
        self.assertIn("ОПРОВЕРГНУТА", text, "опровержение не напечатано")
        self.assertIn("НИЖНЯЯ ГРАНИЦА", text,
                      "отчёт не говорит, что `ПРЕДМЕТ` перестал быть сужением")
        self.assertIn(known, text, "опровергший член не назван поимённо")

    def test_the_control_is_SILENT_when_no_known_member_is_called_not_a_subject(self):
        """Контроль в ОБРАТНУЮ сторону: он не имеет права звонить всегда.

        Известный член, пришедший `subject` либо `already_red`, мерку НЕ
        опровергает — иначе прибор отказывал бы на ВЕРНОМ состоянии, и это ровно
        та краснота, из-за которой ADR-1073 запретил порог «предмет пуст».
        Декой-запись НЕизвестного файла стои́т рядом: ось обязана спрашивать
        ИМЯ, а не «есть ли вообще `not_subject`».
        """
        mod = _load()
        known = next(iter(mod.KNOWN_MEMBERS))
        ok = mod.Differential(root="/nowhere", entries=[
            mod.DiffEntry(known, "spa_core/analytics", mod.SUBJECT, reason="покраснел"),
            mod.DiffEntry("spa_core/tests/test_some_other_guard.py", "pkg",
                          mod.NOT_SUBJECT, reason="оба зонда"),
        ])
        self.assertEqual({}, ok.refuted_known_members,
                         "контроль звонит на верном состоянии — отказ вместо мерки")
        self.assertEqual(1, ok.code, "найденный предмет не дал кода находки")
        self.assertIn("✅", mod.render_differential(ok),
                      "положительный ответ контроля не напечатан — читатель не узнает, "
                      "спрашивали ли контроль вообще")
