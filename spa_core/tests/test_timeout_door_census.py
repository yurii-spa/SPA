"""Приёмка переписи дверей `--timeout` (заказ G108 п. 2, цикл #814).

У каждого звена здесь — обратная сторона с НАЗВАННЫМ звеном: порог читается у
записи (а не перепечатывается), исход `ok` выше порога отличается от провала,
`start` без исхода отличается от обоих, а отсутствие записи — от нуля.

Литеральных дат в файле нет вовсе: предмет прибора — ДЛИТЕЛЬНОСТИ, и все они
подаются входом. Литеральных номеров процесса тоже нет.
"""
from __future__ import annotations

import json
import signal
import sys
import time
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from spa_core.monitoring import timeout_door_census as tdc


def _stream(lines, *, args=("--timeout=180", "--timeout-method=signal")) -> str:
    rows = [{"e": "session", "args": list(args), "t": 0.0}]
    rows.extend(lines)
    return "\n".join(json.dumps(r) for r in rows) + "\n"


def _case(name, *, begin, end, outcome="ok"):
    return [{"e": "start", "n": name, "t": begin},
            {"e": outcome, "n": name, "t": end, "d": end - begin}]


class ThresholdIsReadAtTheRecord(unittest.TestCase):
    def test_threshold_and_method_come_from_the_recorded_command_line(self):
        value, method, why = tdc.read_threshold(
            ["-q", "--timeout=180", "--timeout-method=signal"])
        self.assertEqual((value, method, why), (180.0, "signal", ""))

    def test_a_record_without_the_flag_is_unmeasured_not_zero(self):
        value, _method, why = tdc.read_threshold(["-q", "--tb=short"])
        self.assertIsNone(value)
        self.assertIn("--timeout=", why)

    def test_an_unparsable_threshold_is_unmeasured_with_its_text(self):
        value, _method, why = tdc.read_threshold(["--timeout=позже"])
        self.assertIsNone(value)
        self.assertIn("позже", why)

    def test_the_method_survives_a_record_without_a_threshold(self):
        _value, method, _why = tdc.read_threshold(["--timeout-method=thread"])
        self.assertEqual(method, "thread")


class PopulationFromTheRecord(unittest.TestCase):
    def setUp(self):
        self._tmp = TemporaryDirectory(prefix="c814_pop_")
        self.root = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)

    def _write(self, text) -> Path:
        path = self.root / "stream.jsonl"
        path.write_text(text, encoding="utf-8")
        return path

    def test_a_passing_case_above_the_threshold_is_a_survivor(self):
        doc = tdc.population_from_stream(
            self._write(_stream(_case("t::a", begin=0.0, end=407.1))))
        self.assertTrue(doc["measured"])
        self.assertEqual(doc["counts"][tdc.CASE_SURVIVED], 1)
        self.assertEqual(doc["cases"][0]["wall_s"], 407.1)

    def test_a_failing_case_above_the_threshold_was_taken_by_the_threshold(self):
        doc = tdc.population_from_stream(
            self._write(_stream(_case("t::a", begin=0.0, end=182.0, outcome="fail"))))
        self.assertEqual(doc["counts"][tdc.CASE_TAKEN], 1)
        self.assertEqual(doc["counts"][tdc.CASE_SURVIVED], 0)

    def test_a_start_without_an_outcome_is_unterminated_and_has_no_wall(self):
        doc = tdc.population_from_stream(self._write(_stream(
            [{"e": "start", "n": "t::hung", "t": 10.0}])))
        row = doc["cases"][0]
        self.assertEqual(row["outcome"], tdc.CASE_UNTERMINATED)
        self.assertIsNone(row["wall_s"])

    def test_a_case_below_the_threshold_is_not_in_the_population(self):
        doc = tdc.population_from_stream(
            self._write(_stream(_case("t::a", begin=0.0, end=1.0))))
        self.assertEqual(doc["cases_total"], 0)
        self.assertEqual(doc["cases_closed"], 1)

    def test_a_case_exactly_on_the_threshold_is_in_the_population(self):
        doc = tdc.population_from_stream(
            self._write(_stream(_case("t::a", begin=0.0, end=180.0))))
        self.assertEqual(doc["cases_total"], 1)

    def test_the_outcome_perimeter_sums_to_the_population(self):
        doc = tdc.population_from_stream(self._write(_stream(
            _case("t::a", begin=0.0, end=407.0)
            + _case("t::b", begin=0.0, end=190.0, outcome="fail")
            + [{"e": "start", "n": "t::c", "t": 0.0}])))
        self.assertEqual(sum(doc["counts"].values()), doc["cases_total"])
        self.assertEqual(doc["cases_total"], 3)

    def test_subtest_outcomes_are_counted_apart_from_unparsed_lines(self):
        doc = tdc.population_from_stream(self._write(_stream(
            _case("t::a", begin=0.0, end=200.0)
            + [{"e": "ok", "n": "t::a", "t": 200.5, "d": 0.0}])))
        self.assertEqual(doc["extra_outcome_lines"], 1)
        self.assertEqual(doc["unparsed_lines"], 0)

    def test_a_garbage_line_is_unparsed_and_does_not_become_a_case(self):
        path = self._write(_stream(_case("t::a", begin=0.0, end=200.0)))
        path.write_text(path.read_text(encoding="utf-8") + "{не json\n",
                        encoding="utf-8")
        doc = tdc.population_from_stream(path)
        self.assertEqual(doc["unparsed_lines"], 1)
        self.assertEqual(doc["cases_closed"], 1)

    def test_an_absent_record_is_unmeasured_with_its_reason(self):
        doc = tdc.population_from_stream(self.root / "нет-такой-записи.jsonl")
        self.assertFalse(doc["measured"])
        self.assertIn("не прочитана", doc["reason"])

    def test_a_record_without_a_session_line_is_unmeasured_not_empty(self):
        text = "\n".join(json.dumps(r) for r in _case("t::a", begin=0.0, end=400.0))
        doc = tdc.population_from_stream(self._write(text + "\n"))
        self.assertFalse(doc["measured"])
        self.assertIn("session", doc["reason"])

    def test_a_record_whose_session_declares_no_threshold_is_unmeasured(self):
        doc = tdc.population_from_stream(self._write(_stream(
            _case("t::a", begin=0.0, end=400.0), args=("-q",))))
        self.assertFalse(doc["measured"])
        self.assertIn("--timeout=", doc["reason"])

    def test_zero_survivors_is_measured_and_says_so(self):
        doc = tdc.population_from_stream(self._write(_stream(
            _case("t::a", begin=0.0, end=182.0, outcome="fail"))))
        self.assertTrue(doc["measured"])
        self.assertIn("равно нулю", tdc.format_population(doc))

    def test_an_unmeasured_population_prints_not_measured_with_its_reason(self):
        line = tdc.format_population({"measured": False, "reason": "нет записи"})
        self.assertIn("НЕ ИЗМЕРЕНО", line)
        self.assertIn("нет записи", line)

    def test_an_unterminated_case_prints_an_unbounded_wall_not_a_number(self):
        doc = tdc.population_from_stream(self._write(_stream(
            [{"e": "start", "n": "t::hung", "t": 0.0}])))
        self.assertIn("не ограничена", tdc.format_population(doc))


class DoorSitesAreNamedAtTheCall(unittest.TestCase):
    def _doors(self, src):
        sites, why = tdc.door_sites_in_source(src, where="сцена.py")
        self.assertEqual(why, "")
        return sites

    def test_a_cancelled_alarm_is_the_cancelled_door_with_its_line_and_text(self):
        sites = self._doors("import signal\nsignal.alarm(0)\n")
        self.assertEqual(len(sites), 1)
        self.assertEqual(sites[0]["door"], tdc.DOOR_ALARM_CANCELLED)
        self.assertEqual(sites[0]["line"], 2)
        self.assertEqual(sites[0]["call"], "signal.alarm(0)")

    def test_a_nonzero_alarm_replaces_the_deadline_and_is_its_own_class(self):
        sites = self._doors("import signal\nsignal.alarm(30)\n")
        self.assertEqual(sites[0]["door"], tdc.DOOR_ALARM_REPLACED)

    def test_a_cancelled_real_itimer_is_the_cancelled_door(self):
        sites = self._doors("import signal\nsignal.setitimer(signal.ITIMER_REAL, 0)\n")
        self.assertEqual(sites[0]["door"], tdc.DOOR_ALARM_CANCELLED)

    def test_a_virtual_itimer_carries_no_deadline_and_is_not_a_door(self):
        self.assertEqual(
            self._doors("import signal\nsignal.setitimer(signal.ITIMER_VIRTUAL, 0)\n"),
            [])

    def test_replacing_the_sigalrm_handler_is_a_door(self):
        sites = self._doors("import signal\nsignal.signal(signal.SIGALRM, None)\n")
        self.assertEqual(sites[0]["door"], tdc.DOOR_HANDLER_REPLACED)

    def test_replacing_another_signals_handler_is_not_a_door(self):
        self.assertEqual(
            self._doors("import signal\nsignal.signal(signal.SIGTERM, None)\n"), [])

    def test_a_base_exception_handler_without_raise_swallows_the_verdict(self):
        sites = self._doors("try:\n    pass\nexcept BaseException:\n    pass\n")
        self.assertEqual(sites[0]["door"], tdc.DOOR_VERDICT_SWALLOWED)

    def test_a_base_exception_handler_that_reraises_is_not_a_door(self):
        self.assertEqual(
            self._doors("try:\n    pass\nexcept BaseException:\n    raise\n"), [])

    def test_catching_exception_only_is_not_a_door(self):
        """`Failed` pytest-timeout наследует `BaseException`: `except Exception`
        его не ловит, и считать такой обработчик дверью значило бы выдумать её."""
        self.assertEqual(
            self._doors("try:\n    pass\nexcept Exception:\n    pass\n"), [])

    def test_a_bare_except_without_raise_swallows_the_verdict(self):
        sites = self._doors("try:\n    pass\nexcept:\n    pass\n")
        self.assertEqual(sites[0]["door"], tdc.DOOR_VERDICT_SWALLOWED)

    def test_base_exception_inside_a_tuple_is_still_the_swallowing_door(self):
        sites = self._doors(
            "try:\n    pass\nexcept (ValueError, BaseException):\n    pass\n")
        self.assertEqual(sites[0]["door"], tdc.DOOR_VERDICT_SWALLOWED)

    def test_a_non_literal_alarm_argument_is_the_third_outcome_not_a_guess(self):
        sites = self._doors("import signal\nsignal.alarm(сколько)\n")
        self.assertEqual(sites[0]["door"], tdc.DOOR_ARG_UNPARSED)
        self.assertIn("не литерал", sites[0]["note"])

    def test_a_directly_imported_alarm_is_still_the_door(self):
        sites = self._doors("from signal import alarm\nalarm(0)\n")
        self.assertEqual(sites[0]["door"], tdc.DOOR_ALARM_CANCELLED)

    def test_an_unparsable_source_is_a_named_reason_and_no_sites(self):
        sites, why = tdc.door_sites_in_source("def (\n", where="сцена.py")
        self.assertEqual(sites, [])
        self.assertIn("Error", why)

    def test_the_call_text_is_cut_by_the_node_not_by_byte_offsets(self):
        """Урок ADR-650: `col_offset` узла — БАЙТЫ. Кириллица в строке ВЫШЕ и В
        ТОЙ ЖЕ строке сдвинула бы ручную резку — здесь текст обязан совпасть."""
        src = ('# длинный кириллический комментарий перед вызовом\n'
               'import signal\n'
               'ответ = signal.alarm(0)  # гасим срок\n')
        sites = self._doors(src)
        self.assertEqual(sites[0]["call"], "signal.alarm(0)")

    def test_the_perimeter_of_classes_is_closed_and_named(self):
        self.assertEqual(len(set(tdc.DOOR_CLASSES)), len(tdc.DOOR_CLASSES))
        self.assertIn(tdc.DOOR_ARG_UNPARSED, tdc.DOOR_CLASSES)


class DoorSitesOverATree(unittest.TestCase):
    def setUp(self):
        self._tmp = TemporaryDirectory(prefix="c814_tree_")
        self.root = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)
        (self.root / "spa_core").mkdir()

    def test_a_tree_without_python_files_is_unmeasured_not_clean(self):
        doc = tdc.door_sites(self.root, subdirs=("нет_такого_каталога",))
        self.assertFalse(doc["measured"])
        self.assertIn("ни одного файла", doc["reason"])

    def test_a_door_in_the_tree_is_counted_with_its_relative_path(self):
        (self.root / "spa_core" / "m.py").write_text("import signal\nsignal.alarm(0)\n",
                                                     encoding="utf-8")
        doc = tdc.door_sites(self.root, subdirs=("spa_core",))
        self.assertTrue(doc["measured"])
        self.assertEqual(doc["counts"][tdc.DOOR_ALARM_CANCELLED], 1)
        self.assertEqual(doc["sites"][0]["file"], "spa_core/m.py")

    def test_a_tree_with_no_door_is_measured_and_equals_zero(self):
        (self.root / "spa_core" / "m.py").write_text("x = 1\n", encoding="utf-8")
        doc = tdc.door_sites(self.root, subdirs=("spa_core",))
        self.assertTrue(doc["measured"])
        self.assertEqual(doc["sites_total"], 0)
        self.assertIn("равно нулю", tdc.format_sites(doc))

    def test_an_unparsable_file_is_named_and_does_not_zero_the_rest(self):
        (self.root / "spa_core" / "ok.py").write_text("import signal\nsignal.alarm(0)\n",
                                                      encoding="utf-8")
        (self.root / "spa_core" / "bad.py").write_text("def (\n", encoding="utf-8")
        doc = tdc.door_sites(self.root, subdirs=("spa_core",))
        self.assertEqual(doc["counts"][tdc.DOOR_ALARM_CANCELLED], 1)
        self.assertEqual(len(doc["files_unparsed"]), 1)
        self.assertIn("НЕ РАЗОБРАНО", tdc.format_sites(doc))

    def test_the_instrument_does_not_become_its_own_finding(self):
        """Прибор живёт в населении, которое мерит (урок ADR-620), и молчаливого
        исключения для себя у него НЕТ: его отсутствие в находках — ЗАМЕР. Этот
        тест и есть то место, где появление двери в самом приборе становится
        решением вслух, а не умолчанием."""
        tree = Path(tdc.__file__).resolve().parents[2]
        doc = tdc.door_sites(tree, subdirs=("spa_core/monitoring",))
        mine = "spa_core/monitoring/timeout_door_census.py"
        self.assertTrue(doc["measured"])
        self.assertTrue(any(s["file"].endswith("_artifact_stamp_clock_probe.py")
                            for s in doc["sites"]),
                        "сосед с настоящей дверью обязан найтись — иначе зелень "
                        "этого теста не отличима от слепоты обхода")
        self.assertEqual([s for s in doc["sites"] if s["file"] == mine], [])

    def test_an_unmeasured_tree_prints_not_measured_with_its_reason(self):
        line = tdc.format_sites({"measured": False, "reason": "каталога нет"})
        self.assertIn("НЕ ИЗМЕРЕНЫ", line)
        self.assertIn("каталога нет", line)


def _junit(cases) -> str:
    rows = []
    for name, kind, seconds in cases:
        inner = "" if kind == "ok" else f"<{kind} message='m'/>"
        rows.append(f"<testcase name='{name}' time='{seconds}'>{inner}</testcase>")
    return "<testsuites><testsuite>" + "".join(rows) + "</testsuite></testsuites>"


class TheLiveBattery(unittest.TestCase):
    """Батарея — замер, а не утверждение: прогон дочернего pytest подаётся ВХОДОМ."""

    def setUp(self):
        self._tmp = TemporaryDirectory(prefix="c814_bat_")
        self.root = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)
        self.argv_seen = []

    def _runner(self, cases):
        def run(argv, workdir):
            self.argv_seen.append(list(argv))
            (Path(workdir) / "junit-battery.xml").write_text(_junit(cases),
                                                             encoding="utf-8")
            return 0
        return run

    def test_the_scene_declares_one_case_per_door_and_carries_the_input(self):
        src = tdc.battery_source(over_s=42.5)
        for _door, name, _body in tdc.BATTERY:
            self.assertIn(f"def test_{name}():", src)
        self.assertIn("OVER = 42.5", src)

    def test_a_long_green_case_means_the_door_defeated_the_deadline(self):
        doc = tdc.live_door_verdicts(
            deadline_s=2.0, over_s=6.0, workdir=self.root,
            cases=((tdc.DOOR_ALARM_CANCELLED, "x", "pass"),),
            run=self._runner([("test_x", "ok", 6.1)]))
        self.assertEqual(doc["rows"][0]["verdict"], tdc.LIVE_DEFEATED)

    def test_a_failed_case_means_the_deadline_took_it(self):
        doc = tdc.live_door_verdicts(
            deadline_s=2.0, over_s=6.0, workdir=self.root,
            cases=((tdc.DOOR_ALARM_CANCELLED, "x", "pass"),),
            run=self._runner([("test_x", "failure", 2.1)]))
        self.assertEqual(doc["rows"][0]["verdict"], tdc.LIVE_TAKEN)

    def test_a_case_absent_from_the_record_is_unmeasured_with_its_reason(self):
        doc = tdc.live_door_verdicts(
            deadline_s=2.0, over_s=6.0, workdir=self.root,
            cases=((tdc.DOOR_ALARM_CANCELLED, "x", "pass"),),
            run=self._runner([("test_другое", "ok", 6.1)]))
        self.assertEqual(doc["rows"][0]["verdict"], tdc.LIVE_UNMEASURED)
        self.assertIn("нет в junit", doc["rows"][0]["reason"])

    def test_a_short_green_case_is_unmeasured_not_taken(self):
        """Сцена не дошла до двери — о двери она не говорит ничего, и выдать это
        за «порог сработал» значило бы придумать замер."""
        doc = tdc.live_door_verdicts(
            deadline_s=2.0, over_s=6.0, workdir=self.root,
            cases=((tdc.DOOR_ALARM_CANCELLED, "x", "pass"),),
            run=self._runner([("test_x", "ok", 0.2)]))
        self.assertEqual(doc["rows"][0]["verdict"], tdc.LIVE_UNMEASURED)
        self.assertIn("уложился", doc["rows"][0]["reason"])

    def test_a_skipped_case_is_unmeasured_not_a_pass(self):
        doc = tdc.live_door_verdicts(
            deadline_s=2.0, over_s=6.0, workdir=self.root,
            cases=((tdc.DOOR_ALARM_CANCELLED, "x", "pass"),),
            run=self._runner([("test_x", "skipped", 0.0)]))
        self.assertEqual(doc["rows"][0]["verdict"], tdc.LIVE_UNMEASURED)
        self.assertIn("пропущен", doc["rows"][0]["reason"])

    def test_a_run_leaving_no_record_is_unmeasured_with_its_reason(self):
        doc = tdc.live_door_verdicts(
            deadline_s=2.0, over_s=6.0, workdir=self.root,
            cases=((tdc.DOOR_ALARM_CANCELLED, "x", "pass"),),
            run=lambda argv, workdir: 0)
        self.assertFalse(doc["measured"])
        self.assertIn("junit", doc["reason"])

    def test_an_empty_record_is_unmeasured_not_zero_doors(self):
        def run(argv, workdir):
            (Path(workdir) / "junit-battery.xml").write_text(
                "<testsuites><testsuite></testsuite></testsuites>", encoding="utf-8")
            return 0
        doc = tdc.live_door_verdicts(
            deadline_s=2.0, over_s=6.0, workdir=self.root,
            cases=((tdc.DOOR_ALARM_CANCELLED, "x", "pass"),), run=run)
        self.assertFalse(doc["measured"])
        self.assertIn("ни одного случая", doc["reason"])

    def test_the_child_run_asks_about_the_same_mechanism(self):
        """Батарея обязана спрашивать про ТОТ ЖЕ механизм, иначе её вердикт — про
        другой вопрос: метод и порог уходят в дочерний прогон аргументами."""
        tdc.live_door_verdicts(
            deadline_s=7.0, over_s=1.0, workdir=self.root,
            cases=((tdc.DOOR_ALARM_CANCELLED, "x", "pass"),),
            run=self._runner([("test_x", "ok", 7.5)]))
        argv = self.argv_seen[0]
        self.assertIn("--timeout-method=signal", argv)
        self.assertIn("--timeout=7.0", argv)

    def test_the_verdict_perimeter_sums_to_the_rows(self):
        doc = tdc.live_door_verdicts(
            deadline_s=2.0, over_s=6.0, workdir=self.root,
            cases=((tdc.DOOR_ALARM_CANCELLED, "a", "pass"),
                   (tdc.DOOR_VERDICT_SWALLOWED, "b", "pass")),
            run=self._runner([("test_a", "ok", 6.1), ("test_b", "failure", 2.0)]))
        self.assertEqual(sum(doc["counts"].values()), len(doc["rows"]))

    def test_the_battery_keeps_controls_that_must_be_taken(self):
        """Половина сцены — КОНТРОЛИ. Без них «дверь гасит срок» стои́т без второй
        стороны, и батарея, где всё `defeated`, означала бы сломанный механизм."""
        doors = {door for door, _name, _body in tdc.BATTERY}
        self.assertTrue(any(d.startswith("control_") for d in doors))
        self.assertTrue(any(d in tdc.DOOR_CLASSES for d in doors))

    def test_an_unmeasured_battery_prints_not_measured_with_its_reason(self):
        line = tdc.format_live({"measured": False, "reason": "pytest не найден"})
        self.assertIn("НЕ ИЗМЕРЕНА", line)
        self.assertIn("pytest не найден", line)


class TheLiveDoorWatch(unittest.TestCase):
    def test_a_passage_is_named_at_the_caller_frame_not_at_the_watch(self):
        with tdc.watch_doors() as watch:
            signal.alarm(0)
        row = watch.passages[-1]
        self.assertEqual(row["door"], tdc.DOOR_ALARM_CANCELLED)
        self.assertEqual(Path(row["file"]).name, Path(__file__).name)
        self.assertEqual(row["function"],
                         "test_a_passage_is_named_at_the_caller_frame_not_at_the_watch")

    def test_the_watch_does_not_change_behaviour_the_real_call_happens(self):
        """Сторож ТОЛЬКО называет. Положительный контроль самой проводки: срок,
        поставленный под сторожем, обязан сработать по-настоящему."""
        fired = []
        previous = signal.signal(signal.SIGALRM, lambda *_: fired.append(True))
        try:
            with tdc.watch_doors():
                signal.setitimer(signal.ITIMER_REAL, 0.05)
            time.sleep(0.4)
        finally:
            signal.setitimer(signal.ITIMER_REAL, 0)
            signal.signal(signal.SIGALRM, previous)
        self.assertEqual(fired, [True])

    def test_removing_the_watch_restores_the_original_functions(self):
        original = signal.alarm
        watch = tdc.watch_doors().install()
        self.assertIsNot(signal.alarm, original)
        watch.remove()
        self.assertIs(signal.alarm, original)

    def test_a_nonzero_alarm_is_the_replacing_door_not_the_cancelling_one(self):
        with tdc.watch_doors() as watch:
            signal.alarm(0)            # ставим и сразу снимаем — срок никому не нужен
            signal.alarm(0)
        self.assertTrue(all(p["door"] == tdc.DOOR_ALARM_CANCELLED
                            for p in watch.passages))
        with tdc.watch_doors() as watch2:
            signal.setitimer(signal.ITIMER_REAL, 30.0)
            signal.setitimer(signal.ITIMER_REAL, 0)
        self.assertEqual([p["door"] for p in watch2.passages],
                         [tdc.DOOR_ALARM_REPLACED, tdc.DOOR_ALARM_CANCELLED])

    def test_a_handler_replacement_is_recorded_as_its_own_door(self):
        previous = signal.getsignal(signal.SIGALRM)
        with tdc.watch_doors() as watch:
            signal.signal(signal.SIGALRM, previous)
        self.assertEqual(watch.passages[-1]["door"], tdc.DOOR_HANDLER_REPLACED)

    def test_the_report_perimeter_sums_to_the_passages(self):
        with tdc.watch_doors() as watch:
            signal.alarm(0)
            signal.setitimer(signal.ITIMER_REAL, 0)
        report = watch.report()
        self.assertEqual(sum(report["counts"].values()), report["passages_total"])

    def test_cancelling_the_deadline_really_defeats_it(self):
        """Та самая ДВЕРЬ, измеренная без pytest вовсе: срок поставлен, `alarm(0)`
        его гасит, и обработчик не зовётся НИ РАЗУ. Обратная сторона — соседний
        тест выше, где тот же срок срабатывает."""
        fired = []
        previous = signal.signal(signal.SIGALRM, lambda *_: fired.append(True))
        try:
            signal.setitimer(signal.ITIMER_REAL, 0.05)
            signal.alarm(0)
            time.sleep(0.4)
        finally:
            signal.setitimer(signal.ITIMER_REAL, 0)
            signal.signal(signal.SIGALRM, previous)
        self.assertEqual(fired, [])


class TheRuleOfForeignFailure(unittest.TestCase):
    """Перечень ЧУЖОГО отказа — вход, и у него обе стороны."""

    def test_an_ordinary_exception_is_the_modules_own_failure(self):
        self.assertTrue(tdc.is_foreign_failure(ValueError("модуль упал")))

    def test_a_system_exit_is_foreign_because_a_cli_module_may_call_it(self):
        self.assertTrue(tdc.is_foreign_failure(SystemExit(2)))

    def test_a_keyboard_interrupt_is_not_the_modules_failure(self):
        self.assertFalse(tdc.is_foreign_failure(KeyboardInterrupt()))

    def test_the_shape_of_the_deadline_verdict_is_not_foreign(self):
        """`Failed` pytest-timeout наследует `BaseException` напрямую — ровно эту
        форму обходчик обязан пропустить наружу."""
        class Failed(BaseException):
            pass
        self.assertFalse(tdc.is_foreign_failure(Failed()))


class TheWalkerReRaisesTheDeadlineButSwallowsForeignFailures(unittest.TestCase):
    """Замер двери `run_identity_key_price` — ОБЕ стороны, у вызова (ADR-676).

    До правки `except BaseException` обходчика не отличал «модуль упал» от
    «мой срок истёк»: замер на живом дереве дал 25 проглоченных сроков за один
    вызов `http_modules`, и случай после этого жил без срока вовсе.
    """

    def setUp(self):
        from spa_core.monitoring import run_identity_key_price as g16
        self.g16 = g16
        self._tmp = TemporaryDirectory(prefix="c814_walk_")
        self.root = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)
        self.pkg = self.root / "stubs"
        self.pkg.mkdir()
        sys.path.insert(0, str(self.pkg))
        self.addCleanup(lambda: sys.path.remove(str(self.pkg)))
        self.addCleanup(self._forget_stubs)
        self.stands = {}
        for label in ("s1", "s2", "s3"):
            data = self.root / label / "data"
            data.mkdir(parents=True)
            (data / "h.jsonl").write_text(
                json.dumps({"cycle_date": "д", "verdict": "HOLD"}) + "\n",
                encoding="utf-8")
            self.stands[label] = self.root / label

    def _forget_stubs(self):
        for name in list(sys.modules):
            if name.startswith("c814stub_"):
                del sys.modules[name]

    def _stub(self, name, src):
        (self.pkg / f"c814stub_{name}.py").write_text(src, encoding="utf-8")
        return f"c814stub_{name}"

    def test_a_module_whose_entry_point_raises_an_exception_is_still_unmeasured(self):
        name = self._stub("angry", "def measure(data_dir, write=False):\n"
                                   "    raise ValueError('я сломан')\n")
        row = self.g16.classify_reader(name, self.stands)
        self.assertEqual(row["outcome"], self.g16.READER_UNMEASURED)
        self.assertIn("ValueError", row["reason"])

    def test_a_module_calling_sys_exit_is_still_swallowed(self):
        name = self._stub("exiting", "import sys\n"
                                     "def measure(data_dir, write=False):\n"
                                     "    sys.exit(3)\n")
        row = self.g16.classify_reader(name, self.stands)
        self.assertEqual(row["outcome"], self.g16.READER_UNMEASURED)

    def test_the_deadline_verdict_escapes_the_walker_instead_of_being_recorded(self):
        """Обратная сторона: та же дверь, но исключение формы срока — наружу."""
        name = self._stub("deadline",
                          "class Deadline(BaseException):\n    pass\n\n"
                          "def measure(data_dir, write=False):\n"
                          "    raise Deadline('срок')\n")
        with self.assertRaises(BaseException) as caught:
            self.g16.classify_reader(name, self.stands)
        self.assertEqual(type(caught.exception).__name__, "Deadline")

    def test_an_import_failure_is_still_skipped_by_the_http_walk(self):
        name = self._stub("badimport", "raise ValueError('не ввезусь')\n")
        self.assertEqual(self.g16.http_modules([name]), [])

    def test_a_deadline_during_an_import_escapes_the_http_walk(self):
        name = self._stub("deadlyimport",
                          "class Deadline(BaseException):\n    pass\n"
                          "raise Deadline('срок в импорте')\n")
        with self.assertRaises(BaseException) as caught:
            self.g16.http_modules([name])
        self.assertEqual(type(caught.exception).__name__, "Deadline")

    def test_the_rule_lives_in_one_copy_the_walker_imports_it(self):
        """Второй экземпляр правила разошёлся бы с первым молча."""
        self.assertIs(self.g16.is_foreign_failure, tdc.is_foreign_failure)


class TheEntryPointHasThreeOutcomes(unittest.TestCase):
    def setUp(self):
        self._tmp = TemporaryDirectory(prefix="c814_main_")
        self.root = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)

    def _write(self, text) -> Path:
        path = self.root / "stream.jsonl"
        path.write_text(text, encoding="utf-8")
        return path

    def test_no_axis_asked_is_not_measured_rather_than_clean(self):
        self.assertEqual(tdc.main([]), tdc.RC_UNMEASURED)

    def test_a_survivor_in_the_record_is_a_finding(self):
        path = self._write(_stream(_case("t::a", begin=0.0, end=407.0)))
        self.assertEqual(tdc.main(["--stream", str(path)]), tdc.RC_FINDING)

    def test_a_record_without_survivors_exits_zero(self):
        path = self._write(_stream(_case("t::a", begin=0.0, end=1.0)))
        self.assertEqual(tdc.main(["--stream", str(path)]), tdc.RC_MEASURED)

    def test_an_unreadable_record_exits_two_not_zero(self):
        self.assertEqual(tdc.main(["--stream", str(self.root / "нет.jsonl")]),
                         tdc.RC_UNMEASURED)

    def test_the_json_report_carries_what_it_does_not_prove(self):
        path = self._write(_stream(_case("t::a", begin=0.0, end=1.0)))
        out = self.root / "report.json"
        tdc.main(["--stream", str(path), "--json", str(out)])
        doc = json.loads(out.read_text(encoding="utf-8"))
        self.assertTrue(doc["what_it_does_not_prove"])
        self.assertIn("population", doc)


class TheContractIsCheckedAgainstLITERALS(unittest.TestCase):
    """Мутационный замер показал класс: имена сверялись САМИ С СОБОЙ (урок #722).

    Значение каждой константы читает МАШИНА — отчёт `--json`, журнал проходов,
    строка лога шага. Переименование значения ломает читателя, а тест, сверяющий
    `tdc.X` с `tdc.X`, этого не видит ни одной мутацией.
    """

    def test_the_door_classes_carry_their_literal_names(self):
        self.assertEqual(tdc.DOOR_CLASSES,
                         ("alarm_cancelled", "alarm_replaced", "handler_replaced",
                          "verdict_swallowed", "alarm_arg_unparsed"))

    def test_the_case_outcomes_carry_their_literal_names(self):
        self.assertEqual(tdc.CASE_OUTCOMES,
                         ("taken", "survived_ok", "unterminated"))

    def test_the_live_verdicts_carry_their_literal_names(self):
        self.assertEqual(tdc.LIVE_VERDICTS,
                         ("defeated", "taken", "taken_late", "unmeasured"))

    def test_the_exit_codes_are_the_declared_three(self):
        self.assertEqual((tdc.RC_MEASURED, tdc.RC_FINDING, tdc.RC_UNMEASURED),
                         (0, 1, 2))

    def test_the_schema_and_the_env_variable_are_the_published_strings(self):
        self.assertEqual(tdc.VERSION, "timeout_door_census/v1")
        self.assertEqual(tdc.WATCH_OUT_ENV, "SPA_TIMEOUT_DOOR_WATCH")

    def test_the_population_document_carries_its_declared_keys(self):
        with TemporaryDirectory(prefix="c814_keys_") as tmp:
            path = Path(tmp) / "s.jsonl"
            path.write_text(_stream(_case("t::a", begin=0.0, end=400.0)),
                            encoding="utf-8")
            doc = tdc.population_from_stream(path)
        for key in ("schema", "source", "measured", "threshold_s", "method",
                    "counts", "cases", "cases_total", "cases_closed",
                    "unparsed_lines", "extra_outcome_lines", "reason"):
            self.assertIn(key, doc, key)

    def test_the_sites_document_carries_its_declared_keys(self):
        with TemporaryDirectory(prefix="c814_keys2_") as tmp:
            root = Path(tmp)
            (root / "spa_core").mkdir()
            (root / "spa_core" / "m.py").write_text("import signal\nsignal.alarm(0)\n",
                                                    encoding="utf-8")
            doc = tdc.door_sites(root, subdirs=("spa_core",))
        for key in ("schema", "tree_root", "measured", "sites", "counts",
                    "files_scanned", "files_unparsed", "sites_total"):
            self.assertIn(key, doc, key)
        for key in ("file", "line", "door", "call", "note"):
            self.assertIn(key, doc["sites"][0], key)

    def test_a_passage_row_carries_its_declared_keys(self):
        with tdc.watch_doors() as watch:
            signal.alarm(0)
        for key in ("call", "door", "file", "line", "function", "args"):
            self.assertIn(key, watch.passages[-1], key)

    def test_the_battery_defaults_are_the_declared_numbers(self):
        import inspect
        sig = inspect.signature(tdc.live_door_verdicts)
        self.assertEqual(sig.parameters["deadline_s"].default, 2.0)
        self.assertEqual(sig.parameters["over_s"].default, 6.0)

    def test_the_default_subdirs_of_the_tree_walk_are_declared(self):
        import inspect
        sig = inspect.signature(tdc.door_sites)
        self.assertEqual(sig.parameters["subdirs"].default, ("spa_core", "scripts"))

    def test_the_battery_keeps_a_control_for_every_shape_it_claims(self):
        """Батарея обязана нести и дверь, и блокировку в C, и позднюю разборку —
        иначе её вердикт о посылке заказа опирается на неполную сцену."""
        doors = [door for door, _n, _b in tdc.BATTERY]
        self.assertTrue(any(d.startswith("control_c_block_") for d in doors))
        self.assertIn("control_teardown_waits", doors)
        self.assertGreaterEqual(sum(1 for d in doors
                                    if d.startswith("control_c_block_")), 4)


class TheVerdictOfALateTeardown(unittest.TestCase):
    """`taken_late` — единственная форма, при которой стена больше порога, а
    двери НЕ БЫЛО: вердикт вынесен вовремя, разборка случая не кончается."""

    def setUp(self):
        self._tmp = TemporaryDirectory(prefix="c814_late_")
        self.root = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)

    def _run(self, cases):
        def run(argv, workdir):
            (Path(workdir) / "junit-battery.xml").write_text(_junit(cases),
                                                             encoding="utf-8")
            return 1
        return run

    def _verdict(self, kind, seconds):
        doc = tdc.live_door_verdicts(
            deadline_s=2.0, over_s=6.0, workdir=self.root,
            cases=((tdc.DOOR_ALARM_CANCELLED, "x", "pass"),),
            run=self._run([("test_x", kind, seconds)]))
        return doc["rows"][0]["verdict"]

    def test_a_failure_far_beyond_the_deadline_is_a_late_teardown(self):
        self.assertEqual(self._verdict("failure", 6.1), tdc.LIVE_TAKEN_LATE)

    def test_a_failure_at_the_deadline_is_plainly_taken(self):
        self.assertEqual(self._verdict("failure", 2.1), tdc.LIVE_TAKEN)

    def test_a_late_teardown_is_not_a_door_and_is_not_a_finding(self):
        doc = tdc.live_door_verdicts(
            deadline_s=2.0, over_s=6.0, workdir=self.root,
            cases=((tdc.DOOR_ALARM_CANCELLED, "x", "pass"),),
            run=self._run([("test_x", "failure", 6.1)]))
        self.assertEqual(doc["counts"][tdc.LIVE_DEFEATED], 0)


class ThePassageJournalSurvivesARunThatNeverEnds(unittest.TestCase):
    """Сводка в конце бесполезна там, где сторож нужнее всего: прогон, который не
    кончается, её не оставит никогда (тот же урок, что у `_artifact_stamp_clock_probe`)."""

    def setUp(self):
        self._tmp = TemporaryDirectory(prefix="c814_jrn_")
        self.root = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)
        self.path = self.root / "passages.jsonl"

    def test_a_passage_is_on_disk_before_the_watch_is_removed(self):
        watch = tdc.watch_doors(journal=self.path).install()
        try:
            signal.alarm(0)
            doc = tdc.passages_from_journal(self.path)
        finally:
            watch.remove()
        self.assertTrue(doc["measured"])
        self.assertEqual(doc["passages_total"], 1)
        self.assertEqual(doc["counts"][tdc.DOOR_ALARM_CANCELLED], 1)

    def test_without_a_journal_nothing_is_written(self):
        with tdc.watch_doors() as watch:
            signal.alarm(0)
        self.assertEqual(len(watch.passages), 1)
        self.assertFalse(self.path.exists())

    def test_an_absent_journal_is_unmeasured_with_its_reason(self):
        doc = tdc.passages_from_journal(self.root / "нет.jsonl")
        self.assertFalse(doc["measured"])
        self.assertIn("не прочитан", doc["reason"])

    def test_a_garbage_line_is_counted_apart_from_the_passages(self):
        self.path.write_text(
            json.dumps({"door": tdc.DOOR_ALARM_CANCELLED, "line": 1}) + "\n"
            + "{не json\n" + json.dumps({"door": "чужой класс"}) + "\n",
            encoding="utf-8")
        doc = tdc.passages_from_journal(self.path)
        self.assertEqual(doc["passages_total"], 1)
        self.assertEqual(doc["unparsed_lines"], 2)

    def test_the_journal_perimeter_sums_to_the_passages(self):
        watch = tdc.watch_doors(journal=self.path).install()
        try:
            signal.alarm(0)
            signal.setitimer(signal.ITIMER_REAL, 0)
        finally:
            watch.remove()
        doc = tdc.passages_from_journal(self.path)
        self.assertEqual(sum(doc["counts"].values()), doc["passages_total"])


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
