#!/usr/bin/env python3
"""Батарея прибора РЫЧАГА варианта (а) — заказ G1013 п. 1, ADR-1025.

Каждая проба здесь — положительный контроль на аварию, которая УЖЕ случилась,
либо её обратная сцена. Главная из них: ADR-1024 объявил рычагом ДОСТИЖИМОСТЬ
файла с дверью (`import`), а запись читателя требует ЗОВА двери — и разница
между этими двумя вопросами оказалась 16 против 0.

Сцены строятся на одноразовом дереве: вердикт о рычаге есть свойство СОДЕРЖИМОГО
дерева (`.claude/rules/deployment.md`), и проба, судящая о живом `spa_core`,
меняла бы ответ от чужой правки. Два живых контроля объявлены отдельно и мерят
ровно то, что без живого дерева не измеримо: что измеренный НОЛЬ есть ноль мира,
а не слепота прибора.
"""

from __future__ import annotations

import pathlib
import unittest

from spa_core.monitoring import shared_read_door_leverage as L
from spa_core.monitoring import producer_input_awareness as pia
from spa_core.monitoring.producer_input_awareness import Unmeasured

_LIVE_ROOT = pathlib.Path(__file__).resolve().parents[2]


def _tree(tmp: pathlib.Path, files: dict[str, str]) -> pathlib.Path:
    """Одноразовое дерево из объявленных файлов."""
    for rel, text in files.items():
        p = tmp / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
        init = p.parent / "__init__.py"
        if p.suffix == ".py" and not init.exists():
            init.write_text("", encoding="utf-8")
    return tmp


def _doc(root: pathlib.Path, helper_rel: str, producers: dict[str, str]) -> dict:
    """Документ соседа, собранный РУКАМИ — поверхность у прибора ВХОД.

    Так проба не зависит от живой таблицы ``edition_remeasure.ENTRY``: класс
    членов может расти, а вопрос о рычаге от этого не меняется.
    """
    return {
        "shared_doors": [{"rel": helper_rel, "producers": sorted(producers),
                          "n": len(producers)}],
        "producers": [{"artifact": a, "rel": r} for a, r in producers.items()],
    }


class DoorKindTest(unittest.TestCase):
    """Род ДВЕРИ: под запись читателя годится ровно функция уровня модуля."""

    def setUp(self) -> None:
        self.tmp = pathlib.Path(self.enterContext(
            __import__("tempfile").TemporaryDirectory()))

    def test_a_module_level_read_function_is_a_callable_door(self) -> None:
        root = _tree(self.tmp, {"h/x.py": (
            "def load(path):\n"
            "    with open(path, 'r') as f:\n"
            "        return f.read()\n")})
        doors = L.doors_of(root, "h/x.py")
        self.assertEqual([d.kind for d in doors], [L.D_FUNCTION])
        self.assertEqual([d.name for d in doors], ["load"])

    def test_a_write_only_helper_has_no_callable_read_door(self) -> None:
        """ОБРАТНАЯ сцена той же двери: ``atomic_save`` читателем не является.

        Это дефект №1 ADR-1024 на уровень выше: общий помощник офиса
        (``spa_core/utils/atomic.py``) зовут все шестнадцать — но ради ЗАПИСИ.
        """
        root = _tree(self.tmp, {"h/x.py": (
            "def save(data, path):\n"
            "    with open(path, 'w') as f:\n"
            "        f.write(data)\n")})
        helper = L.Helper("h/x.py", ("a.json",))
        helper.doors = L.doors_of(root, "h/x.py")
        self.assertEqual(helper.doors, ())
        self.assertEqual(helper.callable_doors, ())

    def test_a_method_site_is_named_but_not_callable_by_name(self) -> None:
        root = _tree(self.tmp, {"h/x.py": (
            "class C:\n"
            "    def load(self, path):\n"
            "        return open(path, 'r').read()\n")})
        doors = L.doors_of(root, "h/x.py")
        self.assertEqual([d.kind for d in doors], [L.D_METHOD])
        self.assertIsNone(doors[0].name)
        helper = L.Helper("h/x.py", ("a.json",))
        helper.doors = doors
        self.assertEqual(helper.callable_doors, (),
                         "метод по имени не зовётся — нужен экземпляр")

    def test_an_import_time_site_is_its_own_kind(self) -> None:
        root = _tree(self.tmp, {"h/x.py": "DATA = open('d/seed.json', 'r').read()\n"})
        doors = L.doors_of(root, "h/x.py")
        self.assertEqual([d.kind for d in doors], [L.D_IMPORT_TIME])
        self.assertEqual(L.Helper("h/x.py", ()).callable_doors, ())

    def test_a_foreign_only_helper_has_no_callable_read_door(self) -> None:
        """Форма живого ``call_provenance.py``: единственная площадка — чужой процесс."""
        root = _tree(self.tmp, {"h/x.py": (
            "import subprocess\n"
            "def who():\n"
            "    return subprocess.run(['ps'], capture_output=True)\n")})
        helper = L.Helper("h/x.py", ("a.json", "b.json"))
        helper.doors = L.doors_of(root, "h/x.py")
        self.assertEqual([d.kind for d in helper.doors], [L.D_FOREIGN])
        self.assertEqual(helper.callable_doors, (),
                         "чужой процесс записью читателя не ухватывается")


class CallResolutionTest(unittest.TestCase):
    """ЗОВ против ДОСТИЖИМОСТИ — та самая разница, которой нет у ADR-1024."""

    HELPER = ("def load(path):\n"
              "    with open(path, 'r') as f:\n"
              "        return f.read()\n"
              "def save(data, path):\n"
              "    with open(path, 'w') as f:\n"
              "        f.write(data)\n")

    def setUp(self) -> None:
        self.tmp = pathlib.Path(self.enterContext(
            __import__("tempfile").TemporaryDirectory()))

    def _measure(self, producer_src: str) -> dict:
        root = _tree(self.tmp, {"h/x.py": self.HELPER, "p/one.py": producer_src})
        return L.measure(root, doc=_doc(root, "h/x.py", {"one.json": "p/one.py"}))

    def test_a_call_to_the_read_door_is_found(self) -> None:
        doc = self._measure("from h.x import load\n"
                            "def main():\n"
                            "    return load('d/a.json')\n")
        link = doc["helpers"][0]["links"][0]
        self.assertEqual(link["kind"], L.C_CALLS)
        self.assertEqual([c["door"] for c in link["calls"]], ["load"])
        self.assertEqual(L.verdict(doc), "lever_empty",
                         "один зовущий — ещё не рычаг: рычаг это ДВОЕ и больше")

    def test_two_callers_of_one_door_are_the_lever(self) -> None:
        root = _tree(self.tmp, {
            "h/x.py": self.HELPER,
            "p/one.py": "from h.x import load\ndef m():\n    return load('a.json')\n",
            "p/two.py": "from h.x import load\ndef m():\n    return load('b.json')\n"})
        doc = L.measure(root, doc=_doc(root, "h/x.py",
                                       {"one.json": "p/one.py", "two.json": "p/two.py"}))
        self.assertEqual(doc["best"]["callers_n"], 2)
        self.assertEqual(L.verdict(doc), "lever_found")
        self.assertEqual(L.EXIT_CODES[L.verdict(doc)], 0)

    def test_import_without_a_call_is_imports_only_not_calls(self) -> None:
        """ДОСЛОВНЫЙ дефект рычага ADR-1024: ввезён помощник, дверь не позвана."""
        doc = self._measure("from h.x import save\n"
                            "def main():\n"
                            "    return save('{}', 'd/out.json')\n")
        link = doc["helpers"][0]["links"][0]
        self.assertEqual(link["kind"], L.C_IMPORTS_ONLY)
        self.assertEqual(link["calls"], [])
        self.assertEqual(L.verdict(doc), "lever_empty")
        self.assertEqual(L.EXIT_CODES[L.verdict(doc)], 1)

    def test_a_string_literal_equal_to_a_door_name_is_not_a_call(self) -> None:
        """Ловушка, на которой греп этого цикла дал 1 вместо 0.

        Форма дословно живая: ``_LOADERS`` в ``cio_target_producers.py`` несёт
        строку ``"atomic_load"`` среди имён загрузчиков. Это данные, не вызов.
        """
        doc = self._measure("import h.x\n"
                            "_LOADERS = ('_load_state', 'load', 'read_all')\n"
                            "def main():\n"
                            "    return _LOADERS\n")
        link = doc["helpers"][0]["links"][0]
        self.assertEqual(link["kind"], L.C_IMPORTS_ONLY,
                         "строка, равная имени двери, зовом не является")
        self.assertEqual(link["calls"], [])

    def test_a_same_named_local_function_is_not_a_foreign_call(self) -> None:
        """ОБРАТНАЯ сцена: своё одноимённое ``load`` чужой дверью не является."""
        doc = self._measure("def load(path):\n"
                            "    return path\n"
                            "def main():\n"
                            "    return load('d/a.json')\n")
        link = doc["helpers"][0]["links"][0]
        self.assertEqual(link["kind"], L.C_NO_LINK,
                         "помощник не ввезён вовсе ⇒ и связи нет")

    def test_an_alias_import_resolves_to_the_same_door(self) -> None:
        doc = self._measure("import h.x as hx\n"
                            "def main():\n"
                            "    return hx.load('d/a.json')\n")
        link = doc["helpers"][0]["links"][0]
        self.assertEqual(link["kind"], L.C_CALLS)
        self.assertEqual([c["door"] for c in link["calls"]], ["load"])

    def test_a_from_package_import_module_resolves(self) -> None:
        doc = self._measure("from h import x\n"
                            "def main():\n"
                            "    return x.load('d/a.json')\n")
        self.assertEqual(doc["helpers"][0]["links"][0]["kind"], L.C_CALLS)

    def test_a_call_to_a_non_read_function_is_not_coverage(self) -> None:
        """Зов ЕСТЬ, но не двери чтения — покрытием это не становится."""
        doc = self._measure("from h.x import save\n"
                            "def main():\n"
                            "    return save('{}', 'd/out.json')\n")
        self.assertEqual(doc["helpers"][0]["links"][0]["kind"], L.C_IMPORTS_ONLY)


class SurvivorScenesTest(unittest.TestCase):
    """Три сцены, которых НЕ ХВАТАЛО: мутации 7, 17 и 18 первого прогона ВЫЖИЛИ.

    Выживший мутант записан, а не замазан: он означает, что поведение РАЗНОЕ, а
    ни одна сцена его не различает. Каждая проба ниже — та самая различающая
    сцена, и каждая названа своим мутантом.
    """

    HELPER_WRITE_ONLY = ("def load(path):\n"
                         "    with open(path, 'w') as f:\n"
                         "        f.write(path)\n")

    def setUp(self) -> None:
        self.tmp = pathlib.Path(self.enterContext(
            __import__("tempfile").TemporaryDirectory()))

    def test_with_nobody_calling_there_is_no_best_door_at_all(self) -> None:
        """Мутант 7: «лучшая дверь» печаталась при НУЛЕ зовущих.

        Вердикт от этого не менялся — менялся ОТЧЁТ, и читался он как
        существующий рычаг. Ровно та подмена, против которой написан прибор.
        """
        root = _tree(self.tmp, {
            "h/x.py": "def load(p):\n    return open(p, 'r').read()\n",
            "p/one.py": "from h.x import load as _unused\nx = 1\n",
            "p/two.py": "import h.x\nx = 2\n"})
        doc = L.measure(root, doc=_doc(root, "h/x.py",
                                      {"one.json": "p/one.py", "two.json": "p/two.py"}))
        self.assertIsNone(doc["best"],
                          "ноль зовущих ⇒ лучшей двери НЕ существует")
        report = L.format_report(doc)
        self.assertIn("ЛУЧШЕЙ двери НЕТ", report)
        self.assertNotIn("ЛУЧШАЯ дверь", report)

    def test_a_helper_without_a_read_door_never_gets_a_caller(self) -> None:
        """Мутант 17: пустой перечень дверей подменялся непустым.

        Тогда помощник, у которого двери ЧТЕНИЯ нет вовсе (только запись),
        получал бы зовущих — ноль стал бы неотличим от покрытия.
        """
        root = _tree(self.tmp, {
            "h/x.py": self.HELPER_WRITE_ONLY,
            "p/one.py": ("from h.x import load\n"
                         "def main():\n"
                         "    return load('d/a.json')\n")})
        doc = L.measure(root, doc=_doc(root, "h/x.py", {"one.json": "p/one.py"}))
        helper = doc["helpers"][0]
        self.assertEqual(helper["callable_doors"], [],
                         "у двери ЗАПИСИ рода чтения нет")
        self.assertEqual(helper["callers"], [],
                         "зов есть, но двери чтения нет ⇒ покрытия нет")
        self.assertEqual(helper["links"][0]["kind"], L.C_IMPORTS_ONLY)

    def test_the_missing_tree_is_refused_by_this_module_itself(self) -> None:
        """Мутант 18: свой отказ о пропавшем дереве был снят и проба не заметила.

        Прежняя сцена звала прибор БЕЗ документа соседа, и отказывал сосед
        (``pia.measure``), а не этот модуль. С готовым документом соседа не
        зовут вовсе — и отказать обязан СВОЙ вход.
        """
        root = _tree(self.tmp, {"h/x.py": "def load(p):\n    return open(p,'r').read()\n"})
        ready = _doc(root, "h/x.py", {"one.json": "h/x.py"})
        with self.assertRaises(Unmeasured):
            L.measure(self.tmp / "нет-такого-дерева", doc=ready)


class ThirdOutcomeTest(unittest.TestCase):
    """Инв. #17: «не измерено» никогда не выдаётся за ноль."""

    def setUp(self) -> None:
        self.tmp = pathlib.Path(self.enterContext(
            __import__("tempfile").TemporaryDirectory()))

    def test_an_empty_shared_table_is_unmeasured_not_zero(self) -> None:
        root = _tree(self.tmp, {"p/one.py": "x = 1\n"})
        with self.assertRaises(Unmeasured):
            L.measure(root, doc={"shared_doors": [], "producers": []})

    def test_a_missing_tree_is_unmeasured(self) -> None:
        with self.assertRaises(Unmeasured):
            L.measure(self.tmp / "нет-такого-дерева")

    def test_an_unparsable_producer_is_unmeasured_with_a_reason(self) -> None:
        root = _tree(self.tmp, {
            "h/x.py": "def load(p):\n    return open(p, 'r').read()\n",
            "p/one.py": "def broken(:\n"})
        doc = L.measure(root, doc=_doc(root, "h/x.py", {"one.json": "p/one.py"}))
        link = doc["helpers"][0]["links"][0]
        self.assertEqual(link["kind"], L.C_UNMEASURED)
        self.assertTrue(link["reason"], "причина обязана быть названа")
        self.assertEqual(L.verdict(doc), "unmeasured")
        self.assertEqual(L.EXIT_CODES["unmeasured"], 2)

    def test_an_unparsable_helper_keeps_its_reason_and_measures_nothing(self) -> None:
        root = _tree(self.tmp, {"h/x.py": "def broken(:\n", "p/one.py": "x = 1\n"})
        doc = L.measure(root, doc=_doc(root, "h/x.py", {"one.json": "p/one.py"}))
        self.assertTrue(doc["helpers"][0]["reason"])
        self.assertEqual(doc["helpers"][0]["links"], [])

    def test_an_unresolved_producer_is_unmeasured_not_absent(self) -> None:
        root = _tree(self.tmp, {"h/x.py": "def load(p):\n    return open(p, 'r').read()\n"})
        doc = L.measure(root, doc={
            "shared_doors": [{"rel": "h/x.py", "producers": ["ghost.json"], "n": 1}],
            "producers": []})
        self.assertEqual(doc["helpers"][0]["links"][0]["kind"], L.C_UNMEASURED)


class SurfaceTest(unittest.TestCase):
    """Поверхность — у соседа, своей копии нет."""

    def test_the_surface_comes_from_the_neighbour_at_call_time(self) -> None:
        self.assertIs(L.pia, pia, "сосед импортируется, а не копируется")
        self.assertFalse(
            [n for n in vars(L) if n.isupper() and n.endswith("ENTRY")],
            "своей таблицы членов класса у прибора быть не должно")

    def test_reading_kinds_exclude_the_foreign_process(self) -> None:
        self.assertNotIn(pia.S_FOREIGN, L._READING_KINDS)
        self.assertIn(pia.S_CONDUIT, L._READING_KINDS)


class LiveSurfaceTest(unittest.TestCase):
    """ДВА живых контроля: измеренный ноль есть ноль МИРА, а не слепота прибора.

    Без живого дерева их задать нечем: синтетическая сцена отвечает о себе.
    """

    def test_the_resolver_finds_calls_in_the_very_modules_whose_read_doors_are_zero(
            self) -> None:
        """Тот же разборщик в тех же модулях находит зовы — просто не двери чтения.

        Если бы ``_calls_to`` был слеп, ноль по дверям чтения был бы НЕОТЛИЧИМ
        от «прибор ничего не умеет». Контроль: в модуле производителя находится
        зов ``atomic_save`` — двери ЗАПИСИ того же общего помощника.
        """
        rel = "spa_core/monitoring/decision_journal_coverage.py"
        if not (_LIVE_ROOT / rel).is_file():
            self.fail(f"НЕ ИЗМЕРЕНО: живого модуля {rel} нет в дереве")
        tree = pia._parse(_LIVE_ROOT, rel)
        found = L._calls_to(tree, _LIVE_ROOT, "spa_core/utils/atomic.py",
                            ["atomic_save"])
        self.assertTrue(found, "разборщик обязан находить зов, когда он есть")
        atomic = L.Helper("spa_core/utils/atomic.py", ())
        atomic.doors = L.doors_of(_LIVE_ROOT, "spa_core/utils/atomic.py")
        self.assertIn("atomic_load", atomic.callable_doors)
        self.assertEqual(
            L._calls_to(tree, _LIVE_ROOT, "spa_core/utils/atomic.py",
                        atomic.callable_doors),
            (), "дверь ЧТЕНИЯ того же помощника этот производитель не зовёт")

    def test_the_shared_write_door_is_what_everyone_actually_calls(self) -> None:
        """Общая дверь у офиса ЕСТЬ — и она ПИШЕТ. Отсюда и «16 из 16» ADR-1024."""
        rel = "spa_core/utils/atomic.py"
        if not (_LIVE_ROOT / rel).is_file():
            self.fail(f"НЕ ИЗМЕРЕНО: живого помощника {rel} нет в дереве")
        doors = L.doors_of(_LIVE_ROOT, rel)
        self.assertEqual([d.name for d in doors if d.kind == L.D_FUNCTION],
                         ["atomic_load"],
                         "у общего помощника ровно одна зовомая дверь ЧТЕНИЯ")


if __name__ == "__main__":
    unittest.main()
