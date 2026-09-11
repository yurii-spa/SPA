"""Приёмка прибора «наблюдения, доказуемые НЕ из носителя» (заказ #557, ADR-321).

Каждая сцена ниже — положительный контроль на НАЗВАННУЮ ошибку, а не украшение.
Разбор аварий, которые эти тесты воспроизводят:

* **«Не измерено» выдано за «наблюдений не было».** День старше кольцевого буфера
  независимого носителя обязан получить ``None``, а не ``0``. Ноль здесь читался бы
  как «мир молчал», и ветка закрылась бы третьим исходом, которого никто не мерил.
  Ровно этот дефект заказ #557 назвал заранее.
* **Второй свидетель, который есть тот же свидетель.** Заказ назвал журнал
  расхождений независимым источником. Замером он им не оказался: его метки
  совпадают с метками носителя ПОЛНОСТЬЮ на всех общих днях, потому что оба пишет
  один пробег. Прибор обязан это ИЗМЕРЯТЬ, а не принимать чьё-либо слово — и
  обязан сказать «independent», как только метки разойдутся хоть на одном дне.
* **Число наблюдений, выданное за число сравнимых.** Десять прогонов дня и ноль
  пригодных к сравнению пар — совместимые числа, потому что независимый носитель
  несёт на прогон ставку РОВНО ОДНОГО протокола. Класс ``leg_never_winner`` обязан
  жить отдельно: свалив его в «не покрыто», прибор потерял бы то единственное,
  что здесь чинится составом записи, а не частотой опроса.
* **«Значений два и они равны» ≠ «значение одно».** Первое есть наблюдение покоя,
  второе — отсутствие наблюдения. Прибор обязан различать их вердиктом, а не
  размахом.
* **Разделяющая проба, отвечающая не на тот вопрос.** Первая редакция слоя 3
  спрашивала «есть ли на этом дне переписанная левая сторона И есть ли правые
  стороны» и при утвердительном ответе объявляла переписанными ВСЕ прогоны дня.
  На живых данных это давало верное число по случайности — все левые стороны там
  переписаны. Сцена ``OnePairTranscribedDoesNotCoverTheOther`` строит день, где
  переписана одна левая сторона из двух, и старая логика на ней краснеет.
* **Выдуманное сравнение с маржой.** Маржи для ключа нет ⇒ «размах больше маржи»
  есть изобретённое число. Прибор обязан сказать «НЕ ИЗМЕРЕНО» и не произнести ни
  ``exceeds_margin``, ни ``within_margin``.
* **Порядок слоёв есть утверждение.** Заказ велел назвать пригодность ПРЕЖДЕ
  разницы, а контроль на несвязанном населении печатать после. Порядок проверяется
  тестом, иначе он держится только добрыми намерениями автора.
* **Отказ входа выдан за покой.** Нет независимого носителя ⇒ UNMEASURED и НИ
  ОДНОГО числа, а не «ноль наблюдений вне носителя».

# FROZEN-DATE-OK: injected-clock — часы приходят ВХОДОМ: build(..., now=ANCHOR),
# и все календарные метки сцен производны от того же якоря ANCHOR (D0…D4, _iso).
"""
# LLM_FORBIDDEN
from __future__ import annotations

import json
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

from spa_core.monitoring import rate_observation_census as mod

#: Якорь. Всё календарное в этом файле производно ОТ НЕГО и передаётся коду
#: аргументом — ни одна сцена не спрашивает времени у стены.
ANCHOR = datetime(2026, 9, 10, 12, 0, 0, tzinfo=timezone.utc)


def _day(offset: int) -> str:
    return (ANCHOR - timedelta(days=offset)).date().isoformat()


def _iso(offset_days: int, hour: int, minute: int = 0, second: int = 0) -> str:
    return (ANCHOR - timedelta(days=offset_days)).replace(
        hour=hour, minute=minute, second=second, microsecond=0).isoformat()


D0, D1, D2, D3, D4 = (_day(0), _day(1), _day(2), _day(3), _day(4))


class _Scene(unittest.TestCase):
    """Сцена: каталог на диске, который прибор читает, и ничего сверх него."""

    def setUp(self) -> None:
        self._tmp = TemporaryDirectory()
        self.dir = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)

    def write_jsonl(self, name: str, rows) -> None:
        with open(self.dir / name, "w", encoding="utf-8") as fh:
            for row in rows:
                fh.write(json.dumps(row, ensure_ascii=False) + "\n")

    def write_json(self, name: str, doc) -> None:
        with open(self.dir / name, "w", encoding="utf-8") as fh:
            json.dump(doc, fh, ensure_ascii=False)

    # ── материал сцен ────────────────────────────────────────────────────────

    def carrier_row(self, snapshot: str, seen: str, adapter: str = "aave_v3",
                    apy: float = 2.0) -> dict:
        return {"snapshot": snapshot, "observed_at": seen, "kind": "hint_winner",
                "adapter": adapter, "apy": apy}

    def run_row(self, ts: str, protocol=None, apy=None) -> dict:
        best = ({"protocol": protocol, "apy_pct": apy}
                if protocol is not None else None)
        return {"run_ts": ts, "summary": {"best_apy": best}}

    def divergence_row(self, left: str, right: str) -> dict:
        return {"snapshot_key": f"{left}|{right}", "protocol": "aave_v3",
                "kind": "apy_live_vs_live", "severity": "CRITICAL"}

    def journal_row(self, day: str, legs) -> dict:
        return {"cycle_date": day,
                "current_positions": {leg: 1000.0 for leg in legs},
                "target_positions": {}}

    def build(self, denominator, **patch):
        """Собрать документ, подменив КАНОНИЧЕСКОГО производителя знаменателя."""
        original = mod.scored_days
        mod.scored_days = lambda _d: denominator  # type: ignore[assignment]
        try:
            return mod.build(self.dir, now=ANCHOR, **patch)
        finally:
            mod.scored_days = original  # type: ignore[assignment]


# ─── слой 0: независимость кандидата ───────────────────────────────────────────

class IndependenceIsMeasured(_Scene):

    def test_identical_labels_on_every_shared_day_is_not_a_second_witness(self):
        probe = mod.independence_probe({D1: {"a", "b"}, D2: {"c"}},
                                       {D1: {"a", "b"}, D2: {"c"}}, "cand")
        self.assertEqual(probe["verdict"], "same_producer_suspect")
        self.assertEqual(probe["shared_days"], 2)
        self.assertEqual(probe["identical_days"], 2)

    def test_one_differing_day_is_enough_to_call_it_independent(self):
        """Положительный контроль: проба обязана УМЕТЬ сказать «independent»."""
        probe = mod.independence_probe({D1: {"a"}, D2: {"c"}},
                                       {D1: {"a"}, D2: {"c", "d"}}, "cand")
        self.assertEqual(probe["verdict"], "independent")

    def test_no_shared_days_is_unmeasured_not_independent(self):
        probe = mod.independence_probe({D1: {"a"}}, {D3: {"b"}}, "cand")
        self.assertEqual(probe["verdict"], "unmeasured")
        self.assertIn("не измерена", probe["reason"])


# ─── слой 1: ось прогонов ──────────────────────────────────────────────────────

class RunAxis(_Scene):

    def test_day_older_than_the_buffer_gets_none_not_zero(self):
        """Главный третий исход заказа: «не измерено» нельзя выдать за «не было»."""
        rows = mod.run_axis([D4], {}, {D1: {_iso(1, 6): None}}, _iso(1, 6))
        self.assertEqual(rows[0]["klass"], mod.DAY_UNMEASURED_WINDOW)
        self.assertIsNone(rows[0]["runs_provable"])
        self.assertIsNone(rows[0]["observations_outside_carrier"])
        self.assertIn("буфер", rows[0]["reason"])

    def test_carrier_covers_every_run_of_the_day_means_zero_outside(self):
        rows = mod.run_axis([D1], {D1: {"s1"}}, {D1: {_iso(1, 6): None}}, _iso(1, 6))
        self.assertEqual(rows[0]["klass"], mod.DAY_MEASURED)
        self.assertEqual(rows[0]["runs_provable"], 1)
        self.assertEqual(rows[0]["observations_outside_carrier"], 0)

    def test_carrier_absent_on_a_day_the_independent_carrier_covers(self):
        runs = {D1: {_iso(1, h): None for h in (3, 6, 9, 12, 15)}}
        rows = mod.run_axis([D1], {}, runs, _iso(1, 3))
        self.assertEqual(rows[0]["runs_provable"], 5)
        self.assertEqual(rows[0]["observations_outside_carrier"], 5)


# ─── слой 2: пригодность к сравнению ───────────────────────────────────────────

class ComparableIsNotObserved(_Scene):

    def _axis(self, runs, legs, margins=None, earliest=None):
        return mod.comparable_axis([D1], {D1: legs}, {D1: runs},
                                   margins or {}, earliest or _iso(1, 3))

    def test_two_observations_of_one_leg_are_judged_and_carry_the_range(self):
        rows = self._axis({_iso(1, 6): ("pendle", 13.9), _iso(1, 9): ("pendle", 14.1)},
                          ["pendle"])
        self.assertEqual(rows[0]["klass"], mod.PAIR_JUDGED)
        self.assertEqual(rows[0]["observations"], 2)
        self.assertAlmostEqual(rows[0]["range_pp"], 0.2, places=4)

    def test_two_equal_values_are_judged_with_a_zero_range_not_one_observation(self):
        """«Значений два и они равны» есть наблюдение покоя, а не его отсутствие."""
        rows = self._axis({_iso(1, 6): ("pendle", 13.9), _iso(1, 9): ("pendle", 13.9)},
                          ["pendle"])
        self.assertEqual(rows[0]["klass"], mod.PAIR_JUDGED)
        self.assertEqual(rows[0]["distinct_values"], 1)
        self.assertEqual(rows[0]["range_pp"], 0.0)

    def test_one_observation_is_not_a_range_of_zero(self):
        rows = self._axis({_iso(1, 6): ("pendle", 13.9)}, ["pendle"])
        self.assertEqual(rows[0]["klass"], mod.PAIR_ONE_OBSERVATION)
        self.assertIsNone(rows[0]["range_pp"])

    def test_leg_that_was_never_the_winner_gets_its_own_class(self):
        """Десять наблюдений дня и ноль пригодных пар — совместимые числа."""
        runs = {_iso(1, h): ("pendle", 13.9) for h in (3, 6, 9)}
        rows = self._axis(runs, ["aave_v3"])
        self.assertEqual(rows[0]["klass"], mod.PAIR_LEG_NEVER_WINNER)
        self.assertEqual(rows[0]["observations"], 0)

    def test_day_outside_the_buffer_never_gets_a_pair_verdict(self):
        rows = mod.comparable_axis([D4], {D4: ["pendle"]}, {}, {}, _iso(1, 3))
        self.assertEqual(rows[0]["klass"], mod.PAIR_DAY_OUTSIDE_WINDOW)
        self.assertIsNone(rows[0]["observations"])

    def test_missing_margin_refuses_the_comparison_instead_of_inventing_it(self):
        rows = self._axis({_iso(1, 6): ("pendle", 1.0), _iso(1, 9): ("pendle", 99.0)},
                          ["pendle"])
        self.assertIn("НЕ ИЗМЕРЕНО", rows[0]["margin_comparison"])
        self.assertNotIn("exceeds_margin", rows[0]["margin_comparison"])
        self.assertNotIn("within_margin", rows[0]["margin_comparison"])

    def test_margin_present_and_exceeded_is_said_plainly(self):
        rows = self._axis({_iso(1, 6): ("pendle", 1.0), _iso(1, 9): ("pendle", 2.0)},
                          ["pendle"], margins={"pendle": 0.5})
        self.assertEqual(rows[0]["margin_comparison"], "exceeds_margin")

    def test_margin_present_and_not_exceeded_is_said_plainly(self):
        rows = self._axis({_iso(1, 6): ("pendle", 1.0), _iso(1, 9): ("pendle", 1.1)},
                          ["pendle"], margins={"pendle": 0.5})
        self.assertEqual(rows[0]["margin_comparison"], "within_margin")


# ─── слой 3: механизм ──────────────────────────────────────────────────────────

class Mechanism(_Scene):

    def test_a_run_with_no_transcribed_pair_is_overwritten_not_transcribed(self):
        s_a, s_b = _iso(1, 6), _iso(1, 9)
        r_a, r_b = _iso(1, 6, 0, 2), _iso(1, 9, 0, 2)
        rows = mod.mechanism_axis(
            [D1], {D1: {s_a: _iso(1, 11)}},
            {D1: {r_a: None, r_b: None}},
            {D1: {(s_a, r_a), (s_b, r_b)}})
        self.assertEqual(rows[0]["runs"], 2)
        self.assertEqual(rows[0]["transcribed"], 1)
        self.assertEqual(rows[0]["overwritten_before_transcription"], [r_b])

    def test_one_pair_transcribed_does_not_cover_the_other(self):
        """Проба обязана спрашивать про ПАРУ, а не про «есть левая и есть правые».

        Старая редакция объединяла множества и на этой сцене объявляла
        переписанными ОБА прогона — верный ответ не на тот вопрос.
        """
        s_ok, s_no = _iso(2, 6), _iso(2, 14)
        r_ok, r_no = _iso(2, 6, 0, 2), _iso(2, 14, 0, 2)
        rows = mod.mechanism_axis(
            [D2], {D2: {s_ok: _iso(2, 18)}},
            {D2: {r_ok: None, r_no: None}},
            {D2: {(s_ok, r_ok), (s_no, r_no)}})
        self.assertEqual(rows[0]["transcribed"], 1)
        self.assertIn(r_no, rows[0]["overwritten_before_transcription"])

    def test_day_the_transcriber_never_touched_is_absent_not_a_silent_zero(self):
        rows = mod.mechanism_axis([D1], {}, {D1: {_iso(1, 6): None}}, {})
        self.assertEqual(rows, [])


# ─── слой 4 и порядок слоёв ────────────────────────────────────────────────────

class LayerOrderIsAClaim(_Scene):

    def _full(self):
        s1, s2 = _iso(1, 6), _iso(2, 6)
        r1, r2 = _iso(1, 6, 0, 2), _iso(2, 6, 0, 2)
        r2b = _iso(2, 14, 0, 2)
        self.write_jsonl(mod.CARRIER_FILENAME, [
            self.carrier_row(s1, _iso(1, 11)),
            self.carrier_row(s2, _iso(2, 11)),
        ])
        self.write_json(mod.RUNS_FILENAME, {"max_runs": 30, "runs": [
            self.run_row(r1, "pendle", 13.9),
            self.run_row(r2, "pendle", 14.0),
            self.run_row(r2b, "pendle", 14.4),
            self.run_row(_iso(3, 6, 0, 2), "pendle", 13.5),
            self.run_row(_iso(3, 10, 0, 2), "pendle", 13.7),
        ]})
        self.write_jsonl(mod.DIVERGENCE_FILENAME, [
            self.divergence_row(s1, r1), self.divergence_row(s2, r2)])
        self.write_jsonl(mod.JOURNAL_FILENAME, [
            self.journal_row(D1, ["pendle"]), self.journal_row(D2, ["pendle"]),
            self.journal_row(D3, ["pendle"])])
        # D1 в знаменателе (носитель его касается), D3 в знаменателе (не касается),
        # D2 носитель касается, но знаменателя в нём нет — это слой 4.
        return self.build({D1, D3})

    def test_comparability_is_stated_before_any_difference(self):
        doc = self._full()
        lines = doc["findings"]
        first_move = next(i for i, s in enumerate(lines) if s.startswith("[ДВИЖЕНИЕ]"))
        gate = next(i for i, s in enumerate(lines)
                    if s.startswith("[ПРИГОДНОСТЬ"))
        self.assertLess(gate, first_move)

    def test_the_unrelated_population_control_is_printed_last(self):
        doc = self._full()
        self.assertTrue(doc["findings"][-1].startswith("[КОНТРОЛЬ, НЕСВЯЗАННОЕ"))

    def test_the_unrelated_population_never_leaks_into_the_denominator_layer(self):
        doc = self._full()
        self.assertEqual({m["day"] for m in doc["mechanism"]}, {D1})
        self.assertEqual({m["day"] for m in doc["outside_denominator"]}, {D2})

    def test_a_denominator_day_the_carrier_never_touched_turns_the_verdict_red(self):
        doc = self._full()
        self.assertEqual(doc["status"], mod.STATUS_CRITICAL)
        self.assertTrue(any("ветка мерила ОДИН носитель" in s
                            for s in doc["findings"]))


# ─── отказы входов ─────────────────────────────────────────────────────────────

class RefusalsAreNamed(_Scene):

    def test_no_denominator_produces_no_number_at_all(self):
        doc = self.build(None)
        self.assertEqual(doc["status"], mod.STATUS_UNMEASURED)
        self.assertIsNone(doc["counts"]["denominator_days"])
        self.assertEqual(doc["run_axis"], [])

    def test_no_independent_carrier_is_unmeasured_not_zero_observations(self):
        """Главный отрицательный контроль: без независимого носителя чисел нет."""
        self.write_jsonl(mod.CARRIER_FILENAME,
                         [self.carrier_row(_iso(1, 6), _iso(1, 11))])
        doc = self.build({D1})
        self.assertEqual(doc["status"], mod.STATUS_UNMEASURED)
        self.assertEqual(doc["comparable_axis"], [])
        self.assertTrue(any("ноль здесь был бы выдумкой" in s
                            for s in doc["findings"]))

    def test_unreadable_inputs_are_listed_not_swallowed(self):
        self.write_json(mod.RUNS_FILENAME, {"max_runs": 30, "runs": [
            self.run_row(_iso(1, 6, 0, 2), "pendle", 13.9)]})
        doc = self.build({D1})
        self.assertTrue(any(mod.CARRIER_FILENAME in s for s in doc["unreadable"]))

    def test_broken_jsonl_lines_are_counted_with_a_reason(self):
        path = self.dir / mod.CARRIER_FILENAME
        path.write_text('{"snapshot": "x"}\nNOT JSON\n', encoding="utf-8")
        rows, why = mod._read_jsonl(path)
        self.assertEqual(len(rows), 1)
        self.assertIn("не разобрано 1", why)

    def test_a_run_without_a_timestamp_is_dropped_not_guessed(self):
        runs, earliest, why = mod.independent_runs(
            {"runs": [{"summary": {}}, self.run_row(_iso(1, 6), "pendle", 1.0)],
             "max_runs": 30})
        self.assertEqual(sum(len(v) for v in runs.values()), 1)
        self.assertEqual(earliest, _iso(1, 6))
        self.assertEqual(why, "")

    def test_a_malformed_best_apy_becomes_none_not_a_fabricated_protocol(self):
        runs, _, _ = mod.independent_runs(
            {"runs": [{"run_ts": _iso(1, 6), "summary": {"best_apy": {"protocol": 7}}}],
             "max_runs": 30})
        self.assertIsNone(runs[D1][_iso(1, 6)])

    def test_runs_document_that_is_not_an_object_is_named(self):
        runs, earliest, why = mod.independent_runs(["not", "a", "dict"])
        self.assertEqual(runs, {})
        self.assertIsNone(earliest)
        self.assertIn("не объект", why)


# ─── структурные инварианты ────────────────────────────────────────────────────

class StructuralInvariants(_Scene):

    def test_pair_classes_partition_the_population_exactly(self):
        self.write_json(mod.RUNS_FILENAME, {"max_runs": 30, "runs": [
            self.run_row(_iso(1, 6, 0, 2), "pendle", 13.9),
            self.run_row(_iso(1, 9, 0, 2), "pendle", 14.0)]})
        self.write_jsonl(mod.JOURNAL_FILENAME, [
            self.journal_row(D1, ["pendle", "aave_v3"]),
            self.journal_row(D4, ["pendle", "aave_v3"])])
        doc = self.build({D1, D4})
        classes = {mod.PAIR_JUDGED, mod.PAIR_LEG_NEVER_WINNER,
                   mod.PAIR_ONE_OBSERVATION, mod.PAIR_DAY_OUTSIDE_WINDOW}
        seen = [p["klass"] for p in doc["comparable_axis"]]
        self.assertEqual(len(seen), doc["counts"]["pairs"])
        self.assertTrue(set(seen) <= classes)

    def test_divergence_keys_keep_pairs_by_name_not_two_loose_sets(self):
        l1, r1 = _iso(1, 6), _iso(1, 6, 0, 2)
        l2, r2 = _iso(1, 9), _iso(1, 9, 0, 2)
        _side_a, pairs = mod.divergence_keys([
            self.divergence_row(l1, r1), self.divergence_row(l2, r2)])
        flat = {p for v in pairs.values() for p in v}
        self.assertIn((l1, r1), flat)
        self.assertIn((l2, r2), flat)
        self.assertNotIn((l1, r2), flat)

    def test_a_key_without_a_separator_is_dropped_not_half_read(self):
        side_a, pairs = mod.divergence_keys(
            [{"snapshot_key": _iso(1, 6)}, {"snapshot_key": None}])
        self.assertEqual(side_a, {})
        self.assertEqual(pairs, {})

    def test_carrier_wakeups_keep_both_axes_apart(self):
        rows = [self.carrier_row(_iso(1, 6), _iso(1, 11))]
        snaps = mod.carrier_snapshots(rows)
        wake = mod.carrier_wakeups(rows)
        self.assertEqual(snaps[D1], {_iso(1, 6)})
        self.assertEqual(wake[D1][_iso(1, 6)], _iso(1, 11))
        self.assertNotEqual(_iso(1, 6), _iso(1, 11))

    def test_run_with_write_false_leaves_the_directory_untouched(self):
        self.write_json(mod.RUNS_FILENAME, {"max_runs": 30, "runs": [
            self.run_row(_iso(1, 6, 0, 2), "pendle", 13.9)]})
        before = sorted(p.name for p in self.dir.iterdir())
        original = mod.scored_days
        mod.scored_days = lambda _d: {D1}  # type: ignore[assignment]
        try:
            mod.run(str(self.dir), write=False, now=ANCHOR)
        finally:
            mod.scored_days = original  # type: ignore[assignment]
        self.assertEqual(sorted(p.name for p in self.dir.iterdir()), before)

    def test_margins_are_read_by_key_and_a_missing_one_is_simply_absent(self):
        margins = mod.stability_margins(
            {"protocols": [{"protocol": "aave_v3", "margin_pp": 0.8},
                           {"protocol": "sky_susds", "margin_pp": None}]})
        self.assertEqual(margins, {"aave_v3": 0.8})


# ─── вытеснение на границе кольцевого буфера (замер #562) ──────────────────────

class BoundaryOfASaturatedBufferIsAFloor(_Scene):
    """Авария, которую эти сцены воспроизводят, ИЗМЕРЕНА, а не придумана.

    Цикл #561 намерил на граничном дне буфера **10** прогонов и записал это число
    в ADR-321 как счёт. Цикл #562 на том же неизменном коде намерил **9**. Код не
    менялся ни на байт — сменилось наполнение кольцевого буфера: новый прогон
    вытеснил старый с головы (`runs[-max_runs:]`). Это тот же класс, что
    литеральный pid и замороженная дата из `.claude/rules/deployment.md`, только
    счётчик третий: вердикт решает окружение.

    День СТАРШЕ границы прибор и раньше называл неизмеримым честно. Дыра была
    ровно в один день — в САМ граничный, который проваливался в `measured` с
    `reason: None`, то есть нижняя граница выдавалась за счёт.
    """

    def test_boundary_day_of_a_full_buffer_is_marked_a_floor(self):
        """Положительный контроль: ровно та сцена, на которой 10 стало 9."""
        rows = mod.run_axis([D1], {}, {D1: {_iso(1, h): None for h in (3, 6, 9)}},
                            _iso(1, 3), saturated=True)
        self.assertEqual(rows[0]["klass"], mod.DAY_BOUNDARY_TRUNCATED)
        self.assertTrue(rows[0]["runs_provable_is_floor"])
        self.assertIn("нижняя граница", rows[0]["reason"])

    def test_boundary_day_of_a_buffer_with_room_stays_measured(self):
        """ОБРАТНЫЙ контроль, и без него проверка была бы украшением.

        Пока буфер не полон, вытеснения не было и самый ранний день измерен
        целиком. Метить срезанным любой ранний день — та же выдумка, только в
        другую сторону; поэтому признак берётся из НАПОЛНЕНИЯ, а не из даты.
        """
        rows = mod.run_axis([D1], {}, {D1: {_iso(1, h): None for h in (3, 6, 9)}},
                            _iso(1, 3), saturated=False)
        self.assertEqual(rows[0]["klass"], mod.DAY_MEASURED)
        self.assertFalse(rows[0]["runs_provable_is_floor"])
        self.assertIsNone(rows[0]["reason"])

    def test_unmeasured_saturation_does_not_invent_truncation(self):
        """`None` — «не померили наполнение», и срез отсюда не приписывается."""
        rows = mod.run_axis([D1], {}, {D1: {_iso(1, 3): None}}, _iso(1, 3),
                            saturated=None)
        self.assertEqual(rows[0]["klass"], mod.DAY_MEASURED)

    def test_a_day_older_than_the_boundary_is_still_unmeasured_when_saturated(self):
        """Насыщение не отменяет прежний третий исход, а ДОБАВЛЯЕТ соседний."""
        rows = mod.run_axis([D4], {}, {D1: {_iso(1, 6): None}}, _iso(1, 6),
                            saturated=True)
        self.assertEqual(rows[0]["klass"], mod.DAY_UNMEASURED_WINDOW)
        self.assertIsNone(rows[0]["runs_provable"])

    def test_truncated_day_keeps_contributing_its_proven_observations(self):
        """Зеркальная ошибка: выкинуть срезанный день из счёта.

        Девять наблюдений на граничном дне ДОКАЗАНЫ — вытеснение забрало то, чего
        мы не видели, а не то, что видели. Перестать их считать значило бы молча
        стереть доказанное, то есть ошибиться в ту же цену, что и выдав нижнюю
        границу за счёт.
        """
        self.write_jsonl(mod.CARRIER_FILENAME, [])
        self.write_json(mod.RUNS_FILENAME, {"max_runs": 3, "runs": [
            self.run_row(_iso(1, h), "pendle", 13.9) for h in (3, 6, 9)]})
        original = mod.scored_days
        mod.scored_days = lambda _d: {D1}  # type: ignore[assignment]
        try:
            doc = mod.build(self.dir, now=ANCHOR)
        finally:
            mod.scored_days = original  # type: ignore[assignment]
        self.assertTrue(doc["buffer"]["saturated"])
        self.assertEqual(doc["counts"]["days_boundary_truncated"], 1)
        self.assertEqual(doc["counts"]["runs_provable_outside_carrier"], 3)
        self.assertTrue(doc["counts"]["runs_provable_outside_carrier_is_floor"])
        self.assertTrue(any("НИЖНЯЯ ГРАНИЦА" in f for f in doc["findings"]))


class BufferSaturationIsMeasuredNotAssumed(_Scene):

    def test_full_buffer_is_saturated(self):
        self.assertIs(mod.buffer_saturated(
            {"max_runs": 2, "runs": [{"run_ts": _iso(1, 3)},
                                     {"run_ts": _iso(1, 6)}]}), True)

    def test_buffer_with_room_is_not_saturated(self):
        self.assertIs(mod.buffer_saturated(
            {"max_runs": 5, "runs": [{"run_ts": _iso(1, 3)}]}), False)

    def test_missing_max_runs_is_a_third_outcome_not_false(self):
        """`False` означал бы «вытеснения точно не было» — утверждение без замера."""
        self.assertIsNone(mod.buffer_saturated({"runs": []}))
        self.assertIsNone(mod.buffer_saturated({"max_runs": 0, "runs": []}))
        self.assertIsNone(mod.buffer_saturated(["not", "a", "dict"]))

    def test_boolean_max_runs_is_refused(self):
        """`True` есть `int` в Python, и как глубина буфера он бессмыслен."""
        self.assertIsNone(mod.buffer_saturated({"max_runs": True, "runs": []}))


class TruncationMustNotMisrouteTheRepair(_Scene):
    """У путаницы на оси пригодности есть ЦЕНА, и она — не косметическая.

    `one_observation` чинится частотой опроса, `day_outside_window` — глубиной
    буфера. На срезанном дне «наблюдение одно» и «второе вытеснено» неразличимы,
    и записать там `one_observation` значит послать ремонт не к тому рычагу —
    выдав догадку за факт.
    """

    def _axis(self, runs, legs, saturated):
        return mod.comparable_axis([D1], {D1: legs}, {D1: runs}, {},
                                   _iso(1, 3), saturated=saturated)

    def test_single_observation_on_a_truncated_day_is_not_blamed_on_polling(self):
        rows = self._axis({_iso(1, 3): ("pendle", 13.9)}, ["pendle"],
                          saturated=True)
        self.assertEqual(rows[0]["klass"], mod.PAIR_DAY_BOUNDARY_TRUNCATED)

    def test_same_scene_on_an_unsaturated_buffer_is_one_observation(self):
        """Обратный контроль: без вытеснения вывод «наблюдение одно» ВЕРЕН."""
        rows = self._axis({_iso(1, 3): ("pendle", 13.9)}, ["pendle"],
                          saturated=False)
        self.assertEqual(rows[0]["klass"], mod.PAIR_ONE_OBSERVATION)

    def test_two_survivors_are_still_judged_on_a_truncated_day(self):
        """Вытеснение умеет только УБИРАТЬ: два уцелевших значения остаются двумя."""
        rows = self._axis({_iso(1, 3): ("pendle", 13.9),
                           _iso(1, 6): ("pendle", 14.1)}, ["pendle"],
                          saturated=True)
        self.assertEqual(rows[0]["klass"], mod.PAIR_JUDGED)
        self.assertEqual(rows[0]["range_pp"], 0.2)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
