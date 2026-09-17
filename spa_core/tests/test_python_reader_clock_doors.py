"""Сторож прибора «двери часов, связанные на импорте» (заказ G31 п. 1, ADR-406).

Каждый тест ниже — положительный контроль на конкретное звено: он краснеет,
если звено порвать. Особо: «пин не наблюдён ⇒ НЕ ИЗМЕРЕНО» — это контроль на
fail-OPEN, который тише красной строки (нулевая разность плеч читалась бы как
«дверей нет», хотя мерить было нечем).

Часы здесь НЕ закрепляются литералом: там, где нужен момент, он берётся от
настоящих часов и передаётся внутрь, а сравнение идёт между ДВУМЯ вызовами —
то есть тест не зависит ни от календаря, ни от хоста.

FROZEN-DATE-OK: stand-data — все пять литеральных дат здесь суть СОДЕРЖИМОЕ
СТЕНДА, а не отметка свежести: имена дней книги, `generated_at` поддельного
артефакта переписи и значение, которое прибор обязан ЗАКРЕПИТЬ во втором плече.
Вердикт — РАЗНОСТЬ двух плеч, снятых в ОДИН момент; ни одно плечо с календарём
не сравнивается, и `census.get("generated_at")` прибор только переносит в
артефакт, а по возрасту не судит (проверено чтением обоих модулей). Сдвиг
календаря не может изменить здесь ни один вердикт — `import_time_anchor_bombs.py`
при задержке 95 мин бомб не нашёл.

Причина названа ИМЕННО эта, а не `injected-clock`, и это замер, а не вкус:
пометку `injected-clock` цикл #623 сперва поставил — и сторож
`test_injected_clock_claim.py` её ОПРОВЕРГ («якорей 7, ни один не передан
аргументом ни в один вызов»). Он прав: момент доезжает до прибора переменной
окружения, то есть через контейнер, а контейнер привязкой не является
(`.claude/rules/deployment.md`, поправка #477). Записка не есть инъекция —
поэтому стоит та причина, которая правда.

Файл попал в класс потому, что цикл #622 доставил его БЕЗ пометки вовсе, и
храповик замороженных дат стоял красным на чистом `origin/main`.
"""
# FROZEN-DATE-OK: stand-data — стенд, а не свежесть (см. шапку)
# LLM_FORBIDDEN
from __future__ import annotations

import datetime as dt
import json
import sys
import tempfile
import types
import unittest
from pathlib import Path

from spa_core.monitoring import _python_reader_clock_probe as probe
from spa_core.monitoring import python_reader_clock_doors as doors
from spa_core.monitoring.run_identity_key_price import _NEVER_CALL

_TREE_ROOT = Path(__file__).resolve().parents[2]


def _arm(modules: dict, *, pin_observed: bool,
         pin_requested: "bool | None" = None) -> dict:
    return {"__modules__": modules,
            "__clock__": {"pin_observed": pin_observed,
                          "pin_requested": (pin_requested if pin_requested is not None
                                            else pin_observed),
                          "moment": "2026-01-01T00:00:00+00:00"}}


class CompareNamesTheDoors(unittest.TestCase):
    """Разность плеч поимённая: счётчик одного размера бывает из разных множеств."""

    def test_coord_stable_only_under_pin_is_an_import_bound_door(self):
        rows = doors.compare(
            _arm({"m": {"entry": "run", "unstable": [".a", ".b"]}}, pin_observed=False),
            _arm({"m": {"entry": "run", "unstable": [".b"]}}, pin_observed=True))
        self.assertEqual(rows["m"]["outcome"], "measured")
        self.assertEqual(rows["m"]["import_bound"], [".a"])
        self.assertEqual(rows["m"]["other_door"], [".b"])
        self.assertEqual(rows["m"]["unstable_only_pinned"], [])

    def test_coord_unstable_in_both_arms_is_not_claimed_as_closed(self):
        rows = doors.compare(
            _arm({"m": {"unstable": [".t"]}}, pin_observed=False),
            _arm({"m": {"unstable": [".t"]}}, pin_observed=True))
        self.assertEqual(rows["m"]["import_bound"], [])
        self.assertEqual(rows["m"]["other_door"], [".t"])

    def test_other_door_is_the_intersection_not_the_union(self):
        """Батарея показала дыру: на равных множествах ∩ и ∪ неразличимы.

        Координата, плывущая ТОЛЬКО под пином, дверью «в обоих плечах» не
        является: сложи мера множества объединением — и она доложила бы как
        общую дверь то, чего в плече A не было вовсе.
        """
        rows = doors.compare(
            _arm({"m": {"unstable": [".t"]}}, pin_observed=False),
            _arm({"m": {"unstable": [".t", ".x"]}}, pin_observed=True))
        self.assertEqual(rows["m"]["other_door"], [".t"])
        self.assertEqual(rows["m"]["unstable_only_pinned"], [".x"])
        self.assertEqual(rows["m"]["import_bound"], [])

    def test_reverse_direction_is_named_not_dropped(self):
        """Координата, ставшая нестабильной ОТ ПИНА, — шум меры, и он назван."""
        rows = doors.compare(
            _arm({"m": {"unstable": []}}, pin_observed=False),
            _arm({"m": {"unstable": [".x"]}}, pin_observed=True))
        self.assertEqual(rows["m"]["unstable_only_pinned"], [".x"])
        self.assertEqual(rows["m"]["import_bound"], [])

    def test_reader_missing_from_one_arm_is_unmeasured_with_the_arm_named(self):
        rows = doors.compare(
            _arm({"m": {"cause": "import_failed", "reason": "импорт не удался: X"}},
                 pin_observed=False),
            _arm({"m": {"unstable": []}}, pin_observed=True))
        self.assertEqual(rows["m"]["outcome"], "unmeasured")
        self.assertEqual(rows["m"]["arm"], "A")
        self.assertEqual(rows["m"]["cause"], "import_failed")


class MeasureRefusesWhenTheArmsAreNotDistinguishable(unittest.TestCase):
    """Третий исход обязан быть различим (инв. #17), и он не «ноль дверей»."""

    def _measure_with(self, arm_a, arm_b, *, stand=("2026-09-01", "2026-08-31")):
        calls = []

        def fake_arm(names, stand_dir, tree_root, moment, *, pin):
            calls.append(pin)
            return (arm_b if pin else arm_a), ""

        with tempfile.TemporaryDirectory() as tmp:
            orig_arm, orig_stands, orig_pop = (
                doors.run_arm, doors.build_stands, doors.population)
            doors.run_arm = fake_arm
            doors.build_stands = lambda src, dest: (
                {"s1": Path(tmp) / "s1", "day": stand[0], "donor_day": stand[1]}, "")
            doors.population = lambda root: (["m"], {"python_branch": 1})
            try:
                return doors.measure(Path(tmp), _TREE_ROOT, full=True)
            finally:
                doors.run_arm, doors.build_stands, doors.population = (
                    orig_arm, orig_stands, orig_pop)

    def test_pin_not_observed_in_arm_b_is_unmeasured_not_zero_doors(self):
        doc = self._measure_with(
            _arm({"m": {"unstable": [".a"]}}, pin_observed=False),
            _arm({"m": {"unstable": [".a"]}}, pin_observed=False, pin_requested=True))
        self.assertEqual(doc["status"], "UNMEASURED")
        self.assertIn("пин класса часов НЕ НАБЛЮДЁН", doc["reason"])
        self.assertNotIn("counts", doc)

    def test_arm_a_already_pinned_is_unmeasured(self):
        doc = self._measure_with(
            _arm({"m": {"unstable": []}}, pin_observed=True, pin_requested=False),
            _arm({"m": {"unstable": []}}, pin_observed=True))
        self.assertEqual(doc["status"], "UNMEASURED")
        self.assertIn("плечи неразличимы", doc["reason"])

    def test_finding_when_a_door_is_closed_by_the_pin(self):
        doc = self._measure_with(
            _arm({"m": {"unstable": [".a"]}}, pin_observed=False),
            _arm({"m": {"unstable": []}}, pin_observed=True))
        self.assertEqual(doc["status"], "FINDING")
        self.assertEqual(doc["counts"]["rest_on_import_bound_door"], 1)
        self.assertEqual(doc["import_bound_doors"], {"m": [".a"]})

    def test_ok_when_no_door_closes(self):
        doc = self._measure_with(
            _arm({"m": {"unstable": []}}, pin_observed=False),
            _arm({"m": {"unstable": []}}, pin_observed=True))
        self.assertEqual(doc["status"], "OK")
        self.assertEqual(doc["counts"]["rest_on_import_bound_door"], 0)

    def test_stand_not_built_is_unmeasured_with_the_reason(self):
        orig = doors.build_stands
        doors.build_stands = lambda src, dest: (None, "в журнале меньше двух строк")
        try:
            with tempfile.TemporaryDirectory() as tmp:
                doc = doors.measure(Path(tmp), _TREE_ROOT, full=True)
        finally:
            doors.build_stands = orig
        self.assertEqual(doc["status"], "UNMEASURED")
        self.assertIn("стенд не построен", doc["reason"])

    def test_arm_failure_is_unmeasured_with_the_arm_named(self):
        orig_arm, orig_stands, orig_pop = (
            doors.run_arm, doors.build_stands, doors.population)
        doors.run_arm = lambda *a, **k: (None, "плечо вышло кодом 2: ОТКАЗ")
        doors.population = lambda root: (["m"], {})
        try:
            with tempfile.TemporaryDirectory() as tmp:
                doors.build_stands = lambda src, dest: (
                    {"s1": Path(tmp), "day": "d", "donor_day": "c"}, "")
                doc = doors.measure(Path(tmp), _TREE_ROOT, full=True)
        finally:
            doors.run_arm, doors.build_stands, doors.population = (
                orig_arm, orig_stands, orig_pop)
        self.assertEqual(doc["status"], "UNMEASURED")
        self.assertIn("плечо A", doc["reason"])


class ReportSaysWhatWasMeasured(unittest.TestCase):

    def test_unmeasured_report_never_reads_as_clean(self):
        lines = "\n".join(doors.report({"status": "UNMEASURED", "reason": "нечем"}))
        self.assertIn("[НЕ ИЗМЕРЕНО]", lines)
        self.assertNotIn("[ОТВЕТ]", lines)

    def test_absent_reverse_direction_is_stated_as_support(self):
        lines = "\n".join(doors.report(
            {"status": "OK", "counts": {"measured": 1, "python_branch": 1,
                                        "rest_on_import_bound_door": 0,
                                        "rest_on_other_door": 0, "unmeasured": 0},
             "import_bound_doors": {}, "other_doors": {}, "reverse_direction": {}}))
        self.assertIn("обратной стороны нет", lines)

    def test_present_reverse_direction_is_named(self):
        lines = "\n".join(doors.report(
            {"status": "FINDING", "counts": {"measured": 1, "python_branch": 1,
                                             "rest_on_import_bound_door": 1,
                                             "rest_on_other_door": 0, "unmeasured": 0},
             "import_bound_doors": {"m": [".a"]}, "other_doors": {},
             "reverse_direction": {"m": [".z"]}}))
        self.assertIn("ОБРАТНАЯ СТОРОНА", lines)
        self.assertIn("мера шумит", lines)


class ProbeRefusesWithoutItsPremises(unittest.TestCase):
    """Отказ громкий: без стенда зов пошёл бы против ЖИВОГО каталога."""

    def _run(self, env: dict) -> int:
        import os
        saved = {k: os.environ.get(k) for k in
                 (probe.STAND_ENV, probe.CLOCK_ENV, probe.PIN_CLASS_ENV)}
        try:
            for key, val in env.items():
                if val is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = val
            with tempfile.TemporaryDirectory() as tmp:
                mods = Path(tmp) / "m.json"
                mods.write_text("[]", encoding="utf-8")
                return probe.main([str(mods), str(Path(tmp) / "o.json")])
        finally:
            for key, val in saved.items():
                if val is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = val

    def test_no_stand_is_refusal(self):
        self.assertEqual(self._run({probe.STAND_ENV: None,
                                    probe.CLOCK_ENV: "2026-01-01T00:00:00+00:00"}), 2)

    def test_no_clock_is_refusal(self):
        self.assertEqual(self._run({probe.STAND_ENV: "/tmp", probe.CLOCK_ENV: None}), 2)

    def test_naive_clock_is_refusal(self):
        self.assertEqual(self._run({probe.STAND_ENV: "/tmp",
                                    probe.CLOCK_ENV: "2026-01-01T00:00:00",
                                    probe.PIN_CLASS_ENV: "0"}), 2)

    def test_wrong_argument_count_is_refusal(self):
        self.assertEqual(probe.main([]), 2)


class PinIsMeasuredAtTheDoorNotAssumed(unittest.TestCase):
    """Контроль на сам измеритель пина: без пина — False, с пином — True."""

    def test_clock_is_pinned_answers_both_ways(self):
        self.assertFalse(probe.clock_is_pinned())
        pin = probe._load_pin_clock()
        try:
            pin(dt.datetime.now(dt.timezone.utc).isoformat())
            self.assertTrue(probe.clock_is_pinned())
        finally:
            import importlib.util
            path = Path(probe.__file__).resolve().with_name("_http_reader_probe.py")
            spec = importlib.util.spec_from_file_location("_unpin_probe", path)
            mod = importlib.util.module_from_spec(spec)          # type: ignore[arg-type]
            spec.loader.exec_module(mod)                         # type: ignore[union-attr]
            mod.unpin_clock()
        self.assertFalse(probe.clock_is_pinned())


class SlowClockIsNotMistakenForAPinnedOne(unittest.TestCase):
    """Положительный контроль на НАЙДЕННЫЙ дефект: два соседних зова могут совпасть.

    Первая редакция спрашивала часы РОВНО ДВАЖДЫ, и на хосте, где два зова
    ложатся в одну микросекунду, настоящие часы читались как закреплённые —
    ложный пин, при котором разность плеч стала бы выдумкой. Тест держит
    исправление: часы, сдвигающиеся лишь на k-м зове, обязаны читаться как
    НЕЗАКРЕПЛЁННЫЕ, пока k меньше запаса.
    """

    def test_clock_that_ticks_late_reads_as_not_pinned(self):
        import datetime as _dt

        real = _dt.datetime
        base = real.now(_dt.timezone.utc)
        ticks_after = 5

        class _SlowDatetime(real):                       # type: ignore[misc,valid-type]
            calls = 0

            @classmethod
            def now(cls, tz=None):
                cls.calls += 1
                return base if cls.calls <= ticks_after else base + _dt.timedelta(
                    microseconds=1)

        _dt.datetime = _SlowDatetime
        try:
            self.assertLess(ticks_after, probe.CLOCK_TICK_ATTEMPTS)
            self.assertFalse(probe.clock_is_pinned())
        finally:
            _dt.datetime = real

    def test_clock_that_never_ticks_reads_as_pinned(self):
        import datetime as _dt

        real = _dt.datetime
        frozen = real.now(_dt.timezone.utc)

        class _FrozenDatetime(real):                     # type: ignore[misc,valid-type]
            @classmethod
            def now(cls, tz=None):
                return frozen

        _dt.datetime = _FrozenDatetime
        try:
            self.assertTrue(probe.clock_is_pinned())
        finally:
            _dt.datetime = real


class ProbeFindsTheImportBoundDoorOnARealReader(unittest.TestCase):
    """Сквозной контроль механизма: читатель, чьи часы связаны на импорте.

    Плечо A — класс настоящий, отметка бежит между двумя зовами. Плечо B — тот
    же читатель, но имя класса связано ПОСЛЕ пина, и отметка застывает. Если
    порвать любое звено (пин, пауза, сравнение), тест краснеет.
    """

    @staticmethod
    def _install_reader(name: str) -> None:
        import datetime as _dt
        bound = _dt.datetime                   # ← как `from datetime import datetime`
        mod = types.ModuleType(name)

        def measure(data_dir):
            return {"stamp": bound.now(_dt.timezone.utc).isoformat(), "fixed": 1}

        measure.__module__ = name
        mod.measure = measure                  # type: ignore[attr-defined]
        sys.modules[name] = mod

    def test_pin_closes_the_door_and_only_that_coordinate(self):
        name = "spa_test_fake_import_bound_reader"
        moment = dt.datetime.now(dt.timezone.utc)
        try:
            self._install_reader(name)
            with tempfile.TemporaryDirectory() as tmp:
                unpinned = probe.probe_modules([name], Path(tmp), moment, 0.01)
            self.assertEqual(unpinned[name]["unstable"], [".stamp"])

            pin = probe._load_pin_clock()
            pin(moment.isoformat())
            try:
                self._install_reader(name)     # «импортирован» уже при пине
                with tempfile.TemporaryDirectory() as tmp:
                    pinned = probe.probe_modules([name], Path(tmp), moment, 0.01)
            finally:
                import importlib.util
                path = Path(probe.__file__).resolve().with_name("_http_reader_probe.py")
                spec = importlib.util.spec_from_file_location("_unpin_probe2", path)
                mod = importlib.util.module_from_spec(spec)      # type: ignore[arg-type]
                spec.loader.exec_module(mod)                     # type: ignore[union-attr]
                mod.unpin_clock()
            self.assertEqual(pinned[name]["unstable"], [])

            rows = doors.compare(_arm(unpinned, pin_observed=False),
                                 _arm(pinned, pin_observed=True))
            self.assertEqual(rows[name]["import_bound"], [".stamp"])
        finally:
            sys.modules.pop(name, None)

    def test_reader_without_entry_point_is_a_named_cause_not_a_silent_zero(self):
        name = "spa_test_fake_reader_without_entry"
        sys.modules[name] = types.ModuleType(name)
        try:
            with tempfile.TemporaryDirectory() as tmp:
                out = probe.probe_modules([name], Path(tmp),
                                          dt.datetime.now(dt.timezone.utc), 0.0)
        finally:
            sys.modules.pop(name, None)
        self.assertNotIn("unstable", out[name])
        # Батарея показала дыру: без ветки «точки входа нет» зов всё равно падал
        # бы, и причина стала бы `entry_raised` — то есть прибор доложил бы
        # «вход упал» о читателе, у которого входа НЕТ. Причины разные, и это
        # различие и есть предмет проверки.
        self.assertNotEqual(out[name]["cause"], "entry_raised")
        self.assertEqual(out[name]["cause"], "no_entry_point")
        self.assertTrue(out[name]["reason"])


class PauseBetweenTheTwoCallsIsReal(unittest.TestCase):
    """Пауза — не украшение: без зазора бегущая координата может совпасть.

    Батарея показала, что её удаление не краснило ни одного теста: на этом
    хосте два соседних зова и так разошлись. Значит, покрытия у звена не было —
    ошибка ушла бы в сторону ЗАНИЖЕНИЯ находки (дверь прочлась бы стабильной).
    Проверяется исходом: прогон двух зовов не может быть короче заказанной паузы.
    """

    def test_probe_waits_the_delay_it_was_given(self):
        import time as _time

        name = "spa_test_fake_reader_for_pause"
        mod = types.ModuleType(name)

        def measure(data_dir):
            return {"fixed": 1}

        measure.__module__ = name
        mod.measure = measure                      # type: ignore[attr-defined]
        sys.modules[name] = mod
        delay = 0.4
        try:
            with tempfile.TemporaryDirectory() as tmp:
                started = _time.monotonic()
                probe.probe_modules([name], Path(tmp),
                                    dt.datetime.now(dt.timezone.utc), delay)
                elapsed = _time.monotonic() - started
        finally:
            sys.modules.pop(name, None)
        self.assertGreaterEqual(elapsed, delay)


class ArmBoundaryCarriesThePin(unittest.TestCase):
    """Отдельный процесс — и пин доезжает до него. Проверяется ИСХОДОМ у двери."""

    def test_pin_flag_reaches_the_subprocess_and_only_when_asked(self):
        moment = dt.datetime.now(dt.timezone.utc)
        with tempfile.TemporaryDirectory() as tmp:
            plain, why_a = doors.run_arm([], Path(tmp), _TREE_ROOT, moment, pin=False)
            pinned, why_b = doors.run_arm([], Path(tmp), _TREE_ROOT, moment, pin=True)
        self.assertIsNotNone(plain, why_a)
        self.assertIsNotNone(pinned, why_b)
        self.assertFalse(plain["__clock__"]["pin_observed"])      # type: ignore[index]
        self.assertTrue(pinned["__clock__"]["pin_observed"])      # type: ignore[index]


class NarrowingKeepsEveryCandidateAndRefusesWithoutItsInput(unittest.TestCase):
    """Сужение решает, КОГО спрашивать. Кандидата оно не теряет и нулём не молчит."""

    @staticmethod
    def _census(rows):
        return {"generated_at": "2026-09-17T00:00:00+00:00",
                "readers": {"modules": rows}}

    def test_only_readers_with_unstable_coords_are_kept(self):
        names, why = doors.narrowed_population(
            ["a", "b", "c"],
            self._census([{"module": "a", "unstable_coords": 2},
                          {"module": "b", "unstable_coords": 0},
                          {"module": "c"}]))
        self.assertEqual(names, ["a"])
        self.assertEqual(why["with_unstable_coords"], 1)

    def test_reader_outside_the_python_branch_is_not_smuggled_in(self):
        names, _ = doors.narrowed_population(
            ["a"], self._census([{"module": "a", "unstable_coords": 1},
                                 {"module": "http_one", "unstable_coords": 9}]))
        self.assertEqual(names, ["a"])

    def test_missing_census_is_unmeasured_not_an_empty_population(self):
        names, why = doors.narrowed_population(["a"], None)
        self.assertIsNone(names)
        self.assertIn("артефакта переписи нет", why["reason"])

    def test_census_without_rows_is_unmeasured(self):
        names, why = doors.narrowed_population(["a"], {"readers": {"modules": []}})
        self.assertIsNone(names)
        self.assertIn("нет строк", why["reason"])

    def test_measure_refuses_when_narrowing_has_no_input(self):
        orig_pop, orig_load = doors.population, doors._load_census
        doors.population = lambda root: (["a"], {})
        doors._load_census = lambda data_dir: None
        try:
            with tempfile.TemporaryDirectory() as tmp:
                doc = doors.measure(Path(tmp), _TREE_ROOT)
        finally:
            doors.population, doors._load_census = orig_pop, orig_load
        self.assertEqual(doc["status"], "UNMEASURED")
        self.assertIn("сужение не построено", doc["reason"])

    def test_full_mode_does_not_consult_the_census_at_all(self):
        seen = []
        orig_pop, orig_load, orig_stands = (
            doors.population, doors._load_census, doors.build_stands)
        doors.population = lambda root: (["a"], {})
        doors._load_census = lambda data_dir: seen.append(data_dir)
        doors.build_stands = lambda src, dest: (None, "стенда нет")
        try:
            with tempfile.TemporaryDirectory() as tmp:
                doc = doors.measure(Path(tmp), _TREE_ROOT, full=True)
        finally:
            doors.population, doors._load_census, doors.build_stands = (
                orig_pop, orig_load, orig_stands)
        self.assertEqual(seen, [])
        self.assertEqual(doc["population"]["mode"], "full_population")


class TheInstrumentIsNeverCalledByTheCensusItRuns(unittest.TestCase):
    """Часовой от рекурсии: перепись не смеет позвать прибор, гоняющий перепись."""

    def test_module_is_in_never_call_with_a_reason(self):
        self.assertIn("spa_core.monitoring.python_reader_clock_doors", _NEVER_CALL)
        self.assertIn("перепись",
                      _NEVER_CALL["spa_core.monitoring.python_reader_clock_doors"])

    def test_population_excludes_the_instrument_and_the_census(self):
        names, _ = doors.population(_TREE_ROOT)
        for own in doors._self_modules():
            self.assertNotIn(own, names)


class ExitCodesSeparateTheThreeOutcomes(unittest.TestCase):
    """0 · 1 · 2 — измерено-чисто, находка, не измерено. Инв. #17 на коде возврата."""

    def _main_with(self, doc: dict) -> int:
        orig = doors.measure
        doors.measure = lambda *a, **k: doc
        try:
            with tempfile.TemporaryDirectory() as tmp:
                return doors.main(["--data-dir", tmp, "--no-write"])
        finally:
            doors.measure = orig

    def test_ok_is_zero(self):
        self.assertEqual(self._main_with({"status": "OK", "counts": {}}), 0)

    def test_finding_is_one(self):
        self.assertEqual(self._main_with(
            {"status": "FINDING", "counts": {"rest_on_import_bound_door": 1},
             "import_bound_doors": {"m": [".a"]}}), 1)

    def test_unmeasured_is_two(self):
        self.assertEqual(self._main_with({"status": "UNMEASURED", "reason": "нечем"}), 2)

    def test_artifact_is_written_atomically_and_reads_back(self):
        doc = {"status": "OK", "counts": {}, "generated_at": "x"}
        orig = doors.measure
        doors.measure = lambda *a, **k: doc
        try:
            with tempfile.TemporaryDirectory() as tmp:
                dest = Path(tmp) / doors.ARTIFACT
                self.assertEqual(doors.main(["--data-dir", tmp]), 0)
                self.assertEqual(json.loads(dest.read_text(encoding="utf-8")), doc)
        finally:
            doors.measure = orig



class ReportTellsAbsenceFromZero(unittest.TestCase):
    """Инвариант #17 в ПЕЧАТИ: три исхода обязаны звучать по-разному (цикл #623).

    До правки в `report` стояли `doc.get("counts") or {}` и
    `doc.get("unmeasured_causes") or {}`, и храповик класса
    (`test_absent_observation_ratchet`) был КРАСЕН на чистом `origin/main` — оба
    места пришли с доставкой прибора циклом #622.

    Вред у двух мест разный, и тесты ниже ловят именно его:

    * у `counts` — отчёт печатал ГЛАВНУЮ строку ответа с `None` на месте каждого
      числа, то есть предъявлял находку, которой не измеряли;
    * у `unmeasured_causes` — «разбора причин нет» и «не приведённых читателей
      нет» молчали ОДИНАКОВО, и отсутствие разбора читалось как чистый результат.
      Это самый тихий вид fail-OPEN: он не краснеет и не шумит.
    """

    MEASURED = {
        "status": "OK",
        "counts": {"measured": 50, "python_branch": 87,
                   "rest_on_import_bound_door": 3, "rest_on_other_door": 2,
                   "unmeasured": 37},
        "import_bound_doors": {"shadow_trigger_eval": [".generated_at"]},
        "other_doors": {},
        "reverse_direction": {},
        "unmeasured_causes": {"нет точки входа": 13},
        "advisory": "прибор только читает",
    }

    @staticmethod
    def _text(doc):
        return "\n".join(doors.report(doc))

    def _without(self, key):
        doc = dict(self.MEASURED)
        doc.pop(key)
        return doc

    # ---- counts -----------------------------------------------------------

    def test_answer_line_is_printed_when_counts_were_measured(self):
        """Положительный контроль: на измеренном артефакте ответ звучит."""
        text = self._text(self.MEASURED)
        self.assertIn("[ОТВЕТ]", text)
        self.assertIn("из 50 приведённых", text)
        self.assertIn("**3**", text)

    def test_missing_counts_is_not_an_answer_full_of_none(self):
        text = self._text(self._without("counts"))
        self.assertIn("[НЕ ИЗМЕРЕНО]", text)
        self.assertNotIn("[ОТВЕТ]", text,
                         "строку ответа нельзя печатать, когда чисел ответа нет")

    def test_a_single_missing_counter_says_so_instead_of_printing_none(self):
        """Полумера тоже обязана называться: одна дыра в счётчиках — не ноль."""
        doc = dict(self.MEASURED)
        doc["counts"] = {k: v for k, v in doc["counts"].items() if k != "unmeasured"}
        text = self._text(doc)
        self.assertIn("[ОТВЕТ]", text)
        self.assertIn("не приведено НЕ ИЗМЕРЕНО", text)

    def test_a_measured_zero_is_still_a_number(self):
        """Обратная сторона: измеренный НОЛЬ обязан печататься нулём.

        Если бы правка отвечала «НЕ ИЗМЕРЕНО» и на ноль, она вылечила бы одну
        подмену, заведя обратную.
        """
        doc = dict(self.MEASURED)
        doc["counts"] = dict(doc["counts"], rest_on_import_bound_door=0)
        text = self._text(doc)
        self.assertIn("**0**", text)
        self.assertNotIn("**НЕ ИЗМЕРЕНО**", text)

    # ---- unmeasured_causes ------------------------------------------------

    def test_three_outcomes_of_the_causes_section_sound_different(self):
        """Сердцевина инварианта: ни два из трёх исходов не совпадают текстом."""
        named = self._text(self.MEASURED)
        empty = self._text(dict(self.MEASURED, unmeasured_causes={}))
        absent = self._text(self._without("unmeasured_causes"))

        self.assertIn("[НЕ ИЗМЕРЕНО поимённо]", named)
        self.assertIn("нет точки входа: 13", named)

        self.assertIn("[ОПОРА]", empty)
        self.assertIn("замер, а не пропажа", empty)
        self.assertNotIn("[НЕ ИЗМЕРЕНО поимённо]", empty)

        self.assertIn("разбора причин в артефакте нет", absent)
        self.assertNotIn("[ОПОРА] разбор причин", absent)

        self.assertEqual(3, len({named, empty, absent}),
                         "три исхода, звучащие одинаково, и есть та подмена, "
                         "которую инвариант #17 запрещает")

    def test_absent_breakdown_never_reads_as_a_clean_result(self):
        """Ровно то, что было: отсутствие разбора молчало как «всё чисто»."""
        absent = self._text(self._without("unmeasured_causes"))
        self.assertIn("НЕ ИЗМЕРЕНО", absent)

    # ---- общее ------------------------------------------------------------

    def test_no_none_ever_reaches_the_printed_report(self):
        """`None` в предложении отчёта читается как значение, а не как пробел."""
        for doc in (self.MEASURED,
                    self._without("counts"),
                    self._without("unmeasured_causes"),
                    dict(self.MEASURED, counts={}, unmeasured_causes={})):
            with self.subTest(doc=sorted(doc)):
                self.assertNotIn("None", self._text(doc))

    def test_unmeasured_artifact_still_refuses_early(self):
        """Правка не тронула прежний отказ целиком неизмеренного артефакта."""
        text = self._text({"status": "UNMEASURED", "reason": "стенда нет"})
        self.assertIn("[НЕ ИЗМЕРЕНО] стенда нет", text)
        self.assertNotIn("[ОТВЕТ]", text)


if __name__ == "__main__":                                        # pragma: no cover
    unittest.main()


# ─────────────────────────────────────────────────────────────────────────────
# Заказ G32, п. 1 — ЦЕНА закрытия двери
#
# ADR-406 сосчитал двери и на том остановился. Заказ велел сначала измерить,
# во что обходится закрытие КАЖДОЙ, и лишь потом выбирать. Цена измерима по
# исходу: пин задуман как средство снять ДРОЖЬ, и если от него меняется ВЕРДИКТ
# читателя, средство лечит не ту болезнь. Ниже — контроль на каждое звено
# этого замера, в обе стороны.
# ─────────────────────────────────────────────────────────────────────────────

def _row(unstable, stable):
    """Строка плеча: имена нестабильных координат + значения стабильных."""
    return {"entry": "measure", "clock_injected": True,
            "unstable": sorted(unstable),
            "stable": {c: {"digest": str(v), "preview": str(v)}
                       for c, v in stable.items()}}


def _measure_with_arms(arm_a, arm_a2, arm_b):
    """Боевой `measure()` с подменёнными ПЛЕЧАМИ — не копией его разбора.

    Копия разбора в тесте была бы вырожденным стендом: мутация боевой ветки
    («считать переписывающей ответ ЛЮБУЮ дверь») выжила в батарее #624 ровно
    потому, что тест судил собственный пересказ логики, а не её саму.
    """
    seq = [(arm_a, ""), (arm_a2, ""), (arm_b, "")]
    stands = {"day": "d", "donor_day": "d", "s1": Path("/x")}
    real_run, real_build = doors.run_arm, doors.build_stands
    doors.run_arm = lambda names, stand, root, moment, *, pin: seq.pop(0)
    doors.build_stands = lambda d, t: (stands, "")
    try:
        return doors.measure(Path("/x"), _TREE_ROOT,
                             now=dt.datetime.now(dt.timezone.utc), full=True)
    finally:
        doors.run_arm, doors.build_stands = real_run, real_build


class PriceOfClosingADoorIsMeasuredNotAssumed(unittest.TestCase):
    """Дверь, закрытие которой переписывает вердикт, — не «дверь подешевле».

    Каждый тест краснеет, если порвать своё звено: подсчёт разности значений,
    контрольное плечо, отделение шума процессов, третий исход «цена не измерена».
    """

    @staticmethod
    def _doc(a_stable, a2_stable, b_stable, *, a_unstable=(".stamp",),
             b_unstable=(), a2_unstable=(".stamp",), control=True):
        arm_a = _arm({"r": _row(a_unstable, a_stable)}, pin_observed=False)
        arm_b = _arm({"r": _row(b_unstable, b_stable)}, pin_observed=True)
        arm_a2 = (_arm({"r": _row(a2_unstable, a2_stable)}, pin_observed=False)
                  if control else None)
        return _measure_with_arms(arm_a, arm_a2, arm_b)

    def test_door_whose_pin_rewrites_a_verdict_is_not_free_to_close(self):
        # `.stamp` — дверь (плывёт без пина, застывает с пином).
        # `.verdict` стабилен в ОБОИХ плечах, но значение РАЗНОЕ: пин переписал
        # вывод читателя. Это ровно случай `decision_audit_trail`.
        doc = self._doc({".verdict": "false"}, {".verdict": "false"},
                        {".stamp": "frozen", ".verdict": "true"})
        row = doc["modules"]["r"]
        self.assertEqual(row["import_bound"], [".stamp"])
        self.assertEqual(row["answer_shift"]["outcome"], "measured")
        self.assertEqual(row["answer_shift"]["by_pin"], [".verdict"])
        self.assertIn("r", doc["doors_that_rewrite_the_answer"])
        self.assertNotIn("r", doc["doors_free_to_close"])
        self.assertEqual(doc["door_price_unmeasured"], {})
        self.assertEqual(doc["counts"]["doors_whose_closing_rewrites_the_answer"], 1)
        self.assertEqual(doc["counts"]["doors_free_to_close"], 0)

    def test_door_that_changes_nothing_else_is_free_to_close(self):
        # Обратная сторона: без неё проверка выше проходила бы и на приборе,
        # который объявляет дорогой КАЖДУЮ дверь (мутация, выжившая в первом
        # прогоне батареи #624 — тест судил копию разбора, а не сам разбор).
        doc = self._doc({".verdict": "false"}, {".verdict": "false"},
                        {".stamp": "frozen", ".verdict": "false"})
        self.assertEqual(doc["modules"]["r"]["answer_shift"]["by_pin"], [])
        self.assertEqual(doc["doors_free_to_close"], {"r": [".stamp"]})
        self.assertEqual(doc["doors_that_rewrite_the_answer"], {})
        self.assertEqual(doc["counts"]["doors_free_to_close"], 1)
        self.assertEqual(doc["counts"]["doors_whose_closing_rewrites_the_answer"], 0)

    def test_coordinate_that_differs_between_two_unpinned_arms_is_not_charged_to_the_pin(self):
        # `.pid` отличается уже между A и A′ — двумя процессами БЕЗ пина.
        # Приписать такую разницу пину значило бы выдумать находку.
        doc = self._doc({".pid": "111", ".verdict": "false"},
                        {".pid": "222", ".verdict": "false"},
                        {".stamp": "frozen", ".pid": "333", ".verdict": "false"})
        shift = doc["modules"]["r"]["answer_shift"]
        self.assertEqual(shift["by_pin"], [])
        # Шум НАЗВАН, а не выброшен молча: иначе разность выглядела бы прямым
        # замером, каким она не является.
        self.assertEqual(shift["process_varying"], [".pid"])
        self.assertEqual(doc["doors_free_to_close"], {"r": [".stamp"]})

    def test_the_control_only_forgives_the_coordinate_it_actually_saw_move(self):
        # Положительный контроль на сам контроль: шум по `.pid` не обязан
        # прощать сдвиг по `.verdict`. Иначе одно шумящее поле глушило бы
        # находку по всему читателю.
        doc = self._doc({".pid": "111", ".verdict": "false"},
                        {".pid": "222", ".verdict": "false"},
                        {".stamp": "frozen", ".pid": "333", ".verdict": "true"})
        self.assertEqual(doc["modules"]["r"]["answer_shift"]["by_pin"], [".verdict"])
        self.assertIn("r", doc["doors_that_rewrite_the_answer"])

    def test_missing_control_arm_makes_the_price_unmeasured_not_zero(self):
        # Без контроля «цена нулевая» было бы ДОГАДКОЙ. Инв. #17: третий исход.
        doc = self._doc({".verdict": "false"}, None,
                        {".stamp": "frozen", ".verdict": "true"}, control=False)
        shift = doc["modules"]["r"]["answer_shift"]
        self.assertEqual(shift["outcome"], "unmeasured")
        self.assertIn("A′", shift["reason"])
        self.assertEqual(doc["doors_free_to_close"], {})
        self.assertEqual(doc["doors_that_rewrite_the_answer"], {})
        self.assertIn("r", doc["door_price_unmeasured"])
        self.assertEqual(doc["counts"]["door_price_unmeasured"], 1)

    def test_arm_without_stable_values_names_the_arm(self):
        # Старый формат ответа плеча (до этого цикла) не имеет раздела значений.
        # Он обязан читаться как «нечем мерить», а не как «ничего не изменилось».
        arm_a = _arm({"r": {"entry": "measure", "unstable": [".stamp"]}},
                     pin_observed=False)
        arm_a2 = _arm({"r": _row([".stamp"], {})}, pin_observed=False)
        arm_b = _arm({"r": _row([], {".stamp": "frozen"})}, pin_observed=True)
        doc = _measure_with_arms(arm_a, arm_a2, arm_b)
        shift = doc["modules"]["r"]["answer_shift"]
        self.assertEqual(shift["outcome"], "unmeasured")
        self.assertIn("A", shift["reason"])
        self.assertEqual(doc["doors_free_to_close"], {})
        self.assertIn("r", doc["door_price_unmeasured"])


class ProbeHandsTheValuesThePriceIsMeasuredFrom(unittest.TestCase):
    """Проводка: без значений от ЗОНДА цена не измеряется ничем.

    Мутация «зонд не возвращает `stable`» выжила в первом прогоне батареи #624:
    все проверки цены кормились рукодельными плечами, и ни одна не спрашивала
    настоящий зонд. Тест закрывает именно этот стык.
    """

    def test_probe_returns_values_of_the_coordinates_that_did_not_move(self):
        name = "spa_test_fake_reader_with_stable_values"
        mod = types.ModuleType(name)
        import datetime as _dt
        bound = _dt.datetime

        def measure(data_dir):
            return {"stamp": bound.now(_dt.timezone.utc).isoformat(),
                    "verdict": False, "n": 7}

        measure.__module__ = name
        mod.measure = measure                  # type: ignore[attr-defined]
        sys.modules[name] = mod
        try:
            with tempfile.TemporaryDirectory() as tmp:
                out = probe.probe_modules([name], Path(tmp),
                                          dt.datetime.now(dt.timezone.utc), 0.01)
        finally:
            sys.modules.pop(name, None)
        row = out[name]
        self.assertEqual(row["unstable"], [".stamp"])
        stable = row["stable"]
        # Бегущая координата в значения НЕ попадает — иначе цена мерилась бы
        # по той самой дрожи, ради снятия которой пин и существует.
        self.assertNotIn(".stamp", stable)
        self.assertEqual(sorted(stable), [".n", ".verdict"])
        self.assertTrue(stable[".verdict"]["digest"])
        self.assertEqual(stable[".n"]["preview"], "7")


class ControlArmMustNotBePinnedItself(unittest.TestCase):
    """Закреплённое плечо A′ объявило бы шумом ровно то, что ищет прибор."""

    def _doc(self, a2_pin_observed):
        a = _row([".stamp"], {".verdict": "false"})
        b = _row([], {".stamp": "frozen", ".verdict": "true"})
        arm_a = _arm({"r": a}, pin_observed=False)
        arm_b = _arm({"r": b}, pin_observed=True)
        # A′ — точная копия A: единственное, чем B отличается, это пин.
        arm_a2 = _arm({"r": _row([".stamp"], {".verdict": "false"})},
                      pin_observed=a2_pin_observed)
        stands = {"day": "d", "donor_day": "d", "s1": Path("/x")}
        # Порядок зовов в measure(): A, A′, B. Плечи подменяются целиком —
        # предмет теста в РАЗБОРЕ их ответов, а не в запуске процессов.
        seq = [(arm_a, ""), (arm_a2, ""), (arm_b, "")]

        real_run, real_build = doors.run_arm, doors.build_stands
        doors.run_arm = lambda names, stand, root, moment, *, pin: seq.pop(0)
        doors.build_stands = lambda d, t: (stands, "")
        try:
            return doors.measure(Path("/x"), _TREE_ROOT,
                                 now=dt.datetime.now(dt.timezone.utc), full=True)
        finally:
            doors.run_arm, doors.build_stands = real_run, real_build

    def test_pinned_control_arm_is_refused_and_the_price_goes_unmeasured(self):
        doc = self._doc(True)
        self.assertEqual(doc["control_arm"]["outcome"], "unmeasured")
        self.assertIn("r", doc["door_price_unmeasured"])
        self.assertEqual(doc["doors_that_rewrite_the_answer"], {})

    def test_unpinned_control_arm_lets_the_price_be_measured(self):
        # Обратная сторона: иначе тест выше проходил бы и на приборе, который
        # отказывает ВСЕГДА.
        doc = self._doc(False)
        self.assertEqual(doc["control_arm"]["outcome"], "measured")
        self.assertEqual(doc["door_price_unmeasured"], {})
        self.assertIn("r", doc["doors_that_rewrite_the_answer"])


class ReportSeparatesAFreeDoorFromAFalsifyingOne(unittest.TestCase):
    """Отчёт обязан РАЗЛИЧАТЬ «закрыть даром» и «закрыть = подделать»."""

    @staticmethod
    def _base(**over):
        doc = {"status": "FINDING",
               "counts": {"measured": 1, "python_branch": 1, "unmeasured": 0,
                          "rest_on_import_bound_door": 1, "rest_on_other_door": 0},
               "import_bound_doors": {"r": [".stamp"]},
               "doors_free_to_close": {},
               "doors_that_rewrite_the_answer": {},
               "door_price_unmeasured": {},
               "other_doors": {}, "reverse_direction": {},
               "unmeasured_causes": {},
               "control_arm": {"outcome": "measured", "pin_observed": False},
               "advisory": "a"}
        doc.update(over)
        return doc

    def test_falsifying_door_is_named_with_the_coordinate_that_moved(self):
        text = "\n".join(doors.report(self._base(
            doors_that_rewrite_the_answer={"r": {
                "door": [".stamp"], "answer_changed_at": [".verdict"],
                "samples": {".verdict": {"unpinned": "false", "pinned": "true"}}}})))
        self.assertIn("ЗАКРЫТИЕ ПЕРЕПИШЕТ ОТВЕТ", text)
        self.assertIn(".verdict", text)
        self.assertIn("false", text)
        self.assertIn("true", text)

    def test_falsifying_door_without_previews_says_so_instead_of_showing_nothing(self):
        # Третий исход на превью: раздела значений НЕТ. Без этой ветки отчёт
        # назвал бы координату изменившейся и не показал ни одного значения —
        # читается как «изменение пустое», то есть находка гасится молчанием.
        text = "\n".join(doors.report(self._base(
            doors_that_rewrite_the_answer={"r": {"door": [".stamp"],
                                                 "answer_changed_at": [".verdict"]}})))
        self.assertIn("ЗАКРЫТИЕ ПЕРЕПИШЕТ ОТВЕТ", text)
        self.assertIn("НЕ ИЗМЕРЕНО", text)
        self.assertNotIn("None", text)

    def test_measured_but_empty_previews_sound_different_from_absent_ones(self):
        # Обратная сторона: пустой список — это ЗАМЕР, и звучать он обязан иначе.
        text = "\n".join(doors.report(self._base(
            doors_that_rewrite_the_answer={"r": {"door": [".stamp"],
                                                 "answer_changed_at": [".verdict"],
                                                 "samples": {}}})))
        self.assertIn("значений не приложено", text)
        self.assertNotIn("[НЕ ИЗМЕРЕНО] значений этих координат", text)

    def test_free_door_is_named_as_free(self):
        text = "\n".join(doors.report(self._base(
            doors_free_to_close={"r": [".stamp"]})))
        self.assertIn("ЗАКРЫТИЕ ДАРОМ", text)
        self.assertIn("ОПОРА", text)

    def test_absent_price_sections_never_read_as_a_free_door(self):
        # Инв. #17 на печати: раздела НЕТ ⇒ «не измерено», а не молчание,
        # которое читается как разрешение закрывать.
        doc = self._base()
        for key in ("doors_free_to_close", "doors_that_rewrite_the_answer",
                    "door_price_unmeasured"):
            doc.pop(key)
        text = "\n".join(doors.report(doc))
        self.assertIn("НЕ ИЗМЕРЕНО", text)
        self.assertIn("цены закрытия", text)
        self.assertNotIn("ЗАКРЫТИЕ ДАРОМ", text)

    def test_unpriced_door_is_named_not_swallowed(self):
        text = "\n".join(doors.report(self._base(
            door_price_unmeasured={"r": "контрольного плеча A′ нет"})))
        self.assertIn("ЦЕНА НЕ ИЗМЕРЕНА", text)
        self.assertNotIn("ОПОРА] ни у одной двери", text)

    def test_missing_control_arm_is_said_out_loud(self):
        text = "\n".join(doors.report(self._base(
            control_arm={"outcome": "unmeasured", "reason": "плечо A′: упало"})))
        self.assertIn("контрольное плечо A′", text)

    def test_no_none_reaches_the_printed_price_lines(self):
        text = "\n".join(doors.report(self._base(
            doors_that_rewrite_the_answer={"r": {"door": [".stamp"],
                                                 "answer_changed_at": [".v"]}},
            door_price_unmeasured={"q": "причина"})))
        self.assertNotIn("None", text)


class StableLeafDigestsCannotHideADifference(unittest.TestCase):
    """Сравнение идёт по ДАЙДЖЕСТУ: обрезка текста не вправе гасить находку."""

    def test_two_long_values_with_the_same_prefix_get_different_digests(self):
        from spa_core.monitoring.run_identity_key_price import stable_leaf_digests
        head = "x" * 300
        one = stable_leaf_digests({"v": head + "A"}, set())
        two = stable_leaf_digests({"v": head + "B"}, set())
        self.assertEqual(one[".v"]["preview"], two[".v"]["preview"])   # превью совпали
        self.assertNotEqual(one[".v"]["digest"], two[".v"]["digest"])  # находка цела

    def test_equal_values_get_equal_digests(self):
        from spa_core.monitoring.run_identity_key_price import stable_leaf_digests
        self.assertEqual(stable_leaf_digests({"v": [1, {"k": "z"}]}, set()),
                         stable_leaf_digests({"v": [1, {"k": "z"}]}, set()))

    def test_unstable_subtree_is_pruned_whole(self):
        from spa_core.monitoring.run_identity_key_price import stable_leaf_digests
        got = stable_leaf_digests({"a": {"b": 1, "c": 2}, "d": 3}, {".a"})
        self.assertEqual(sorted(got), [".d"])

    def test_coordinates_match_the_names_unstable_coords_produces(self):
        # Второго правила обхода здесь нет — имена обязаны совпадать с теми,
        # которыми судит сама перепись, иначе множества не пересекутся никогда
        # и цена молча оказалась бы нулевой у всех.
        from spa_core.monitoring.run_identity_key_price import (
            stable_leaf_digests, unstable_coords)
        one = {"a": [{"b": 1}], "s": "x"}
        two = {"a": [{"b": 2}], "s": "x"}
        unstable = unstable_coords(one, two)
        self.assertEqual(unstable, {".a[0].b"})
        self.assertEqual(sorted(stable_leaf_digests(one, unstable)), [".s"])


class SnapshotProbeInstabilityIsTheFindingNotTheNoise(unittest.TestCase):
    """Живой контроль замера цикла #624 на НАСТОЯЩЕМ читателе.

    `decision_audit_trail` зовёт `audit_trail._make_snapshot_id` ДВАЖДЫ нарочно
    и объявляет `content_addressed` по тому, СОВПАЛИ ли ответы. Пин класса часов
    делает их одинаковыми — и вердикт читателя переворачивается с «идентификатор
    именует ПРОГОН» на «именует содержимое». Дрожь тут не помеха замеру, она и
    есть замер; закрыть эту дверь значит подделать находку.
    """

    def test_pinning_the_clock_flips_content_addressed_on_the_real_producer(self):
        import importlib
        from spa_core.audit import audit_trail as at
        from spa_core.monitoring.decision_audit_trail import probe_snapshot_id

        day = "2026-01-01"          # FROZEN-DATE-OK: stand-data — вход производителя
        real = probe_snapshot_id(at._make_snapshot_id, day)
        self.assertTrue(real["measured"])
        self.assertFalse(real["content_addressed"])

        pin = probe._load_pin_clock()
        moment = dt.datetime.now(dt.timezone.utc)
        pin(moment.isoformat())
        try:
            importlib.reload(at)    # ← имя `datetime` связывается ПОСЛЕ пина
            pinned = probe_snapshot_id(at._make_snapshot_id, day)
        finally:
            import importlib.util
            path = Path(probe.__file__).resolve().with_name("_http_reader_probe.py")
            spec = importlib.util.spec_from_file_location("_unpin_c624", path)
            mod = importlib.util.module_from_spec(spec)          # type: ignore[arg-type]
            spec.loader.exec_module(mod)                         # type: ignore[union-attr]
            mod.unpin_clock()
            importlib.reload(at)    # вернуть настоящий класс читателю
        self.assertTrue(pinned["measured"])
        self.assertTrue(pinned["content_addressed"])
        # После снятия пина вердикт обязан вернуться — иначе тест доказывал бы
        # не действие пина, а порчу модуля на весь прогон.
        self.assertFalse(probe_snapshot_id(at._make_snapshot_id, day)["content_addressed"])
