"""Контроль переписи `live_registry_scene_census` (заказ G95 п. 2, хвост ADR-507).

Каждый тест здесь — положительный контроль на КОНКРЕТНЫЙ способ соврать, а не
украшение (`.claude/rules/deployment.md`, «Проверка сторожа сторожей»). Прибор
ищет тесты, чей зелёный не зависит от состава живого реестра, — и первая же
ошибка, которую он мог бы сделать, это стать таким тестом сам.

Литеральных дат в файле нет: у переписи нет понятия свежести, и заводить его
фикстурой значило бы поставить бомбу на пустом месте. Литеральных pid нет по той
же причине. Живой реестр дерева ни один тест здесь не перечисляет: сцена —
одноразовое дерево со СВОИМ реестром, иначе контроль прибора сам сидел бы за той
дверью, которую прибор измеряет.
"""

from __future__ import annotations

import os
import subprocess
import sys
import textwrap
import unittest
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
if str(_REPO) not in sys.path:  # pragma: no cover - путь импорта
    sys.path.insert(0, str(_REPO))

from spa_core.monitoring import live_registry_scene_census as lrs  # noqa: E402


class PluginSourceIsRealCode(unittest.TestCase):
    """Плагин лежит СТРОКОЙ, и сломанная строка не обязана выглядеть как ноль."""

    def test_the_generated_plugin_compiles(self):
        # Положительный контроль на пережитую аварию: `\\n` вместо `\\\\n` в
        # исходнике плагина давал синтаксически битый файл, pytest падал на
        # сборе, и замер отвечал «НЕ ИЗМЕРЕНО». Громко — но дешевле поймать тут.
        compile(lrs._PLUGIN_SRC, "lrs_plugin.py", "exec")

    def test_the_plugin_declares_every_read_form_it_claims_to_record(self):
        for form in lrs.ENUMERATING_READS:
            self.assertIn(f'_note("{form}")', lrs._PLUGIN_SRC,
                          f"форма {form} объявлена перечисляющей, но плагин её не пишет")

    def test_the_plugin_records_the_call_site(self):
        self.assertIn("_caller_site", lrs._PLUGIN_SRC)
        self.assertIn('return "registry"', lrs._PLUGIN_SRC)


class ReadsAreParsedWithTheirFrame(unittest.TestCase):
    def test_a_read_carries_its_site(self):
        self.assertEqual(lrs._parse_read("iter@test"), ("iter", "test"))
        self.assertEqual(lrs._parse_read("get:name@registry"), ("get:name", "registry"))

    def test_a_read_without_a_frame_is_unknown_not_silently_a_test(self):
        # Иначе запись прежнего формата читалась бы как «кадр теста» и давала
        # находку там, где кадр не измерен вовсе.
        self.assertEqual(lrs._parse_read("iter"), ("iter", "unknown"))


class RegistrySizeKeepsAbsenceDistinctFromZero(unittest.TestCase):
    """Инв. #17 — на СВОЁМ докладе прибора в первую очередь."""

    def test_an_unreadable_registry_is_none_not_zero(self):
        self.assertIsNone(lrs._registry_size("spa_core.monitoring.no_such_module_at_all"))

    def test_a_readable_registry_is_a_count(self):
        size = lrs._registry_size()
        self.assertIsInstance(size, int)
        self.assertGreater(size, 0)


class ClassifyTestNamesSixDistinctOutcomes(unittest.TestCase):
    """Каждый вердикт — своя причина, и ни один не выдаётся за другой."""

    @staticmethod
    def _rec(outcome="passed", reads=()):
        return {"outcome": outcome, "reads": list(reads)}

    def test_absent_from_the_base_run_is_unmeasured(self):
        verdict, detail = lrs.classify_test(base=None, empty=None, grown=None)
        self.assertEqual(verdict, lrs.VERDICT_UNMEASURED)
        self.assertIn("базового", detail)

    def test_red_on_the_base_run_is_unmeasured_not_a_finding(self):
        verdict, _ = lrs.classify_test(base=self._rec("failed", ["iter@test"]),
                                       empty=self._rec(), grown=self._rec())
        self.assertEqual(verdict, lrs.VERDICT_UNMEASURED)

    def test_skipped_on_the_base_run_is_unmeasured(self):
        verdict, _ = lrs.classify_test(base=self._rec("skipped", ["iter@test"]),
                                       empty=self._rec(), grown=self._rec())
        self.assertEqual(verdict, lrs.VERDICT_UNMEASURED)

    def test_no_read_at_all_is_not_reached_so_zero_is_not_wrong_form(self):
        verdict, detail = lrs.classify_test(base=self._rec("passed", []),
                                            empty=self._rec(), grown=self._rec())
        self.assertEqual(verdict, lrs.VERDICT_NOT_REACHED)
        self.assertIn("не прочитан", detail)

    def test_red_under_substitution_is_loud_and_not_a_finding(self):
        verdict, detail = lrs.classify_test(base=self._rec("passed", ["iter@test"]),
                                            empty=self._rec("failed"), grown=self._rec())
        self.assertEqual(verdict, lrs.VERDICT_BREAKS)
        self.assertIn(lrs.MODE_EMPTY, detail)
        self.assertNotIn(verdict, lrs.FINDING_VERDICTS)

    def test_skipped_under_substitution_is_measured_on_a_par_with_failed(self):
        # Урок #465: в дифференциальном замере такой тест не краснеет и не
        # проходит — он ИСЧЕЗАЕТ, и глазами это читается как «всё в порядке».
        verdict, detail = lrs.classify_test(base=self._rec("passed", ["iter@test"]),
                                            empty=self._rec("skipped"), grown=self._rec())
        self.assertEqual(verdict, lrs.VERDICT_DISAPPEARS)
        self.assertIn(verdict, lrs.FINDING_VERDICTS)
        self.assertIn("skipped", detail)

    def test_enumerating_read_from_the_test_frame_green_on_empty_is_the_finding(self):
        verdict, detail = lrs.classify_test(base=self._rec("passed", ["items@test"]),
                                            empty=self._rec(), grown=self._rec())
        self.assertEqual(verdict, lrs.VERDICT_VACUOUS)
        self.assertIn(verdict, lrs.FINDING_VERDICTS)
        self.assertIn("items", detail)

    def test_enumerating_read_from_the_registry_frame_is_NOT_the_finding(self):
        # Разница между замером и догадкой: `validate_spec`, собирая текст
        # отказа, перечисляет реестр ВНУТРИ себя. Тест, проверяющий отказ
        # поимённо, этого цикла не писал — и в находки попадать не обязан.
        verdict, detail = lrs.classify_test(
            base=self._rec("passed", ["iter@registry", "contains:near_name@test"]),
            empty=self._rec(), grown=self._rec())
        self.assertEqual(verdict, lrs.VERDICT_INDEPENDENT)
        self.assertNotIn(verdict, lrs.FINDING_VERDICTS)
        self.assertIn("САМ реестр", detail)

    def test_pointed_reads_only_is_independent_of_the_members(self):
        verdict, detail = lrs.classify_test(
            base=self._rec("passed", ["get:absent_name@test"]),
            empty=self._rec(), grown=self._rec())
        self.assertEqual(verdict, lrs.VERDICT_INDEPENDENT)
        self.assertIn("поимённые", detail)

    def test_absent_from_a_substitution_run_without_a_collection_error_is_unmeasured(self):
        # Запись потеряна, а файл собрался: это НЕ измерено, и выдать её за
        # «вердикт не изменился» значило бы записать находку по пустому месту.
        verdict, detail = lrs.classify_test(base=self._rec("passed", ["iter@test"]),
                                            empty=None, grown=self._rec())
        self.assertEqual(verdict, lrs.VERDICT_UNMEASURED)
        self.assertIn("пустого", detail)

    def test_a_file_that_stops_collecting_under_substitution_is_breaks_not_unmeasured(self):
        # Самая сильная форма класса: реестр читается на ИМПОРТЕ. Тест исчезает
        # из прогона целиком, и прочесть это как «нет записи» значило бы назвать
        # измеренное неизмеренным.
        verdict, detail = lrs.classify_test(
            base=self._rec("passed", ["getitem:x@test"]), empty=None, grown=self._rec(),
            collect_failed={lrs.MODE_EMPTY: "KeyError: 'x'"})
        self.assertEqual(verdict, lrs.VERDICT_BREAKS)
        self.assertIn("ИМПОРТЕ", detail)

    def test_collection_broken_already_on_the_base_is_unmeasured(self):
        verdict, detail = lrs.classify_test(
            base=None, empty=None, grown=None,
            collect_failed={lrs.MODE_RECORD: "ImportError: boom"})
        self.assertEqual(verdict, lrs.VERDICT_UNMEASURED)
        self.assertIn("БАЗЕ", detail)

    def test_every_verdict_has_a_russian_gloss(self):
        for verdict in lrs.ALL_VERDICTS:
            self.assertIn(verdict, lrs.RU)


class SummaryCountsEveryVerdict(unittest.TestCase):
    def test_absent_verdicts_are_zero_not_missing_keys(self):
        counts = lrs.summarise([{"verdict": lrs.VERDICT_VACUOUS}])
        for verdict in lrs.ALL_VERDICTS:
            self.assertIn(verdict, counts)
        self.assertEqual(counts[lrs.VERDICT_VACUOUS], 1)
        self.assertEqual(counts[lrs.VERDICT_NOT_REACHED], 0)


class TheReportKeepsAbsenceDistinctFromZero(unittest.TestCase):
    """Прибор, ищущий `or`-подстановку у других, не вправе носить её сам."""

    def test_a_measurement_without_a_summary_is_unmeasured_not_all_zeroes(self):
        lines = lrs.report({})
        self.assertIn("НЕ ИЗМЕРЕНО", lines[0])
        self.assertIn("counts", lines[0])
        self.assertIn("НЕ СКАЗАНО НИЧЕГО", lines[1])
        for verdict in lrs.ALL_VERDICTS:
            self.assertNotIn(f"{verdict} 0", "\n".join(lines),
                             "нули напечатаны там, где не измерено ничего")

    def test_a_measurement_without_the_population_is_unmeasured(self):
        lines = lrs.report({"counts": {v: 0 for v in lrs.ALL_VERDICTS}})
        self.assertIn("НЕ ИЗМЕРЕНО", lines[0])
        self.assertIn("static", lines[0])

    def test_an_empty_summary_is_a_VALUE_and_still_prints(self):
        # Пустая сводка — «измерено, и вот сколько», а не «не измерено».
        lines = lrs.report({"counts": {v: 0 for v in lrs.ALL_VERDICTS},
                            "static": {}, "order": "G95 п. 2"})
        self.assertNotIn("НЕ ИЗМЕРЕНО", lines[0])
        self.assertIn("not_reached 0", "\n".join(lines))


class PopulationIsMeasuredByTwoIndependentNets(unittest.TestCase):
    """Сеть, нашедшая меньше, и есть «не та форма» — её обязано быть ВИДНО."""

    def setUp(self):
        import tempfile
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        (self.root / "tests").mkdir()

    def tearDown(self):
        self._tmp.cleanup()

    def _write(self, name, body):
        (self.root / "tests" / name).write_text(textwrap.dedent(body), encoding="utf-8")

    def test_a_file_naming_the_registry_lands_in_both_nets(self):
        self._write("test_a.py", """
            from spa_core.monitoring.card_acceptance import PROBES
            def test_x():
                assert PROBES is not None
        """)
        out = lrs.discover_population(self.root, ("tests",))
        self.assertEqual(out["net_textual"], 1)
        self.assertEqual(out["net_by_form"], 1)
        self.assertEqual(out["population"], ["tests/test_a.py"])

    def test_a_file_naming_only_the_module_is_found_by_text_and_not_by_the_registry_form(self):
        # Ровно расхождение сетей, которое прибор обязан НАПЕЧАТАТЬ, а не сгладить.
        self._write("test_b.py", """
            def test_y():
                assert "card_acceptance" in "card_acceptance"
        """)
        out = lrs.discover_population(self.root, ("tests",))
        self.assertEqual(out["net_textual"], 1)
        self.assertEqual(out["net_by_form"], 0)
        self.assertEqual(out["only_textual"], ["tests/test_b.py"])

    def test_a_helper_read_is_a_read_so_the_helper_form_counts(self):
        self._write("test_c.py", """
            from spa_core.monitoring.card_acceptance import run_probe
            def test_z():
                assert run_probe("nope")
        """)
        out = lrs.discover_population(self.root, ("tests",))
        forms = out["forms"]["tests/test_c.py"]
        self.assertIn("helper_import", forms)

    def test_an_unparsable_file_does_not_vanish_from_the_textual_net(self):
        self._write("test_d.py", "this is not python at all PROBES\n")
        out = lrs.discover_population(self.root, ("tests",))
        self.assertIn("tests/test_d.py", out["population"])

    def test_no_test_files_at_all_is_unmeasured_not_an_empty_population(self):
        import tempfile
        with tempfile.TemporaryDirectory() as empty:
            with self.assertRaises(lrs.Unmeasured) as caught:
                lrs.discover_population(Path(empty), ("tests",))
            self.assertIn("НЕ ИЗМЕРЕНО", str(caught.exception))


SCENE_REGISTRY = '''
"""Одноразовый реестр сцены. Форма та же, что у живого: имя → вызываемое."""
def _one(arg=None):
    return ("satisfied", "сцена")
_one.s49_criterion = "Scene criterion"
PROBES = {"scene_probe": _one}


def probes_by_s49_criterion():
    out = {}
    for name, fn in PROBES.items():
        crit = getattr(fn, "s49_criterion", None)
        if crit:
            out.setdefault(crit, []).append(name)
    return out


def validate_spec(name):
    """Помощник реестра, перечисляющий его ВНУТРИ себя — ради текста отказа."""
    if name in PROBES:
        return None
    return "проба не зарегистрирована. Известные: " + ", ".join(sorted(PROBES))
'''

#: Сцена: по одному представителю на каждый вердикт И на каждую сторону подмены.
#: Файл на род, чтобы ошибка сбора одного не уносила остальных.
SCENE_FILES = {
    "test_vacuous.py": '''
        from scene_registry import PROBES

        def test_vacuous_walks_the_members():
            """Зелен на ПУСТОМ реестре: цикл обойдёт ноль членов."""
            for name in sorted(PROBES):
                assert callable(PROBES[name])
    ''',
    "test_loud.py": '''
        from scene_registry import PROBES

        def test_loud_pins_the_content():
            """Роняется ЛЮБОЙ подменой: состав закреплён утверждением."""
            assert "scene_probe" in PROBES
            assert len(PROBES) == 1
    ''',
    "test_only_empty_breaks_it.py": '''
        from scene_registry import PROBES

        def test_breaks_only_when_the_registry_is_emptied():
            """Красен на пустом, зелен на выросшем — сторона ПУСТОТЫ."""
            assert len(PROBES) >= 1
    ''',
    "test_only_grown_breaks_it.py": '''
        from scene_registry import PROBES

        def test_breaks_only_when_the_registry_grows():
            """Зелен на пустом, красен на выросшем — сторона РОСТА."""
            assert len(PROBES) <= 1
    ''',
    "test_pointed.py": '''
        from scene_registry import PROBES

        def test_pointed_refusal_is_independent():
            """Поимённый отказ: от состава не зависит и зелен по делу."""
            assert PROBES.get("name_that_is_not_registered") is None
    ''',
    "test_helper_enumerates.py": '''
        from scene_registry import validate_spec

        def test_refusal_names_a_near_name_without_walking_the_members():
            """Перечисление делает САМ реестр (текст отказа), а не этот тест."""
            assert validate_spec("scene_prob") is not None
    ''',
    "test_untouched.py": '''
        from scene_registry import probes_by_s49_criterion

        def test_does_not_touch_the_registry_at_all():
            assert probes_by_s49_criterion is not None
    ''',
    "test_skips_under_substitution.py": '''
        import pytest
        from scene_registry import PROBES

        def test_vanishes_into_skipped_when_the_registry_empties():
            """Не краснеет и не проходит — ИСЧЕЗАЕТ (урок #465)."""
            if len(PROBES) < 1:
                pytest.skip("реестр пуст — предпосылки нет")
            assert True
    ''',
    "test_reads_at_import_time.py": '''
        from scene_registry import PROBES

        _NAMES = sorted(PROBES)  # чтение на СБОРЕ, до первого теста

        def test_uses_the_list_built_at_collection_time():
            assert all(isinstance(name, str) for name in _NAMES)
    ''',
    "test_dies_at_collection.py": '''
        from scene_registry import PROBES

        _FIRST = sorted(PROBES)[0]  # на ПУСТОМ реестре — IndexError на СБОРЕ

        def test_the_first_registered_probe_is_named():
            assert _FIRST == "scene_probe"
    ''',
}


def _build_scene(root: Path, files=None, registry: str = SCENE_REGISTRY) -> None:
    (root / "tests").mkdir(exist_ok=True)
    (root / "scene_registry.py").write_text(textwrap.dedent(registry), encoding="utf-8")
    for name, body in (files if files is not None else SCENE_FILES).items():
        (root / "tests" / name).write_text(textwrap.dedent(body), encoding="utf-8")


class TheDifferentialRunsOnADisposableSceneAndTellsTheKindsApart(unittest.TestCase):
    """Сквозной контроль: прибор целиком, на сцене со СВОИМ реестром.

    Живой реестр дерева здесь не участвует — иначе контроль зависел бы от того,
    сколько проб зарегистрировано сегодня, то есть сидел бы за измеряемой
    дверью. У каждого рода свой представитель, и вердикт каждого ИМЕНОВАН:
    подмена, переставшая различать любые два рода, красит этот тест.
    """

    def setUp(self):
        import tempfile
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        _build_scene(self.root)
        self.doc = lrs.measure(self.root, test_dirs=("tests",),
                               module="scene_registry", timeout=900)
        self.verdicts = {row["nodeid"].split("::")[-1]: row["verdict"]
                         for row in self.doc["rows"]}

    def tearDown(self):
        self._tmp.cleanup()

    def test_a_test_walking_the_members_is_the_finding(self):
        self.assertEqual(self.verdicts["test_vacuous_walks_the_members"],
                         lrs.VERDICT_VACUOUS)

    def test_a_test_pinning_the_content_breaks_loudly(self):
        self.assertEqual(self.verdicts["test_loud_pins_the_content"],
                         lrs.VERDICT_BREAKS)

    def test_the_emptied_side_of_the_substitution_is_load_bearing(self):
        # Снятие прогона «реестр ПУСТ» обязано красить этот тест: иначе сторона
        # пустоты не измеряется вовсе, а именно она ловит ТИХИЙ вред.
        self.assertEqual(self.verdicts["test_breaks_only_when_the_registry_is_emptied"],
                         lrs.VERDICT_BREAKS)

    def test_the_grown_side_of_the_substitution_is_load_bearing(self):
        self.assertEqual(self.verdicts["test_breaks_only_when_the_registry_grows"],
                         lrs.VERDICT_BREAKS)

    def test_a_pointed_refusal_is_not_called_a_finding(self):
        self.assertEqual(self.verdicts["test_pointed_refusal_is_independent"],
                         lrs.VERDICT_INDEPENDENT)

    def test_enumeration_done_by_the_registry_itself_is_not_the_tests_doing(self):
        # Кадр — разница между замером и догадкой. Без него этот тест попал бы
        # в находки за цикл, которого он не писал.
        name = "test_refusal_names_a_near_name_without_walking_the_members"
        self.assertEqual(self.verdicts[name], lrs.VERDICT_INDEPENDENT)

    def test_a_test_that_never_reads_the_registry_is_out_of_the_class(self):
        self.assertEqual(self.verdicts["test_does_not_touch_the_registry_at_all"],
                         lrs.VERDICT_NOT_REACHED)

    def test_a_test_that_skips_under_substitution_is_measured_not_lost(self):
        self.assertEqual(
            self.verdicts["test_vanishes_into_skipped_when_the_registry_empties"],
            lrs.VERDICT_DISAPPEARS)

    def test_a_collection_time_read_is_attributed_to_the_files_tests(self):
        # `_NAMES = sorted(PROBES)` на СБОРЕ — самая чистая форма дефекта. Не
        # приписать это чтение никому значило бы объявить её отсутствующей.
        self.assertEqual(self.verdicts["test_uses_the_list_built_at_collection_time"],
                         lrs.VERDICT_VACUOUS)

    def test_a_file_that_dies_at_collection_under_substitution_is_breaks(self):
        self.assertEqual(self.verdicts["test_the_first_registered_probe_is_named"],
                         lrs.VERDICT_BREAKS)
        self.assertIn("tests/test_dies_at_collection.py",
                      self.doc["collect_errors"][lrs.MODE_EMPTY])

    def test_a_collection_error_does_not_abort_the_whole_measurement(self):
        # Без `--continue-on-collection-errors` один такой файл обнулял ВЕСЬ
        # прогон: самая сильная находка класса делала класс неизмеримым.
        self.assertGreaterEqual(self.doc["tests_recorded"], len(SCENE_FILES) - 1)

    def test_the_substitution_demonstrably_bites(self):
        # Положительный контроль САМОЙ подмены: без него «находок нет» было бы
        # неотличимо от «подмена не состоялась».
        self.assertGreaterEqual(self.doc["counts"][lrs.VERDICT_BREAKS], 1,
                                "ни один тест не упал под подменой — реестр не подменён")

    def test_the_instrument_changes_nothing(self):
        self.assertFalse(self.doc["applied"])

    def test_the_report_names_the_finding_and_what_it_does_not_report(self):
        text = "\n".join(lrs.report(self.doc))
        self.assertIn("G95", self.doc["order"])
        self.assertIn("test_vacuous_walks_the_members", text)
        self.assertIn("НЕ ДОКЛАДЫВАЕТ", text)
        self.assertIn("ADVISORY", text)
        self.assertTrue(lrs.NOT_REPORTED)


class APopulationThatRecordsNothingIsUnmeasuredNotClean(unittest.TestCase):
    """`if not records` — не украшение: пустая запись есть третий исход."""

    def test_a_scene_whose_only_file_cannot_be_imported_is_unmeasured(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _build_scene(root, files={"test_broken.py": '''
                from scene_registry import PROBES
                this line is not python at all
            '''})
            with self.assertRaises(lrs.Unmeasured) as caught:
                lrs.measure(root, test_dirs=("tests",), module="scene_registry",
                            timeout=600)
        self.assertIn("не записал ни одного исхода", str(caught.exception))


class TheCliExitCodeSeparatesFindingsFromClean(unittest.TestCase):
    """Находка обязана быть видна КОДОМ ВОЗВРАТА, а не только в тексте."""

    def _run(self, root):
        return subprocess.run(
            [sys.executable, "-m", "spa_core.monitoring.live_registry_scene_census",
             "--root", str(root), "--timeout", "900",
             "--module", "scene_registry", "--test-dirs", "tests"],
            cwd=str(_REPO), capture_output=True, text=True, timeout=1800,
            env={**os.environ, "SPA_ENV": "ci"})

    def test_a_scene_with_a_finding_exits_one(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _build_scene(root, files={"test_vacuous.py": SCENE_FILES["test_vacuous.py"]})
            proc = self._run(root)
        self.assertEqual(proc.returncode, 1, proc.stdout + proc.stderr)
        self.assertIn("vacuous_over_members", proc.stdout)

    def test_a_scene_without_a_finding_exits_zero(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _build_scene(root, files={"test_loud.py": SCENE_FILES["test_loud.py"]})
            proc = self._run(root)
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)


class ThePluginSubstitutesBothCopiesAndRecordsTheFrame(unittest.TestCase):
    """Плагин — КОД, и мерить его надо как код, а не только сквозным прогоном.

    Половина инъекции — та же бомба (урок #453): подмена обязана дойти и до
    модульного атрибута, и до ПРЕЖНЕЙ ссылки, которую держит тот, кто сделал
    `from ... import PROBES` раньше. Сквозной прогон этого не различает, потому
    что в нём прежней ссылки ни у кого нет.
    """

    PLUGIN_FILENAME = "lrs_plugin.py"

    def _load(self, mode, registry_name):
        import types
        namespace = {"__file__": self.PLUGIN_FILENAME, "__name__": "lrs_plugin"}
        env = {"LRS_OUT": os.devnull, "LRS_MODE": mode, "LRS_MODULE": registry_name,
               "LRS_SYNTH_PROBE": lrs.SYNTHETIC_PROBE,
               "LRS_SYNTH_CRITERION": lrs.SYNTHETIC_CRITERION}
        previous_env = {k: os.environ.get(k) for k in env}
        os.environ.update(env)
        try:
            exec(compile(lrs._PLUGIN_SRC, self.PLUGIN_FILENAME, "exec"), namespace)
        finally:
            for key, value in previous_env.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value
        module = types.ModuleType(registry_name)

        def _probe(arg=None):
            return ("satisfied", "фикстура")

        module.PROBES = {"fixture_probe": _probe}
        sys.modules[registry_name] = module
        self.addCleanup(sys.modules.pop, registry_name, None)
        return namespace, module

    def test_the_module_attribute_is_rebound_to_a_recording_registry(self):
        plugin, module = self._load(lrs.MODE_RECORD, "lrs_fixture_registry_a")
        original = module.PROBES
        plugin["pytest_configure"](None)
        self.assertIsNot(module.PROBES, original)
        self.assertEqual(set(module.PROBES), {"fixture_probe"})

    def test_the_previous_reference_sees_the_same_content(self):
        plugin, module = self._load(lrs.MODE_EMPTY, "lrs_fixture_registry_b")
        stale = module.PROBES  # как у держателя `from ... import PROBES`
        plugin["pytest_configure"](None)
        self.assertEqual(dict(stale), {},
                         "прежняя ссылка не подменена — подмена ПОЛОВИННАЯ")

    def test_the_empty_mode_actually_empties_the_registry(self):
        plugin, module = self._load(lrs.MODE_EMPTY, "lrs_fixture_registry_c")
        plugin["pytest_configure"](None)
        self.assertEqual(dict(module.PROBES), {})

    def test_the_grown_mode_adds_a_probe_declaring_its_own_criterion(self):
        plugin, module = self._load(lrs.MODE_GROWN, "lrs_fixture_registry_d")
        plugin["pytest_configure"](None)
        self.assertIn(lrs.SYNTHETIC_PROBE, module.PROBES)
        self.assertEqual(
            getattr(module.PROBES[lrs.SYNTHETIC_PROBE], "s49_criterion"),
            lrs.SYNTHETIC_CRITERION)

    def test_a_read_from_this_test_frame_is_recorded_as_a_test_frame(self):
        plugin, module = self._load(lrs.MODE_RECORD, "lrs_fixture_registry_e")
        plugin["pytest_configure"](None)
        plugin["_state"]["nodeid"] = "tests/test_x.py::test_y"
        list(module.PROBES.items())
        self.assertIn("items@test", plugin["_per_test"]["tests/test_x.py::test_y"])

    def test_a_read_from_the_registrys_own_frame_is_recorded_as_the_registry(self):
        plugin, module = self._load(lrs.MODE_RECORD, "lrs_fixture_registry_f")
        plugin["pytest_configure"](None)
        plugin["_state"]["nodeid"] = "tests/test_x.py::test_y"
        helper = {}
        exec(compile("def read(registry):\n    return sorted(registry)\n",
                     "card_acceptance.py", "exec"), helper)
        helper["read"](module.PROBES)
        reads = plugin["_per_test"]["tests/test_x.py::test_y"]
        self.assertIn("iter@registry", reads)
        self.assertNotIn("iter@test", reads)

    def test_a_read_with_no_test_in_flight_is_attributed_to_the_collected_file(self):
        plugin, module = self._load(lrs.MODE_RECORD, "lrs_fixture_registry_g")
        plugin["pytest_configure"](None)
        plugin["_state"]["nodeid"] = None
        plugin["_state"]["collect"] = "tests/test_x.py"
        len(module.PROBES)
        self.assertIn("len@test", plugin["_per_file"]["tests/test_x.py"])


class TheCliKeepsUnmeasuredDistinctFromClean(unittest.TestCase):
    """Третий исход обязан иметь СВОЙ код возврата (инв. #17)."""

    def test_an_unreadable_tree_exits_two_and_says_nothing_is_known(self):
        import tempfile
        with tempfile.TemporaryDirectory() as empty:
            proc = subprocess.run(
                [sys.executable, "-m", "spa_core.monitoring.live_registry_scene_census",
                 "--root", empty],
                cwd=str(_REPO), capture_output=True, text=True, timeout=300,
                env={**os.environ, "SPA_ENV": "ci"})
        self.assertEqual(proc.returncode, 2, proc.stdout + proc.stderr)
        self.assertIn("НЕ ИЗМЕРЕНО", proc.stdout)
        self.assertIn("НЕ СКАЗАНО НИЧЕГО", proc.stdout)


class TheOrderIsNamedInTheArtifact(unittest.TestCase):
    """Замер без названного заказа нечем связать с приказом, который его просил."""

    def test_the_module_names_the_order_and_the_decision_that_posted_it(self):
        self.assertIn("G95", lrs.__doc__)
        self.assertIn("ADR-507", lrs.__doc__)


if __name__ == "__main__":
    unittest.main()
