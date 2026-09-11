"""ADR-309: обратное заполнение переписи — ответ владельца «Вариант Б».

Владелец выбрал Б против рекомендации агента. Возражение агента было ровно об
одном — о ПРОБЕ дописанного значения, — и оно не снято выбором, а превращено в
условие исполнения: дописанное метится отдельно и никогда не выдаётся за живое.
Тесты ниже держат именно это условие, а не удобство прибора.
"""
# LLM_FORBIDDEN
import json
import unittest
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

from spa_core.monitoring import journal_population_backfill as b

# FROZEN-DATE-OK: injected-clock — якорь NOW уходит параметром now= в corrected_lines()/run().
NOW = datetime(2026, 9, 10, 12, 0, tzinfo=timezone.utc)

POINTS = {
    "outside": {"2026-08-12": 7.5, "2026-08-13": 7.6},
    "held": {"2026-08-12": 3.0},
    "stale_leg": {"2026-08-12": 4.4},
}


def _line(date, *, evidenced=None, unevidenced=None):
    return {
        "schema": "shadow-hist-v2", "cycle_date": date, "verdict": "HOLD",
        "apy_evidenced_pct": dict(evidenced or {}),
        "apy_unevidenced": list(unevidenced or []),
        "current_positions": {"held": 100.0}, "target_positions": {},
    }


def _pair(date, proto):
    return {"decision_date": "2026-08-11", "forward_date": date, "protocol": proto}


class ThePlanRefusesByName(unittest.TestCase):
    def test_a_cut_pair_with_material_is_planned(self):
        lines = [_line("2026-08-12", evidenced={"held": 3.0})]
        out = b.plan_for_pairs(lines, POINTS, [_pair("2026-08-12", "outside")])
        self.assertEqual(out["plan"], {"2026-08-12": {"outside": 7.5}})
        self.assertEqual(out["counts"], {b.PLANNED: 1})

    def test_an_already_evidenced_rate_is_refused_not_overwritten(self):
        """Живое значение того дня — авторитет. Дописывать поверх него нечего."""
        lines = [_line("2026-08-12", evidenced={"held": 3.0, "outside": 9.9})]
        out = b.plan_for_pairs(lines, POINTS, [_pair("2026-08-12", "outside")])
        self.assertEqual(out["plan"], {})
        self.assertEqual(out["per_pair"][0]["outcome"], b.REFUSED_ALREADY_EVIDENCED)
        self.assertTrue(out["per_pair"][0]["note"])

    def test_a_leg_the_writer_called_unevidenced_is_refused(self):
        """Собственное живое суждение писателя не перебивается меньшей пробой."""
        lines = [_line("2026-08-12", evidenced={"held": 3.0},
                       unevidenced=["stale_leg"])]
        out = b.plan_for_pairs(lines, POINTS, [_pair("2026-08-12", "stale_leg")])
        self.assertEqual(out["plan"], {})
        self.assertEqual(out["per_pair"][0]["outcome"],
                         b.REFUSED_WRITER_SAID_UNEVIDENCED)

    def test_a_pair_without_material_is_refused_by_name(self):
        lines = [_line("2026-08-12", evidenced={"held": 3.0})]
        out = b.plan_for_pairs(lines, POINTS, [_pair("2026-08-12", "pendle")])
        self.assertEqual(out["plan"], {})
        self.assertEqual(out["per_pair"][0]["outcome"], b.REFUSED_NO_MATERIAL)

    def test_a_day_absent_from_the_journal_is_refused_by_name(self):
        lines = [_line("2026-08-12", evidenced={"held": 3.0})]
        out = b.plan_for_pairs(lines, POINTS, [_pair("2026-08-30", "outside")])
        self.assertEqual(out["plan"], {})
        self.assertEqual(out["per_pair"][0]["outcome"], b.REFUSED_DAY_NOT_IN_JOURNAL)

    def test_the_same_pair_named_by_two_decision_days_is_counted_once(self):
        """43 отсечённые пары дают 40 адресов: пара адресуется днём и ногой."""
        lines = [_line("2026-08-12", evidenced={"held": 3.0})]
        pairs = [_pair("2026-08-12", "outside"), _pair("2026-08-12", "outside")]
        out = b.plan_for_pairs(lines, POINTS, pairs)
        self.assertEqual(out["values_planned"], 1)
        self.assertEqual(len(out["per_pair"]), 1)


class TheGradeNeverMixes(unittest.TestCase):
    """Условие владельца дословно: дописанное не выдаётся за живое."""

    def test_backfilled_values_never_enter_apy_evidenced_pct(self):
        lines = [_line("2026-08-12", evidenced={"held": 3.0})]
        fresh = b.corrected_lines(lines, {"2026-08-12": {"outside": 7.5}}, now=NOW)
        self.assertEqual(fresh[0]["apy_evidenced_pct"], {"held": 3.0})
        self.assertEqual(fresh[0][b.KEY_VALUES], {"outside": 7.5})

    def test_the_grade_is_written_into_the_line_and_is_not_live(self):
        lines = [_line("2026-08-12", evidenced={"held": 3.0})]
        fresh = b.corrected_lines(lines, {"2026-08-12": {"outside": 7.5}}, now=NOW)
        self.assertEqual(fresh[0][b.KEY_GRADE], b.BACKFILL_GRADE)
        self.assertNotEqual(fresh[0][b.KEY_GRADE], "live")

    def test_backfilled_values_never_enter_apy_unevidenced(self):
        lines = [_line("2026-08-12", evidenced={"held": 3.0}, unevidenced=["x"])]
        fresh = b.corrected_lines(lines, {"2026-08-12": {"outside": 7.5}}, now=NOW)
        self.assertEqual(fresh[0]["apy_unevidenced"], ["x"])

    def test_the_edit_is_purely_additive(self):
        """Ни одно прежнее поле не изменилось и не исчезло — измерено, не заявлено."""
        lines = [_line("2026-08-12", evidenced={"held": 3.0})]
        before = json.loads(json.dumps(lines[0]))
        fresh = b.corrected_lines(lines, {"2026-08-12": {"outside": 7.5}}, now=NOW)
        for key, value in before.items():
            self.assertEqual(fresh[0][key], value, key)
        self.assertEqual(set(fresh[0]) - set(before),
                         {b.KEY_VALUES, b.KEY_GRADE, b.KEY_SOURCE})

    def test_a_day_outside_the_plan_is_returned_untouched(self):
        lines = [_line("2026-08-12", evidenced={"held": 3.0}),
                 _line("2026-08-13", evidenced={"held": 3.1})]
        fresh = b.corrected_lines(lines, {"2026-08-12": {"outside": 7.5}}, now=NOW)
        self.assertNotIn(b.KEY_VALUES, fresh[1])

    def test_the_source_lines_are_not_mutated(self):
        lines = [_line("2026-08-12", evidenced={"held": 3.0})]
        b.corrected_lines(lines, {"2026-08-12": {"outside": 7.5}}, now=NOW)
        self.assertNotIn(b.KEY_VALUES, lines[0])


class UnreadableIsNotDeletable(unittest.TestCase):
    def test_an_unparseable_line_survives_byte_for_byte(self):
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "allocation_rationale_history.jsonl"
            path.write_text(
                json.dumps(_line("2026-08-12", evidenced={"held": 3.0})) + "\n"
                + "{не json\n", encoding="utf-8")
            b.apply_plan(Path(tmp), plan={"2026-08-12": {"outside": 7.5}}, now=NOW)
            kept = path.read_text(encoding="utf-8").splitlines()
            self.assertIn("{не json", kept)

    def test_apply_backs_up_before_writing_not_after(self):
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "allocation_rationale_history.jsonl"
            original = json.dumps(_line("2026-08-12", evidenced={"held": 3.0})) + "\n"
            path.write_text(original, encoding="utf-8")
            receipt = b.apply_plan(Path(tmp), plan={"2026-08-12": {"outside": 7.5}},
                                   now=NOW)
            self.assertTrue(receipt["applied"])
            self.assertEqual(Path(receipt["backup"]).read_text(encoding="utf-8"),
                             original)

    def test_an_empty_plan_writes_nothing_and_leaves_no_backup(self):
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "allocation_rationale_history.jsonl"
            original = json.dumps(_line("2026-08-12", evidenced={"held": 3.0})) + "\n"
            path.write_text(original, encoding="utf-8")
            receipt = b.apply_plan(Path(tmp), plan={}, now=NOW)
            self.assertFalse(receipt["applied"])
            self.assertEqual(path.read_text(encoding="utf-8"), original)
            self.assertEqual(list(Path(tmp).glob("*.bak.*")), [])

    def test_apply_is_idempotent(self):
        """Второй прогон того же плана не удваивает и не портит ничего."""
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "allocation_rationale_history.jsonl"
            path.write_text(
                json.dumps(_line("2026-08-12", evidenced={"held": 3.0})) + "\n",
                encoding="utf-8")
            plan = {"2026-08-12": {"outside": 7.5}}
            b.apply_plan(Path(tmp), plan=plan, now=NOW)
            once = [json.loads(x) for x in path.read_text().splitlines() if x.strip()]
            b.apply_plan(Path(tmp), plan=plan, now=NOW)
            twice = [json.loads(x) for x in path.read_text().splitlines() if x.strip()]
            self.assertEqual(once, twice)


class TheThirdOutcome(unittest.TestCase):
    """«Нечем мерить» и «закрывать нечего» — РАЗНЫЕ исходы."""

    def test_a_missing_journal_is_unmeasured_not_a_clean_plan(self):
        with TemporaryDirectory() as tmp:
            doc = b.measure(Path(tmp), now=NOW,
                            material={"status": "OK", "per_pair": []})
            self.assertEqual(doc["status"], b.STATUS_UNMEASURED)
            self.assertTrue(doc["reason"])

    def test_unmeasured_material_is_carried_not_swallowed(self):
        with TemporaryDirectory() as tmp:
            doc = b.measure(Path(tmp), now=NOW,
                            material={"status": "UNMEASURED",
                                      "reason": "ряд не прочитан"})
            self.assertEqual(doc["status"], b.STATUS_UNMEASURED)
            self.assertIn("ряд не прочитан", doc["reason"])

    def test_nothing_left_to_backfill_is_CRITICAL_not_UNMEASURED(self):
        """Ноль закрываемых пар при исправных входах — это ОТВЕТ."""
        with TemporaryDirectory() as tmp:
            data = Path(tmp)
            (data / "allocation_rationale_history.jsonl").write_text(
                json.dumps(_line("2026-08-12", evidenced={"held": 3.0, "outside": 1.0}))
                + "\n", encoding="utf-8")
            (data / "apy_series_daily.json").write_text(
                json.dumps({"series": {"outside": [["2026-08-12", 7.5]]}}),
                encoding="utf-8")
            doc = b.measure(data, now=NOW,
                            material={"status": "OK",
                                      "per_pair": [_pair("2026-08-12", "outside")]})
            self.assertEqual(doc["status"], b.STATUS_CRITICAL)
            self.assertEqual(doc["values_planned"], 0)
            self.assertTrue(any("CRITICAL" in f for f in doc["findings"]))

    def test_a_malformed_series_is_unmeasured_with_a_named_reason(self):
        with TemporaryDirectory() as tmp:
            data = Path(tmp)
            (data / "allocation_rationale_history.jsonl").write_text(
                json.dumps(_line("2026-08-12")) + "\n", encoding="utf-8")
            (data / "apy_series_daily.json").write_text("[]", encoding="utf-8")
            doc = b.measure(data, now=NOW, material={"status": "OK", "per_pair": []})
            self.assertEqual(doc["status"], b.STATUS_UNMEASURED)
            self.assertIn("формы", doc["reason"])


class ThePointParserIsShared(unittest.TestCase):
    """Правило «что такое точка ряда» живёт ОДНИМ местом (ADR-309)."""

    def test_dates_are_derived_from_points_not_parsed_twice(self):
        from spa_core.monitoring import journal_backfill_material as mat
        series = {"p": [["2026-08-12", 1.0], ["2026-08-13", None],
                        ["2026-08-14"], "мусор"]}
        self.assertEqual(mat.series_points(series), {"p": {"2026-08-12": 1.0}})
        self.assertEqual(mat.series_dates(series), {"p": {"2026-08-12"}})

    def test_a_protocol_whose_rows_are_all_unreadable_keeps_an_empty_entry(self):
        """«Протокола нет в ряду» и «ряд нечитаем» — разные ответы."""
        from spa_core.monitoring import journal_backfill_material as mat
        self.assertEqual(mat.series_points({"p": ["мусор"]}), {"p": {}})


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
