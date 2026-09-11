"""Перепись окон: граничный день ПОЛНОГО буфера есть нижняя граница (заказ #562).

Каждый тест ниже — положительный контроль на РЕАЛЬНУЮ поломку, а не украшение:

* эталон — `orchestrator_runs.json` из ADR-322 (30 из 30, граница 02.09, 9 прогонов);
* второй носитель — `alert_history.json`, найденный ЭТОЙ переписью (500 из 500,
  граница 16.08), и утверждение о полноте, которое над ним печаталось;
* третий исход — хранилище, не объявляющее вместимости: про него нечем ответить,
  и `None` не имеет права свернуться в `False`.

FROZEN-DATE-OK: даты здесь — ПРЕДМЕТ проверки, а не окружение. Прибор сравнивает
даты только МЕЖДУ СОБОЙ (берёт минимальную), стенных часов не читает ни в одной
ветке, понятия свежести/TTL у него нет вовсе. Календарь может сдвинуться на год —
вердикт этих тестов не изменится ни в одном.
"""
# FROZEN-DATE-OK: даты здесь ЕСТЬ ПРЕДМЕТ проверки — прибор сравнивает их только
# между собой (минимальная = граница окна), стенных часов не читает ни в одной
# ветке, понятия свежести/TTL у него нет. Календарь сдвинется — вердикт не изменится.
import json
import tempfile
import unittest
from pathlib import Path

from spa_core.monitoring.bounded_window_census import (
    WINDOW_NAMED_SATURATED,
    WINDOW_NAMED_UNSATURATED,
    WINDOW_NOT_NAMED,
    census_store,
    consumers,
    day_of,
    declared_cap,
    run_census,
    saturation,
)


def _runs(day_counts):
    """Записи по дням: {'2026-09-02': 9, ...} → список записей с отметками."""
    out = []
    for day, n in day_counts.items():
        for i in range(n):
            out.append({"ts": f"{day}T{i % 24:02d}:11:00+00:00", "adapters": 8})
    return out


class ReferenceCase(unittest.TestCase):
    """Эталон ADR-322 воспроизводится дословно — иначе прибор мерит не то."""

    def setUp(self):
        # 30 прогонов, ровно как в живом буфере на день замера #563.
        self.records = _runs({"2026-09-02": 9, "2026-09-03": 7,
                              "2026-09-04": 7, "2026-09-05": 7})
        self.doc = {"runs": self.records, "max_runs": 30}

    def test_saturated_boundary_day_is_a_floor(self):
        row = census_store("orchestrator_runs.json", "runs", self.doc, self.records)
        self.assertIs(row["saturated"], True)
        self.assertEqual(row["class"], WINDOW_NAMED_SATURATED)
        self.assertEqual(row["boundary_day"], "2026-09-02")
        self.assertEqual(row["boundary_day_records"], 9)
        self.assertTrue(row["boundary_day_records_is_floor"])
        self.assertEqual(row["declared_cap_field"], "max_runs")

    def test_the_same_day_is_MEASURED_when_the_buffer_is_not_full(self):
        """Признак берётся из НАПОЛНЕНИЯ, а не из даты (решение №2 ADR-322).

        Если бы срезанность определялась «самый ранний день», проверка была бы
        истинной по построению и метила бы нижней границей любой ранний день.
        """
        doc = dict(self.doc, max_runs=100)
        row = census_store("orchestrator_runs.json", "runs", doc, self.records)
        self.assertIs(row["saturated"], False)
        self.assertEqual(row["class"], WINDOW_NAMED_UNSATURATED)
        self.assertEqual(row["boundary_day"], "2026-09-02")
        self.assertFalse(row["boundary_day_records_is_floor"])


class ThirdOutcome(unittest.TestCase):
    """`None` — «окно не названо», и оно НЕ сворачивается в `False`."""

    def test_no_declared_cap_gives_none_not_false(self):
        records = _runs({"2026-09-02": 3, "2026-09-03": 3})
        doc = {"entries": records}
        self.assertIsNone(saturation(doc, records))
        row = census_store("something.json", "entries", doc, records)
        self.assertIsNone(row["saturated"])
        self.assertIsNot(row["saturated"], False)
        self.assertEqual(row["class"], WINDOW_NOT_NAMED)
        self.assertFalse(row["window_named"])
        self.assertIn("НЕ «вытеснения не было»", row["reason"])

    def test_unnamed_window_never_claims_a_floor(self):
        """Нижняя граница при `None` была бы догадкой, поданной как факт."""
        records = _runs({"2026-09-02": 3})
        row = census_store("x.json", "entries", {"entries": records}, records)
        self.assertFalse(row["boundary_day_records_is_floor"])

    def test_a_lookalike_field_is_NOT_taken_for_a_window(self):
        """`max_drawdown_pct` именем похоже на потолок, а говорит о предмете.

        Принять его значило бы объявить окно там, где его нет, — и напечатать
        `saturated` про хранилище, которое своей вместимости не объявляло.
        """
        records = _runs({"2026-09-02": 3})
        self.assertIsNone(declared_cap({"entries": records, "max_drawdown_pct": 12}))
        self.assertIsNone(saturation({"entries": records, "max_drawdown_pct": 12}, records))

    def test_real_cap_names_other_than_max_runs_are_found(self):
        """Ищется ФОРМА правила, а не константа `max_runs` (ловушка заказа)."""
        records = _runs({"2026-09-02": 3})
        for field in ("max_entries", "ring_buffer_max", "log_cap", "history_limit"):
            self.assertEqual(declared_cap({"entries": records, field: 3}), (field, 3),
                             msg=f"форма не опознана: {field}")


class RecordsWithoutADay(unittest.TestCase):
    def test_undated_records_are_counted_apart_not_assigned_to_a_day(self):
        dated = _runs({"2026-09-02": 3})
        records = dated + [{"adapters": 8}, {"adapters": 9}]
        row = census_store("x.json", "entries", {"entries": records, "max_entries": 5},
                           records)
        self.assertEqual(row["undated_records"], 2)
        self.assertEqual(row["boundary_day_records"], 3)

    def test_day_of_refuses_a_non_timestamp(self):
        self.assertIsNone(day_of({"note": "не дата"}))
        self.assertIsNone(day_of("строка"))
        self.assertEqual(day_of({"ts": "2026-09-02T01:00:00Z"}), "2026-09-02")


class CensusIsFailClosed(unittest.TestCase):
    def test_missing_data_dir_is_unmeasured_not_clean(self):
        rep = run_census(Path("/nonexistent/spa/data/dir"))
        self.assertFalse(rep["measured"])
        self.assertIn("не найден", rep["reason"])
        self.assertEqual(rep["stores"], [])

    def test_counts_name_both_halves_of_the_order(self):
        with tempfile.TemporaryDirectory() as td:
            data = Path(td)
            (data / "full.json").write_text(json.dumps(
                {"runs": _runs({"2026-09-02": 4, "2026-09-03": 4}), "max_runs": 8}),
                encoding="utf-8")
            (data / "unnamed.json").write_text(json.dumps(
                {"entries": _runs({"2026-09-02": 4})}), encoding="utf-8")
            rep = run_census(data)
        self.assertTrue(rep["measured"])
        self.assertEqual(rep["counts"]["journals"], 2)
        self.assertEqual(rep["counts"]["window_named"], 1)
        self.assertEqual(rep["counts"]["window_not_named"], 1)
        self.assertEqual(rep["counts"]["saturated_boundary_is_floor"], 1)

    def test_a_list_whose_records_are_mostly_undated_is_not_a_journal(self):
        """Судить границу не-журнала значило бы мерить не то население."""
        with tempfile.TemporaryDirectory() as td:
            data = Path(td)
            (data / "notalog.json").write_text(json.dumps(
                {"items": [{"name": "a"}, {"name": "b"}, {"name": "c"},
                           {"ts": "2026-09-02T01:00:00Z"}]}), encoding="utf-8")
            rep = run_census(data)
        self.assertEqual(rep["counts"]["journals"], 0)

    def test_consumers_refuses_an_unreadable_root(self):
        out = consumers("x.json", [Path("/nonexistent/spa/src")])
        self.assertFalse(out["measured"])
        self.assertIn("не найден", out["reason"])


if __name__ == "__main__":
    unittest.main()
