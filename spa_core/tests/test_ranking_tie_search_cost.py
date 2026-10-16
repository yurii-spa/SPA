"""Цена поиска перестановки в переписях ничьих — и журнал, который она писала.

Замер 16.10 (агент ``com.spa.decision_loop``, ступень ``findings_bridge``):
``ranking_tie_persistence`` звал ``smallest_flip`` ≈18 400 раз за прогон, каждый
вызов шагал по сетке сдвигов ЛИНЕЙНО (до 127 полных прогонов аллокатора), и
каждый прогон печатал одни и те же предупреждения аллокатора. Одна стадия шла
47.6 мин, журнал агента дорос до 835 МБ / 6.36 млн строк повторов.

Сцены этого файла — положительные контроли починки, и каждая КРАСНАЯ на коде
до неё:

* бисекция по ТОЙ ЖЕ сетке даёт ровно тот же ответ, что линейный обход
  (эталон переписан здесь дословно), на ничьей, на границах сетки, без
  перестановки, при выпавшем из порядка ключе и при упавшем прогоне — и
  платит за это логарифм прогонов, а не сетку целиком (контроль цены);
* повторы ОДНОГО И ТОГО ЖЕ предупреждения сворачиваются в счётчик, а каждое
  РАЗЛИЧНОЕ сообщение — в том числе впервые появившееся посреди стадии —
  печатается.
"""
from __future__ import annotations

import io
import logging
import math
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from spa_core.monitoring import ranking_tie_census as rtc
from spa_core.tests.test_ranking_tie_census import (
    EXACT_TIE_CAPS, EXACT_TIE_RATES, NOISY_HISTORY, NOW, QUANTUM,
    make_producer, write_snapshot)


def reference_linear_flip(produce, provider, universe, above, below, quantum):
    """Исходный ``smallest_flip`` (origin/main 8f913113) — дословно, как эталон."""
    base_pp = float(provider[below]) * 100.0
    step = max(quantum, 1e-12)
    delta = step
    control = 0.0
    while delta <= rtc._FLIP_MAX_PP:
        prov = dict(provider)
        prov[below] = max(1e-12, (base_pp + delta) / 100.0)
        try:
            target, breakdown, _cap = produce(prov)
        except Exception:  # noqa: BLE001
            return None
        order = rtc.ranked_order(breakdown, universe)
        if below in order and above in order and order.index(below) < order.index(above):
            return {"flip_pp": delta, "control_pp": control,
                    "target": target, "order": order}
        control = delta
        delta = (delta + step) if delta < 100 * step else delta * 1.3
    return None


class Counting:
    def __init__(self, produce):
        self.produce, self.calls = produce, 0

    def __call__(self, provider):
        self.calls += 1
        return self.produce(provider)


CAPS = {"a_top": 0.4, "b_hi": 0.2, "c_lo": 0.2}


def scene(gap_pp, *, above="b_hi", below="c_lo"):
    rates = {"a_top": 0.20, above: 0.05, below: 0.05 - gap_pp / 100.0}
    return rates, sorted(rates)


def linear_walk(quantum):
    """Точки, которые обходил исходный линейный поиск, — в его же арифметике."""
    walk, step, delta = [], quantum, quantum
    while delta <= rtc._FLIP_MAX_PP:
        walk.append(delta)
        delta = (delta + step) if delta < 100 * step else delta * 1.3
    return walk


GRID = linear_walk(QUANTUM)


class BisectionEqualsLinearSearch(unittest.TestCase):
    """Тот же ответ — до бита, включая цель, порядок и отрицательный контроль."""

    def assert_same(self, produce, rates, universe, above="b_hi", below="c_lo"):
        ref = reference_linear_flip(produce, rates, universe, above, below, QUANTUM)
        got = rtc.smallest_flip(produce, rates, universe, above, below, QUANTUM)
        self.assertEqual(got, ref)
        return got

    def test_grid_is_exactly_the_linear_walk(self):
        for q in (QUANTUM, 1e-3, 1e-6, 1e-12):
            with self.subTest(quantum=q):
                self.assertEqual(rtc.flip_grid(q), linear_walk(q))

    def test_exact_tie_flips_at_the_first_quantum(self):
        got = self.assert_same(make_producer(CAPS), *scene(0.0))
        self.assertEqual(got["flip_pp"], GRID[0])
        self.assertEqual(got["control_pp"], 0.0)

    def test_flip_inside_the_linear_part_of_the_grid(self):
        got = self.assert_same(make_producer(CAPS), *scene(0.0057))
        self.assertIsNotNone(got)

    def test_flip_inside_the_geometric_part_of_the_grid(self):
        got = self.assert_same(make_producer(CAPS), *scene(3.3))
        self.assertGreater(got["flip_pp"], 100 * QUANTUM)

    def test_flip_at_the_last_grid_point(self):
        got = self.assert_same(make_producer(CAPS),
                               *scene((GRID[-2] + GRID[-1]) / 2.0))
        self.assertEqual(got["flip_pp"], GRID[-1])
        self.assertEqual(got["control_pp"], GRID[-2])

    def test_flip_at_the_first_geometric_grid_point(self):
        # первая точка, где шаг сетки перестаёт быть квантом (начало ×1.3)
        i = next(i for i in range(1, len(GRID))
                 if GRID[i] - GRID[i - 1] > 1.5 * QUANTUM)
        got = self.assert_same(make_producer(CAPS),
                               *scene((GRID[i - 1] + GRID[i]) / 2.0))
        self.assertEqual(got["flip_pp"], GRID[i])

    def test_no_flip_in_range(self):
        self.assertIsNone(self.assert_same(make_producer(CAPS), *scene(15.0)))

    def test_alphabetical_tie_break_on_equal_scores(self):
        # нижний по ставке ключ алфавитно ПЕРВЫЙ: при равенстве счётов он уже выше
        rates = {"a_top": 0.20, "z_hi": 0.05, "b_lo": 0.05 - 0.0042 / 100.0}
        self.assert_same(make_producer({"a_top": 0.4, "z_hi": 0.2, "b_lo": 0.2}),
                         rates, sorted(rates), above="z_hi", below="b_lo")

    def test_key_dropping_out_of_the_order_falls_back_to_the_linear_answer(self):
        """Немонотонный производитель: ключ выпадает из разбора в окне сдвигов
        (бисекция ничего не доказывает) — ответ обязан остаться линейным."""
        base = make_producer(CAPS)

        def produce(provider):
            target, bd, cap = base(provider)
            if 0.5 <= (provider["c_lo"] * 100.0) - 4.9 <= 8.0:
                bd = {k: v for k, v in bd.items() if k != "c_lo"}
            return target, bd, cap
        for gap in (0.3, 4.0, 9.5, 15.0):
            with self.subTest(gap=gap):
                self.assert_same(produce, *scene(gap))

    def test_a_failing_run_gives_the_linear_answer(self):
        base = make_producer(CAPS)

        def produce_failing_above(limit_pp):
            def produce(provider):
                if provider["c_lo"] * 100.0 > limit_pp:
                    raise RuntimeError("прогон упал")
                return base(provider)
            return produce
        # падает ДО перестановки (линейный отвечает None) и ПОСЛЕ неё (флип найден)
        for gap, limit in ((3.3, 5.0), (3.3, 9.0), (0.0057, 4.95)):
            with self.subTest(gap=gap, limit=limit):
                self.assert_same(produce_failing_above(limit), *scene(gap))


class BisectionPaysLogarithmNotTheWholeGrid(unittest.TestCase):
    """Положительный контроль цены: линейный обход платит до len(GRID) прогонов."""

    BOUND = 1 + math.ceil(math.log2(len(GRID) + 1))

    def test_no_flip_costs_one_run(self):
        prod = Counting(make_producer(CAPS))
        self.assertIsNone(rtc.smallest_flip(prod, *scene(15.0), "b_hi", "c_lo", QUANTUM))
        self.assertEqual(prod.calls, 1)
        ref = Counting(make_producer(CAPS))
        reference_linear_flip(ref, *scene(15.0), "b_hi", "c_lo", QUANTUM)
        self.assertEqual(ref.calls, len(GRID))

    def test_a_flip_costs_at_most_a_logarithm(self):
        for gap in (0.0, 0.0057, 0.6, 3.3, (GRID[-2] + GRID[-1]) / 2.0):
            with self.subTest(gap=gap):
                prod = Counting(make_producer(CAPS))
                self.assertIsNotNone(
                    rtc.smallest_flip(prod, *scene(gap), "b_hi", "c_lo", QUANTUM))
                self.assertLessEqual(prod.calls, self.BOUND)


class ListHandler(logging.Handler):
    def __init__(self):
        super().__init__(level=logging.WARNING)
        self.lines = []

    def emit(self, record):
        self.lines.append(record.getMessage())


class RepeatedWarningsCollapse(unittest.TestCase):
    def setUp(self):
        self.handler = ListHandler()
        logging.getLogger().addHandler(self.handler)
        self.addCleanup(logging.getLogger().removeHandler, self.handler)
        self.log = logging.getLogger("spa_core.allocator.test_repeat")

    def test_first_occurrence_of_each_distinct_message_and_a_counted_summary(self):
        with rtc.collapse_repeated_warnings("stage_x"):
            for _ in range(5):
                self.log.warning("MP-011: TVL-floor отфильтровал %s", ["euler_v2"])
            self.log.warning("MP-011: TVL-floor отфильтровал %s", ["aave_v3"])
            for _ in range(3):
                self.log.warning("ADR-053: сетевые потолки %s → %s", "40%", "33%")
            self.log.warning("НОВЫЙ класс: впервые посреди стадии")
        body, summary = self.handler.lines[:-1], self.handler.lines[-1]
        self.assertEqual(body, [
            "MP-011: TVL-floor отфильтровал ['euler_v2']",
            "MP-011: TVL-floor отфильтровал ['aave_v3']",
            "ADR-053: сетевые потолки 40% → 33%",
            "НОВЫЙ класс: впервые посреди стадии",
        ])
        self.assertIn("stage_x: свёрнуто 6 повтор", summary)
        self.assertIn("×5 «MP-011: TVL-floor отфильтровал ['euler_v2']»", summary)
        self.assertIn("×3 «ADR-053", summary)

    def test_filter_is_removed_after_the_stage(self):
        with rtc.collapse_repeated_warnings("stage_y"):
            self.log.warning("same")
            self.log.warning("same")
        self.log.warning("same")
        self.log.warning("same")
        self.assertEqual(self.handler.lines.count("same"), 3)

    def test_no_summary_when_nothing_repeated(self):
        with rtc.collapse_repeated_warnings("stage_z"):
            self.log.warning("one")
            self.log.warning("two")
        self.assertEqual(self.handler.lines, ["one", "two"])

    def test_without_root_handlers_output_goes_to_stderr_like_last_resort(self):
        root = logging.getLogger()
        saved = list(root.handlers)
        for h in saved:
            root.removeHandler(h)
        old_err, sys.stderr = sys.stderr, io.StringIO()
        try:
            with rtc.collapse_repeated_warnings("stage_w"):
                self.log.warning("repeat me")
                self.log.warning("repeat me")
            text = sys.stderr.getvalue()
            self.assertEqual(root.handlers, [])
        finally:
            sys.stderr = old_err
            for h in saved:
                root.addHandler(h)
        self.assertEqual(text.splitlines()[0], "repeat me")
        self.assertEqual(text.count("repeat me"), 2)   # строка + итог со счётом
        self.assertIn("×2 «repeat me»", text)


class CensusStageLogsEachDistinctWarningOnce(unittest.TestCase):
    """Стадия целиком: производитель печатает одно и то же на КАЖДОМ прогоне."""

    def test_measure_collapses_allocator_repeats_and_keeps_a_new_class(self):
        handler = ListHandler()
        logging.getLogger().addHandler(handler)
        self.addCleanup(logging.getLogger().removeHandler, handler)
        noisy = logging.getLogger("spa_core.allocator.test_stage")
        base = make_producer(EXACT_TIE_CAPS)
        calls = {"n": 0}

        def produce(provider):
            calls["n"] += 1
            noisy.warning("MP-011: TVL-floor отфильтровал адаптеры: ['euler_v2']")
            if calls["n"] == 7:
                noisy.warning("новое предупреждение, впервые на 7-м прогоне")
            return base(provider)
        with TemporaryDirectory() as d:
            write_snapshot(Path(d), EXACT_TIE_RATES, history=NOISY_HISTORY,
                           compared=list(EXACT_TIE_RATES), collisions=[])
            doc = rtc.measure(Path(d), now=NOW, producer_factory=lambda _s: produce)
        self.assertEqual(doc["status"], rtc.STATUS_CRITICAL)
        self.assertGreater(calls["n"], 7)
        self.assertEqual(handler.lines.count(
            "MP-011: TVL-floor отфильтровал адаптеры: ['euler_v2']"), 1)
        self.assertEqual(handler.lines.count(
            "новое предупреждение, впервые на 7-м прогоне"), 1)
        summary = [ln for ln in handler.lines if "свёрнуто" in ln]
        self.assertEqual(len(summary), 1)
        self.assertIn(f"×{calls['n']} «MP-011", summary[0])


class SameInputIsProducedOncePerStage(unittest.TestCase):
    """Память прогонов стадии: тот же вход — один прогон; другой вход — новый."""

    def test_unchanged_input_is_reused_and_a_changed_one_recomputed(self):
        inner = Counting(make_producer(CAPS))
        memo = rtc.memoized_producer(inner)
        rates, _u = scene(0.3)
        first = memo(dict(rates))
        again = memo(dict(rates))
        self.assertEqual(inner.calls, 1)
        self.assertEqual(first, again)
        changed = dict(rates, c_lo=rates["c_lo"] + 1e-6)
        memo(changed)
        self.assertEqual(inner.calls, 2)

    def test_callers_get_independent_copies(self):
        memo = rtc.memoized_producer(make_producer(CAPS))
        rates, _u = scene(0.3)
        target, breakdown, _c = memo(dict(rates))
        target.clear()
        breakdown["c_lo"]["score"] = -1.0
        target2, breakdown2, _c2 = memo(dict(rates))
        self.assertTrue(target2)
        self.assertNotEqual(breakdown2["c_lo"]["score"], -1.0)

    def test_a_failure_is_not_remembered(self):
        calls = {"n": 0}

        def flaky(provider):
            calls["n"] += 1
            raise RuntimeError("прогон упал")
        memo = rtc.memoized_producer(flaky)
        for _ in range(2):
            with self.assertRaises(RuntimeError):
                memo({"a": 0.05})
        self.assertEqual(calls["n"], 2)

    def test_lru_bound_evicts_the_oldest(self):
        inner = Counting(make_producer(CAPS))
        memo = rtc.memoized_producer(inner, maxsize=2)
        for v in (0.01, 0.02, 0.03, 0.01):
            memo({"a_top": v})
        self.assertEqual(inner.calls, 4)

    def test_census_stage_never_runs_the_producer_twice_on_one_input(self):
        """Положительный контроль: до починки стадия гоняла один и тот же вход
        десятки раз (сдвиг ``below`` заново для каждого ``above``)."""
        seen, dups = set(), {"n": 0}
        base = make_producer(EXACT_TIE_CAPS)

        def produce(provider):
            key = tuple(sorted(provider.items()))
            if key in seen:
                dups["n"] += 1
            seen.add(key)
            return base(provider)
        with TemporaryDirectory() as d:
            write_snapshot(Path(d), EXACT_TIE_RATES, history=NOISY_HISTORY,
                           compared=list(EXACT_TIE_RATES), collisions=[])
            doc = rtc.measure(Path(d), now=NOW, producer_factory=lambda _s: produce)
        self.assertEqual(doc["status"], rtc.STATUS_CRITICAL)
        self.assertEqual(dups["n"], 0)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
