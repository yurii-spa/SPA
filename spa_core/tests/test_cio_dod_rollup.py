"""Контроль сводного замера §50 приказа «Portfolio CIO» (`scripts/cio_dod_rollup.py`).

Каждый тест здесь — положительный контроль на КОНКРЕТНЫЙ способ соврать, а не
проверка, что функция что-то вернула. Способов ровно столько, сколько у прибора
дверей, и у §50 есть своя, которой у §49 нет: **строка-анкер**. Владелец начал
§50 запретом считать работу законченной по признакам «code implemented · tests
green · agent exists» — разбор, берущий тело раздела целиком, зачёл бы эти
признаки-обманки в приёмку и ответил бы НАОБОРОТ.

Литеральных дат в файле нет ни одной: ни прибор, ни его сцены к календарю не
обращаются, поэтому и закреплять нечего.
"""
from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))
_SCRIPTS = _REPO / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

import cio_dod_rollup as dod  # noqa: E402

from spa_core.monitoring import card_acceptance as ca  # noqa: E402
from spa_core.monitoring.card_acceptance import (  # noqa: E402
    NOT_SATISFIED,
    SATISFIED,
    UNMEASURED,
)

#: Отрицательная преамбула владельца — ДОСЛОВНО, включая вводную строку.
_PREAMBLE = ["Не считать задачу завершенной после:", "code implemented",
             "tests green", "agent exists"]


def _card(criteria, *, preamble=_PREAMBLE, anchor=dod.POPULATION_ANCHOR,
          head=dod.SECTION_HEAD, heads=1, anchors=1) -> str:
    """Собрать тело карточки вокруг §50. Форма — ровно как у владельца."""
    out = ["---", "title: fake", "---", "", "49. Acceptance criteria", "", "⸻", ""]
    for _ in range(heads):
        out.append(head)
        out.extend(preamble)
        for _ in range(anchors):
            if anchor is not None:
                out.append(anchor)
        out.extend(criteria)
        out.extend(["", "⸻", ""])
    out.extend(["51. Required final report", "итог владельцу.", ""])
    return "\n".join(out)


def _tree(card_text: str) -> str:
    """Одноразовое дерево с карточкой и БЕЗ git — `ref` честно не прочитается.

    Дерева без git здесь достаточно и оно намеренно: вторая копия карточки — это
    отдельная ось (`comparison`), и мешать её в сцены про РАЗБОР значило бы
    мерить две вещи одной пробой.
    """
    root = tempfile.mkdtemp(prefix="dod_scene_")
    path = Path(root) / dod.CARD_REL
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(card_text, encoding="utf-8")
    return root


def _runner(verdicts):
    """Подменная мерка: имя пробы → (вердикт, деталь). Считает свои зовы."""
    calls = []

    def run(name, **kw):
        calls.append((name, kw))
        return verdicts.get(name, (UNMEASURED, "сцена об этой пробе не говорит"))

    run.calls = calls
    return run


class TheAnchorIsTheBorderOfThePopulation(unittest.TestCase):
    """Про единственную дверь, которой у §49 нет, — и про то, как она врёт."""

    def test_the_owners_negative_preamble_is_NOT_counted_as_acceptance(self):
        # Положительный контроль на дефект «взять тело раздела целиком»: тогда в
        # население попали бы «code implemented», «tests green», «agent exists»,
        # то есть РОВНО те признаки, которые владелец назвал недостаточными.
        parsed = dod.parse_s50_criteria(_card(["Сделано А.", "Сделано Б."]))
        self.assertEqual(parsed["criteria"], ["Сделано А.", "Сделано Б."])
        self.assertEqual([r["text"] for r in parsed["rejected"]], _PREAMBLE)
        for bad in parsed["rejected"]:
            self.assertIn("ДО анкера", bad["reason"])
        # Отброшенное ПЕЧАТАЕТСЯ числом: «отбросил четыре строки» и «их там не
        # было» — разные наблюдения, и слить их значило бы потерять ось.
        self.assertEqual(parsed["body_lines"],
                         len(_PREAMBLE) + 1 + len(parsed["criteria"]))

    def test_a_missing_anchor_is_UNMEASURED_not_the_whole_body(self):
        with self.assertRaises(dod.Unmeasured) as got:
            dod.parse_s50_criteria(_card(["Сделано А."], anchor=None))
        self.assertIn("анкера", str(got.exception))
        self.assertIn("НЕ ИЗМЕРЕНО", str(got.exception))

    def test_two_anchors_are_UNMEASURED_not_the_first_one(self):
        with self.assertRaises(dod.Unmeasured) as got:
            dod.parse_s50_criteria(_card(["Сделано А."], anchors=2))
        self.assertIn("2 раз", str(got.exception))

    def test_two_sections_numbered_50_are_UNMEASURED_not_the_first_one(self):
        with self.assertRaises(dod.Unmeasured) as got:
            dod.parse_s50_criteria(_card(["Сделано А."], heads=2))
        self.assertIn("какую", str(got.exception))

    def test_a_missing_section_is_UNMEASURED(self):
        with self.assertRaises(dod.Unmeasured) as got:
            dod.parse_s50_criteria("---\ntitle: fake\n---\n\n51. Отчёт\n")
        self.assertIn("не найден", str(got.exception))

    def test_an_anchor_with_nothing_after_it_is_UNMEASURED_not_green(self):
        # Пустое население зелено ПО ПОСТРОЕНИЮ — это и есть способ соврать.
        with self.assertRaises(dod.Unmeasured) as got:
            dod.parse_s50_criteria(_card([]))
        self.assertIn("НЕТ НИ ОДНОЙ строки", str(got.exception))

    def test_a_duplicated_criterion_is_UNMEASURED_not_deduplicated(self):
        with self.assertRaises(dod.Unmeasured) as got:
            dod.parse_s50_criteria(_card(["Сделано А.", "Сделано А."]))
        self.assertIn("дважды", str(got.exception))

    def test_the_population_comes_from_the_CARD_not_from_the_instrument(self):
        # Двадцать нигде не зашито: сцена даёт три критерия — прибор отвечает
        # про три, и порядок ТЗ сохранён.
        parsed = dod.parse_s50_criteria(_card(["Раз.", "Два.", "Три."]))
        self.assertEqual(parsed["criteria"], ["Раз.", "Два.", "Три."])


class TheThreeOutcomesAreDistinguishable(unittest.TestCase):
    """Инв. #17 у СВОДКИ: «мерки нет» ≠ «мера говорит нет» ≠ «выполнено»."""

    def setUp(self):
        self.root = _tree(_card(["Есть мерка и да.", "Есть мерка и нет.",
                                 "Мерки нет."]))
        self.declared = {"Есть мерка и да.": ["p_yes"],
                         "Есть мерка и нет.": ["p_no"]}

    def _measure(self, runner, declared=None):
        real = ca.probes_by_s50_criterion
        real_inputs = dod.probe_tree_inputs
        ca.probes_by_s50_criterion = lambda: dict(
            self.declared if declared is None else declared)
        dod.probes_by_s50_criterion = ca.probes_by_s50_criterion
        dod.probe_tree_inputs = lambda name: ()
        try:
            return dod.measure(self.root, probe_runner=runner)
        finally:
            ca.probes_by_s50_criterion = real
            dod.probes_by_s50_criterion = real
            dod.probe_tree_inputs = real_inputs

    def test_each_of_the_three_lands_in_its_own_counter(self):
        rep = self._measure(_runner({"p_yes": (SATISFIED, "да"),
                                     "p_no": (NOT_SATISFIED, "нет")}))
        self.assertEqual(rep["counts"][SATISFIED], 1)
        self.assertEqual(rep["counts"][NOT_SATISFIED], 1)
        self.assertEqual(rep["counts"][UNMEASURED], 1)

    def test_a_criterion_without_a_probe_is_unmeasured_with_the_class_NAMED(self):
        rep = self._measure(_runner({"p_yes": (SATISFIED, "да"),
                                     "p_no": (NOT_SATISFIED, "нет")}))
        row = next(r for r in rep["rows"] if r["criterion"] == "Мерки нет.")
        self.assertEqual(row["verdict"], UNMEASURED)
        self.assertIsNone(row["probe"])
        self.assertEqual(row["unmeasured_class"], dod.s49.UNMEASURED_NO_MEASURE)
        self.assertEqual(rep["unmeasured_classes"][dod.s49.UNMEASURED_NO_MEASURE], 1)

    def test_a_measured_row_carries_the_class_as_None_not_as_a_missing_field(self):
        # `None` значит «вопрос не стои́т» и обязан быть отличим от «класс не
        # считали вовсе»: второе читалось бы как отсутствие оси.
        rep = self._measure(_runner({"p_yes": (SATISFIED, "да"),
                                     "p_no": (NOT_SATISFIED, "нет")}))
        row = next(r for r in rep["rows"] if r["criterion"] == "Есть мерка и да.")
        self.assertIn("unmeasured_class", row)
        self.assertIsNone(row["unmeasured_class"])

    def test_two_probes_on_one_criterion_is_unmeasured_not_a_silent_pick(self):
        rep = self._measure(_runner({"p_yes": (SATISFIED, "да")}),
                            declared={"Есть мерка и да.": ["p_yes", "p_other"]})
        row = next(r for r in rep["rows"] if r["criterion"] == "Есть мерка и да.")
        self.assertEqual(row["verdict"], UNMEASURED)
        self.assertIn("столкновение объявлений", row["detail"])

    def test_a_declaration_pointing_PAST_the_population_is_a_finding(self):
        rep = self._measure(_runner({"p_yes": (SATISFIED, "да")}),
                            declared={"Есть мерка и да.": ["p_yes"],
                                      "Критерия с таким текстом в §50 нет.": ["p_x"]})
        self.assertIn("Критерия с таким текстом в §50 нет.",
                      rep["orphan_declarations"])
        # И он НЕ попадает в население: сводка остаётся о том, что написал владелец.
        self.assertEqual(len(rep["rows"]), 3)

    def test_the_injected_runner_really_REPLACES_the_measure(self):
        # Контроль на «половину инъекции» (`.claude/rules/deployment.md`): если
        # подмена не доходит, сцены выше зелены по построению и мерят настоящие
        # пробы. Здесь это проверяется СМЕНОЙ вердикта на тех же байтах.
        yes = self._measure(_runner({"p_yes": (SATISFIED, "да"),
                                     "p_no": (SATISFIED, "и да")}))
        no = self._measure(_runner({"p_yes": (NOT_SATISFIED, "нет"),
                                    "p_no": (NOT_SATISFIED, "нет")}))
        self.assertEqual(yes["counts"][SATISFIED], 2)
        self.assertEqual(no["counts"][NOT_SATISFIED], 2)


class TheDeclarationDoorIsSingleAndReadsTheRegistry(unittest.TestCase):
    """Про дверь объявления: одна копия обхода, и реестр, а не модуль."""

    def test_both_acceptance_doors_route_through_ONE_traversal(self):
        # Две копии одной мерки расходятся МОЛЧА (ADR-220), и разошлись бы они
        # ровно у читателя-человека — в ИТОГЕ. Контроль прямой: подменяем
        # единственную дверь и смотрим, что ОБА читателя это видят.
        real = ca._probes_by_declared_criterion
        seen = []

        def fake(attr):
            seen.append(attr)
            return {"-": ["-"]}

        ca._probes_by_declared_criterion = fake
        try:
            self.assertEqual(ca.probes_by_s49_criterion(), {"-": ["-"]})
            self.assertEqual(ca.probes_by_s50_criterion(), {"-": ["-"]})
        finally:
            ca._probes_by_declared_criterion = real
        self.assertEqual(seen, ["s49_criterion", "s50_criterion"])

    def test_a_declaration_on_an_UNREGISTERED_probe_does_not_count(self):
        # Проба, потерявшая регистрацию, измерять уже ничего не может, и считать
        # её объявление действующим значило бы записать критерий в измеренные по
        # мёртвой ссылке.
        #
        # Объявляющая функция кладётся в НАЗВАННОЕ ПРОСТРАНСТВО МОДУЛЯ, а не
        # остаётся локальной в тесте, и это не придирка к сцене: мутация,
        # заменяющая обход реестра обходом модуля, на локальной функции
        # ВЫЖИВАЕТ — её там не видно, поэтому вердикт мутанта совпадает с
        # вердиктом кода (замер цикла #1213, M13). Мутация без РАЗЛИЧАЮЩЕЙ
        # сцены выживает, и лечится это сценой, а не мутацией.
        def orphan():
            return (SATISFIED, "я вне реестра")

        orphan.s50_criterion = "Объявлено мёртвой ссылкой."
        self.assertNotIn("orphan_probe_outside_the_registry", ca.PROBES)
        ca.orphan_probe_outside_the_registry = orphan
        try:
            declared = ca.probes_by_s50_criterion()
        finally:
            del ca.orphan_probe_outside_the_registry
        self.assertNotIn("Объявлено мёртвой ссылкой.", declared)

    def test_the_same_holds_for_the_s49_door_sharing_the_traversal(self):
        # Обход ОДИН, значит и дыра была бы одна: контроль ставится у обеих
        # дверей, иначе «реестр, а не модуль» доказано только у одной.
        def orphan():
            return (SATISFIED, "я вне реестра")

        orphan.s49_criterion = "Объявлено мёртвой ссылкой у §49."
        ca.orphan_probe_outside_the_registry_49 = orphan
        try:
            declared = ca.probes_by_s49_criterion()
        finally:
            del ca.orphan_probe_outside_the_registry_49
        self.assertNotIn("Объявлено мёртвой ссылкой у §49.", declared)

    def test_the_two_doors_do_not_read_each_others_attribute(self):
        # Если бы дверь читала чужой атрибут, §50 «измерялся» бы объявлениями
        # §49 — тринадцать критериев приёмки появились бы из ниоткуда.
        s49_names = set(ca.probes_by_s49_criterion())
        s50_names = set(ca.probes_by_s50_criterion())
        self.assertTrue(s49_names)
        self.assertTrue(s50_names)
        self.assertEqual(s49_names & s50_names, set())


class TheLiveDeclarationsMatchTheLiveCard(unittest.TestCase):
    """Сцена на ЖИВОМ дереве: объявления и карточка обязаны сходиться по байту."""

    def test_every_live_s50_declaration_EXISTS_in_the_live_population(self):
        # Расхождение на байт делает объявление СИРОТОЙ, и критерий тихо
        # перестаёт считаться измеренным. Этот тест и есть то, что краснеет,
        # когда строку §50 в ТЗ поправят, а объявление забудут.
        card = (_REPO / dod.CARD_REL).read_text(encoding="utf-8")
        population = set(dod.parse_s50_criteria(card)["criteria"])
        orphans = sorted(set(ca.probes_by_s50_criterion()) - population)
        self.assertEqual(orphans, [], f"объявления указывают мимо §50: {orphans}")

    def test_the_live_population_is_read_and_is_not_empty(self):
        card = (_REPO / dod.CARD_REL).read_text(encoding="utf-8")
        parsed = dod.parse_s50_criteria(card)
        self.assertGreater(len(parsed["criteria"]), 0)
        # Преамбула владельца в живой карточке ЕСТЬ, и прибор её отбрасывает:
        # пустой `rejected` здесь означал бы, что дверь анкера не работала.
        self.assertEqual([r["text"] for r in parsed["rejected"]], _PREAMBLE)


class TheSplitTreeIsNamedOutLoud(unittest.TestCase):
    """Сборный замер обязан называть себя — иначе это вердикт ни об одном дереве."""

    def setUp(self):
        self.root = _tree(_card(["Мерки нет."]))

    def _measure(self, **kw):
        real = dod.probes_by_s50_criterion
        dod.probes_by_s50_criterion = lambda: {}
        try:
            return dod.measure(self.root, probe_runner=_runner({}), **kw)
        finally:
            dod.probes_by_s50_criterion = real

    def test_a_data_dir_from_ANOTHER_tree_is_reported_as_split(self):
        # Самый частый зов: из worktree живого `data/` нет по построению,
        # поэтому `--data-dir` прод-дерева передают БЕЗ `--measure-tree`.
        rep = self._measure(data_dir="/somewhere/else/data")
        self.assertTrue(rep["split_tree"])

    def test_the_tree_own_data_dir_is_NOT_reported_as_split(self):
        rep = self._measure(data_dir=os.path.join(self.root, "data"))
        self.assertFalse(rep["split_tree"])

    def test_no_data_dir_at_all_is_NOT_split(self):
        self.assertFalse(self._measure()["split_tree"])


class TheExitCodesAreThree(unittest.TestCase):
    """0 · 1 · 2 — и второй отличим от третьего, иначе «не измерено» = «чисто»."""

    def _run(self, root, extra=()):
        out = subprocess.run(
            [sys.executable, str(_SCRIPTS / "cio_dod_rollup.py"),
             "--repo-root", root, *extra],
            capture_output=True, timeout=300)
        return out.returncode, out.stdout.decode("utf-8", errors="replace")

    def test_an_unparsable_section_exits_2_and_says_NOTHING_is_known(self):
        rc, text = self._run(_tree(_card(["Сделано А."], anchor=None)))
        self.assertEqual(rc, 2)
        self.assertIn("НЕ ИЗМЕРЕНО", text)
        self.assertIn("НЕ СКАЗАНО НИЧЕГО", text)

    def test_a_missing_card_exits_2(self):
        rc, text = self._run(tempfile.mkdtemp(prefix="dod_nocard_"))
        self.assertEqual(rc, 2)
        self.assertIn("НЕ ИЗМЕРЕНО", text)

    def test_a_population_without_measures_exits_1_not_0(self):
        # Самый важный из трёх: «мерки нет у всех» НЕ есть «всё выполнено».
        rc, text = self._run(_tree(_card(["Мерки нет ни у кого."])))
        self.assertEqual(rc, 1)
        self.assertIn("НЕ ИЗМЕРЕНО 1", text)

    def test_the_live_tree_is_measurable_and_exits_1(self):
        # Живой зов: сводка §50 сегодня не «всё выполнено», и код это говорит.
        rc, text = self._run(str(_REPO))
        self.assertEqual(rc, 1)
        self.assertIn("ИТОГ:", text)


class TheInstrumentOnlyReads(unittest.TestCase):
    """ADVISORY — заявление обязано быть проверяемым, а не строкой в докстринге."""

    def test_the_source_does_not_write_anywhere(self):
        src = (_SCRIPTS / "cio_dod_rollup.py").read_text(encoding="utf-8")
        for forbidden in ('open(', 'atomic_save', 'os.remove', 'shutil.',
                          'launchctl'):
            if forbidden == 'open(':
                # Чтение разрешено; запрещён режим записи у любого `open`.
                self.assertNotIn('"w"', src)
                self.assertNotIn("'w'", src)
                continue
            self.assertNotIn(forbidden, src)

    def test_the_module_imports_without_touching_the_fleet(self):
        spec = importlib.util.spec_from_file_location(
            "_dod_under_test", _SCRIPTS / "cio_dod_rollup.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        self.assertTrue(callable(mod.measure))
        self.assertEqual(mod.SECTION_HEAD, "50. Definition of Done")


if __name__ == "__main__":
    unittest.main()
