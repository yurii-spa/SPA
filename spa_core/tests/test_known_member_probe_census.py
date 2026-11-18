"""Батарея прибора `spa_core/monitoring/known_member_probe_census.py` (ADR-1041).

# LLM_FORBIDDEN

Заказ **G1029 п. 2** требует от ЛЮБОГО замера класса предъявить известного
члена ДО печати населения. Эта батарея устроена по тому же правилу и на двух
уровнях сразу:

* сцены ниже — положительные контроли КАЖДОГО звена формы, и каждая сцена
  воспроизводит ту причину, по которой первая редакция прибора ТЕРЯЛА
  известного члена (помощник сцены · умолчание корня у прибора · область
  видимости имени `root` · одноразовость через помощника · ось известных
  членов, названная самим прибором);
* `TheLiveTreeIsMeasuredAndKnownMembersAreShown` зовёт прибор о ЖИВОМ дереве и
  предъявляет ему известных членов по ОБЕ стороны — то есть сам прибор
  перестаёт быть членом класса, который мерит, не умолчанием, а пробой.

Литеральных дат в файле нет ни одной: о свежести прибор не судит, и дверей к
календарю у него нет по построению.
"""
from __future__ import annotations

import ast
import json
import pathlib
import sys
import tempfile
import textwrap
import unittest

_REPO = pathlib.Path(__file__).resolve().parents[2]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from spa_core.monitoring import known_member_probe_census as km  # noqa: E402

_SUBJECT = "spa_core/monitoring/thing_census.py"
_BATTERY = "spa_core/tests/test_thing_census.py"

#: Прибор сцены: объявляет два ярлыка исхода и читает AST — ровно форма
#: поверхности `_population_verdict_surface`. Корень приходит аргументом.
_INSTRUMENT = '''
import ast
GOOD = "good"
BAD = "bad"

def measure(root):
    population = []
    return {"population": population, "declared_outside_form": []}
'''

#: Тот же прибор, но корень у него ПО УМОЛЧАНИЮ живой.
_INSTRUMENT_LIVE_DEFAULT = '''
import ast
import pathlib
GOOD = "good"
BAD = "bad"
REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]

def scan_repo(root=None):
    root = root or REPO_ROOT
    population = []
    return {"population": population}
'''


def _scene(tmp: str, battery_body: str, *, instrument: str = _INSTRUMENT,
           subject: str = _SUBJECT, battery: str = _BATTERY) -> pathlib.Path:
    """Одноразовое дерево: прибор + его батарея. Ничего живого не трогает."""
    root = pathlib.Path(tmp)
    for rel, body in ((subject, instrument), (battery, battery_body)):
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(textwrap.dedent(body).lstrip("\n"), encoding="utf-8")
    return root


def _outcome(root: pathlib.Path, subject: str = _SUBJECT) -> km.Row:
    census = km.measure(root, [subject])
    return census.rows[0]


# ─────────────────────────── форма пробы, звено за звеном ────────────────────


class TheProbeFormIsMeasuredLinkByLink(unittest.TestCase):
    """Каждый тест — ОДНО звено формы, и порванное звено обязано краснеть."""

    def test_a_live_call_naming_a_member_is_a_probe(self):
        body = '''
        import pathlib
        from spa_core.monitoring import thing_census as tc

        _ROOT = pathlib.Path(__file__).resolve().parents[2]

        def test_a_known_member_is_found():
            doc = tc.measure(_ROOT)
            assert "spa_core/monitoring/watcher.py" in doc["population"]
        '''
        with tempfile.TemporaryDirectory() as tmp:
            row = _outcome(_scene(tmp, body))
            self.assertEqual(row.outcome, km.HAS_PROBE, row)
            self.assertEqual(row.probes[0].item_form, km.ITEM_PATH)
            self.assertEqual(row.probes[0].item, "spa_core/monitoring/watcher.py")

    def test_a_disposable_scene_is_not_a_probe(self):
        """Сцена в одноразовом каталоге проверяет ФОРМУ автора и опровергнуть
        её не способна — именно поэтому она пробой не считается."""
        body = '''
        import tempfile
        from spa_core.monitoring import thing_census as tc

        def test_a_planted_member_is_found():
            with tempfile.TemporaryDirectory() as tmp:
                doc = tc.measure(tmp)
                assert "spa_core/monitoring/watcher.py" in doc["population"]
        '''
        with tempfile.TemporaryDirectory() as tmp:
            row = _outcome(_scene(tmp, body))
            self.assertEqual(row.outcome, km.NO_PROBE, row)
            self.assertEqual(row.rod, km.BATTERY_WITHOUT_PROBE)

    def test_a_disposable_root_built_by_a_helper_is_still_disposable(self):
        """Одноразовость через ОДИН хоп: `tmp = _tree(...)` слова `tempfile`
        не содержит, и без вопроса о помощнике зов объявлялся живым."""
        body = '''
        import tempfile
        from spa_core.monitoring import thing_census as tc

        def _tree(files):
            box = tempfile.mkdtemp()
            return box

        def test_a_planted_member_is_found():
            tmp = _tree({"pkg/x.py": ""})
            doc = tc.measure(tmp)
            assert "pkg/neighbour.py" in doc["population"]
        '''
        with tempfile.TemporaryDirectory() as tmp:
            row = _outcome(_scene(tmp, body))
            self.assertEqual(row.outcome, km.NO_PROBE, row)

    def test_a_live_call_hidden_in_a_helper_is_still_a_probe(self):
        """Сцену и зов строит ПОМОЩНИК — так терялся известный член
        `scripts/forbidden_reach_census.py`."""
        body = '''
        import pathlib
        from spa_core.monitoring import thing_census as tc

        _ROOT = pathlib.Path(__file__).resolve().parents[2]

        def _live():
            return tc.measure(_ROOT)

        def test_a_known_member_is_found():
            doc = _live()
            assert "spa_core/monitoring/watcher.py" in doc["population"]
        '''
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(_outcome(_scene(tmp, body)).outcome, km.HAS_PROBE)

    def test_a_no_argument_call_counts_only_when_the_default_is_read(self):
        """`doors.scan_repo()` без аргументов: умолчание ЧИТАЕТСЯ у прибора.

        Обе стороны в одном тесте — иначе «считается» неотличимо от
        «считается всегда», и подстановка за прибор прошла бы незаметно.
        """
        body = '''
        from spa_core.monitoring import thing_census as tc

        def test_a_known_member_is_found():
            doc = tc.scan_repo()
            assert "spa_core/monitoring/watcher.py" in doc["population"]
        '''
        with tempfile.TemporaryDirectory() as tmp:
            row = _outcome(_scene(tmp, body, instrument=_INSTRUMENT_LIVE_DEFAULT))
            self.assertEqual(row.outcome, km.HAS_PROBE, row)
        body_no_default = body.replace("tc.scan_repo()", "tc.measure()")
        with tempfile.TemporaryDirectory() as tmp:
            row = _outcome(_scene(tmp, body_no_default))
            self.assertEqual(row.outcome, km.NO_PROBE, row)

    def test_a_prose_literal_is_not_the_name_of_a_member(self):
        """`assertIn("НЕ ИЗМЕРЕНО", doc["reason"])` — проба о СТАТУСЕ."""
        body = '''
        import pathlib
        from spa_core.monitoring import thing_census as tc

        _ROOT = pathlib.Path(__file__).resolve().parents[2]

        def test_the_reason_is_named():
            doc = tc.measure(_ROOT)
            assert "НЕ ИЗМЕРЕНО" in doc["reason"]
        '''
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(_outcome(_scene(tmp, body)).outcome, km.NO_PROBE)

    def test_a_member_taken_from_the_answer_is_not_a_known_member(self):
        """Сверять ответ прибора с его же ответом — известный класс (ADR-913)."""
        body = '''
        import pathlib
        from spa_core.monitoring import thing_census as tc

        _ROOT = pathlib.Path(__file__).resolve().parents[2]

        def test_the_first_row_is_in_the_population():
            doc = tc.measure(_ROOT)
            first = doc["population"][0]
            assert first in doc["population"]
        '''
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(_outcome(_scene(tmp, body)).outcome, km.NO_PROBE)

    def test_an_axis_of_known_members_named_by_the_instrument_is_a_probe(self):
        """Сильнейшая форма: перечень известных членов у ИСТОЧНИКА, и батарея
        утверждает о нём (`assertEqual([], census.declared_outside_form)`).
        Без этой формы терялся `_population_verdict_surface`."""
        body = '''
        import pathlib
        from spa_core.monitoring import thing_census as tc

        _ROOT = pathlib.Path(__file__).resolve().parents[2]

        def test_no_declared_member_fell_outside_the_form():
            doc = tc.measure(_ROOT)
            assert [] == doc["declared_outside_form"]
        '''
        with tempfile.TemporaryDirectory() as tmp:
            row = _outcome(_scene(tmp, body))
            self.assertEqual(row.outcome, km.HAS_PROBE, row)
            self.assertEqual(row.probes[0].item_form, km.ITEM_DECLARED_SLOT)

    def test_a_sibling_test_cannot_poison_the_root_of_this_one(self):
        """Имя `root` живое ЗДЕСЬ и одноразовое У СОСЕДА. Пока множества
        считались по всему файлу, сосед отравлял живого — и форма теряла
        известного члена."""
        body = '''
        import pathlib
        import tempfile
        from spa_core.monitoring import thing_census as tc

        def test_a_disposable_neighbour():
            with tempfile.TemporaryDirectory() as box:
                root = box
                tc.measure(root)

        def test_a_known_member_is_found():
            root = pathlib.Path(__file__).resolve().parents[2]
            doc = tc.measure(root)
            assert "spa_core/monitoring/watcher.py" in doc["population"]
        '''
        with tempfile.TemporaryDirectory() as tmp:
            row = _outcome(_scene(tmp, body))
            self.assertEqual(row.outcome, km.HAS_PROBE, row)
            self.assertEqual(row.probes[0].test, "test_a_known_member_is_found")


# ───────────────── подготовка класса — живой зов, а не его отсутствие ────────


class APreparationOfTheClassIsALiveCallToo(unittest.TestCase):
    """Зов в `setUpClass` — ТАКОЙ ЖЕ живой зов (G1044 п. 1, ADR-1057).

    Контроль обязателен в ОБЕ стороны, и обе здесь: сцена, где зов стои́т в
    подготовке и проба находится, и ЧЕТЫРЕ сцены, где подготовка есть, а пробы
    по-прежнему нет. Без второй половины правка была бы не снятием ложного
    отрицательного ответа, а ослаблением формы.

    Почему вопрос вообще возник: прежняя форма искала живой зов ТОЛЬКО среди
    функций с префиксом `test_`, поэтому каждый несущий пробу тест был обязан
    сделать СВОЙ зов. Цена замерена ADR-1056 — три зова вместо одного, 541.4 с
    против 181.2 с при пороге `pytest-timeout` 180 с НА ТЕСТ, то есть форма
    сама производила род обморока по стенным часам.
    """

    def test_a_live_call_in_setUpClass_is_a_probe(self):
        body = '''
        import pathlib
        import unittest
        from spa_core.monitoring import thing_census as tc

        _ROOT = pathlib.Path(__file__).resolve().parents[2]

        class TheLiveTree(unittest.TestCase):

            @classmethod
            def setUpClass(cls):
                cls.doc = tc.measure(_ROOT)

            def test_a_known_member_is_found(self):
                self.assertIn("spa_core/monitoring/watcher.py",
                              self.doc["population"])
        '''
        with tempfile.TemporaryDirectory() as tmp:
            row = _outcome(_scene(tmp, body))
            self.assertEqual(row.outcome, km.HAS_PROBE, row)
            self.assertEqual(row.probes[0].test, "test_a_known_member_is_found")
            self.assertEqual(row.probes[0].item_form, km.ITEM_PATH)

    def test_a_live_call_in_setUp_is_a_probe(self):
        """`setUp` — та же гарантия харнесса, только на каждый тест."""
        body = '''
        import pathlib
        import unittest
        from spa_core.monitoring import thing_census as tc

        _ROOT = pathlib.Path(__file__).resolve().parents[2]

        class TheLiveTree(unittest.TestCase):

            def setUp(self):
                self.doc = tc.measure(_ROOT)

            def test_a_known_member_is_found(self):
                self.assertIn("spa_core/monitoring/watcher.py",
                              self.doc["population"])
        '''
        with tempfile.TemporaryDirectory() as tmp:
            row = _outcome(_scene(tmp, body))
            self.assertEqual(row.outcome, km.HAS_PROBE, row)

    def test_a_disposable_scene_built_in_setUpClass_is_still_not_a_probe(self):
        """Одноразовость корня через подготовку не теряется: иначе правка
        объявила бы пробой сцену в tempfile-каталоге, то есть СЛОМАЛА бы
        несущее условие формы."""
        body = '''
        import pathlib
        import tempfile
        import unittest
        from spa_core.monitoring import thing_census as tc

        class TheDisposableTree(unittest.TestCase):

            @classmethod
            def setUpClass(cls):
                cls.root = pathlib.Path(tempfile.mkdtemp())
                cls.doc = tc.measure(cls.root)

            def test_a_planted_member_is_found(self):
                self.assertIn("spa_core/monitoring/watcher.py",
                              self.doc["population"])
        '''
        with tempfile.TemporaryDirectory() as tmp:
            row = _outcome(_scene(tmp, body))
            self.assertEqual(row.outcome, km.NO_PROBE, row)

    def test_a_preparation_the_harness_does_not_guarantee_is_not_a_probe(self):
        """Перечень подготовок ЗАКРЫТ (`km.FIXTURE_METHODS`). Метод с любым
        другим именем харнесс не зовёт, и считать его подготовкой значило бы
        объявить пробой зов, который может не состояться вовсе."""
        body = '''
        import pathlib
        import unittest
        from spa_core.monitoring import thing_census as tc

        _ROOT = pathlib.Path(__file__).resolve().parents[2]

        class TheLiveTree(unittest.TestCase):

            @classmethod
            def prepare(cls):
                cls.doc = tc.measure(_ROOT)

            def test_a_known_member_is_found(self):
                self.assertIn("spa_core/monitoring/watcher.py",
                              self.doc["population"])
        '''
        with tempfile.TemporaryDirectory() as tmp:
            row = _outcome(_scene(tmp, body))
            self.assertEqual(row.outcome, km.NO_PROBE, row)

    def test_a_local_name_of_the_preparation_is_not_visible_to_the_test(self):
        """Вывозятся ТОЛЬКО атрибуты: локальная переменная подготовки телу теста
        не видна, и привязкой она не является.

        **Две формы обращения, и РАЗЛИЧАЮЩАЯ здесь вторая.** Первая редакция
        сцены предъявляла тесту `self.doc` — и мутация «вывозить все имена, а не
        только атрибуты» её ПЕРЕЖИЛА: засев `{'doc'}` с именем `self.doc` не
        пересекается, ответ `no_probe` выходил по другой причине. Поэтому ниже
        проверяются ОБА обращения, и второе ссылается на локальное имя
        подготовки ДОСЛОВНО. Сцена не исполняется — её только разбирают, —
        поэтому `NameError`, которым такой код кончился бы в прогоне, вопроса о
        форме не меняет: предмет в том, считает ли прибор это привязкой.
        """
        shapes = {
            "атрибут": 'self.doc["population"]',
            "локальное имя подготовки": 'doc["population"]',
        }
        for shape, read in shapes.items():
            body = '''
            import pathlib
            import unittest
            from spa_core.monitoring import thing_census as tc

            _ROOT = pathlib.Path(__file__).resolve().parents[2]

            class TheLiveTree(unittest.TestCase):

                @classmethod
                def setUpClass(cls):
                    doc = tc.measure(_ROOT)

                def test_a_known_member_is_found(self):
                    self.assertIn("spa_core/monitoring/watcher.py",
                                  %s)
            ''' % read
            with self.subTest(shape=shape), tempfile.TemporaryDirectory() as tmp:
                row = _outcome(_scene(tmp, body))
                self.assertEqual(row.outcome, km.NO_PROBE, row)

    def test_a_sibling_class_does_not_inherit_the_preparation_of_another(self):
        """Гарантия харнесса — про тесты ТОГО ЖЕ класса. Засев, перелившийся в
        соседний класс, был бы ровно тем отравлением соседа, которое уже
        закрыто по области видимости (`scope_nodes`)."""
        body = '''
        import pathlib
        import unittest
        from spa_core.monitoring import thing_census as tc

        _ROOT = pathlib.Path(__file__).resolve().parents[2]

        class TheOneWithThePreparation(unittest.TestCase):

            @classmethod
            def setUpClass(cls):
                cls.doc = tc.measure(_ROOT)

            def test_the_reason_is_named(self):
                self.assertEqual("НЕ ИЗМЕРЕНО", "НЕ ИЗМЕРЕНО")

        class TheNeighbour(unittest.TestCase):

            def test_a_known_member_is_found(self):
                self.assertIn("spa_core/monitoring/watcher.py",
                              self.doc["population"])
        '''
        with tempfile.TemporaryDirectory() as tmp:
            row = _outcome(_scene(tmp, body))
            self.assertEqual(row.outcome, km.NO_PROBE, row)

    def test_a_disposable_bound_in_the_class_body_is_not_lost_by_the_preparation(self):
        """Одноразовость ТЕЛА КЛАССА обязана доехать до разбора подготовки.

        Сцена РАЗЛИЧАЮЩАЯ, и выбрана именно такой: у прибора здесь ЖИВОЕ
        УМОЛЧАНИЕ корня (`scan_repo(root=None)`), поэтому стоит перестать
        спрашивать об одноразовости — и зов по tempfile-каталогу объявится
        живым через умолчание. Без такой сцены мутация «не спрашивать
        одноразовость в подготовке» выживает: обычный прибор с ОБЯЗАТЕЛЬНЫМ
        аргументом корня отвечает `no_probe` и так.
        """
        body = '''
        import pathlib
        import tempfile
        import unittest
        from spa_core.monitoring import thing_census as tc

        class TheDisposableTree(unittest.TestCase):

            box = tempfile.mkdtemp()

            @classmethod
            def setUpClass(cls):
                cls.doc = tc.scan_repo(cls.box)

            def test_a_planted_member_is_found(self):
                self.assertIn("spa_core/monitoring/watcher.py",
                              self.doc["population"])
        '''
        with tempfile.TemporaryDirectory() as tmp:
            row = _outcome(_scene(tmp, body, instrument=_INSTRUMENT_LIVE_DEFAULT))
            self.assertEqual(row.outcome, km.NO_PROBE, row)

    def test_a_live_root_bound_inside_the_preparation_is_still_live(self):
        """Живой корень, связанный В ТЕЛЕ подготовки, обязан быть виден.

        Сцена РАЗЛИЧАЮЩАЯ для наследования наоборот: если считать живые имена
        только по телу КЛАССА, имя `root` подготовки живым не станет, и проба
        потеряется — то есть вернётся ровно тот ложный отрицательный ответ,
        который закрывает ADR-1057, только на один уровень глубже.
        """
        body = '''
        import pathlib
        import unittest
        from spa_core.monitoring import thing_census as tc

        class TheLiveTree(unittest.TestCase):

            @classmethod
            def setUpClass(cls):
                root = pathlib.Path(__file__).resolve().parents[2]
                cls.doc = tc.measure(root)

            def test_a_known_member_is_found(self):
                self.assertIn("spa_core/monitoring/watcher.py",
                              self.doc["population"])
        '''
        with tempfile.TemporaryDirectory() as tmp:
            row = _outcome(_scene(tmp, body))
            self.assertEqual(row.outcome, km.HAS_PROBE, row)

    def test_a_live_root_bound_in_the_class_body_reaches_the_preparation(self):
        """Та же привязка «тело класса → атрибут», но со стороны ЖИВОГО корня.

        Контроль парный к сцене об одноразовости выше: обе стороны одной
        привязки обязаны доезжать, иначе правка чинит одну и ломает другую.
        """
        body = '''
        import pathlib
        import unittest
        from spa_core.monitoring import thing_census as tc

        class TheLiveTree(unittest.TestCase):

            root = pathlib.Path(__file__).resolve().parents[2]

            @classmethod
            def setUpClass(cls):
                cls.doc = tc.measure(cls.root)

            def test_a_known_member_is_found(self):
                self.assertIn("spa_core/monitoring/watcher.py",
                              self.doc["population"])
        '''
        with tempfile.TemporaryDirectory() as tmp:
            row = _outcome(_scene(tmp, body))
            self.assertEqual(row.outcome, km.HAS_PROBE, row)

    def test_the_preparation_list_is_the_one_the_sibling_prober_reads(self):
        """ОДНО ИМЯ — ОДИН ОБЪЕКТ (урок #274): два прибора одного семейства
        закрывают дверь фикстуры с двух сторон и обязаны считать подготовкой
        ОДНО И ТО ЖЕ. Своя копия перечня у соседа означала бы два ответа под
        одним словом."""
        from spa_core.monitoring import probe_candidate_root_census as pcr
        self.assertIs(pcr.FIXTURE_METHODS, km.FIXTURE_METHODS)
        self.assertIn("setUpClass", km.FIXTURE_METHODS)
        self.assertNotIn("prepare", km.FIXTURE_METHODS)


# ─────────────────────────── двери к прибору ─────────────────────────────────


class BothDoorsToTheInstrumentAreMeasured(unittest.TestCase):

    def test_a_script_imported_by_its_bare_name_is_found(self):
        """`scripts/*.py` ввозят ГОЛЫМ именем после `sys.path.insert`; дверь,
        знавшая только точечную форму, теряла известного члена с живой
        батареей."""
        body = '''
        import pathlib
        import thing_census as census

        _ROOT = pathlib.Path(__file__).resolve().parents[2]

        def test_a_known_member_is_found():
            doc = census.measure(_ROOT)
            assert "spa_core/monitoring/watcher.py" in doc["population"]
        '''
        with tempfile.TemporaryDirectory() as tmp:
            root = _scene(tmp, body, subject="scripts/thing_census.py",
                          battery="scripts/tests/test_thing_census.py")
            row = _outcome(root, subject="scripts/thing_census.py")
            self.assertEqual(row.outcome, km.HAS_PROBE, row)
            self.assertEqual(row.doors, (km.DOOR_IMPORT,))

    def test_an_instrument_named_only_by_its_path_still_has_a_battery(self):
        """CLI-прибор батарея зовёт по ПУТИ. Дверь слабее, и она НАЗВАНА."""
        body = '''
        import pathlib
        import subprocess
        import sys

        _ROOT = pathlib.Path(__file__).resolve().parents[2]

        def test_the_tool_runs():
            tool = _ROOT / "scripts/thing_census.py"
            subprocess.run([sys.executable, str(tool)], capture_output=True)
        '''
        with tempfile.TemporaryDirectory() as tmp:
            root = _scene(tmp, body, subject="scripts/thing_census.py",
                          battery="scripts/tests/test_thing_census.py")
            row = _outcome(root, subject="scripts/thing_census.py")
            self.assertEqual(row.doors, (km.DOOR_PATH,))


# ─────────────────────────── три исхода различимы ────────────────────────────


class TheThreeOutcomesAreDistinguishable(unittest.TestCase):
    """Инв. #17: измерено · измерено и равно нулю · НЕ ИЗМЕРЕНО."""

    def test_an_instrument_without_any_battery_is_named_by_its_own_rod(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            (root / "spa_core/monitoring").mkdir(parents=True)
            (root / _SUBJECT).write_text(_INSTRUMENT, encoding="utf-8")
            (root / "spa_core/tests").mkdir(parents=True)
            (root / "spa_core/tests/test_other.py").write_text(
                "def test_nothing():\n    pass\n", encoding="utf-8")
            row = _outcome(root)
            self.assertEqual((row.outcome, row.rod),
                             (km.NO_PROBE, km.BATTERY_ABSENT))

    def test_an_unparsable_battery_is_unmeasured_not_absent_probe(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = _scene(tmp, "from spa_core.monitoring import thing_census\n")
            (root / _BATTERY).write_text(
                "from spa_core.monitoring import thing_census\ndef test_x(:\n",
                encoding="utf-8")
            row = _outcome(root)
            self.assertEqual((row.outcome, row.rod),
                             (km.UNMEASURED, km.BATTERY_UNPARSED))
            self.assertIn("SyntaxError", row.reason or "")

    def test_a_missing_instrument_is_unmeasured_with_its_reason(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = _scene(tmp, "def test_x():\n    pass\n")
            (root / _SUBJECT).unlink()
            row = _outcome(root)
            self.assertEqual((row.outcome, row.rod),
                             (km.UNMEASURED, km.SUBJECT_UNPARSED))

    def test_the_sum_of_outcomes_equals_the_population(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = _scene(tmp, "def test_x():\n    pass\n")
            census = km.measure(root, [_SUBJECT, "spa_core/monitoring/absent.py"])
            self.assertEqual(sum(census.counts[o] for o in km.OUTCOMES),
                             census.population)
            self.assertEqual(census.population, 2)

    def test_an_empty_subject_list_is_refused_not_answered_with_zero(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = _scene(tmp, "def test_x():\n    pass\n")
            with self.assertRaises(km.Refused) as ctx:
                km.measure(root, [])
            self.assertIn("ПУСТ", str(ctx.exception))

    def test_a_tree_without_battery_dirs_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(km.Refused) as ctx:
                km.measure(pathlib.Path(tmp), [_SUBJECT])
            self.assertIn("батарей не найдено", str(ctx.exception))

    def test_a_missing_surface_tool_is_refused_not_an_empty_surface(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(km.Refused) as ctx:
                km.surface_subjects(pathlib.Path(tmp))
            self.assertIn("НЕ ПРОЧИТАНА", str(ctx.exception))

    def test_the_report_never_prints_a_zero_as_clean(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = _scene(tmp, "def test_x():\n    pass\n")
            text = km.format_report(km.measure(root, [_SUBJECT]))
            self.assertIn("ВЕРХНЯЯ граница", text)
            self.assertIn("ADVISORY", text)


# ─────────────────────── калибровка: известные члены ────────────────────────


class TheFormIsRefutedByALostKnownMember(unittest.TestCase):
    """Положительный контроль САМОГО отказа: без него «калибровка прошла»
    неотличимо от «калибровка ничего не проверяет»."""

    @staticmethod
    def _agreeing_rows() -> dict:
        """Сцена, где форма СОГЛАСНА со всеми известными членами."""
        rows = {rel: km.Row(rel=rel, outcome=km.HAS_PROBE)
                for rel in km.KNOWN_WITH_PROBE}
        rows.update({rel: km.Row(rel=rel, outcome=km.NO_PROBE,
                                 rod=km.BATTERY_WITHOUT_PROBE)
                     for rel in km.KNOWN_WITHOUT_PROBE})
        return rows

    def test_an_agreeing_scene_loses_nobody(self):
        """Без этой стороны «ничего не потеряно» неотличимо от «не проверяется»."""
        self.assertEqual(km.calibrate(_REPO, self._agreeing_rows())["lost"], [])

    def test_calibration_names_a_known_member_the_form_lost(self):
        rows = self._agreeing_rows()
        victim = sorted(km.KNOWN_WITH_PROBE)[0]
        rows[victim] = km.Row(rel=victim, outcome=km.NO_PROBE,
                              rod=km.BATTERY_WITHOUT_PROBE)
        lost = km.calibrate(_REPO, rows)["lost"]
        self.assertEqual(len(lost), 1, lost)
        self.assertIn("не нашла ИЗВЕСТНОЙ пробы", lost[0])
        self.assertIn(victim, lost[0])

    def test_calibration_names_a_member_the_form_invented_a_probe_for(self):
        rows = self._agreeing_rows()
        victim = sorted(km.KNOWN_WITHOUT_PROBE)[0]
        rows[victim] = km.Row(rel=victim, outcome=km.HAS_PROBE)
        lost = km.calibrate(_REPO, rows)["lost"]
        self.assertEqual(len(lost), 1, lost)
        self.assertIn("объявила пробу", lost[0])

    def test_a_known_member_missing_from_the_census_is_named_too(self):
        """Третий способ потерять члена — не спросить о нём вовсе."""
        rows = self._agreeing_rows()
        victim = sorted(km.KNOWN_WITH_PROBE)[0]
        rows.pop(victim)
        lost = km.calibrate(_REPO, rows)["lost"]
        self.assertEqual(len(lost), 1, lost)
        self.assertIn("вне переписи", lost[0])

    def test_both_sides_of_the_calibration_are_non_empty(self):
        """Калибровка с пустой стороной не проверяет НИЧЕГО."""
        self.assertGreaterEqual(len(km.KNOWN_WITH_PROBE), 3)
        self.assertGreaterEqual(len(km.KNOWN_WITHOUT_PROBE), 2)
        self.assertEqual(set(km.KNOWN_WITH_PROBE) & set(km.KNOWN_WITHOUT_PROBE),
                         set())

    def test_every_calibration_address_names_a_file_of_this_tree(self):
        for rel in list(km.KNOWN_WITH_PROBE) + list(km.KNOWN_WITHOUT_PROBE):
            with self.subTest(member=rel):
                self.assertTrue((_REPO / rel).exists(),
                                f"калибровка ссылается на {rel}, которого в "
                                "дереве нет — адрес устарел молча")


class TheLiveTreeIsMeasuredAndKnownMembersAreShown(unittest.TestCase):
    """ЗАМЕР ЖИВОГО ДЕРЕВА — и ровно та проба, которую требует G1029 п. 2.

    Население литералом НЕ закрепляется (урок #1119: закрепить замер числом
    значит краснеть от своего же производителя). Закрепляется СВОЙСТВО:
    известные члены по обе стороны обязаны выйти своим исходом, а состав
    класса — не вырасти против объявления.
    """

    @classmethod
    def setUpClass(cls):
        """ЕДИНСТВЕННЫЙ живой зов на весь класс — и он остаётся ПРОБОЙ.

        Цена переписи живого дерева: 121.7 с на хосте и **541.4 с у раннера**
        при пороге `pytest-timeout` 180 с НА ТЕСТ (ADR-1056). Пока каждый тест
        делал СВОЙ зов, класс платил её трижды и отдавал ТРИ имени в красный
        набор БЕЗ вердикта. Ленивый классовый кэш множитель не снимал:
        присваивание идёт ПОСЛЕ возврата, а по сроку возврата нет.

        Дешёвая форма была ЗАПРЕЩЕНА формой пробы до ADR-1057: засев искал
        живой зов только среди функций с префиксом `test_`, и зов в
        `setUpClass` пробой не считался ВОВСЕ. Теперь метка живого ответа
        течёт из классовой подготовки в тела тестов того же класса
        (`_class_fixture_seeds`), и это закреплено контролем в ОБЕ стороны —
        `APreparationOfTheClassIsALiveCallToo`. Порог НЕ поднят (инв. #16):
        снята ПРИЧИНА множителя, а не проверка.
        """
        cls.census = km.calibrated_measure(_REPO)

    def test_the_live_census_does_not_refuse_on_this_tree(self):
        census = self.census
        self.assertGreater(census.population, 0)
        self.assertEqual(sum(census.counts[o] for o in km.OUTCOMES),
                         census.population)

    def test_every_known_member_comes_out_with_its_own_outcome(self):
        rows = {row.rel: row for row in self.census.rows}
        for rel in km.KNOWN_WITH_PROBE:
            if rel not in rows:
                continue  # вне поверхности — сказано вслух в докстроке прибора
            with self.subTest(member=rel):
                self.assertEqual(rows[rel].outcome, km.HAS_PROBE,
                                 f"известная проба {rel} не найдена — замер, не "
                                 "нашедший известного члена, мерой класса не является")
        for rel in km.KNOWN_WITHOUT_PROBE:
            if rel not in rows:
                continue
            with self.subTest(member=rel):
                self.assertEqual(rows[rel].outcome, km.NO_PROBE, rel)

    def test_the_declared_class_has_not_grown(self):
        baseline = json.loads(
            (_REPO / "spa_core/tests/known_member_probe_baseline.json")
            .read_text(encoding="utf-8"))
        declared = set(baseline["members"])
        measured = {row.rel for row in self.census.rows
                    if row.outcome == km.NO_PROBE}
        new = sorted(measured - declared)
        self.assertEqual(
            new, [],
            "прибор БЕЗ пробы «ЖИВОЕ дерево + ИЗВЕСТНЫЙ член» появился после "
            f"замера: {new}. Выход — ПРОБА в его батарее (живой зов + названный "
            "член), а НЕ строка в "
            "spa_core/tests/known_member_probe_baseline.json (инв. #16)")
        self.assertLessEqual(
            len(measured), len(declared),
            "база класса может только УМЕНЬШАТЬСЯ")

    def test_the_baseline_names_only_files_that_exist(self):
        baseline = json.loads(
            (_REPO / "spa_core/tests/known_member_probe_baseline.json")
            .read_text(encoding="utf-8"))
        missing = [rel for rel in baseline["members"] if not (_REPO / rel).exists()]
        self.assertEqual(missing, [], f"объявление ссылается на исчезнувшее: {missing}")


class TheInstrumentDoesNotExemptItself(unittest.TestCase):
    """Прибор живёт в населении, которое мерит (урок ADR-620)."""

    def test_the_instrument_is_itself_on_the_surface_of_its_class(self):
        tree = ast.parse((_REPO / "spa_core/monitoring/known_member_probe_census.py")
                         .read_text(encoding="utf-8"))
        labels = {node.targets[0].id for node in ast.walk(tree)
                  if isinstance(node, ast.Assign) and len(node.targets) == 1
                  and isinstance(node.targets[0], ast.Name)
                  and node.targets[0].id.isupper()
                  and isinstance(node.value, ast.Constant)
                  and isinstance(node.value.value, str)}
        self.assertGreaterEqual(len(labels), 2,
                                "прибор обязан объявлять ≥2 ярлыка исхода — иначе "
                                "поверхность собственного класса его не увидит")
        self.assertIn("ast", {alias.name for node in ast.walk(tree)
                              if isinstance(node, ast.Import)
                              for alias in node.names})

    def test_the_instrument_has_no_entry_point_of_its_own(self):
        """Точка входа без зовущего краснит `test_unwired_guard_modules_ratchet`;
        прибор зовут батарея и рука, и это решение, а не недосмотр."""
        source = (_REPO / "spa_core/monitoring/known_member_probe_census.py") \
            .read_text(encoding="utf-8")
        self.assertNotIn('if __name__ == "__main__"', source)


if __name__ == "__main__":
    unittest.main()
