"""Приёмка прибора «где теряется отсчёт предела `_run_bounded`» (ADR-1017).

Правило батареи: про ЖИВЫЕ сцены здесь утверждается только то, что не зависит от того, как
хозяину повезло с GIL. Предмет замера — занятый вычислением ребёнок — по построению не
детерминирован (ADR-1015 § 4), и тест, требующий от него конкретного исхода, был бы бомбой
того же рода, что литеральный pid (`.claude/rules/deployment.md` § «ЛИЧНОСТЬ ПРОЦЕССА»).
Поэтому исходы утверждаются у СПЯЩИХ сцен (спящий ребёнок GIL не держит), а разбор мест —
на рукотворных отметках, где часов нет вовсе.
"""

import importlib.util
import sys
import threading
import unittest
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
_SPEC = importlib.util.spec_from_file_location(
    "bounded_countdown_probe", _REPO / "scripts" / "bounded_countdown_probe.py")
probe = importlib.util.module_from_spec(_SPEC)
sys.modules["bounded_countdown_probe"] = probe
_SPEC.loader.exec_module(probe)

from spa_core.analytics import signal_aggregator  # noqa: E402


def _raw(**kw):
    """Рукотворные отметки: часов нет, поэтому разбор мест проверяем ТОЧНО, а не приблизительно."""
    base = {"t_call": 0.0, "t_start_enter": 0.0, "t_start_exit": 0.1, "t_wait_enter": 0.1,
            "t_flag_read": 0.1, "t_timed_acquire": 0.1, "t_timed_acquire_done": 0.2,
            "t_set_enter": 1.0, "t_set": 1.0, "t_child_enter": 0.0, "t_child_exit": 1.0,
            "t_return": 1.0}
    base.update(kw)
    return base


def _row(raw, *, limit_s=0.001, free_at_ask=False, wait_result=True, outcome="ok"):
    return {"limit_s": limit_s, "free_at_ask": free_at_ask, "wait_result": wait_result,
            "outcome": outcome, "wait_s": 0.1, "timed_acquire_s": 0.1}, raw


class ClassifyRowNamesThePlace(unittest.TestCase):
    """Пять мест и три «не измерено» — каждое со своей сценой, отличающейся РОВНО одним входом."""

    def test_late_in_start_when_start_returns_after_the_child_finished(self):
        row, raw = _row(_raw(t_start_exit=1.5, t_wait_enter=1.5, t_flag_read=1.5,
                             t_timed_acquire=1.5))
        place, reason = probe.classify_row(row, raw)
        self.assertEqual(place, "late_in_start")
        self.assertIn("start()", reason)

    def test_late_before_wait_when_the_call_itself_came_after_the_event(self):
        row, raw = _row(_raw(t_start_exit=0.5, t_wait_enter=1.5, t_flag_read=1.5,
                             t_timed_acquire=1.5))
        place, _ = probe.classify_row(row, raw)
        self.assertEqual(place, "late_before_wait")

    def test_late_flag_read_when_the_flag_was_read_after_the_event(self):
        row, raw = _row(_raw(t_flag_read=1.5, t_timed_acquire=1.6))
        place, _ = probe.classify_row(row, raw)
        self.assertEqual(place, "late_flag_read")

    def test_deadline_never_asked_when_the_waiter_was_already_free(self):
        row, raw = _row(_raw(t_timed_acquire=0.9), free_at_ask=True)
        place, reason = probe.classify_row(row, raw)
        self.assertEqual(place, "deadline_never_asked")
        self.assertIn("СВОБОДЕН", reason)

    def test_primitive_overstays_when_the_waiter_was_held_at_the_ask(self):
        row, raw = _row(_raw(), free_at_ask=False)
        place, reason = probe.classify_row(row, raw)
        self.assertEqual(place, "primitive_overstays")
        self.assertIn("ЗАНЯТ", reason)

    def test_within_limit_when_the_child_finished_inside_the_deadline(self):
        row, raw = _row(_raw(t_set_enter=0.15, t_set=0.15), limit_s=1.0)
        place, _ = probe.classify_row(row, raw)
        self.assertEqual(place, "within_limit")

    def test_missing_stamp_is_a_third_outcome_not_a_place(self):
        raw = _raw()
        del raw["t_set"]
        row, raw = _row(raw)
        place, reason = probe.classify_row(row, raw)
        self.assertIsNone(place)
        self.assertIn("НЕ ИЗМЕРЕНО", reason)

    def test_missing_flag_read_is_a_third_outcome_with_its_own_cause(self):
        raw = _raw()
        del raw["t_flag_read"]
        row, raw = _row(raw)
        place, reason = probe.classify_row(row, raw)
        self.assertIsNone(place)
        self.assertIn("флаг", reason.lower())

    def test_flag_read_inside_the_write_window_is_not_guessed(self):
        # Запись флага НАЧАЛАСЬ, но ещё не видна: утверждать «уже стояло» здесь нельзя.
        row, raw = _row(_raw(t_set_enter=1.0, t_set=1.2, t_flag_read=1.1))
        place, reason = probe.classify_row(row, raw)
        self.assertIsNone(place)
        self.assertIn("окна записи", reason)

    def test_missing_timed_acquire_observation_is_a_third_outcome(self):
        raw = _raw()
        del raw["t_timed_acquire"]
        row, raw = _row(raw, free_at_ask=None)
        place, reason = probe.classify_row(row, raw)
        self.assertIsNone(place)
        self.assertIn("НЕ ИЗМЕРЕНО", reason)


class SeriesVerdictRequiresUnanimity(unittest.TestCase):

    @staticmethod
    def _rows(places, outcome="ok"):
        return [{"outcome": outcome, "place": p, "place_reason": "—"} for p in places]

    def test_unanimous_series_names_its_place(self):
        v = probe.verdict_of_series(self._rows(["primitive_overstays"] * 3))
        self.assertEqual(v["verdict"], "COUNTDOWN_PRIMITIVE_OVERSTAYS")

    def test_every_place_has_its_own_verdict_word(self):
        for place in probe.PLACES:
            with self.subTest(place=place):
                v = probe.verdict_of_series(self._rows([place] * 2))
                self.assertEqual(v["verdict"], probe._PLACE_TO_VERDICT[place])

    def test_mixed_series_is_measured_and_says_so(self):
        v = probe.verdict_of_series(self._rows(["late_in_start", "primitive_overstays"]))
        self.assertEqual(v["verdict"], "COUNTDOWN_LATE_MIXED")
        self.assertIn("НЕ единогласен", v["reason"])

    def test_series_without_a_blind_row_is_unmeasured_not_a_place(self):
        v = probe.verdict_of_series(self._rows(["within_limit"], outcome="timeout"))
        self.assertEqual(v["verdict"], "COUNTDOWN_UNMEASURED")
        self.assertIn("ни одной слепой", v["reason"])

    def test_empty_series_is_unmeasured_not_zero(self):
        v = probe.verdict_of_series([])
        self.assertEqual(v["verdict"], "COUNTDOWN_UNMEASURED")

    def test_a_row_without_a_place_poisons_the_series_loudly(self):
        rows = self._rows(["primitive_overstays"]) + [
            {"outcome": "ok", "place": None, "place_reason": "НЕ ИЗМЕРЕНО: нет отметок"}]
        v = probe.verdict_of_series(rows)
        self.assertEqual(v["verdict"], "COUNTDOWN_UNMEASURED")

    def test_the_declaration_owns_its_own_contract(self):
        # Словарь мест и словарь вердиктов — одна мерка в двух видах; разойдись они, прибор
        # печатал бы вердикт, которого не умеет объяснить ни одна строка.
        self.assertEqual(len(probe.COUNTDOWN_VERDICTS), len(probe.PLACES) + 2)
        self.assertEqual(set(probe._PLACE_TO_VERDICT), set(probe.PLACES))


class CanaryAsksWhetherTheProbePerturbsItsSubject(unittest.TestCase):

    @staticmethod
    def _rows(oks, total):
        return ([{"outcome": "ok"}] * oks) + ([{"outcome": "timeout"}] * (total - oks))

    def test_transparent_when_both_series_see_blindness(self):
        c = probe.canary(self._rows(3, 4), self._rows(2, 4))
        self.assertEqual(c["verdict"], "CANARY_TRANSPARENT")
        self.assertIsNone(c["reason"])

    def test_perturbed_when_only_the_bare_series_sees_it(self):
        c = probe.canary(self._rows(0, 4), self._rows(4, 4))
        self.assertEqual(c["verdict"], "CANARY_PERTURBED")
        self.assertIn("ПЕРЕВЕРНУЛ", c["reason"])

    def test_subject_absent_when_the_bare_series_is_never_blind(self):
        c = probe.canary(self._rows(4, 4), self._rows(0, 4))
        self.assertEqual(c["verdict"], "CANARY_SUBJECT_ABSENT")

    def test_empty_series_is_not_an_answer(self):
        self.assertEqual(probe.canary([], [])["verdict"], "CANARY_SUBJECT_ABSENT")


class ControlsFailLoudlyOnEachBrokenLink(unittest.TestCase):

    def test_limit_honoured_control_holds_on_a_healthy_set(self):
        rows = [{"outcome": "timeout", "wait_result": False}] * 3
        self.assertTrue(probe._control_limit_honoured(rows)["ok"])

    def test_limit_honoured_control_breaks_when_the_limit_stays_silent(self):
        rows = [{"outcome": "ok", "wait_result": True}] * 3
        c = probe._control_limit_honoured(rows)
        self.assertFalse(c["ok"])
        self.assertIn("не показал честный отсчёт", c["reason"])

    def test_limit_honoured_control_breaks_on_an_empty_set(self):
        self.assertFalse(probe._control_limit_honoured([])["ok"])

    def test_legal_ok_control_holds_and_breaks(self):
        good = [{"outcome": "ok", "place": "within_limit"}] * 2
        bad = [{"outcome": "ok", "place": "primitive_overstays"}] * 2
        self.assertTrue(probe._control_legal_ok(good)["ok"])
        self.assertFalse(probe._control_legal_ok(bad)["ok"])
        self.assertFalse(probe._control_legal_ok([])["ok"])

    def test_primitive_quiet_control_holds_and_breaks(self):
        good = [{"place": "honoured"}] * 2
        bad = [{"place": "overstay"}] * 2
        self.assertTrue(probe._control_primitive_quiet(good)["ok"])
        self.assertFalse(probe._control_primitive_quiet(bad)["ok"])
        self.assertFalse(probe._control_primitive_quiet([])["ok"])


class RefusalsAreRefusalsNotSubstitutions(unittest.TestCase):

    def test_unknown_busyness_kind_is_refused(self):
        with self.assertRaises(probe.NotMeasured):
            probe._work("hibernate", 0.01, None)

    def test_unknown_kind_is_refused_by_the_independent_scene_too(self):
        with self.assertRaises(probe.NotMeasured):
            probe.primitive_control(kind="hibernate", work_s=0.01, limit_s=0.01, repeats=1)

    def test_stamp_vocabulary_is_closed(self):
        with self.assertRaises(probe.NotMeasured):
            probe._Stamps().mark("t_whenever")

    def test_zero_repeats_is_unmeasured_with_a_named_cause(self):
        doc = probe.measure(repeats=0)
        self.assertEqual(doc["verdict"], "COUNTDOWN_UNMEASURED")
        self.assertIn("повторов 0", doc["unmeasured_reason"])
        self.assertEqual(doc["canary"]["verdict"], "CANARY_SUBJECT_ABSENT")


class TheDoorToTheRunnerIsSingleAndReal(unittest.TestCase):

    def test_by_default_the_probe_calls_the_runner_itself(self):
        seen = []

        def spy(fn, timeout, label):
            seen.append((timeout, label))
            return signal_aggregator._run_bounded(fn, timeout, label)

        row = probe.trace_once(kind="sleep", work_s=0.01, limit_s=2.0, runner=spy)
        self.assertEqual(len(seen), 1)
        self.assertEqual(row["outcome"], "ok")
        # Инъекция существует ТОЛЬКО для контроля: умолчание есть сам бегун, а не копия.
        self.assertIs(probe._sa._run_bounded, signal_aggregator._run_bounded)

    def test_the_probe_restores_every_door_it_patched(self):
        before_threading = signal_aggregator.threading
        before_alloc = threading._allocate_lock
        probe.trace_once(kind="sleep", work_s=0.01, limit_s=2.0)
        self.assertIs(signal_aggregator.threading, before_threading)
        self.assertIs(threading._allocate_lock, before_alloc)

    def test_the_probe_restores_its_doors_even_when_the_module_raises(self):
        before_threading = signal_aggregator.threading
        before_alloc = threading._allocate_lock

        def boom():
            raise ValueError("модуль упал")

        row = probe.trace_once(kind="sleep", work_s=0.0, limit_s=2.0,
                               runner=lambda _fn, t, l: signal_aggregator._run_bounded(boom, t, l))
        self.assertEqual(row["outcome"], "error")
        self.assertEqual(row["exc"], "ValueError")
        self.assertIs(signal_aggregator.threading, before_threading)
        self.assertIs(threading._allocate_lock, before_alloc)

    def test_the_shim_delegates_everything_it_does_not_stamp(self):
        shim = probe._ThreadingShim(probe._Stamps())
        self.assertIs(shim.Lock, threading.Lock)
        self.assertIs(shim.current_thread, threading.current_thread)


class TheWaiterDoorObservesWhetherTheLockWasFree(unittest.TestCase):
    """Прямое наблюдение `free_at_ask` — своя сцена, и она детерминирована.

    Без неё значение `deadline_never_asked` было бы словом, которого прибор не напечатал ни
    разу: живая занятая сцена его не производит, а снятие неблокирующей пробы не краснило бы
    ничего — ровно тот выживший мутант, что указывает на НЕРАЗЛИЧАЮЩУЮ сцену (ADR-1015).
    """

    def test_a_free_lock_is_seen_as_free_and_the_deadline_is_not_asked(self):
        stamps = probe._Stamps()
        stamps.in_wait = True
        w = probe._StampedWaiter(stamps, threading.Lock())
        self.assertTrue(w.acquire())          # первый зов — очередь ожидающих, не предмет
        w.release()
        self.assertTrue(w.acquire(True, 0.001))
        self.assertIs(stamps.free_at_ask, True)
        self.assertIsNotNone(stamps.rows.get("t_timed_acquire"))

    def test_a_held_lock_is_seen_as_held_and_the_deadline_goes_to_the_os(self):
        stamps = probe._Stamps()
        stamps.in_wait = True
        real = threading.Lock()
        w = probe._StampedWaiter(stamps, real)
        self.assertTrue(w.acquire())          # первый зов занимает замок
        self.assertFalse(w.acquire(True, 0.001))
        self.assertIs(stamps.free_at_ask, False)


class ThePrimitivePlaceHasThreeBranches(unittest.TestCase):

    def test_not_acquired_is_an_honoured_deadline(self):
        self.assertEqual(probe._primitive_place(False, 0.5, 0.001), "honoured")

    def test_acquired_past_the_deadline_is_an_overstay(self):
        self.assertEqual(probe._primitive_place(True, 0.02, 0.001), "overstay")

    def test_acquired_inside_the_deadline_is_a_missed_window(self):
        self.assertEqual(probe._primitive_place(True, 0.0005, 0.001), "instant")


class LiveScenesThatDoNotDependOnGilLuck(unittest.TestCase):
    """Спящий ребёнок GIL не держит, поэтому эти исходы одинаковы на любом хозяине."""

    def test_a_sleeping_child_under_the_limit_makes_the_runner_say_its_word(self):
        row = probe.trace_once(kind="sleep", work_s=0.30, limit_s=0.01)
        self.assertEqual(row["outcome"], "timeout")
        self.assertIs(row["wait_result"], False)
        # Отметки конца работы к этому моменту НЕТ по построению — и это законно.
        self.assertIsNone(row["at"]["t_set"])
        self.assertIsNone(row["place"])
        self.assertIn("НЕ ИЗМЕРЕНО", row["place_reason"])

    def test_a_sleeping_child_over_the_limit_is_a_legal_ok(self):
        row = probe.trace_once(kind="sleep", work_s=0.05, limit_s=5.0)
        self.assertEqual(row["outcome"], "ok")
        self.assertEqual(row["place"], "within_limit")
        self.assertIsNotNone(row["child_work_s"])
        self.assertIs(row["free_at_ask"], False)

    def test_the_independent_scene_honours_a_deadline_beside_a_sleeping_neighbour(self):
        rows = probe.primitive_control(kind="sleep", work_s=0.30, limit_s=0.01, repeats=2)
        self.assertEqual([r["place"] for r in rows], ["honoured", "honoured"])
        self.assertEqual([r["got"] for r in rows], [False, False])

    def test_measure_answers_in_its_declared_vocabulary(self):
        doc = probe.measure(repeats=2, busy_s=0.03, sleep_s=0.05, sleep_limit_s=0.01,
                            sleep_over_limit_s=5.0)
        self.assertIn(doc["verdict"], probe.COUNTDOWN_VERDICTS)
        self.assertIn(doc["canary"]["verdict"], probe.CANARY_VERDICTS)
        self.assertEqual(set(doc["sides"]), {
            "busy_under_limit", "busy_over_limit", "sleep_under_limit", "sleep_over_limit",
            "bare_busy_under_limit"})
        self.assertIn("НЕЗАВИСИМЫЙ ПРИМИТИВ", probe.render(doc))


class CrossCheckOfTwoIndependentObservations(unittest.TestCase):
    """Утверждение о примитиве обязано держаться и у ГОЛОЙ сцены — иначе мерка подтверждает
    сама себя (класс ADR-913). Две сцены отличаются РОВНО ответом голой сцены."""

    @staticmethod
    def _trace(*, kind, work_s, limit_s):
        blind = kind == "busy" and limit_s < work_s
        timed_out = kind == "sleep" and limit_s < work_s
        return {"kind": kind, "work_s": work_s, "limit_s": limit_s,
                "outcome": "timeout" if timed_out else "ok",
                "wait_result": not timed_out, "free_at_ask": False, "shim": True,
                "place": "primitive_overstays" if blind else "within_limit",
                "place_reason": "—", "wait_s": 0.1, "timed_acquire_s": 0.1,
                "start_cost_s": 0.0, "gap_to_wait_s": 0.0, "child_work_s": work_s,
                "wall_s": work_s, "at": {n: 0.0 for n in probe.STAMPS}, "exc": None}

    @staticmethod
    def _bare(*, kind, work_s, limit_s):
        return {"kind": kind, "work_s": work_s, "limit_s": limit_s, "outcome": "ok",
                "exc": None, "wall_s": work_s, "shim": False}

    @staticmethod
    def _prim(place):
        def door(*, kind, work_s, limit_s, repeats):
            # У СПЯЩЕГО соседа срок обязан соблюдаться — иначе не держится свой контроль.
            p = "honoured" if kind == "sleep" else place
            return [{"kind": kind, "work_s": work_s, "limit_s": limit_s,
                     "got": p != "honoured", "seconds": 0.02, "place": p, "over_x": 20.0}
                    for _ in range(repeats)]
        return door

    def _measure(self, place):
        return probe.measure(repeats=2, busy_s=0.05, busy_limit_s=0.001, busy_over_limit_s=5.0,
                             sleep_s=0.05, sleep_limit_s=0.001, sleep_over_limit_s=5.0,
                             trace_door=self._trace, bare_door=self._bare,
                             primitive_door=self._prim(place))

    def test_agreeing_observations_let_the_verdict_stand(self):
        doc = self._measure("overstay")
        self.assertEqual(doc["verdict"], "COUNTDOWN_PRIMITIVE_OVERSTAYS")
        self.assertIsNone(doc["unmeasured_reason"])

    def test_disagreeing_observations_give_no_answer_at_all(self):
        doc = self._measure("honoured")
        self.assertEqual(doc["verdict"], "COUNTDOWN_UNMEASURED")
        self.assertIn("СПОРЯТ", doc["unmeasured_reason"])
        self.assertEqual(doc["primitive"]["overstay_n"], 0)


if __name__ == "__main__":
    unittest.main()
