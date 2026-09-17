"""Сторож прибора «двери часов, связанные на импорте» (заказ G31 п. 1, ADR-406).

Каждый тест ниже — положительный контроль на конкретное звено: он краснеет,
если звено порвать. Особо: «пин не наблюдён ⇒ НЕ ИЗМЕРЕНО» — это контроль на
fail-OPEN, который тише красной строки (нулевая разность плеч читалась бы как
«дверей нет», хотя мерить было нечем).

Часы здесь НЕ закрепляются литералом: там, где нужен момент, он берётся от
настоящих часов и передаётся внутрь, а сравнение идёт между ДВУМЯ вызовами —
то есть тест не зависит ни от календаря, ни от хоста.
"""
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


if __name__ == "__main__":                                        # pragma: no cover
    unittest.main()
