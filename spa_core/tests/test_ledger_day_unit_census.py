"""Единица у читателей ленты вердиктов: запись или день (ADR-766, заказ G765 п. 3).

Каждый тест здесь — положительный контроль на НАСТОЯЩИЙ замер 16.10, а не
украшение:

* лента рукава несёт **16.16 записи на день** (727 записей / 45 дней; за 15.10
  — 24), лента Conservative — 1.92 (138 / 72). Прибор, считающий записи и
  говорящий «дни», завышает на рукавах в ~16 раз, и завышает МОЛЧА;
* выдача владельцу (`cio_brief`) после ADR-765 считает ДНИ в числителе, но
  серию по-прежнему обрывает ЗАПИСЬ: на одних и тех же днях с той же решающей
  строкой дня `unchanged_days` даёт **37** при одном прогоне в дне и **14** при
  двадцати четырёх. Это и есть находка переписи;
* `target_stability.observed_days` движется от ОДНОЙ ЛИШЬ плотности — число
  называется днями, а меряет записи.

Дат-литералов в файле нет намеренно: все даты и отметки производны от часов
прогона либо от инъектированного `now` — приёмы №1 и №2
`.claude/rules/deployment.md`. Красная сторона каждой проверки воспроизводит
ДОСОБЫТИЙНУЮ форму ответа (поле считается в записях), потому что именно она и
была дефектом.
"""
from __future__ import annotations

import json
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

from spa_core.monitoring import ledger_day_unit_census as cen
from spa_core.monitoring.run_identity_key_price import (
    CAUSE_RESTS_ON_UNSTABLE,
    CAUSE_SELF,
    CAUSE_WOULD_ACT,
)
from spa_core.paper_trading.allocation_rationale import history_filename, run_identity


def _now() -> datetime:
    """Часы прогона — ВХОД тестов; литеральной даты в файле нет."""
    return datetime.now(timezone.utc).replace(microsecond=0)


def _day(now: datetime, back: int) -> str:
    return (now - timedelta(days=back)).date().isoformat()


def _stamp(now: datetime, back_days: int, hour: int) -> str:
    return (now - timedelta(days=back_days)).replace(
        hour=hour, minute=0, second=0, microsecond=0).isoformat()


def _rec(now: datetime, back: int, hour: int, **over) -> dict:
    """Строка ленты в той же схеме, что пишет настоящий писатель."""
    day = _day(now, back)
    rec = {
        "schema": "shadow-hist-v2",
        "cycle_date": day,
        "decision_id": f"adr060-shadow-{day}",
        "generated_at": _stamp(now, back, hour),
        "verdict": "HOLD",
        "gates": {"has_legs": False},
        "legs": [],
        "reasons": [],
        "current_positions": {"aave_v3": 100.0},
        "target_positions": {"aave_v3": 100.0},
        "book_apy_pp": 4.0,
        "target_apy_pp": 4.0,
        "gain_pp": 0.0,
        "capital_usd": 100.0,
        "turnover_frac": 0.0,
        "mode": "paper",
        "policy_version": "v1.0",
        "warnings_count": 0,
    }
    rec.update(over)
    return rec


def _write_tape(data_dir: Path, book_id, rows) -> Path:
    path = Path(data_dir) / history_filename(book_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "\n".join(json.dumps(r, sort_keys=True, default=str) for r in rows) + "\n",
        encoding="utf-8")
    return path


class ThickenInvariants(unittest.TestCase):
    """Стенды различаются РОВНО плотностью — иначе вывод переписи ни о чём."""

    def setUp(self) -> None:
        self.now = _now()
        self.rows = [
            _rec(self.now, 3, 6),
            _rec(self.now, 2, 6, verdict="ACT"),
            _rec(self.now, 2, 18),
            _rec(self.now, 1, 6),
        ]

    def test_day_set_is_identical_on_both_stands(self):
        one, many, stats = cen.thicken(self.rows, 5)
        self.assertEqual({r["cycle_date"] for r in one},
                         {r["cycle_date"] for r in many})
        self.assertEqual(stats["days"], 3)

    def test_last_row_of_every_day_is_byte_identical(self):
        """Читатель, схлопывающий день по правилу писателя, ОБЯЗАН не шелохнуться."""
        one, many, _ = cen.thicken(self.rows, 5)

        def last_by_day(rows):
            out = {}
            for row in rows:
                out[row["cycle_date"]] = json.dumps(row, sort_keys=True,
                                                    default=str)
            return out

        self.assertEqual(last_by_day(one), last_by_day(many))

    def test_many_carries_factor_rows_per_day(self):
        one, many, stats = cen.thicken(self.rows, 4)
        self.assertEqual(stats["records_one"], 3)
        self.assertEqual(stats["records_many"], 12)
        self.assertEqual(len(one), 3)
        self.assertEqual(len(many), 12)

    def test_padding_rows_are_distinct_runs_of_the_same_day(self):
        """У подложки своя `run_identity` — иначе писательское правило её схлопнет."""
        _, many, _ = cen.thicken(self.rows, 6)
        day = _day(self.now, 2)
        same_day = [r for r in many if r["cycle_date"] == day]
        self.assertEqual(len(same_day), 6)
        self.assertEqual(len({run_identity(r) for r in same_day}), 6)
        self.assertEqual(len({r["cycle_date"] for r in same_day}), 1)

    def test_padding_material_comes_from_that_very_day(self):
        """Выдуманная строка проверяла бы читателя на том, чего не было."""
        _, many, _ = cen.thicken(self.rows, 3)
        day = _day(self.now, 2)
        real = {json.dumps({k: v for k, v in r.items() if k != "generated_at"},
                           sort_keys=True, default=str)
                for r in self.rows if r["cycle_date"] == day}
        for row in [r for r in many if r["cycle_date"] == day]:
            body = json.dumps({k: v for k, v in row.items() if k != "generated_at"},
                              sort_keys=True, default=str)
            self.assertIn(body, real)

    def test_factor_one_makes_the_stands_coincide(self):
        """Красная сторона `_MIN_FACTOR`: при одном прогоне в дне мерить нечем."""
        one, many, _ = cen.thicken(self.rows, 1)
        self.assertEqual(one, many)

    def test_unparsable_stamp_is_a_named_third_outcome(self):
        rows = [_rec(self.now, 1, 6, generated_at="не-отметка")]
        _, many, stats = cen.thicken(rows, 4)
        self.assertEqual(stats["days_not_thickened"], [_day(self.now, 1)])
        self.assertEqual(len(many), 1)

    def test_undated_rows_sit_identically_on_both_stands(self):
        """Строка без даты — не день и не прогон дня: ВТОРОЙ вещи между стендами нет."""
        rows = [_rec(self.now, 1, 6), _rec(self.now, 1, 7, cycle_date="")]
        one, many, stats = cen.thicken(rows, 3)
        self.assertEqual(stats["undated_records"], 1)
        self.assertEqual([r for r in one if not r["cycle_date"]],
                         [r for r in many if not r["cycle_date"]])


class DensityIsMeasured(unittest.TestCase):
    def test_density_counts_days_and_records_separately(self):
        now = _now()
        rows = [_rec(now, 2, 6), _rec(now, 2, 12), _rec(now, 1, 6)]
        den = cen.density(rows)
        self.assertEqual(den["records"], 3)
        self.assertEqual(den["days"], 2)
        self.assertEqual(den["records_per_day_max"], 2)
        self.assertEqual(den["records_per_day_mean"], 1.5)

    def test_row_without_a_date_is_its_own_outcome_not_a_day_and_not_zero(self):
        now = _now()
        den = cen.density([_rec(now, 1, 6), _rec(now, 1, 7, cycle_date=None)])
        self.assertEqual(den["undated_records"], 1)
        self.assertEqual(den["days"], 1)
        self.assertEqual(den["records"], 2)

    def test_factor_is_taken_from_the_tape_not_from_a_constant(self):
        books = {"balanced": {"density": {"records_per_day_max": 24}},
                 "conservative": {"density": {"records_per_day_max": 15}}}
        factor, why = cen.measured_factor(books)
        self.assertEqual(factor, 24)
        self.assertIn("24", why)
        self.assertIn("balanced", why)

    def test_nothing_measured_names_the_reason_instead_of_pretending(self):
        factor, why = cen.measured_factor({})
        self.assertEqual(factor, cen._MIN_FACTOR)
        self.assertIn("не измерена", why)

    def test_density_below_two_is_raised_and_said_out_loud(self):
        factor, why = cen.measured_factor(
            {"c": {"density": {"records_per_day_max": 1}}})
        self.assertEqual(factor, cen._MIN_FACTOR)
        self.assertIn("тождественны", why)


class DayNamedCoords(unittest.TestCase):
    def test_names_that_claim_days_are_recognised(self):
        self.assertEqual(
            cen.day_named({".balanced.unchanged_days",
                           '.protocols[protocol="aave_v3"].observed_days',
                           ".track.дней", ".x.сутки", ".daily_rows"}),
            {".balanced.unchanged_days",
             '.protocols[protocol="aave_v3"].observed_days',
             ".track.дней", ".x.сутки", ".daily_rows"})

    def test_names_that_claim_something_else_are_not_dragged_in(self):
        """Обратная сторона: образец «что-нибудь про время» покрасил бы исправных."""
        self.assertEqual(
            cen.day_named({".history_rows", ".age_s", ".hours", ".ttl_seconds",
                           ".records", ".count"}),
            set())

    def test_only_the_last_segment_is_asked(self):
        """Полный путь считал бы названным в днях и то, что названо иначе."""
        self.assertEqual(cen.day_named({".days.records"}), set())


class VerdictFromProbes(unittest.TestCase):
    """Вердикт по трём ответам — красная сторона у каждого исхода."""

    def test_identical_answers_are_day_invariant(self):
        answer = {"unchanged_days": 14, "rows": 7}
        row = cen.verdict_from_probes({"module": "m"}, answer, answer, answer)
        self.assertEqual(row["outcome"], cen.OUT_DAY_INVARIANT)
        self.assertEqual(row["day_named_moved"], [])

    def test_days_field_moving_with_density_is_the_finding(self):
        """ДОСОБЫТИЙНАЯ форма: число названо днями, а меряет записи."""
        one = {"unchanged_days": 37}
        many = {"unchanged_days": 14}
        row = cen.verdict_from_probes({"module": "m"}, one, one, many)
        self.assertEqual(row["outcome"], cen.OUT_RECORD_SENSITIVE)
        self.assertEqual(row["day_named_moved"], [".unchanged_days"])

    def test_sensitive_without_a_day_name_is_read_not_accused(self):
        """Читатель оси прогонов обязан быть чувствительным — это НЕ находка."""
        row = cen.verdict_from_probes({"module": "m"},
                                      {"history_rows": 45}, {"history_rows": 45},
                                      {"history_rows": 1080})
        self.assertEqual(row["outcome"], cen.OUT_RECORD_SENSITIVE)
        self.assertEqual(row["day_named_moved"], [])
        self.assertEqual(row["moved_coords"], [".history_rows"])

    def test_field_that_floats_on_one_stand_cannot_accuse_anyone(self):
        """Иначе перепись сообщала бы о СЕБЕ: всякий со стенными часами — находка."""
        row = cen.verdict_from_probes(
            {"module": "m"},
            {"took_s": 0.1, "unchanged_days": 14},
            {"took_s": 0.2, "unchanged_days": 14},
            {"took_s": 0.3, "unchanged_days": 14})
        self.assertEqual(row["outcome"], cen.OUT_DAY_INVARIANT)
        self.assertEqual(row["unstable_coords"], [".took_s"])

    def test_a_days_field_that_itself_floats_cannot_be_judged(self):
        """Обратная сторона: снять ПРЕДМЕТ вопроса молча — выдать зачёт по слепоте."""
        row = cen.verdict_from_probes(
            {"module": "m"},
            {"unchanged_days": 14}, {"unchanged_days": 15},
            {"unchanged_days": 14})
        self.assertEqual(row["outcome"], cen.OUT_UNMEASURED)
        self.assertEqual(row["cause"], CAUSE_RESTS_ON_UNSTABLE)
        self.assertNotEqual(row["outcome"], cen.OUT_DAY_INVARIANT)

    def test_named_clock_fields_never_decide_anything(self):
        row = cen.verdict_from_probes(
            {"module": "m"},
            {"generated_at": "a", "unchanged_days": 14},
            {"generated_at": "b", "unchanged_days": 14},
            {"generated_at": "c", "unchanged_days": 14})
        self.assertEqual(row["outcome"], cen.OUT_DAY_INVARIANT)


class RefusalsKeepTheirOwnCause(unittest.TestCase):
    """Отказ ЗВАТЬ — не «нечего позвать». Общее ведро скрыло бы и то, и то."""

    def setUp(self) -> None:
        self.stands = {"s_one": Path("/nonexistent/s_one"),
                       "s_many": Path("/nonexistent/s_many")}
        self.now = _now()

    def test_the_census_refuses_to_grade_itself(self):
        row = cen.classify_reader(cen.__name__, self.stands, sweepers={},
                                  now=self.now)
        self.assertEqual(row["outcome"], cen.OUT_UNMEASURED)
        self.assertEqual(row["cause"], CAUSE_SELF)

    def test_a_module_that_sweeps_a_population_is_never_called(self):
        """Зов поднял бы полную перепись на КАЖДОМ стенде, а внутри неё — следующую."""
        row = cen.classify_reader(
            "spa_core.monitoring.run_identity_key_price", self.stands,
            sweepers={"spa_core.monitoring.run_identity_key_price": "гоняет перепись"},
            now=self.now)
        self.assertEqual(row["outcome"], cen.OUT_UNMEASURED)
        self.assertEqual(row["cause"], cen.CAUSE_SWEEPS_POPULATION)

    def test_the_sweeper_list_is_measured_and_finds_the_known_ones(self):
        sweepers = cen._sweepers(Path(__file__).resolve().parents[2])
        self.assertIn("spa_core.monitoring.run_identity_key_price", sweepers)
        self.assertIn("spa_core.monitoring.ledger_day_unit_census", sweepers)
        for name, why in sweepers.items():
            self.assertTrue(why.strip(), f"{name} без названной причины отказа")

    def test_the_census_is_on_the_neighbours_never_call_list_too(self):
        """Иначе отказ соседа стои́т на ФОРМЕ ПОДПИСИ и снимается любой её правкой.

        `run_identity_key_price` зовёт всё население читателей ленты, и эта
        перепись в его населении есть. До ADR-766 его отказ был случайным:
        `measure(data_dir, tree_root, …)` требует второй позиционный аргумент,
        которого привод не передаёт, и зов падал `TypeError`. Перепись внутри
        переписи — не «не измерено», а рекурсия по населению.
        """
        from spa_core.monitoring import run_identity_key_price as g16
        self.assertIn("spa_core.monitoring.ledger_day_unit_census", g16._NEVER_CALL)
        self.assertTrue(
            g16._NEVER_CALL["spa_core.monitoring.ledger_day_unit_census"].strip())

    def test_the_money_path_entry_is_refused_with_its_own_reason(self):
        row = cen.classify_reader("spa_core.paper_trading.cycle_runner",
                                  self.stands, sweepers={}, now=self.now)
        self.assertEqual(row["outcome"], cen.OUT_UNMEASURED)
        self.assertEqual(row["cause"], CAUSE_WOULD_ACT)
        self.assertIn("денежный путь", row["reason"])

    def test_a_module_that_cannot_be_imported_is_unmeasured_not_clean(self):
        row = cen.classify_reader("spa_core.no_such_module_at_all", self.stands,
                                  sweepers={}, now=self.now)
        self.assertEqual(row["outcome"], cen.OUT_UNMEASURED)
        self.assertNotEqual(row["outcome"], cen.OUT_DAY_INVARIANT)


class CallBudgetHasAnEnd(unittest.TestCase):
    """У прогона обязан быть КОНЕЦ: прибор без конца не работает вовсе.

    Замер 16.10: безбюджетный обход всего населения на наблюдённой плотности шёл
    более 35 минут при 99 % CPU и не закончился. «Не измерено» с названной
    причиной — исход, который можно читать; бесконечный прогон — нет.
    """

    def test_a_slow_entry_is_unmeasured_with_its_own_cause(self):
        import sys
        import types

        name = "spa_core_fake_slow_ledger_reader"
        mod = types.ModuleType(name)

        def measure(data_dir, *, now=None):          # noqa: ARG001
            import time as _t
            _t.sleep(5.0)
            return {"unchanged_days": 1}

        mod.measure = measure
        sys.modules[name] = mod
        try:
            row = cen.classify_reader(
                name, {"s_one": Path("/x"), "s_many": Path("/y")},
                sweepers={}, now=_now(), budget_s=0.4)
        finally:
            del sys.modules[name]
        self.assertEqual(row["outcome"], cen.OUT_UNMEASURED)
        self.assertEqual(row["cause"], cen.CAUSE_OVER_BUDGET)
        self.assertNotEqual(row["outcome"], cen.OUT_DAY_INVARIANT)

    def test_a_fast_entry_is_judged_normally_under_the_same_budget(self):
        """Порванное звено: без этой стороны бюджет мог бы глушить ВСЕХ."""
        import sys
        import types

        name = "spa_core_fake_fast_ledger_reader"
        mod = types.ModuleType(name)
        mod.measure = lambda data_dir, *, now=None: {"unchanged_days": 7}  # noqa: ARG005
        sys.modules[name] = mod
        try:
            row = cen.classify_reader(
                name, {"s_one": Path("/x"), "s_many": Path("/y")},
                sweepers={}, now=_now(), budget_s=5.0)
        finally:
            del sys.modules[name]
        self.assertEqual(row["outcome"], cen.OUT_DAY_INVARIANT)
        self.assertEqual(row["budget_s"], 5.0)

    def test_the_budget_is_recorded_as_a_fact_not_as_an_intention(self):
        import sys
        import types

        name = "spa_core_fake_budget_fact_reader"
        mod = types.ModuleType(name)
        mod.measure = lambda data_dir, *, now=None: {"rows": 1}  # noqa: ARG005
        sys.modules[name] = mod
        try:
            row = cen.classify_reader(
                name, {"s_one": Path("/x"), "s_many": Path("/y")},
                sweepers={}, now=_now(), budget_s=3.0)
        finally:
            del sys.modules[name]
        self.assertIn("budget_s", row)
        self.assertEqual(row["budget_s"], 3.0)
        self.assertNotIn("budget_reason", row)

    def test_the_alarm_is_cancelled_after_every_call(self):
        """Иначе будильник прибора выстрелил бы в следующего читателя."""
        import signal as _sig
        import sys
        import types

        name = "spa_core_fake_cancel_check_reader"
        mod = types.ModuleType(name)
        mod.measure = lambda data_dir, *, now=None: {"rows": 1}  # noqa: ARG005
        sys.modules[name] = mod
        try:
            cen.classify_reader(name, {"s_one": Path("/x"), "s_many": Path("/y")},
                                sweepers={}, now=_now(), budget_s=2.0)
        finally:
            del sys.modules[name]
        self.assertEqual(_sig.getitimer(_sig.ITIMER_REAL)[0], 0.0)


class TapeReadingHasThreeOutcomes(unittest.TestCase):
    def test_absent_tape_is_a_named_reason(self):
        with TemporaryDirectory() as tmp:
            rows, why = cen.read_book_rows(Path(tmp), "balanced")
            self.assertIsNone(rows)
            self.assertIn("нет", why)

    def test_unparsable_line_is_counted_not_fatal_and_not_in_the_stand(self):
        now = _now()
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / history_filename("balanced")
            path.write_text(json.dumps(_rec(now, 1, 6)) + "\nне json\n",
                            encoding="utf-8")
            rows, why = cen.read_book_rows(Path(tmp), "balanced")
            self.assertEqual(len(rows), 1)
            self.assertIn("нечитаемых строк 1", why)

    def test_stands_are_not_built_without_a_single_tape(self):
        with TemporaryDirectory() as tmp:
            src = Path(tmp) / "data"
            src.mkdir()
            stands, why = cen.build_stands(src, Path(tmp) / "stands", factor=4)
            self.assertIsNone(stands)
            self.assertIn("ни одна лента", why)


class MeasurementTact(unittest.TestCase):
    def test_absent_artifact_means_measure_now(self):
        with TemporaryDirectory() as tmp:
            due, why = cen.measurement_due(Path(tmp) / "nope.json", now=_now())
            self.assertTrue(due)
            self.assertIn("артефакта нет", why)

    def test_unreadable_stamp_means_measure_now_not_recently(self):
        with TemporaryDirectory() as tmp:
            out = Path(tmp) / "a.json"
            out.write_text("{}", encoding="utf-8")
            due, why = cen.measurement_due(out, now=_now())
            self.assertTrue(due)
            self.assertIn("не прочитана", why)

    def test_fresh_stamp_means_not_due_and_that_is_a_measurement(self):
        now = _now()
        with TemporaryDirectory() as tmp:
            out = Path(tmp) / "a.json"
            out.write_text(json.dumps({"generated_at": now.isoformat()}),
                           encoding="utf-8")
            due, why = cen.measurement_due(out, now=now)
            self.assertFalse(due)
            self.assertIn("из", why)

    def test_inside_the_tact_run_refuses_to_invent_a_verdict(self):
        now = _now()
        with TemporaryDirectory() as tmp:
            data = Path(tmp) / "data"
            data.mkdir()
            (data / cen.ARTIFACT).write_text(
                json.dumps({"generated_at": now.isoformat()}), encoding="utf-8")
            res = cen.run(root=tmp, data_dir=str(data), if_due=True, now=now,
                          write=False)
            self.assertFalse(res["measured"])
            self.assertNotIn("status", res)


class TheRealReaderOnRealStands(unittest.TestCase):
    """Сквозной контроль на НАСТОЯЩЕЙ выдаче владельцу, а не на подделке.

    Контур целый ⇒ находка есть (`unchanged_days` считается серией ЗАПИСЕЙ);
    звено порвано (у дня один прогон) ⇒ находки нет. Обе стороны — у того же
    кода, который читает владелец.
    """

    def _tape(self, now):
        """Четыре дня неизменности, и у одного из них разнородные прогоны."""
        return [
            _rec(now, 4, 6, verdict="ACT", gates={"has_legs": True}),
            _rec(now, 3, 6),
            _rec(now, 2, 6, verdict="ACT", gates={"has_legs": True}),
            _rec(now, 2, 18),
            _rec(now, 1, 6),
        ]

    def test_brief_reports_a_different_day_count_on_the_denser_stand(self):
        from spa_core.paper_trading import cio_brief
        now = _now()
        with TemporaryDirectory() as tmp:
            src = Path(tmp) / "data"
            src.mkdir()
            _write_tape(src, None, self._tape(now))
            stands, why = cen.build_stands(src, Path(tmp) / "stands", factor=6)
            self.assertIsNotNone(stands, why)
            thin = cio_brief.build_books_brief(stands["s_one"] / "data")
            dense = cio_brief.build_books_brief(stands["s_many"] / "data")
            self.assertNotEqual(thin["conservative"]["unchanged_days"],
                                dense["conservative"]["unchanged_days"])

    def test_the_very_same_days_with_one_run_each_agree(self):
        """Порванное звено: плотность снята ⇒ расхождения нет."""
        from spa_core.paper_trading import cio_brief
        now = _now()
        with TemporaryDirectory() as tmp:
            src = Path(tmp) / "data"
            src.mkdir()
            _write_tape(src, None, self._tape(now))
            stands, _ = cen.build_stands(src, Path(tmp) / "stands", factor=1)
            thin = cio_brief.build_books_brief(stands["s_one"] / "data")
            dense = cio_brief.build_books_brief(stands["s_many"] / "data")
            self.assertEqual(thin["conservative"]["unchanged_days"],
                             dense["conservative"]["unchanged_days"])

    def test_census_names_the_brief_as_the_finding_on_those_stands(self):
        now = _now()
        with TemporaryDirectory() as tmp:
            src = Path(tmp) / "data"
            src.mkdir()
            _write_tape(src, None, self._tape(now))
            doc = cen.measure(src, Path(__file__).resolve().parents[2], now=now,
                              stand_dest=Path(tmp) / "stands",
                              population=["spa_core.paper_trading.cio_brief"])
            self.assertTrue(doc["measured"])
            self.assertEqual(doc["status"], cen.STATUS_FINDINGS)
            self.assertEqual([f["module"] for f in doc["findings"]],
                             ["spa_core.paper_trading.cio_brief"])
            self.assertEqual(doc["factor"], 2)

    def test_artifact_and_producer_are_declared_not_derived(self):
        self.assertEqual(cen.ARTIFACT, "ledger_day_unit_census.json")
        self.assertEqual(cen.PRODUCER,
                         "spa_core/monitoring/ledger_day_unit_census.py")

    def test_the_instrument_says_what_it_does_not_prove(self):
        now = _now()
        with TemporaryDirectory() as tmp:
            src = Path(tmp) / "data"
            src.mkdir()
            _write_tape(src, None, self._tape(now))
            doc = cen.measure(src, Path(__file__).resolve().parents[2], now=now,
                              stand_dest=Path(tmp) / "stands", population=[])
            self.assertTrue(doc["advisory"])
            self.assertTrue(doc["what_it_does_not_prove"])


class ProbeHasBothSides(unittest.TestCase):
    """Проба приёмки: зелена на целом контуре, красна на КАЖДОМ порванном звене."""

    def setUp(self) -> None:
        from spa_core.monitoring import card_acceptance as ca
        self.ca = ca
        self.probe = ca.PROBES["ledger_day_unit_census_names_the_unit"]
        self.now = _now()
        self.root = str(Path(__file__).resolve().parents[2])
        roads, _ = cen.reader_population(Path(self.root))
        self.population = sorted(roads)

    def _report(self, **over) -> dict:
        doc = {
            "measured": True,
            "generated_at": self.now.isoformat(),
            "factor": 24,
            "tally": {cen.OUT_DAY_INVARIANT: len(self.population)},
            "readers": [{"module": m, "outcome": cen.OUT_DAY_INVARIANT}
                        for m in self.population],
            "findings": [],
            "needs_reading": [],
        }
        doc.update(over)
        return doc

    def test_registered_in_the_registry_so_the_queue_accepts_it(self):
        self.assertIn("ledger_day_unit_census_names_the_unit", self.ca.PROBES)

    def test_whole_circuit_is_satisfied(self):
        verdict, detail = self.probe(None, now=self.now, repo_root=self.root,
                                     report=self._report())
        self.assertEqual(verdict, self.ca.SATISFIED)
        self.assertIn("плотность стенда 24", detail)

    def test_a_finding_makes_it_red_and_names_the_reader(self):
        verdict, detail = self.probe(
            None, now=self.now, repo_root=self.root,
            report=self._report(findings=[{
                "finding": cen.F_RECORDS_AS_DAYS,
                "module": "spa_core.paper_trading.cio_brief",
                "coords": [".balanced.unchanged_days"]}]))
        self.assertEqual(verdict, self.ca.NOT_SATISFIED)
        self.assertIn("cio_brief", detail)
        self.assertIn("unchanged_days", detail)

    def test_missing_artifact_is_unmeasured_not_satisfied(self):
        with TemporaryDirectory() as tmp:
            verdict, detail = self.probe(None, now=self.now, repo_root=self.root,
                                         data_dir=tmp)
            self.assertEqual(verdict, self.ca.UNMEASURED)
            self.assertNotEqual(verdict, self.ca.SATISFIED)
            self.assertIn("НЕ наблюдена", detail)

    def test_stale_census_is_unmeasured(self):
        stale = (self.now - timedelta(hours=400)).isoformat()
        verdict, detail = self.probe(None, now=self.now, repo_root=self.root,
                                     report=self._report(generated_at=stale))
        self.assertEqual(verdict, self.ca.UNMEASURED)
        self.assertIn("старше предела", detail)

    def test_unreadable_stamp_is_unmeasured(self):
        verdict, detail = self.probe(None, now=self.now, repo_root=self.root,
                                     report=self._report(generated_at="вчера"))
        self.assertEqual(verdict, self.ca.UNMEASURED)
        self.assertIn("возраст записи НЕ ИЗМЕРЕН", detail)

    def test_a_reader_added_after_the_census_cannot_be_credited(self):
        """Покрытие НАСЕЛЕНИЯ: иначе новый читатель зачитывался бы по слепоте."""
        short = self._report(
            readers=[{"module": m, "outcome": cen.OUT_DAY_INVARIANT}
                     for m in self.population[:-1]])
        verdict, detail = self.probe(None, now=self.now, repo_root=self.root,
                                     report=short)
        self.assertEqual(verdict, self.ca.UNMEASURED)
        self.assertIn("исхода в переписи НЕТ", detail)

    def test_census_that_did_not_measure_is_not_a_pass(self):
        verdict, detail = self.probe(None, now=self.now, repo_root=self.root,
                                     report={"measured": False,
                                             "reason": "стенды не построены"})
        self.assertEqual(verdict, self.ca.UNMEASURED)
        self.assertIn("стенды не построены", detail)

    def test_the_probe_takes_no_argument(self):
        verdict, detail = self.probe("spa_core", now=self.now,
                                     repo_root=self.root, report=self._report())
        self.assertEqual(verdict, self.ca.UNMEASURED)
        self.assertIn("не принимает аргумента", detail)

    def test_needs_reading_is_named_but_does_not_make_it_red(self):
        verdict, detail = self.probe(
            None, now=self.now, repo_root=self.root,
            report=self._report(needs_reading=[
                {"kind": cen.NEEDS_READING, "module": "x"}]))
        self.assertEqual(verdict, self.ca.SATISFIED)
        self.assertIn("не находка", detail)

    def test_prose_alone_never_passes_the_probe(self):
        """ADR-333: зачёт меряется ЗНАЧЕНИЕМ полей, а не подстрокой в тексте."""
        prose = self._report(findings=[{
            "finding": cen.F_RECORDS_AS_DAYS, "module": "m",
            "coords": [".unchanged_days"],
            "detail": "считаются ДНИ, а не записи"}])
        verdict, _ = self.probe(None, now=self.now, repo_root=self.root,
                                report=prose)
        self.assertEqual(verdict, self.ca.NOT_SATISFIED)


class LedgerWindowCutsDaysAndNothingElse(unittest.TestCase):
    """Урезанное окно (ADR-767): дешевле — но та же ОДНА разница между стендами.

    Средство заказа G766 п. 3 работает только если окно режет РОВНО дни. Режь
    оно записи — обрезка смешалась бы с плотностью, то есть с самим предметом
    вопроса, и сдвиг нельзя было бы отнести ни к одной из двух причин.
    """

    def setUp(self) -> None:
        self.now = _now()
        self.rows = [_rec(self.now, back, hour)
                     for back in range(10, 0, -1) for hour in (6, 18)]
        self.undated = dict(self.rows[0])
        self.undated.pop("cycle_date")
        self.rows.append(self.undated)

    def test_window_keeps_the_last_days_not_the_first(self):
        """Читатель ленты судит о СВЕЖЕМ: окно из начала истории — другой вопрос."""
        kept, note = cen.tail_days(self.rows, 3)
        days = sorted({r["cycle_date"] for r in kept if "cycle_date" in r})
        self.assertEqual(days, sorted(_day(self.now, b) for b in (1, 2, 3)))
        self.assertTrue(note["truncated"])
        self.assertEqual((note["days_before"], note["days_after"]), (10, 3))

    def test_undated_rows_stay_in_full_on_both_stands(self):
        """Порванное звено: выброси их — и между стендами менялась бы ВТОРАЯ вещь."""
        kept, _ = cen.tail_days(self.rows, 2)
        self.assertEqual(sum(1 for r in kept if "cycle_date" not in r), 1)

    def test_no_window_leaves_the_tape_whole_and_says_so(self):
        kept, note = cen.tail_days(self.rows, None)
        self.assertEqual(len(kept), len(self.rows))
        self.assertFalse(note["truncated"])
        self.assertIn("целиком", note["reason"])

    def test_window_wider_than_the_tape_cuts_nothing_and_names_why(self):
        """«Урезал» на ленте короче окна было бы ложью о наблюдении."""
        kept, note = cen.tail_days(self.rows, 99)
        self.assertEqual(len(kept), len(self.rows))
        self.assertFalse(note["truncated"])
        self.assertIn("резать нечего", note["reason"])

    def test_a_non_positive_window_is_refused_not_obeyed(self):
        """Окно 0 дн оставило бы стенд без единого дня — мерить стало бы нечем."""
        for bad in (0, -5):
            kept, note = cen.tail_days(self.rows, bad)
            self.assertEqual(len(kept), len(self.rows), bad)
            self.assertFalse(note["truncated"], bad)

    def test_stands_on_a_window_still_share_one_day_set(self):
        """Главный инвариант стендов обязан выжить обрезку — иначе вывод ни о чём."""
        with TemporaryDirectory() as tmp:
            data = Path(tmp) / "data"
            data.mkdir()
            _write_tape(data, None, self.rows)
            stands, why = cen.build_stands(data, Path(tmp) / "st", factor=4,
                                           window_days=3, prefix="w_")
            self.assertIsNotNone(stands, why)
            assert stands is not None
            self.assertEqual(stands["window_days"], 3)
            one = cen.read_book_rows(stands["s_one"] / "data", None)[0]
            many = cen.read_book_rows(stands["s_many"] / "data", None)[0]
            assert one is not None and many is not None
            self.assertEqual({r["cycle_date"] for r in one if "cycle_date" in r},
                             {r["cycle_date"] for r in many if "cycle_date" in r})
            self.assertEqual(len({r["cycle_date"] for r in one
                                  if "cycle_date" in r}), 3)
            self.assertLess(len(one), len(many))

    def test_the_prefix_keeps_two_stand_sets_apart(self):
        """Без него урезанный стенд записался бы ПОВЕРХ полного."""
        with TemporaryDirectory() as tmp:
            data = Path(tmp) / "data"
            data.mkdir()
            _write_tape(data, None, self.rows)
            dest = Path(tmp) / "st"
            full, _ = cen.build_stands(data, dest, factor=4)
            short, _ = cen.build_stands(data, dest, factor=4, window_days=2,
                                        prefix="w_")
            assert full is not None and short is not None
            self.assertNotEqual(full["s_one"], short["s_one"])
            whole = cen.read_book_rows(full["s_one"] / "data", None)[0]
            assert whole is not None
            self.assertEqual(len({r["cycle_date"] for r in whole
                                  if "cycle_date" in r}), 10)


class ShortWindowAnswerIsNotDressedUpAsAFullOne(unittest.TestCase):
    """ADR-767: сдвиг на коротком окне ДОКАЗАН, его отсутствие — НЕТ.

    Несимметричность намеренная и есть вся суть правила. Координата, поехавшая
    от одной лишь плотности на семи днях, едет от неё и на сорока пяти. Обратное
    неверно: читатель с оглядкой назад длиннее окна инвариантен на коротком окне
    ПО ПОСТРОЕНИЮ, и зачесть ему это значило бы выдать слепоту прибора за
    исправность читателя (инв. #17).
    """

    def setUp(self) -> None:
        self.full = {"module": "m", "outcome": cen.OUT_UNMEASURED,
                     "cause": cen.CAUSE_OVER_BUDGET, "reason": "не уложился"}

    def test_a_shift_found_on_the_short_window_counts_as_found(self):
        row = cen.merge_short_window_row(
            self.full, {"module": "m", "outcome": cen.OUT_RECORD_SENSITIVE,
                        "day_named_moved": ["cio.unchanged_days"]}, 7)
        self.assertEqual(row["outcome"], cen.OUT_RECORD_SENSITIVE)
        self.assertEqual(row["day_named_moved"], ["cio.unchanged_days"])
        self.assertTrue(row["measured_on_short_window"])
        self.assertEqual(row["short_window_days"], 7)

    def test_absence_of_a_shift_on_the_short_window_is_not_clean(self):
        """Порванное звено: зачти его — и слепота прибора стала бы зачётом."""
        row = cen.merge_short_window_row(
            self.full, {"module": "m", "outcome": cen.OUT_DAY_INVARIANT,
                        "moved_coords": []}, 7)
        self.assertEqual(row["outcome"], cen.OUT_UNMEASURED)
        self.assertEqual(row["cause"], cen.CAUSE_INVARIANT_SHORT_ONLY)
        self.assertNotEqual(row["outcome"], cen.OUT_DAY_INVARIANT)
        self.assertIn("7", str(row["reason"]))

    def test_still_over_budget_means_the_cost_is_not_the_ledger(self):
        """Средство заказа на такого читателя НЕ действует — и это сказано."""
        row = cen.merge_short_window_row(
            self.full, {"module": "m", "outcome": cen.OUT_UNMEASURED,
                        "cause": cen.CAUSE_OVER_BUDGET, "reason": "не уложился"}, 7)
        self.assertEqual(row["cause"], cen.CAUSE_OVER_BUDGET_SHORT)
        self.assertNotEqual(row["cause"], cen.CAUSE_OVER_BUDGET)

    def test_another_failure_keeps_its_own_cause(self):
        """Порванное звено: ссыпь всё в бюджет — и причина стала бы ложной."""
        row = cen.merge_short_window_row(
            self.full, {"module": "m", "outcome": cen.OUT_UNMEASURED,
                        "cause": cen.CAUSE_ENTRY_RAISED, "reason": "ValueError"}, 7)
        self.assertEqual(row["cause"], cen.CAUSE_ENTRY_RAISED)

    def test_the_full_window_observation_is_never_overwritten(self):
        """Иначе строка выдавала бы дешёвый замер за тот, которого не было."""
        row = cen.merge_short_window_row(
            self.full, {"module": "m", "outcome": cen.OUT_RECORD_SENSITIVE,
                        "day_named_moved": ["a.days"]}, 7)
        self.assertEqual(row["full_window"]["cause"], cen.CAUSE_OVER_BUDGET)
        self.assertEqual(row["full_window"]["outcome"], cen.OUT_UNMEASURED)


class TheCheaperWindowReachesTheWiring(unittest.TestCase):
    """Проводка, а не только правило: «половина инъекции — та же бомба».

    `.claude/rules/deployment.md`: проверять надо не наличие параметра, а
    доходит ли он до того пути, который идёт замер. Поэтому тесты ниже зовут
    `measure()` целиком — со стендами, импортом и будильником, — и отличаются
    РОВНО тем, где лежит цена читателя.
    """

    def setUp(self) -> None:
        self.now = _now()
        self.rows = [_rec(self.now, back, hour)
                     for back in range(20, 0, -1) for hour in (6, 12, 18)]

    def _tree(self, tmp: Path) -> Path:
        data = tmp / "data"
        data.mkdir(parents=True, exist_ok=True)
        for _name, book_id in cen.BOOKS:
            _write_tape(data, book_id, self.rows)
        return data

    def _fake(self, name: str, fn):
        import sys
        import types
        mod = types.ModuleType(name)
        mod.measure = fn
        sys.modules[name] = mod
        self.addCleanup(lambda: sys.modules.pop(name, None))
        return name

    def test_a_reader_whose_cost_is_the_ledger_gets_an_answer(self):
        """Положительный контроль: бюджет дал бы НЕОТВЕТ, окно даёт НАХОДКУ."""
        def slow_by_tape(data_dir, *, now=None):            # noqa: ARG001
            import time as _t
            rows = cen.read_book_rows(Path(data_dir), None)[0] or []
            # Цена читателя пропорциональна ДЛИНЕ ленты — ровно тот класс, на
            # который средство заказа и рассчитано: полное окно (60 строк на
            # `s_many`) в бюджет не укладывается, урезанное (9) укладывается.
            _t.sleep(0.02 * len(rows))
            return {"observed_days": len(rows)}

        name = self._fake("spa_core_fake_tape_priced_reader", slow_by_tape)
        with TemporaryDirectory() as tmp:
            data = self._tree(Path(tmp))
            doc = cen.measure(data, Path(tmp), now=self.now,
                              stand_dest=Path(tmp) / "st", population=[name],
                              budget_s=0.9, short_window_days=3)
        row = doc["readers"][0]
        self.assertEqual(row["full_window"]["cause"], cen.CAUSE_OVER_BUDGET)
        self.assertTrue(row["measured_on_short_window"])
        self.assertEqual(row["outcome"], cen.OUT_RECORD_SENSITIVE)
        self.assertEqual(row["day_named_moved"], [".observed_days"])
        self.assertEqual(doc["short_window_rescue"]["attempted"], 1)
        self.assertEqual(doc["short_window_rescue"]["answered"], 1)
        self.assertEqual(doc["short_window_rescue"]["findings_on_short_window"],
                         [name])
        self.assertEqual(doc["findings"][0]["short_window_days"], 3)
        self.assertEqual(doc["status"], cen.STATUS_FINDINGS)

    def test_a_reader_priced_elsewhere_is_named_not_rescued(self):
        """Порванное звено: цена не в ленте ⇒ окно не помогает, и это НАЗВАНО."""
        def slow_always(data_dir, *, now=None):              # noqa: ARG001
            import time as _t
            _t.sleep(3.0)
            return {"observed_days": 1}

        name = self._fake("spa_core_fake_elsewhere_priced_reader", slow_always)
        with TemporaryDirectory() as tmp:
            data = self._tree(Path(tmp))
            doc = cen.measure(data, Path(tmp), now=self.now,
                              stand_dest=Path(tmp) / "st", population=[name],
                              budget_s=0.5, short_window_days=3)
        row = doc["readers"][0]
        self.assertEqual(row["outcome"], cen.OUT_UNMEASURED)
        self.assertEqual(row["cause"], cen.CAUSE_OVER_BUDGET_SHORT)
        self.assertEqual(doc["short_window_rescue"]["answered"], 0)
        self.assertEqual(
            doc["short_window_rescue"]["still_unmeasured"],
            {cen.CAUSE_OVER_BUDGET_SHORT: 1})
        self.assertEqual(doc["status"], cen.STATUS_CLEAN)
        self.assertNotIn(cen.CAUSE_OVER_BUDGET, doc["unmeasured_causes"])

    def test_a_fast_reader_is_never_sent_to_the_short_window(self):
        """Порванное звено: спасай всех — и вердикты уехали бы на дешёвое окно."""
        name = self._fake("spa_core_fake_fast_full_window_reader",
                          lambda data_dir, *, now=None: {"rows": 1})  # noqa: ARG005
        with TemporaryDirectory() as tmp:
            data = self._tree(Path(tmp))
            doc = cen.measure(data, Path(tmp), now=self.now,
                              stand_dest=Path(tmp) / "st", population=[name],
                              budget_s=5.0, short_window_days=3)
        row = doc["readers"][0]
        self.assertNotIn("measured_on_short_window", row)
        self.assertEqual(doc["short_window_rescue"]["attempted"], 0)
        self.assertIn("спасать некого", doc["short_window_rescue"]["reason"])

    def test_the_window_is_an_input_and_the_artifact_records_it(self):
        """Число, решившее цену вопроса, обязано быть видно читателю отчёта."""
        name = self._fake("spa_core_fake_window_recorded_reader",
                          lambda data_dir, *, now=None: {"rows": 1})  # noqa: ARG005
        with TemporaryDirectory() as tmp:
            data = self._tree(Path(tmp))
            doc = cen.measure(data, Path(tmp), now=self.now,
                              stand_dest=Path(tmp) / "st", population=[name],
                              budget_s=5.0, short_window_days=5)
        self.assertEqual(doc["short_window_days"], 5)
        self.assertEqual(doc["short_window_rescue"]["short_window_days"], 5)

    def test_an_unbuildable_short_stand_is_its_own_cause(self):
        """Третий исход у самого средства: окно не построено — своя причина."""
        rows = [{"module": "m", "outcome": cen.OUT_UNMEASURED,
                 "cause": cen.CAUSE_OVER_BUDGET, "reason": "не уложился"}]
        with TemporaryDirectory() as tmp:
            out, report = cen.rescue_over_budget(
                rows, Path(tmp) / "no_data", Path(tmp) / "st", factor=4,
                sweepers={}, now=self.now, budget_s=1.0, short_window_days=3)
        self.assertEqual(out[0]["cause"], cen.CAUSE_SHORT_STAND_ABSENT)
        self.assertNotEqual(out[0]["outcome"], cen.OUT_DAY_INVARIANT)
        self.assertIn("reason", report)

    def test_the_report_shows_the_rescue_to_a_human(self):
        """Исход, которого не видно в отчёте, читателю не достаётся."""
        doc = {"measured": True, "books": {}, "factor": 4,
               "call_budget_s": 90.0, "tally": {cen.OUT_UNMEASURED: 1},
               "short_window_rescue": {
                   "attempted": 2, "answered": 1, "short_window_days": 7,
                   "stand": {"factor": 4},
                   "still_unmeasured": {cen.CAUSE_OVER_BUDGET_SHORT: 1},
                   "findings_on_short_window": ["mod.a"]}}
        text = "\n".join(cen.format_report(doc))
        self.assertIn("урезанное окно 7 дн", text)
        self.assertIn("получили ОТВЕТ 1", text)
        self.assertIn(cen.CAUSE_OVER_BUDGET_SHORT, text)
        self.assertIn("mod.a", text)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
