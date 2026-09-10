"""Сторож прибора «сколько снимков видит запись» (заказ #550/#551, ADR-314).

Каждый тест — либо воспроизведение настоящего замера 10.09, либо ГРАНИЦА порога.
Условие цикла #551 к приёмке: у каждого порога проверяется САМА граница
(равенство), а не две точки далеко по разные стороны — «N из N красных» есть
утверждение о списке, который составил автор, и оно молчит о координатах,
которых в списке нет.

Часы инъектируются (`measure(..., now=)`), и ВСЕ отметки фикстур строятся от
одного якоря — обе стороны закреплены, календарь на вердикт не влияет.
FROZEN-DATE-OK: injected-clock — якорь ANCHOR передаётся в measure(now=) и от
него же производятся все отметки фикстур (cycle_start, снимки, generated_at).
"""
# LLM_FORBIDDEN
from __future__ import annotations

import json
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

from spa_core.monitoring import decision_record_run_identity as M

ANCHOR = datetime(2026, 9, 8, 6, 0, 0, tzinfo=timezone.utc)
DAY = ANCHOR.date().isoformat()


def ts(**kw) -> str:
    return (ANCHOR + timedelta(**kw)).isoformat()


def record(*, generated_at: str, evidenced=None, day: str = DAY) -> dict:
    return {
        "schema": "shadow-hist-v2",
        "cycle_date": day,
        "generated_at": generated_at,
        "apy_evidenced_pct": dict(evidenced or {}),
    }


def start_event(corr: str, stamp: str) -> dict:
    return {"correlation_id": corr, "event_type": M.EVENT_CYCLE_START,
            "timestamp": stamp}


def proposal_event(corr: str, stamp: str, target: dict) -> dict:
    return {"correlation_id": corr, "event_type": M.EVENT_PROPOSAL,
            "timestamp": stamp, "data": {"target_usd": target}}


def observation(snapshot: str, adapter: str, apy) -> dict:
    return {"observed_at": snapshot, "snapshot": snapshot, "kind": "hint_winner",
            "adapter": adapter, "apy": apy}


class Tree:
    """Одноразовое `data/`. Живое дерево не открывается ни на чтение, ни на запись."""

    def __init__(self) -> None:
        self._tmp = TemporaryDirectory()
        self.data = Path(self._tmp.name) / "data"
        self.data.mkdir(parents=True)

    def write(self, name: str, rows) -> None:
        if name.endswith(".jsonl"):
            (self.data / name).write_text(
                "".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
        else:
            (self.data / name).write_text(json.dumps(rows), encoding="utf-8")

    def measure(self) -> dict:
        return M.measure(self.data, now=ANCHOR + timedelta(days=1))

    def close(self) -> None:
        self._tmp.cleanup()


class RunIdentityBase(unittest.TestCase):
    def setUp(self) -> None:
        self.tree = Tree()
        self.addCleanup(self.tree.close)

    def day_entry(self, doc: dict, day: str = DAY) -> dict:
        for entry in doc.get("days") or []:
            if entry["cycle_date"] == day:
                return entry
        self.fail(f"дня {day} нет в замере")


class TestRunPairingBoundary(RunIdentityBase):
    """Граница окна опознания прогона — САМА граница, а не две точки по бокам."""

    def _delta(self, seconds: float) -> dict:
        gen = ts(seconds=0)
        self.tree.write("allocation_rationale_history.jsonl",
                        [record(generated_at=gen)])
        self.tree.write("audit_trail.jsonl",
                        [start_event("c1", ts(seconds=seconds))])
        return self.day_entry(self.tree.measure())["run"]

    def test_delta_exactly_at_tolerance_is_identified(self):
        """Ровно PAIR_TOLERANCE_S — ВНУТРИ: граница объявлена включающей."""
        self.assertEqual(self._delta(M.PAIR_TOLERANCE_S)["verdict"],
                         M.RUN_IDENTIFIED)

    def test_delta_just_past_tolerance_is_not_identified(self):
        self.assertEqual(self._delta(M.PAIR_TOLERANCE_S + 0.001)["verdict"],
                         M.RUN_NO_START)

    def test_negative_delta_exactly_at_tolerance_is_identified(self):
        """Окно симметрично: запись позже старта на ровно допуск — тоже опознание."""
        self.assertEqual(self._delta(-M.PAIR_TOLERANCE_S)["verdict"],
                         M.RUN_IDENTIFIED)

    def test_zero_delta_is_equal_not_earlier(self):
        """Граница ориентации: Δ=0 не есть «раньше» и не есть «позже»."""
        self.assertEqual(self._delta(0.0)["orientation"], M.ORIENT_EQUAL)

    def test_positive_delta_is_record_earlier(self):
        self.assertEqual(self._delta(0.5)["orientation"], M.ORIENT_RECORD_EARLIER)

    def test_negative_delta_is_record_later(self):
        self.assertEqual(self._delta(-0.5)["orientation"], M.ORIENT_RECORD_LATER)


class TestValueMatchBoundary(RunIdentityBase):
    """Граница сравнения ставок — САМА граница, и она есть сетка округления.

    Отдельного эпсилона у сравнения нет намеренно: при округлении до
    ``VALUE_ROUND`` граница «почти равно» недостижима по построению, и тест на
    неё был бы истинным всегда — украшением, а не контролем (замер батареи #552).
    Настоящая граница — ЕДИНИЦА последнего разряда: на ней совпадения быть уже
    не должно, а на половине единицы округление ещё сводит числа.
    """

    UNIT = 10 ** -M.VALUE_ROUND

    def _match(self, offset: float) -> dict:
        snap = ts(hours=2)
        self.tree.write("allocation_rationale_history.jsonl",
                        [record(generated_at=ts(seconds=0),
                                evidenced={"aave_v3": 4.0 + offset})])
        self.tree.write("audit_trail.jsonl", [start_event("c1", ts(seconds=0))])
        self.tree.write("apy_composition_log.jsonl",
                        [observation(snap, "aave_v3", 4.0)])
        return self.day_entry(self.tree.measure())["snapshot"]

    def test_exact_equality_matches(self):
        self.assertEqual(self._match(0.0)["verdict"], M.SNAP_SINGLE)

    def test_one_unit_of_the_last_place_does_not_match(self):
        """Ровно единица последнего разряда — уже РАЗНЫЕ ставки."""
        self.assertEqual(self._match(self.UNIT)["verdict"], M.SNAP_NO_MATCH)

    def test_below_half_a_unit_is_the_same_rate_after_rounding(self):
        """Ниже половины единицы округление сводит числа — это ОДНА ставка."""
        self.assertEqual(self._match(self.UNIT / 4)["verdict"], M.SNAP_SINGLE)

    def test_difference_far_past_the_grid_does_not_match(self):
        self.assertEqual(self._match(0.001)["verdict"], M.SNAP_NO_MATCH)


class TestReplacementBoundary(RunIdentityBase):
    """Граница «день затёрт» — РОВНО MIN_RUNS_FOR_REPLACEMENT прогонов."""

    def _runs(self, n: int) -> dict:
        gen = ts(hours=n - 1)
        events = [start_event(f"c{i}", ts(hours=i)) for i in range(n)]
        self.tree.write("allocation_rationale_history.jsonl",
                        [record(generated_at=gen)])
        self.tree.write("audit_trail.jsonl", events)
        return self.tree.measure()["population"]

    def test_exactly_min_runs_counts_as_replacement(self):
        pop = self._runs(M.MIN_RUNS_FOR_REPLACEMENT)
        self.assertEqual(pop["days_with_replacement"], 1)
        self.assertEqual(pop["runs_not_in_journal"],
                         M.MIN_RUNS_FOR_REPLACEMENT - 1)

    def test_one_below_min_runs_is_not_a_replacement(self):
        pop = self._runs(M.MIN_RUNS_FOR_REPLACEMENT - 1)
        self.assertEqual(pop["days_with_replacement"], 0)
        self.assertEqual(pop["runs_not_in_journal"], 0)


class TestTheTrapIsMeasuredNotAssumed(RunIdentityBase):
    """Главный предмет заказа: снимок НОВЕЕ записи — и запись его прочитала."""

    def _live_day(self, *, snapshot_offset_s: float, apy: float) -> dict:
        gen = ts(seconds=0)
        self.tree.write("allocation_rationale_history.jsonl",
                        [record(generated_at=gen, evidenced={"aave_v3": 3.7124})])
        self.tree.write("audit_trail.jsonl", [start_event("c1", ts(seconds=0.001))])
        self.tree.write("adapter_orchestrator_status.json", {
            "generated_at": ts(seconds=snapshot_offset_s),
            "adapters": [{"protocol": "aave_v3", "apy_pct": apy}],
        })
        return self.tree.measure()

    def test_newer_snapshot_with_equal_values_raises_the_trap_finding(self):
        """ПОЛОЖИТЕЛЬНЫЙ КОНТРОЛЬ: воспроизведение замера 10.09 (Δ=+2.805 с, 9/9)."""
        doc = self._live_day(snapshot_offset_s=2.805, apy=3.7124)
        live = self.day_entry(doc)["live_snapshot"]
        self.assertTrue(live["snapshot_newer_than_record"])
        self.assertEqual(live["legs_equal"], 1)
        self.assertEqual(live["legs_differ"], 0)
        self.assertTrue(any("прямой контроль на ловушку" in f
                            for f in doc["findings"]))
        self.assertEqual(doc["status"], M.STATUS_CRITICAL)

    def test_newer_snapshot_with_different_values_does_not_raise_it(self):
        """ОТРИЦАТЕЛЬНЫЙ КОНТРОЛЬ: одной новизны мало, нужно совпадение значений."""
        doc = self._live_day(snapshot_offset_s=2.805, apy=9.9999)
        live = self.day_entry(doc)["live_snapshot"]
        self.assertTrue(live["snapshot_newer_than_record"])
        self.assertEqual(live["legs_equal"], 0)
        self.assertFalse(any("прямой контроль на ловушку" in f
                             for f in doc["findings"]))

    def test_snapshot_exactly_as_old_as_record_is_not_newer(self):
        """Граница новизны: Δ=0 — снимок НЕ новее."""
        doc = self._live_day(snapshot_offset_s=0.0, apy=3.7124)
        self.assertFalse(self.day_entry(doc)["live_snapshot"]
                         ["snapshot_newer_than_record"])

    def test_snapshot_of_another_day_does_not_testify(self):
        """Носитель перезаписывается: о чужом дне он свидетельствовать не вправе."""
        self.tree.write("allocation_rationale_history.jsonl",
                        [record(generated_at=ts(seconds=0),
                                evidenced={"aave_v3": 3.7124})])
        self.tree.write("audit_trail.jsonl", [start_event("c1", ts(seconds=0.001))])
        self.tree.write("adapter_orchestrator_status.json", {
            "generated_at": ts(days=3),
            "adapters": [{"protocol": "aave_v3", "apy_pct": 3.7124}],
        })
        self.assertNotIn("live_snapshot", self.day_entry(self.tree.measure()))


class TestRecordStampIsTheCycleStart(RunIdentityBase):
    """Ответ ADR-314: отметка записи — отметка НАЧАЛА её собственного прогона."""

    def _three_days(self, offset_s: float) -> dict:
        history, audit = [], []
        for i in range(3):
            day = (ANCHOR + timedelta(days=i)).date().isoformat()
            gen = (ANCHOR + timedelta(days=i)).isoformat()
            history.append(record(generated_at=gen, day=day))
            audit.append(start_event(
                f"c{i}", (ANCHOR + timedelta(days=i, seconds=offset_s)).isoformat()))
        self.tree.write("allocation_rationale_history.jsonl", history)
        self.tree.write("audit_trail.jsonl", audit)
        return self.tree.measure()

    def test_all_days_earlier_raises_the_critical(self):
        doc = self._three_days(+0.001)
        self.assertEqual(doc["population"]["orientations"],
                         {M.ORIENT_RECORD_EARLIER: 3})
        self.assertTrue(any("отметка записи есть отметка НАЧАЛА" in f
                            for f in doc["findings"]))

    def test_records_later_than_their_runs_do_not_raise_it(self):
        """ОТРИЦАТЕЛЬНЫЙ КОНТРОЛЬ: обратный знак — и claim не выдаётся."""
        doc = self._three_days(-0.001)
        self.assertEqual(doc["population"]["orientations"],
                         {M.ORIENT_RECORD_LATER: 3})
        self.assertFalse(any("отметка записи есть отметка НАЧАЛА" in f
                             for f in doc["findings"]))

    def test_a_mixed_population_downgrades_the_claim_to_info(self):
        """Claim про 100 % обязан УМЕРЕТЬ, как только хоть один день против.

        Без этого теста «на N днях из N» не отличается от «хотя бы на одном»:
        батарея #552 показала, что ослабление `earlier == identified` до
        `earlier >= 1` не краснело — оба контроля были чистыми по знаку и ни
        один не был СМЕШАННЫМ.
        """
        history, audit = [], []
        for i, offset in enumerate((+0.001, +0.001, -0.001)):
            day = (ANCHOR + timedelta(days=i)).date().isoformat()
            history.append(record(generated_at=(ANCHOR + timedelta(days=i)).isoformat(),
                                  day=day))
            audit.append(start_event(
                f"c{i}", (ANCHOR + timedelta(days=i, seconds=offset)).isoformat()))
        self.tree.write("allocation_rationale_history.jsonl", history)
        self.tree.write("audit_trail.jsonl", audit)
        doc = self.tree.measure()
        self.assertEqual(doc["population"]["orientations"],
                         {M.ORIENT_RECORD_EARLIER: 2, M.ORIENT_RECORD_LATER: 1})
        self.assertFalse(any("отметка записи есть отметка НАЧАЛА" in f
                             for f in doc["findings"]))
        self.assertTrue(any(f.startswith("[ИНФО]") and "предшествует старту" in f
                            for f in doc["findings"]))

    def test_survivor_is_the_last_run_of_the_day(self):
        gen = ts(hours=11)
        self.tree.write("allocation_rationale_history.jsonl",
                        [record(generated_at=gen)])
        self.tree.write("audit_trail.jsonl", [
            start_event("early", ts(hours=0)),
            start_event("mid", ts(hours=4)),
            start_event("late", ts(hours=11, seconds=0.001)),
        ])
        run = self.day_entry(self.tree.measure())["run"]
        self.assertEqual(run["verdict"], M.RUN_IDENTIFIED)
        self.assertEqual(run["position"], M.POS_LAST)
        self.assertEqual(run["runs_that_day"], 3)


class TestSnapshotIdentification(RunIdentityBase):
    """Опознание снимка по значению: один · склейка · неоднозначность · отказ."""

    def _snapshot_day(self, evidenced: dict, observations) -> dict:
        self.tree.write("allocation_rationale_history.jsonl",
                        [record(generated_at=ts(seconds=0), evidenced=evidenced)])
        self.tree.write("audit_trail.jsonl", [start_event("c1", ts(seconds=0.001))])
        self.tree.write("apy_composition_log.jsonl", observations)
        return self.day_entry(self.tree.measure())["snapshot"]

    def test_legs_pointing_at_one_snapshot_identify_it(self):
        """Замер 08.09: три ноги указали на ТРЕТИЙ снимок и ни одна на первые два."""
        s1, s2, s3 = ts(hours=0), ts(hours=4, minutes=41), ts(hours=11, minutes=27)
        snap = self._snapshot_day(
            {"aave_v3": 3.61, "compound_v3": 4.6454, "morpho_blue": 4.2907},
            [observation(s1, "aave_v3", 12.7651),
             observation(s2, "aave_v3", 3.6298),
             observation(s3, "aave_v3", 3.61),
             observation(s1, "compound_v3", 4.1962),
             observation(s2, "compound_v3", 5.1355),
             observation(s3, "compound_v3", 4.6454),
             observation(s1, "morpho_blue", 4.2879),
             observation(s2, "morpho_blue", 4.2945),
             observation(s3, "morpho_blue", 4.2907)])
        self.assertEqual(snap["verdict"], M.SNAP_SINGLE)
        self.assertEqual(snap["snapshot"], s3)
        self.assertEqual(snap["legs_matched"], 3)
        self.assertTrue(snap["snapshot_is_last_known"])

    def test_legs_pointing_at_different_snapshots_are_mixed(self):
        s1, s2 = ts(hours=0), ts(hours=6)
        snap = self._snapshot_day(
            {"aave_v3": 1.0, "compound_v3": 2.0},
            [observation(s1, "aave_v3", 1.0), observation(s2, "aave_v3", 9.0),
             observation(s1, "compound_v3", 8.0), observation(s2, "compound_v3", 2.0)])
        self.assertEqual(snap["verdict"], M.SNAP_MIXED)
        self.assertEqual(len(snap["snapshots_pointed_to"]), 2)

    def test_value_present_in_two_snapshots_identifies_nothing(self):
        """Ставка не двигалась ⇒ нога неоднозначна, а не «опознала первый»."""
        s1, s2 = ts(hours=0), ts(hours=6)
        snap = self._snapshot_day(
            {"aave_v3": 1.0},
            [observation(s1, "aave_v3", 1.0), observation(s2, "aave_v3", 1.0)])
        self.assertEqual(snap["verdict"], M.SNAP_NO_MATCH)
        self.assertEqual(snap["legs_ambiguous_value"], 1)
        self.assertEqual(snap["legs_matched"], 0)

    def test_no_match_is_a_third_outcome_not_a_hole(self):
        s1 = ts(hours=0)
        snap = self._snapshot_day({"aave_v3": 5.2651},
                                  [observation(s1, "aave_v3", 2.5804)])
        self.assertEqual(snap["verdict"], M.SNAP_NO_MATCH)
        self.assertEqual(snap["legs_unmatched"], 1)

    def test_boolean_apy_is_not_a_rate(self):
        """`True` прошла бы как 1.0 и опознала снимок ставкой, которой нет.

        День намеренно несёт ВТОРУЮ, настоящую строку наблюдения: без неё
        носитель не знал бы за день ни одного снимка, и тест зеленел бы на
        отказе «носителя нет» — то есть проверял бы не то, что заявляет.
        """
        s1 = ts(hours=0)
        snap = self._snapshot_day(
            {"aave_v3": 1.0},
            [observation(s1, "aave_v3", True),
             observation(s1, "compound_v3", 4.0)])
        self.assertEqual(snap["snapshots_known_that_day"], 1)
        self.assertEqual(snap["verdict"], M.SNAP_NO_MATCH)
        self.assertEqual(snap["legs_matched"], 0)


class TestThirdOutcomes(RunIdentityBase):
    """«Не измерено» отдельно от нуля — иначе молчание неотличимо от чистоты."""

    def test_day_without_run_carrier_is_unmeasured(self):
        self.tree.write("allocation_rationale_history.jsonl",
                        [record(generated_at=ts(seconds=0))])
        self.tree.write("audit_trail.jsonl", [])
        doc = self.tree.measure()
        self.assertEqual(self.day_entry(doc)["run"]["verdict"], M.RUN_NO_CARRIER)
        self.assertEqual(doc["status"], M.STATUS_UNMEASURED)
        self.assertTrue(any(f.startswith("[НЕ ИЗМЕРЕНО]") for f in doc["findings"]))

    def test_two_starts_inside_the_window_are_ambiguous_not_nearest(self):
        self.tree.write("allocation_rationale_history.jsonl",
                        [record(generated_at=ts(seconds=0))])
        self.tree.write("audit_trail.jsonl", [
            start_event("a", ts(seconds=0.1)),
            start_event("b", ts(seconds=0.2)),
        ])
        run = self.day_entry(self.tree.measure())["run"]
        self.assertEqual(run["verdict"], M.RUN_AMBIGUOUS)
        self.assertEqual(run["candidates"], 2)

    def test_empty_journal_is_unmeasured_not_ok(self):
        self.tree.write("allocation_rationale_history.jsonl", [])
        doc = self.tree.measure()
        self.assertEqual(doc["status"], M.STATUS_UNMEASURED)
        self.assertIn("why_unmeasured", doc)

    def test_mandatory_office_keys_survive_an_empty_input(self):
        """Ключи схемы шага 0-офис есть и на пустом входе.

        Артефакт, потерявший `days`/`population`, шаг 0-офис прочитал бы как
        нарушение схемы, а читатель — как «поле не заполнено» вместо «мерить
        было нечего».
        """
        self.tree.write("allocation_rationale_history.jsonl", [])
        doc = self.tree.measure()
        for key in ("status", "journal_rows", "population", "days",
                    "findings", "does_not_report"):
            self.assertIn(key, doc, key)
        self.assertEqual(doc["days"], [])
        self.assertEqual(doc["population"]["journal_days"], 0)

    def test_unreadable_jsonl_line_is_skipped_not_fatal(self):
        (self.tree.data / "allocation_rationale_history.jsonl").write_text(
            "{не json\n" + json.dumps(record(generated_at=ts(seconds=0))) + "\n",
            encoding="utf-8")
        self.tree.write("audit_trail.jsonl", [start_event("c1", ts(seconds=0.001))])
        self.assertEqual(self.tree.measure()["journal_rows"], 1)

    def test_run_without_cycle_start_is_not_a_run(self):
        """Опознание идёт по cycle_start; прогон без него опознать нечем."""
        self.tree.write("allocation_rationale_history.jsonl",
                        [record(generated_at=ts(seconds=0))])
        self.tree.write("audit_trail.jsonl",
                        [proposal_event("c1", ts(seconds=0.001), {"aave_v3": 1.0})])
        self.assertEqual(self.day_entry(self.tree.measure())["run"]["verdict"],
                         M.RUN_NO_CARRIER)


class TestHiddenTargetsAreABoundNotAClaim(RunIdentityBase):
    def test_distinct_live_targets_are_counted_per_day(self):
        gen = ts(hours=2)
        self.tree.write("allocation_rationale_history.jsonl",
                        [record(generated_at=gen)])
        self.tree.write("audit_trail.jsonl", [
            start_event("a", ts(hours=0)),
            proposal_event("a", ts(hours=0, seconds=20), {"aave_v3": 100.0}),
            start_event("b", ts(hours=1)),
            proposal_event("b", ts(hours=1, seconds=20), {"aave_v3": 100.0}),
            start_event("c", ts(hours=2, seconds=0.001)),
            proposal_event("c", ts(hours=2, seconds=20), {"aave_v3": 200.0}),
        ])
        pop = self.tree.measure()["population"]
        # Три прогона, но РАЗНЫХ целей две ⇒ скрыта одна, а не две.
        self.assertEqual(pop["runs_not_in_journal"], 2)
        self.assertEqual(pop["hidden_distinct_live_targets"], 1)

    def test_shadow_targets_lost_are_declared_unreportable(self):
        """Единственный носитель теневой цели — строка, которую замена стёрла."""
        self.tree.write("allocation_rationale_history.jsonl",
                        [record(generated_at=ts(seconds=0))])
        self.tree.write("audit_trail.jsonl", [start_event("c1", ts(seconds=0.001))])
        doc = self.tree.measure()
        self.assertIn("ТЕНЕВЫХ", doc["does_not_report"])


class TestArtifactHygiene(RunIdentityBase):
    def test_run_writes_only_its_own_artifact(self):
        self.tree.write("allocation_rationale_history.jsonl",
                        [record(generated_at=ts(seconds=0))])
        self.tree.write("audit_trail.jsonl", [start_event("c1", ts(seconds=0.001))])
        before = {p.name for p in self.tree.data.iterdir()}
        M.run(root=str(self.tree.data.parent), now=ANCHOR + timedelta(days=1))
        after = {p.name for p in self.tree.data.iterdir()}
        self.assertEqual(after - before, {M.OUTPUT_FILENAME})

    def test_run_reports_counts_and_overall(self):
        self.tree.write("allocation_rationale_history.jsonl",
                        [record(generated_at=ts(seconds=0))])
        self.tree.write("audit_trail.jsonl", [start_event("c1", ts(seconds=0.001))])
        doc = M.run(root=str(self.tree.data.parent),
                    now=ANCHOR + timedelta(days=1), write=False)
        self.assertEqual(doc["overall"], doc["status"])
        self.assertEqual(set(doc["counts"]), {"critical", "warn", "info", "unchecked"})

    def test_unmeasured_is_counted_as_unchecked_not_as_zero(self):
        self.tree.write("allocation_rationale_history.jsonl", [])
        doc = M.run(root=str(self.tree.data.parent),
                    now=ANCHOR + timedelta(days=1), write=False)
        self.assertEqual(doc["overall"], M.STATUS_UNMEASURED)
        self.assertGreaterEqual(doc["counts"]["unchecked"], 1)

    def test_format_report_prints_population_before_verdicts(self):
        self.tree.write("allocation_rationale_history.jsonl",
                        [record(generated_at=ts(seconds=0))])
        self.tree.write("audit_trail.jsonl", [start_event("c1", ts(seconds=0.001))])
        lines = M.format_report(self.tree.measure())
        self.assertIn("дней журнала", lines[0])
        self.assertTrue(any("ADVISORY" in x for x in lines))

    def test_measure_takes_the_clock_as_an_input(self):
        self.tree.write("allocation_rationale_history.jsonl",
                        [record(generated_at=ts(seconds=0))])
        self.tree.write("audit_trail.jsonl", [start_event("c1", ts(seconds=0.001))])
        pinned = datetime(2031, 1, 2, 3, 4, 5, tzinfo=timezone.utc)
        self.assertEqual(M.measure(self.tree.data, now=pinned)["generated_at"],
                         pinned.isoformat())


class TestRunIndexHygiene(unittest.TestCase):
    def test_day_comes_from_cycle_start_not_from_every_event(self):
        """Прогон через полночь не удваивает население, попадая в оба дня."""
        rows = [
            start_event("c1", "2026-09-08T23:59:59+00:00"),
            proposal_event("c1", "2026-09-09T00:00:20+00:00", {"aave_v3": 1.0}),
        ]
        index = M.run_index(rows)
        self.assertEqual(sorted(index), ["2026-09-08"])
        self.assertEqual(len(index["2026-09-08"]["c1"]["proposals"]), 1)

    def test_repeated_cycle_start_keeps_the_earliest(self):
        rows = [
            start_event("c1", "2026-09-08T10:00:00+00:00"),
            start_event("c1", "2026-09-08T06:00:00+00:00"),
        ]
        index = M.run_index(rows)
        self.assertEqual(index["2026-09-08"]["c1"]["cycle_start"],
                         "2026-09-08T06:00:00+00:00")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
