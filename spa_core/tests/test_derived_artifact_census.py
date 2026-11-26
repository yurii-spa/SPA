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
