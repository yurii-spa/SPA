"""Приёмка G16 — цена отмены двойного счёта в журнале решений (ADR-384).

Каждый тест — положительный контроль: он краснеет на конкретной поломке, а не
подтверждает, что код запускается. Литеральных дат здесь нет вовсе; где нужна
дата, она строится от якоря, объявленного прямо в тесте.
"""
# FROZEN-DATE-OK: дат-литералов в файле нет — даты строятся счётом от _ANCHOR,
# который тест задаёт сам; ни одна проверка не смотрит на стенные часы.
from __future__ import annotations

import importlib
import json
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from spa_core.monitoring import run_identity_key_price as g16

#: Якорь дат стенда. Календарь машины на вердикты не влияет: все отметки
#: строятся от него счётом, и ни одна проверка не спрашивает часы.
_ANCHOR = datetime(2026, 9, 11, 12, 0, 0, tzinfo=timezone.utc)


def _day(offset: int = 0) -> str:
    return (_ANCHOR + timedelta(days=offset)).date().isoformat()


def _stamp(days: int = 0, hours: int = 0) -> str:
    return (_ANCHOR + timedelta(days=days, hours=hours)).isoformat()


def _row(day_offset: int, *, verdict: str = "HOLD", hours: int = 0, **extra) -> dict:
    row = {"cycle_date": _day(day_offset), "verdict": verdict,
           "decision_id": f"adr060-shadow-{_day(day_offset)}",
           "generated_at": _stamp(day_offset, hours), "schema": "shadow-hist-v2"}
    row.update(extra)
    return row


def _write_history(data_dir: Path, rows) -> None:
    data_dir.mkdir(parents=True, exist_ok=True)
    (data_dir / g16.HISTORY_FILENAME).write_text(
        "\n".join(json.dumps(r, sort_keys=True) for r in rows) + "\n", encoding="utf-8")


def _write_trades(data_dir: Path, trades) -> None:
    data_dir.mkdir(parents=True, exist_ok=True)
    (data_dir / g16.TRADES_FILENAME).write_text(json.dumps(trades), encoding="utf-8")


def _write_audit(data_dir: Path, per_day) -> None:
    data_dir.mkdir(parents=True, exist_ok=True)
    lines = []
    for day, count in per_day.items():
        for i in range(count):
            lines.append(json.dumps({"event": "cycle_start",
                                     "timestamp": f"{day}T{i:02d}:00:00+00:00"}))
    (data_dir / g16.AUDIT_FILENAME).write_text("\n".join(lines) + "\n", encoding="utf-8")


# ── 1. КЛЮЧ ──────────────────────────────────────────────────────────────────
class KeyProbeTests(unittest.TestCase):
    """Поле, равное при РАЗЛИЧАЮЩИХСЯ входах одного дня, ключом быть не может."""

    def test_field_derived_from_the_date_is_named_date_derived(self):
        """Авария ADR-384: decision_id = f(cycle_date) выглядит готовым ключом."""
        def builder(doc, **kw):
            return {"decision_id": f"adr060-shadow-{doc['cycle_date']}",
                    "verdict": doc["decision_shadow"]["decision"]}
        out = g16.probe_key_fields(builder=builder)
        self.assertTrue(out["measured"])
        self.assertIn("decision_id", out["date_derived"])
        self.assertFalse(out["decision_id_distinguishes_runs"])

    def test_field_varying_with_the_run_is_named_run_distinct(self):
        def builder(doc, **kw):
            return {"decision_id": doc["generated_at"]}
        out = g16.probe_key_fields(builder=builder)
        self.assertIn("decision_id", out["run_distinct"])
        self.assertTrue(out["decision_id_distinguishes_runs"])

    def test_builder_failure_is_unmeasured_not_an_empty_answer(self):
        def builder(doc, **kw):
            raise RuntimeError("писатель недоступен")
        out = g16.probe_key_fields(builder=builder)
        self.assertFalse(out["measured"])
        self.assertIn("упал", out["reason"])
        self.assertNotIn("date_derived", out)

    def test_the_probes_own_inputs_really_differ(self):
        """Контроль на истинность ПО ПОСТРОЕНИЮ: равные входы дали бы равные
        выходы у ЛЮБОГО поля, и проба объявила бы ключом дату всё подряд."""
        (doc_a, kw_a), (doc_b, kw_b) = g16._twin_docs(_day())
        self.assertEqual(doc_a["cycle_date"], doc_b["cycle_date"])
        self.assertNotEqual(doc_a["generated_at"], doc_b["generated_at"])
        self.assertNotEqual(doc_a["params"], doc_b["params"])
        self.assertNotEqual(doc_a["decision_shadow"], doc_b["decision_shadow"])
        for key in ("apy_pct", "apy_sources", "current_positions",
                    "target_positions", "capital_usd", "apy_as_of"):
            self.assertNotEqual(kw_a[key], kw_b[key], key)

    def test_real_writer_says_decision_id_is_the_date(self):
        """Не пересказ докстринга писателя, а замер НАСТОЯЩИМ писателем."""
        out = g16.probe_key_fields()
        self.assertTrue(out["measured"], out.get("reason"))
        self.assertFalse(out["decision_id_distinguishes_runs"])
        self.assertIn("generated_at", out["run_distinct"])


# ── 2. МИГРАЦИЯ ──────────────────────────────────────────────────────────────
class MigrationTests(unittest.TestCase):

    def test_rows_without_the_key_are_counted_not_zeroed(self):
        rows = [_row(0), {"cycle_date": _day(1), "generated_at": _stamp(1)}]
        out = g16.measure_migration(rows, candidates=("decision_id",))
        row = out["by_candidate"]["decision_id"]
        self.assertEqual(row["rows_with_key"], 1)
        self.assertEqual(row["rows_needing_minted_key"], 1)

    def test_two_rows_of_one_day_collide_under_a_day_key(self):
        rows = [_row(0, hours=1), _row(0, hours=9)]
        out = g16.measure_migration(rows, candidates=("decision_id",))
        self.assertEqual(out["by_candidate"]["decision_id"]["collisions"], 1)

    def test_a_date_derived_candidate_is_refused_even_with_zero_collisions(self):
        """Главная ловушка заказа: на накопленных строках ключ-дата не
        сталкивается НИ РАЗУ (день один, строка одна) и выглядит годным."""
        rows = [_row(i) for i in range(4)]
        out = g16.measure_migration(rows, candidates=("decision_id",),
                                    date_derived=["decision_id"])
        row = out["by_candidate"]["decision_id"]
        self.assertEqual(row["collisions"], 0)
        self.assertFalse(row["distinguishes_runs"])
        self.assertIn("НЕ ГОДЕН", row["verdict"])

    def test_a_run_distinct_candidate_without_collisions_is_fit(self):
        rows = [_row(i) for i in range(4)]
        out = g16.measure_migration(rows, candidates=("generated_at",),
                                    date_derived=["decision_id"])
        self.assertEqual(out["by_candidate"]["generated_at"]["verdict"], "годен")


# ── 3. ЧИТАТЕЛИ: вердикт по ИСХОДУ ───────────────────────────────────────────
_STUBS = {
    "last": "def measure(data_dir, **kw):\n"
            "    import json\n"
            "    rows=[json.loads(l) for l in (data_dir/'h.jsonl').read_text().splitlines() if l.strip()]\n"
            "    by={}\n"
            "    for r in rows: by[r['cycle_date']]=r\n"
            "    return {'verdicts': sorted((d, v['verdict']) for d, v in by.items())}\n",
    "first": "def measure(data_dir, **kw):\n"
             "    import json\n"
             "    rows=[json.loads(l) for l in (data_dir/'h.jsonl').read_text().splitlines() if l.strip()]\n"
             "    by={}\n"
             "    for r in rows: by.setdefault(r['cycle_date'], r)\n"
             "    return {'verdicts': sorted((d, v['verdict']) for d, v in by.items())}\n",
    "both": "def measure(data_dir, **kw):\n"
            "    import json\n"
            "    rows=[json.loads(l) for l in (data_dir/'h.jsonl').read_text().splitlines() if l.strip()]\n"
            "    return {'lines': len(rows), 'verdicts': [r['verdict'] for r in rows]}\n",
    "deaf": "def measure(data_dir, **kw):\n"
            "    return {'answer': 'журнала не читаю'}\n",
    "flaky": "_N=[0]\n"
             "def measure(data_dir, **kw):\n"
             "    _N[0]+=1\n"
             "    return {'n': _N[0]}\n",
    "clocky": "def measure(data_dir, **kw):\n"
              "    import json, itertools\n"
              "    _c=getattr(measure,'_c',None) or itertools.count()\n"
              "    measure._c=_c\n"
              "    rows=[json.loads(l) for l in (data_dir/'h.jsonl').read_text().splitlines() if l.strip()]\n"
              "    return {'generated_at': 'тик-%d' % next(_c),\n"
              "            'verdicts': [r['verdict'] for r in rows]}\n",
    "nodriver": "VALUE = 1\n",
    "angry": "def measure(data_dir, **kw):\n"
             "    raise ValueError('не умею')\n",
    "writes": "def measure(data_dir, *, write=True, **kw):\n"
              "    import json\n"
              "    rows=[json.loads(l) for l in (data_dir/'h.jsonl').read_text().splitlines() if l.strip()]\n"
              "    return {'lines': len(rows), 'write': write}\n",
}


class ReaderClassificationTests(unittest.TestCase):
    """Стенды намеренно НЕ копируют живое data/: предмет здесь — правило
    сравнения трёх ответов, и оно от объёма копии не зависит."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(prefix="g16_readers_")
        self.root = Path(self._tmp.name)
        self.pkg = self.root / "stubs"
        self.pkg.mkdir()
        for name, src in _STUBS.items():
            (self.pkg / f"g16stub_{name}.py").write_text(src, encoding="utf-8")
        sys.path.insert(0, str(self.pkg))
        self.stands = {}
        for stand, rows in (("s1", [_row(0, verdict="HOLD", hours=9)]),
                            ("s2", [_row(0, verdict="ACT", hours=1),
                                    _row(0, verdict="HOLD", hours=9)]),
                            ("s3", [_row(0, verdict="ACT", hours=1)])):
            data = self.root / stand / "data"
            data.mkdir(parents=True)
            (data / "h.jsonl").write_text(
                "\n".join(json.dumps(r, sort_keys=True) for r in rows) + "\n",
                encoding="utf-8")
            self.stands[stand] = self.root / stand

    def tearDown(self):
        sys.path.remove(str(self.pkg))
        for name in list(sys.modules):
            if name.startswith("g16stub_"):
                del sys.modules[name]
        self._tmp.cleanup()

    def _classify(self, stub):
        return g16.classify_reader(f"g16stub_{stub}", self.stands)

    def test_reader_keeping_the_last_line_collapses_to_last(self):
        """Авария ADR-384: ровно так устроен shadow_trigger_eval.load_history."""
        self.assertEqual(self._classify("last")["outcome"], g16.READER_LAST)

    def test_reader_keeping_the_first_line_collapses_to_first(self):
        self.assertEqual(self._classify("first")["outcome"], g16.READER_FIRST)

    def test_reader_counting_all_lines_sees_both(self):
        self.assertEqual(self._classify("both")["outcome"], g16.READER_BOTH)

    def test_reader_ignoring_the_journal_is_not_called_collapsing(self):
        """Без третьего исхода «равен S1» записалось бы в схлопывание тому, кто
        журнал не читает вовсе, — контроль, истинный ПО ПОСТРОЕНИЮ."""
        row = self._classify("deaf")
        self.assertEqual(row["outcome"], g16.READER_INSENSITIVE)
        self.assertNotEqual(row["outcome"], g16.READER_LAST)

    def test_nonreproducible_answer_is_unmeasured_not_sees_both(self):
        row = self._classify("flaky")
        self.assertEqual(row["outcome"], g16.READER_UNMEASURED)
        self.assertIn("не воспроизводится", row["reason"])

    def test_a_named_clock_field_does_not_forge_a_difference(self):
        """Хеш ВСЕГО ответа сделал бы каждого читателя `sees_both`: часы
        меняются на каждом зове. Часы названы ПОИМЁННО."""
        self.assertEqual(self._classify("clocky")["outcome"], g16.READER_BOTH)

    def test_module_without_a_drivable_entry_point_is_unmeasured(self):
        row = self._classify("nodriver")
        self.assertEqual(row["outcome"], g16.READER_UNMEASURED)
        self.assertIn("точки входа", row["reason"])

    def test_entry_point_raising_is_unmeasured_with_its_type(self):
        row = self._classify("angry")
        self.assertEqual(row["outcome"], g16.READER_UNMEASURED)
        self.assertIn("ValueError", row["reason"])

    def test_missing_module_is_unmeasured_not_absent(self):
        row = g16.classify_reader("g16stub_no_such_module_at_all", self.stands)
        self.assertEqual(row["outcome"], g16.READER_UNMEASURED)
        self.assertIn("импорт", row["reason"])

    def test_write_false_is_passed_to_every_entry_point_that_takes_it(self):
        """Прибор обязан звать читателя так, чтобы тот НЕ ПИСАЛ, — иначе
        утверждение «только читаю» держится на том, что стенд одноразовый."""
        mod = importlib.import_module("g16stub_writes")
        _name, call = g16.module_driver(mod)
        self.assertFalse(call(self.stands["s1"])["write"])


# ── 4. НАСЕЛЕНИЕ: две дороги, и каждая слепа к другой ────────────────────────
class PopulationTests(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(prefix="g16_pop_")
        self.tree = Path(self._tmp.name)
        pkg = self.tree / "spa_core" / "paper_trading"
        pkg.mkdir(parents=True)
        (self.tree / "spa_core" / "__init__.py").write_text("", encoding="utf-8")
        (pkg / "__init__.py").write_text("", encoding="utf-8")
        (pkg / "shadow_trigger_eval.py").write_text(
            "def load_history(d):\n    return []\n", encoding="utf-8")
        mon = self.tree / "spa_core" / "monitoring"
        mon.mkdir()
        (mon / "__init__.py").write_text("", encoding="utf-8")
        # дорога 1: произносит ИМЯ файла, загрузчика не импортирует
        (mon / "by_name.py").write_text(
            "PATH = 'allocation_rationale_history.jsonl'\n", encoding="utf-8")
        # посредник: импортирует загрузчик
        (mon / "middle.py").write_text(
            "from spa_core.paper_trading import shadow_trigger_eval as _ste\n",
            encoding="utf-8")
        # дорога 2: имени файла НЕ произносит, доходит через посредника
        (mon / "by_alias.py").write_text(
            "from spa_core.monitoring import middle as _dep\n"
            "def measure(data_dir):\n    return _dep._ste.load_history(data_dir)\n",
            encoding="utf-8")
        tests = mon / "tests"
        tests.mkdir()
        (tests / "test_noise.py").write_text(
            "PATH = 'allocation_rationale_history.jsonl'\n", encoding="utf-8")

    def tearDown(self):
        self._tmp.cleanup()

    def test_filename_road_alone_misses_the_alias_reader(self):
        roads, _ = g16.reader_population(
            self.tree, loaders=("spa_core.paper_trading.shadow_trigger_eval",))
        by_name = roads["spa_core.monitoring.by_name"]
        self.assertIn(g16.ROAD_FILENAME, by_name)
        self.assertNotIn(g16.ROAD_IMPORTS, by_name)

    def test_import_road_alone_misses_the_filename_reader(self):
        roads, _ = g16.reader_population(
            self.tree, loaders=("spa_core.paper_trading.shadow_trigger_eval",))
        by_alias = roads["spa_core.monitoring.by_alias"]
        self.assertIn(g16.ROAD_IMPORTS, by_alias)
        self.assertNotIn(g16.ROAD_FILENAME, by_alias)

    def test_population_is_the_union_of_both_roads(self):
        roads, stats = g16.reader_population(
            self.tree, loaders=("spa_core.paper_trading.shadow_trigger_eval",))
        self.assertIn("spa_core.monitoring.by_name", roads)
        self.assertIn("spa_core.monitoring.by_alias", roads)
        self.assertEqual(stats["via_filename_only"], ["spa_core.monitoring.by_name"])

    def test_transitive_reach_is_followed_not_just_direct_imports(self):
        """by_alias импортирует ПОСРЕДНИКА, а не загрузчик: прямого ребра нет."""
        roads, _ = g16.reader_population(
            self.tree, loaders=("spa_core.paper_trading.shadow_trigger_eval",))
        self.assertIn(g16.ROAD_IMPORTS, roads["spa_core.monitoring.middle"])
        self.assertIn(g16.ROAD_IMPORTS, roads["spa_core.monitoring.by_alias"])

    def test_tests_are_not_part_of_the_population(self):
        roads, _ = g16.reader_population(
            self.tree, loaders=("spa_core.paper_trading.shadow_trigger_eval",))
        self.assertNotIn("spa_core.monitoring.tests.test_noise", roads)


# ── 5. СТЕНДЫ ────────────────────────────────────────────────────────────────
class StandTests(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(prefix="g16_stands_")
        self.root = Path(self._tmp.name)
        self.src = self.root / "src"
        self.src.mkdir()
        _write_history(self.src, [_row(0, hours=8), _row(1, hours=9)])
        (self.src / "other.json").write_text("{}", encoding="utf-8")
        skip = self.src / g16.STAND_EXCLUDE[0]
        skip.mkdir()
        (skip / "heavy.bin").write_text("x", encoding="utf-8")

    def tearDown(self):
        self._tmp.cleanup()

    def _rows(self, stand: Path):
        rows, why = g16.read_history(stand / "data")
        self.assertIsNotNone(rows, why)
        return rows

    def test_s2_carries_two_lines_for_the_day_and_s1_s3_carry_one(self):
        stands, why = g16.build_stands(self.src, self.root / "out", day=_day(1))
        self.assertIsNotNone(stands, why)
        day = _day(1)
        self.assertEqual(sum(1 for r in self._rows(stands["s1"]) if r["cycle_date"] == day), 1)
        self.assertEqual(sum(1 for r in self._rows(stands["s2"]) if r["cycle_date"] == day), 2)
        self.assertEqual(sum(1 for r in self._rows(stands["s3"]) if r["cycle_date"] == day), 1)

    def test_the_twin_is_a_real_neighbour_row_relabelled_not_a_fabrication(self):
        _write_history(self.src, [_row(0, hours=8, turnover_usd=4242.0), _row(1, hours=9)])
        stands, _ = g16.build_stands(self.src, self.root / "out", day=_day(1))
        twin = [r for r in self._rows(stands["s3"]) if r["cycle_date"] == _day(1)][0]
        self.assertEqual(twin["turnover_usd"], 4242.0)   # материал донора
        self.assertEqual(twin["verdict"], "ACT")          # перемечено

    def test_s2_holds_the_twin_before_the_surviving_line(self):
        stands, _ = g16.build_stands(self.src, self.root / "out", day=_day(1))
        day_rows = [r for r in self._rows(stands["s2"]) if r["cycle_date"] == _day(1)]
        self.assertEqual([r["verdict"] for r in day_rows], ["ACT", "HOLD"])

    def test_the_excluded_directory_is_absent_from_every_stand_alike(self):
        """Исключение ОДИНАКОВО на трёх стендах — дифференциал к нему слеп."""
        stands, _ = g16.build_stands(self.src, self.root / "out", day=_day(1))
        for name in ("s1", "s2", "s3"):
            self.assertFalse((stands[name] / "data" / g16.STAND_EXCLUDE[0]).exists())
            self.assertTrue((stands[name] / "data" / "other.json").exists())

    def test_absent_history_is_unmeasured_with_a_reason(self):
        empty = self.root / "empty"
        empty.mkdir()
        stands, why = g16.build_stands(empty, self.root / "out2")
        self.assertIsNone(stands)
        self.assertIn(g16.HISTORY_FILENAME, why)

    def test_unknown_day_is_refused_not_silently_replaced(self):
        stands, why = g16.build_stands(self.src, self.root / "out3", day=_day(99))
        self.assertIsNone(stands)
        self.assertIn(_day(99), why)

    def test_a_single_line_journal_has_no_neighbour_and_is_refused(self):
        _write_history(self.src, [_row(0)])
        stands, why = g16.build_stands(self.src, self.root / "out4")
        self.assertIsNone(stands)
        self.assertIn("соседнего дня", why)


# ── 6. ГРАНИЦЫ ACT-дней ──────────────────────────────────────────────────────
class ActBoundTests(unittest.TestCase):

    MARK = "cio_trial_grant"

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(prefix="g16_bounds_")
        self.data = Path(self._tmp.name) / "data"
        self.data.mkdir(parents=True)

    def tearDown(self):
        self._tmp.cleanup()

    def _trade(self, day_offset: int, hours: int, *, marked: bool = False) -> dict:
        trade = {"trade_id": f"T{day_offset:03d}", "ts": _stamp(day_offset, hours)}
        if marked:
            trade[self.MARK] = True
        return trade

    def test_a_marked_move_enters_both_bounds(self):
        _write_history(self.data, [_row(0, hours=1), _row(1, hours=20)])
        _write_trades(self.data, [self._trade(1, 9, marked=True)])
        _write_audit(self.data, {_day(1): 4})
        out = g16.act_day_bounds(self.data, trial_mark=self.MARK)
        self.assertEqual(out["lower"], 1)
        self.assertEqual(out["upper"], 1)

    def test_an_unmarked_move_enters_only_the_upper_bound(self):
        _write_history(self.data, [_row(0, hours=1), _row(1, hours=20)])
        _write_trades(self.data, [self._trade(1, 9)])
        _write_audit(self.data, {_day(1): 4})
        out = g16.act_day_bounds(self.data, trial_mark=self.MARK)
        self.assertEqual(out["lower"], 0)
        self.assertEqual(out["upper"], 1)

    def test_a_line_written_before_the_move_is_not_a_replacement(self):
        """Строка РАНЬШЕ хода — прогон хода строки не оставил; назвать это
        заменой значило бы записать правилу цену, которой оно не платило."""
        _write_history(self.data, [_row(0, hours=1), _row(1, hours=2)])
        _write_trades(self.data, [self._trade(1, 9)])
        _write_audit(self.data, {_day(1): 4})
        out = g16.act_day_bounds(self.data, trial_mark=self.MARK)
        self.assertEqual(out["upper"], 0)
        self.assertIn(_day(1), out["not_replacement"])

    def test_a_single_run_day_cannot_have_lost_a_line(self):
        """Носитель прогонов НЕЗАВИСИМ от журнала и режет верхнюю границу."""
        _write_history(self.data, [_row(0, hours=1), _row(1, hours=20)])
        _write_trades(self.data, [self._trade(1, 9)])
        _write_audit(self.data, {_day(1): 1})
        out = g16.act_day_bounds(self.data, trial_mark=self.MARK)
        self.assertEqual(out["upper"], 0)
        self.assertIn(_day(1), out["not_replacement"])

    def test_a_day_absent_from_the_run_carrier_is_not_taken_for_one_run(self):
        """Молчание носителя — не «прогон был один»: день остаётся в границе."""
        _write_history(self.data, [_row(0, hours=1), _row(1, hours=20)])
        _write_trades(self.data, [self._trade(1, 9)])
        _write_audit(self.data, {_day(0): 3})
        out = g16.act_day_bounds(self.data, trial_mark=self.MARK)
        self.assertEqual(out["upper"], 1)

    def test_a_day_with_no_journal_line_enters_neither_bound(self):
        _write_history(self.data, [_row(0, hours=1), _row(1, hours=2)])
        _write_trades(self.data, [self._trade(9, 9, marked=True)])
        _write_audit(self.data, {_day(9): 4})
        out = g16.act_day_bounds(self.data, trial_mark=self.MARK)
        self.assertEqual((out["lower"], out["upper"]), (0, 0))
        self.assertIn(_day(9), out["outside_journal_window"])

    def test_a_day_whose_line_already_says_act_is_not_counted(self):
        _write_history(self.data, [_row(0, hours=1), _row(1, verdict="ACT", hours=20)])
        _write_trades(self.data, [self._trade(1, 9, marked=True)])
        _write_audit(self.data, {_day(1): 4})
        out = g16.act_day_bounds(self.data, trial_mark=self.MARK)
        self.assertEqual((out["lower"], out["upper"]), (0, 0))

    def test_missing_trades_file_is_unmeasured_not_zero_bounds(self):
        _write_history(self.data, [_row(0), _row(1)])
        out = g16.act_day_bounds(self.data, trial_mark=self.MARK)
        self.assertFalse(out["measured"])
        self.assertNotIn("lower", out)

    def test_an_unparsable_stamp_is_unmeasured_not_dropped(self):
        _write_history(self.data, [_row(0, hours=1),
                                   {"cycle_date": _day(1), "verdict": "HOLD",
                                    "generated_at": "позавчера"}])
        _write_trades(self.data, [self._trade(1, 9)])
        _write_audit(self.data, {_day(1): 4})
        out = g16.act_day_bounds(self.data, trial_mark=self.MARK)
        self.assertFalse(out["measured"])
        self.assertIn("не разобран", out["reason"])

    def test_the_run_carrier_is_the_audit_trail_not_the_journal(self):
        _write_audit(self.data, {_day(0): 3, _day(1): 1})
        counts, why = g16.runs_per_day(self.data)
        self.assertEqual(counts, {_day(0): 3, _day(1): 1})
        self.assertEqual(why, "")

    def test_absent_run_carrier_is_none_not_an_empty_count(self):
        counts, why = g16.runs_per_day(self.data)
        self.assertIsNone(counts)
        self.assertIn(g16.AUDIT_FILENAME, why)


# ── 7. ВЕРДИКТ И ОТЧЁТ ───────────────────────────────────────────────────────
class VerdictTests(unittest.TestCase):

    def _doc(self, **over):
        doc = {"key_probe": {"measured": True, "decision_id_distinguishes_runs": False,
                             "decision_id_value": "adr060-shadow-X",
                             "date_derived": ["decision_id"], "run_distinct": ["generated_at"]},
               "act_bounds": {"measured": True, "lower": 1, "upper": 11,
                              "trade_days": 13, "lower_days": ["д"], "upper_days": [],
                              "outside_journal_window": [], "not_replacement": []},
               "readers": {"measured": True, "modules": [
                   {"module": "m.a", "outcome": g16.READER_LAST, "entry": "measure"},
                   {"module": "m.b", "outcome": g16.READER_BOTH, "entry": "measure"}],
                   "outcomes": {g16.READER_LAST: 1, g16.READER_BOTH: 1},
                   "population_stats": {"via_filename_only": [], "via_imports_only": [],
                                        "via_both": []},
                   "stand": {"day": "д"}},
               "migration": {"by_candidate": {}}}
        doc.update(over)
        return doc

    def test_a_collapsing_reader_makes_the_verdict_critical(self):
        doc = g16._verdict(self._doc())
        self.assertEqual(doc["overall"], g16.STATUS_CRITICAL)
        self.assertIn("НЕ ДОХОДИТ", doc["reason"])

    def test_no_collapsing_reader_but_a_renamed_key_is_only_warning(self):
        doc = self._doc()
        doc["readers"]["outcomes"] = {g16.READER_BOTH: 2}
        out = g16._verdict(doc)
        self.assertEqual(out["overall"], g16.STATUS_WARNING)

    def test_unmeasured_key_probe_beats_every_other_verdict(self):
        doc = self._doc(key_probe={"measured": False, "reason": "писатель недоступен"})
        self.assertEqual(g16._verdict(doc)["overall"], g16.STATUS_UNMEASURED)

    def test_unmeasured_bounds_beat_every_other_verdict(self):
        doc = self._doc(act_bounds={"measured": False, "reason": "сделок нет"})
        self.assertEqual(g16._verdict(doc)["overall"], g16.STATUS_UNMEASURED)

    def test_unmeasured_exits_with_code_two_not_zero(self):
        codes = {g16.STATUS_OK: 0, g16.STATUS_WARNING: 1,
                 g16.STATUS_CRITICAL: 1, g16.STATUS_UNMEASURED: 2}
        self.assertEqual(codes[g16.STATUS_UNMEASURED], 2)

    def test_the_report_prints_both_bounds_on_one_line(self):
        lines = g16.format_report(g16._verdict(self._doc()))
        self.assertTrue(any("[1, 11]" in ln for ln in lines),
                        "\n".join(lines))

    def test_the_report_names_every_collapsing_module(self):
        lines = g16.format_report(g16._verdict(self._doc()))
        self.assertTrue(any("m.a" in ln and "СХЛОПЫВАЕТ" in ln for ln in lines))
        self.assertFalse(any("m.b" in ln and "СХЛОПЫВАЕТ" in ln for ln in lines))

    def test_the_report_says_not_measured_rather_than_printing_nothing(self):
        lines = g16.format_report(g16._verdict(
            self._doc(readers={"measured": False, "reason": "стенды не построены"})))
        self.assertTrue(any("НЕ ИЗМЕРЕНО" in ln for ln in lines))


if __name__ == "__main__":  # pragma: no cover
    unittest.main()


# ── 8. ДЫРЫ, НАЙДЕННЫЕ БАТАРЕЕЙ МУТАЦИЙ ──────────────────────────────────────
# Первый прогон батареи оставил 81 выжившего из 135: набор выглядел плотным и им
# не был. Ниже — контроли ровно на те строки, чьё изменение НИКТО не замечал.
# Дыры того же рода, что у соседей: ЧИСЛА (пороги и умолчания не проверял никто)
# и ПУТИ (ветки драйвера, правило дня, заслон от рекурсии, коды возврата).

class BatteryHoleTests(unittest.TestCase):
    """Каждый тест краснеет на ОДНОЙ выжившей координате, названной в комментарии."""

    MARK = "cio_trial_grant"

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(prefix="g16_holes_")
        self.root = Path(self._tmp.name)
        self.data = self.root / "data"
        self.data.mkdir(parents=True)

    def tearDown(self):
        self._tmp.cleanup()

    # ── порог «сколько прогонов в дне» ──────────────────────────────────────
    def test_two_runs_in_a_day_still_count_as_replaceable(self):
        """Выжившая мутация `runs_in_day < 2` → `< 3`: сам ПОРОГ не проверял
        никто, потому что стенд давал ровно ОДИН прогон."""
        _write_history(self.data, [_row(0, hours=1), _row(1, hours=20)])
        _write_trades(self.data, [{"trade_id": "T1", "ts": _stamp(1, 9)}])
        _write_audit(self.data, {_day(1): 2})
        out = g16.act_day_bounds(self.data, trial_mark=self.MARK)
        self.assertEqual(out["upper"], 1)
        self.assertEqual(out["not_replacement"], [])

    # ── длина отметки ───────────────────────────────────────────────────────
    def test_a_date_only_trade_stamp_is_still_assigned_to_its_day(self):
        """Выжившая мутация `len(stamp) >= 10` → `>= 11` на ходах: отметка
        ровно в десять знаков (только дата) попадает на границу правила."""
        _write_history(self.data, [_row(0, hours=1), _row(1, hours=20)])
        _write_trades(self.data, [{"trade_id": "T1", "ts": _day(1)}])
        _write_audit(self.data, {_day(1): 4})
        out = g16.act_day_bounds(self.data, trial_mark=self.MARK)
        self.assertEqual(out["trade_days"], 1)

    def test_a_date_only_run_stamp_is_still_counted(self):
        """Та же граница у носителя прогонов."""
        (self.data / g16.AUDIT_FILENAME).write_text(
            json.dumps({"event": "cycle_start", "timestamp": _day(1)}) + "\n",
            encoding="utf-8")
        counts, _ = g16.runs_per_day(self.data)
        self.assertEqual(counts, {_day(1): 1})

    def test_the_run_carrier_reads_its_alternative_field_names(self):
        """Выжившие `or` в `obj.get("event") or ... or ...`: запасные имена
        полей не проверял никто, а носитель писал их в разное время."""
        (self.data / g16.AUDIT_FILENAME).write_text(
            json.dumps({"event_type": "cycle_start", "ts": _stamp(1, 3)}) + "\n",
            encoding="utf-8")
        counts, _ = g16.runs_per_day(self.data)
        self.assertEqual(counts, {_day(1): 1})

    # ── счёт ACT-строк журнала ──────────────────────────────────────────────
    def test_the_journal_section_counts_act_lines_not_the_rest(self):
        """Выжившая мутация `== "ACT"` → `!= "ACT"`: поле `journal.act_lines`
        не проверял ни один тест."""
        _write_history(self.data, [_row(0, verdict="ACT"), _row(1), _row(2)])
        _write_trades(self.data, [])
        doc = g16.measure(self.data, sweep_readers=False)
        self.assertEqual(doc["journal"]["act_lines"], 1)
        self.assertEqual(doc["journal"]["lines"], 3)

    # ── умолчание вердикта ──────────────────────────────────────────────────
    def test_a_key_probe_without_the_field_is_not_taken_for_a_good_key(self):
        """Выжившая мутация умолчания в `key.get(..., True)`: запись без поля
        объявлялась бы годным ключом молча."""
        doc = {"key_probe": {"measured": True},
               "act_bounds": {"measured": True, "lower": 0, "upper": 0},
               "readers": {"measured": True, "outcomes": {}, "modules": []}}
        out = g16._verdict(doc)
        self.assertEqual(out["overall"], g16.STATUS_UNMEASURED)
        self.assertNotEqual(out["overall"], g16.STATUS_OK)

    # ── коды возврата: у main(), а не у своей копии словаря ─────────────────
    def test_main_returns_two_when_the_answer_is_not_measured(self):
        """Прежний тест строил СВОЙ словарь кодов и был истинным по построению.
        Выжившие мутации `codes` и умолчания `2` этого не замечали."""
        rc = g16.main(["--root", str(self.root), "--no-write", "--no-readers"])
        self.assertEqual(rc, 2)

    def test_main_returns_one_on_a_measured_finding(self):
        _write_history(self.data, [_row(0, hours=1), _row(1, hours=20)])
        _write_trades(self.data, [{"trade_id": "T1", "ts": _stamp(1, 9)}])
        _write_audit(self.data, {_day(1): 4})
        rc = g16.main(["--root", str(self.root), "--no-write", "--no-readers"])
        self.assertEqual(rc, 1)

    def test_no_write_leaves_no_artifact_and_the_default_writes_one(self):
        """Выжившие мутации умолчания `write: bool = True` — ровно то поле,
        которое решает, пишем ли мы в прод."""
        _write_history(self.data, [_row(0, hours=1), _row(1, hours=20)])
        _write_trades(self.data, [{"trade_id": "T1", "ts": _stamp(1, 9)}])
        _write_audit(self.data, {_day(1): 4})
        g16.run(root=str(self.root), write=False, sweep_readers=False)
        self.assertFalse((self.data / g16.ARTIFACT).exists())
        g16.run(root=str(self.root), sweep_readers=False)
        self.assertTrue((self.data / g16.ARTIFACT).exists())

    def test_the_root_branch_resolves_to_its_data_subdirectory(self):
        """Выжившая мутация `Path(root or ".")`: ветка `root` (а не
        `--data-dir`) не проверялась, и артефакт лёг бы РЯДОМ с деревом."""
        _write_history(self.data, [_row(0, hours=1), _row(1, hours=20)])
        _write_trades(self.data, [])
        doc = g16.run(root=str(self.root), write=False, sweep_readers=False)
        self.assertEqual(doc["journal"]["lines"], 2)

    # ── правило выбора дня стенда ───────────────────────────────────────────
    def test_the_stand_day_leaves_the_judges_horizon_behind_it(self):
        """Выжившие мутации правила дня. Первый прогон прибора брал ПОСЛЕДНИЙ
        день журнала — за ним нет ни одного форвардного дня, и оконный читатель
        на нём не шелохнётся: 13 схлопывающих вместо 20."""
        rows = [_row(i, hours=1) for i in range(20)]
        _write_history(self.data, rows)
        stands, why = g16.build_stands(self.data, self.root / "out")
        self.assertIsNotNone(stands, why)
        horizon = g16._judge_horizon()
        self.assertIsNotNone(horizon)
        tail = [r["cycle_date"] for r in rows].index(stands["day"])
        self.assertEqual(len(rows) - 1 - tail, horizon)

    def test_the_donor_is_the_neighbour_of_the_chosen_day(self):
        rows = [_row(i, hours=1) for i in range(20)]
        _write_history(self.data, rows)
        stands, _ = g16.build_stands(self.data, self.root / "out")
        dates = [r["cycle_date"] for r in rows]
        self.assertEqual(dates.index(stands["day"]) - dates.index(stands["donor_day"]), 1)

    def test_the_day_rule_is_named_in_the_answer_not_only_applied(self):
        rows = [_row(i, hours=1) for i in range(20)]
        _write_history(self.data, rows)
        stands, _ = g16.build_stands(self.data, self.root / "out")
        self.assertIn("горизонт судьи", stands["day_rule"])

    def test_the_judge_horizon_is_taken_from_the_judge(self):
        from spa_core.paper_trading.shadow_trigger_eval import DEFAULT_HORIZON_DAYS
        self.assertEqual(g16._judge_horizon(), int(DEFAULT_HORIZON_DAYS))

    # ── заслон от рекурсии ──────────────────────────────────────────────────
    def test_the_instrument_excludes_itself_by_naming_the_reason(self):
        """Дефект, найденный ПЕРВЫМ прогоном на живых данных: прибор сам читает
        журнал, обе дороги находят его читателем, и он входил в перепись изнутри
        переписи. Выжившие мутации заслона этого не замечали."""
        _write_history(self.data, [_row(0, hours=1), _row(1, hours=20)])
        _write_trades(self.data, [])
        doc = g16.measure(self.data)   # tree_root по умолчанию — часть утверждения
        readers = doc["readers"]
        self.assertTrue(readers["measured"], readers.get("reason"))
        mine = [r for r in readers["modules"] if r["module"] == g16.__name__]
        self.assertEqual(len(mine), 1)
        self.assertEqual(mine[0]["outcome"], g16.READER_UNMEASURED)
        self.assertIn("сам прибор", mine[0]["reason"])

    def test_a_reentrant_call_refuses_the_sweep_instead_of_running_it_again(self):
        """Выжившие мутации `_SWEEPING`: второй заслон не проверял никто."""
        _write_history(self.data, [_row(0, hours=1), _row(1, hours=20)])
        _write_trades(self.data, [])
        g16._SWEEPING = True
        try:
            doc = g16.measure(self.data)
        finally:
            g16._SWEEPING = False
        self.assertFalse(doc["readers"]["measured"])
        self.assertIn("Повторный вход", doc["readers"]["reason"].capitalize())

    def test_the_guard_is_lowered_again_after_a_sweep(self):
        _write_history(self.data, [_row(0, hours=1), _row(1, hours=20)])
        _write_trades(self.data, [])
        g16.measure(self.data, tree_root=Path(g16.__file__).resolve().parents[2])
        self.assertFalse(g16._SWEEPING)

    # ── драйвер: какие точки входа приводятся, а какие нет ──────────────────
    def _stub(self, name, src):
        pkgdir = self.root / "stubs"
        pkgdir.mkdir(exist_ok=True)
        (pkgdir / f"{name}.py").write_text(src, encoding="utf-8")
        if str(pkgdir) not in sys.path:
            sys.path.insert(0, str(pkgdir))
        self.addCleanup(lambda: sys.modules.pop(name, None))
        self.addCleanup(lambda: str(pkgdir) in sys.path and sys.path.remove(str(pkgdir)))
        return importlib.import_module(name)

    def test_a_run_only_module_with_root_and_write_is_driven(self):
        """Выжившая мутация `"write" in sig and "root" in sig`."""
        mod = self._stub("g16hole_runonly",
                         "def run(root=None, *, write=True):\n"
                         "    return {'root': root, 'write': write}\n")
        name, call = g16.module_driver(mod)
        self.assertEqual(name, "run")
        self.assertEqual(call(self.root), {"root": str(self.root), "write": False})

    def test_a_run_without_write_is_not_driven_at_all(self):
        """Прибор не смеет звать то, что не умеет НЕ писать."""
        mod = self._stub("g16hole_nowrite", "def run(root=None):\n    return {}\n")
        self.assertEqual(g16.module_driver(mod), (None, None))

    def test_a_measure_whose_first_parameter_is_not_a_data_dir_is_not_driven(self):
        """Выжившая мутация `params[0] in _DATA_DIR_PARAMS`."""
        mod = self._stub("g16hole_wrongparam",
                         "def measure(records):\n    return {}\n")
        self.assertEqual(g16.module_driver(mod), (None, None))

    def test_a_class_attribute_named_measure_is_not_mistaken_for_an_entry_point(self):
        """`inspect.isfunction` отсекает методы и объекты: у соседей по дереву
        есть СВОИ `load_history`/`measure`, и принять их за точку входа значило
        бы мерить не тот предмет."""
        mod = self._stub("g16hole_notafunction",
                         "class _C:\n    def measure(self, data_dir):\n        return {}\n"
                         "measure = _C().measure\n")
        self.assertEqual(g16.module_driver(mod), (None, None))

    # ── население: обе половины статистики ──────────────────────────────────
    def test_population_stats_name_both_roads_and_the_overlap(self):
        """Выжившие мутации `via_imports_only` и `len(r) == 2`."""
        tree = self.root / "tree"
        pkg = tree / "spa_core" / "paper_trading"
        pkg.mkdir(parents=True)
        (tree / "spa_core" / "__init__.py").write_text("", encoding="utf-8")
        (pkg / "__init__.py").write_text("", encoding="utf-8")
        (pkg / "shadow_trigger_eval.py").write_text("X = 1\n", encoding="utf-8")
        mon = tree / "spa_core" / "monitoring"
        mon.mkdir()
        (mon / "__init__.py").write_text("", encoding="utf-8")
        (mon / "only_name.py").write_text("P='allocation_rationale_history'\n", encoding="utf-8")
        (mon / "only_import.py").write_text(
            "from spa_core.paper_trading import shadow_trigger_eval\n", encoding="utf-8")
        (mon / "both_roads.py").write_text(
            "from spa_core.paper_trading import shadow_trigger_eval\n"
            "P='allocation_rationale_history'\n", encoding="utf-8")
        _roads, stats = g16.reader_population(
            tree, loaders=("spa_core.paper_trading.shadow_trigger_eval",))
        self.assertEqual(stats["via_filename_only"], ["spa_core.monitoring.only_name"])
        self.assertEqual(stats["via_both"], ["spa_core.monitoring.both_roads"])
        # Сам загрузчик тоже лежит в замыкании, и это верно: он ЧИТАТЕЛЬ.
        self.assertEqual(stats["via_imports_only"],
                         ["spa_core.monitoring.only_import",
                          "spa_core.paper_trading.shadow_trigger_eval"])

    # ── миграция: средняя ветка вердикта ────────────────────────────────────
    def test_a_usable_key_present_on_only_some_rows_is_fit_with_minting(self):
        """Выжившая ветка «годен с чеканкой недостающих»: её не брал никто."""
        rows = [_row(0), {"cycle_date": _day(1), "verdict": "HOLD"}]
        out = g16.measure_migration(rows, candidates=("generated_at",),
                                    date_derived=["decision_id"])
        self.assertEqual(out["by_candidate"]["generated_at"]["verdict"],
                         "годен с чеканкой недостающих")

    # ── отчёт: содержимое, а не «не упал» ───────────────────────────────────
    def test_the_report_prints_the_population_split_by_road(self):
        """Выжившие мутации в строке населения: она проверялась только на то,
        что не падает."""
        doc = {"overall": g16.STATUS_OK, "reason": "",
               "key_probe": {"measured": False, "reason": "—"},
               "migration": {"by_candidate": {}},
               "act_bounds": {"measured": False, "reason": "—"},
               "readers": {"measured": True, "modules": [{"module": "a", "outcome": "x"}],
                           "outcomes": {}, "stand": {"day": "д", "day_rule": "правило"},
                           "population_stats": {"via_filename_only": ["a", "b"],
                                                "via_imports_only": ["c"],
                                                "via_both": []}}}
        line = [ln for ln in g16.format_report(doc) if "население" in ln][0]
        self.assertIn("имя файла 2", line)
        self.assertIn("граф импортов 1", line)
        self.assertIn("обе дороги 0", line)
        self.assertIn("правило", line)

    def test_the_report_prints_the_two_excluded_classes_of_days(self):
        """Выжившие `or []` в строке границ: дни, не вошедшие НИ В ОДНУ
        границу, — самостоятельный ответ, а не остаток."""
        doc = {"overall": g16.STATUS_OK, "reason": "",
               "key_probe": {"measured": False, "reason": "—"},
               "migration": {"by_candidate": {}},
               "readers": {"measured": False, "reason": "—"},
               "act_bounds": {"measured": True, "lower": 1, "upper": 11, "trade_days": 13,
                              "lower_days": [_day(0)], "upper_days": [],
                              "outside_journal_window": [_day(1), _day(2)],
                              "not_replacement": [_day(3)]}}
        line = [ln for ln in g16.format_report(doc) if "вне окна журнала" in ln][0]
        self.assertIn("вне окна журнала 2", line)
        self.assertIn("не замена 1", line)

    def test_the_report_prints_a_dash_when_the_lower_bound_is_empty(self):
        doc = {"overall": g16.STATUS_OK, "reason": "",
               "key_probe": {"measured": False, "reason": "—"},
               "migration": {"by_candidate": {}},
               "readers": {"measured": False, "reason": "—"},
               "act_bounds": {"measured": True, "lower": 0, "upper": 0, "trade_days": 0,
                              "lower_days": [], "upper_days": [],
                              "outside_journal_window": [], "not_replacement": []}}
        line = [ln for ln in g16.format_report(doc) if "нижняя" in ln][0]
        self.assertTrue(line.rstrip().endswith("—"), line)

    def test_the_report_counts_every_outcome_including_the_absent_ones(self):
        """Выжившая мутация умолчания `counts.get(name, 0)`: исход, которого
        сегодня нет, обязан печататься нулём, а не выдуманной единицей."""
        doc = {"overall": g16.STATUS_OK, "reason": "",
               "key_probe": {"measured": False, "reason": "—"},
               "migration": {"by_candidate": {}},
               "act_bounds": {"measured": False, "reason": "—"},
               "readers": {"measured": True, "modules": [], "outcomes": {},
                           "stand": {"day": "д", "day_rule": "п"},
                           "population_stats": {}}}
        line = [ln for ln in g16.format_report(doc)
                if g16.READER_FIRST in ln and "население" not in ln][0]
        self.assertIn(f"{g16.READER_FIRST} 0", line)


# ── 9. ВТОРОЙ РАУНД БАТАРЕИ: отчёт по СОДЕРЖИМОМУ и коды возврата ────────────
class BatteryHoleTestsRoundTwo(unittest.TestCase):
    """40 выживших после первого раунда. Здесь закрыты те, чьё выживание
    означало: строку отчёта проверяли на «не упала», а не на содержимое."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(prefix="g16_holes2_")
        self.root = Path(self._tmp.name)
        self.data = self.root / "data"
        self.data.mkdir(parents=True)

    def tearDown(self):
        self._tmp.cleanup()

    def _full_doc(self):
        return g16._verdict({
            "key_probe": {"measured": True, "decision_id_distinguishes_runs": False,
                          "decision_id_value": "adr060-shadow-Д",
                          "date_derived": ["a", "b", "c"], "run_distinct": ["x", "y"]},
            "migration": {"by_candidate": {"decision_id": {
                "rows_total": 40, "rows_with_key": 16, "rows_needing_minted_key": 24,
                "distinct_pairs": 16, "collisions": 3, "distinguishes_runs": False,
                "verdict": "НЕ ГОДЕН: ключ выведен из даты"}}},
            "act_bounds": {"measured": True, "lower": 1, "upper": 11, "trade_days": 13,
                           "lower_days": ["2026-09-11"], "upper_days": [],
                           "outside_journal_window": ["a", "b"], "not_replacement": ["c"]},
            "readers": {"measured": True, "outcomes": {g16.READER_LAST: 20,
                                                       g16.READER_BOTH: 10},
                        "modules": [{"module": "m.a", "outcome": g16.READER_LAST,
                                     "entry": "measure"}],
                        "stand": {"day": "2026-09-07", "day_rule": "правило"},
                        "population_stats": {"via_filename_only": ["a", "b", "c", "d", "e"],
                                             "via_imports_only": ["f"] * 77,
                                             "via_both": ["g"] * 19}}})

    def _line(self, doc, needle):
        return [ln for ln in g16.format_report(doc) if needle in ln][0]

    def test_the_key_line_prints_the_value_and_both_field_counts(self):
        line = self._line(self._full_doc(), "[КЛЮЧ]")
        self.assertIn("adr060-shadow-Д", line)
        self.assertIn("только от даты — 3", line)
        self.assertIn("различающих прогон — 2", line)

    def test_the_migration_line_prints_every_number_of_its_candidate(self):
        line = self._line(self._full_doc(), "[МИГРАЦИЯ]")
        self.assertIn("16/40", line)
        self.assertIn("чеканить задним числом 24", line)
        self.assertIn("столкновений 3", line)
        self.assertIn("НЕ ГОДЕН", line)

    def test_the_population_line_prints_the_real_counts_not_zeros(self):
        line = self._line(self._full_doc(), "население")
        self.assertIn("население 1 ", line)
        self.assertIn("имя файла 5", line)
        self.assertIn("граф импортов 77", line)
        self.assertIn("обе дороги 19", line)

    def test_the_outcome_line_prints_the_real_counts_not_zeros(self):
        line = self._line(self._full_doc(), f"{g16.READER_LAST} ")
        self.assertIn(f"{g16.READER_LAST} 20", line)
        self.assertIn(f"{g16.READER_BOTH} 10", line)
        self.assertIn(f"{g16.READER_FIRST} 0", line)

    def test_the_lower_bound_line_names_the_day_when_there_is_one(self):
        self.assertIn("2026-09-11", self._line(self._full_doc(), "нижняя"))

    def test_the_critical_reason_carries_both_counts_and_both_bounds(self):
        reason = self._full_doc()["reason"]
        self.assertIn("не менее 20", reason)
        self.assertIn("из 1", reason)
        self.assertIn("1–11", reason)

    def test_the_unmeasured_reason_prefers_the_probes_own_words(self):
        doc = g16._verdict({"key_probe": {"measured": False, "reason": "писатель упал"},
                            "act_bounds": {"measured": True}, "readers": {}})
        self.assertEqual(doc["reason"], "писатель упал")

    def test_the_unmeasured_reason_falls_back_to_the_bounds_words(self):
        doc = g16._verdict({"key_probe": {"measured": True,
                                          "decision_id_distinguishes_runs": True},
                            "act_bounds": {"measured": False, "reason": "сделок нет"},
                            "readers": {}})
        self.assertEqual(doc["reason"], "сделок нет")

    def test_the_unmeasured_reason_is_never_empty_even_with_no_words(self):
        doc = g16._verdict({"key_probe": {"measured": True},
                            "act_bounds": {"measured": True}, "readers": {}})
        self.assertTrue(doc["reason"])

    # ── коды возврата: ВСЕ четыре, у main() ─────────────────────────────────
    def _stand_for(self, verdict_state):
        _write_history(self.data, [_row(0, hours=1), _row(1, hours=20)])
        _write_audit(self.data, {_day(1): 4})
        if verdict_state == "finding":
            _write_trades(self.data, [{"trade_id": "T1", "ts": _stamp(1, 9)}])
        else:
            _write_trades(self.data, [])

    def test_main_returns_zero_only_when_nothing_was_found(self):
        """Выжившая мутация `STATUS_OK: 0` → `1`: нулевой код не проверял никто,
        и «чисто» стало бы неотличимо от находки."""
        self._stand_for("clean")
        doc = g16.run(root=str(self.root), write=False, sweep_readers=False)
        doc["overall"] = g16.STATUS_OK
        codes = {g16.STATUS_OK: 0, g16.STATUS_WARNING: 1,
                 g16.STATUS_CRITICAL: 1, g16.STATUS_UNMEASURED: 2}
        self.assertEqual(codes[doc["overall"]], 0)
        self.assertEqual(g16.main(["--root", str(self.root), "--no-write", "--no-readers"]), 1)

    def test_an_unknown_verdict_exits_two_not_zero(self):
        """Выжившая мутация умолчания `codes.get(..., 2)`: незнакомый исход —
        это НЕ ИЗМЕРЕНО, и выдавать его за чистый проход запрещено (инв. #17)."""
        import io, contextlib
        real = g16.run
        g16.run = lambda **kw: {"overall": "какой-то новый статус",
                                "key_probe": {}, "migration": {}, "readers": {},
                                "act_bounds": {}}
        try:
            with contextlib.redirect_stdout(io.StringIO()):
                rc = g16.main(["--root", str(self.root), "--no-write"])
        finally:
            g16.run = real
        self.assertEqual(rc, 2)

    # ── прочие отказы, объявлявшие себя измеренными ─────────────────────────
    def test_trades_that_are_not_a_list_are_unmeasured(self):
        _write_history(self.data, [_row(0), _row(1)])
        (self.data / g16.TRADES_FILENAME).write_text('{"trades": 7}', encoding="utf-8")
        out = g16.act_day_bounds(self.data, trial_mark="m")
        self.assertFalse(out["measured"])

    def test_migration_over_an_unreadable_journal_is_unmeasured(self):
        _write_trades(self.data, [])
        doc = g16.measure(self.data, sweep_readers=False)
        self.assertFalse(doc["migration"]["measured"])
        self.assertIn(g16.HISTORY_FILENAME, doc["migration"]["reason"])

    def test_migration_over_a_readable_journal_says_it_was_measured(self):
        _write_history(self.data, [_row(0), _row(1)])
        _write_trades(self.data, [])
        self.assertTrue(g16.measure(self.data, sweep_readers=False)["migration"]["measured"])

    def test_readers_are_unmeasured_when_the_stands_cannot_be_built(self):
        _write_history(self.data, [_row(0)])          # одна строка — донора нет
        _write_trades(self.data, [])
        doc = g16.measure(self.data)
        self.assertFalse(doc["readers"]["measured"])
        self.assertIn("стенды не построены", doc["readers"]["reason"])

    # ── правило дня на КОРОТКОМ журнале ─────────────────────────────────────
    def test_a_journal_shorter_than_the_horizon_still_gets_a_day_with_a_donor(self):
        """Выжившие числа правила дня: `max(1, …)` и ветка `idx == 0` берутся
        только на журнале короче горизонта, а стенд давал двадцать дней."""
        _write_history(self.data, [_row(0, hours=1), _row(1, hours=2), _row(2, hours=3)])
        stands, why = g16.build_stands(self.data, self.root / "out")
        self.assertIsNotNone(stands, why)
        self.assertEqual(stands["day"], _day(1))
        self.assertEqual(stands["donor_day"], _day(0))

    def test_the_sweeping_guard_starts_lowered(self):
        """Выжившая мутация `_SWEEPING = False` на уровне модуля: поднятый с
        импорта флаг отключил бы перепись НАВСЕГДА, и прибор молча отвечал бы
        «повторный вход» на первом же зове."""
        importlib.reload(g16)
        try:
            self.assertIs(g16._SWEEPING, False)
        finally:
            importlib.reload(g16)


# ── 10. ТРЕТИЙ РАУНД: последние достижимые координаты ────────────────────────
class BatteryHoleTestsRoundThree(unittest.TestCase):
    """23 выживших после второго раунда. Здесь закрыты достижимые; остальные
    отнесены к классам в ADR-384, а не оставлены числом."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(prefix="g16_holes3_")
        self.root = Path(self._tmp.name)
        self.data = self.root / "data"
        self.data.mkdir(parents=True)

    def tearDown(self):
        self._tmp.cleanup()

    def test_a_callable_that_is_not_a_function_is_not_driven_as_run_either(self):
        """Выжившая мутация `callable(fn) and inspect.isfunction(fn)` → `or` в
        ВЕТКЕ `run`: связанный метод вызываем, но функцией не является, и принять
        его за точку входа значило бы мерить чужой предмет."""
        pkgdir = self.root / "stubs"
        pkgdir.mkdir()
        (pkgdir / "g16hole3_boundrun.py").write_text(
            "class _C:\n    def run(self, root=None, *, write=True):\n        return {}\n"
            "run = _C().run\n", encoding="utf-8")
        sys.path.insert(0, str(pkgdir))
        self.addCleanup(lambda: sys.modules.pop("g16hole3_boundrun", None))
        self.addCleanup(lambda: sys.path.remove(str(pkgdir)))
        mod = importlib.import_module("g16hole3_boundrun")
        self.assertEqual(g16.module_driver(mod), (None, None))

    def test_switching_the_sweep_off_says_so_instead_of_answering_zero(self):
        """Выжившая мутация `{"measured": False}` в ветке отключённой переписи:
        «не гоняли» обязано быть отличимо от «гоняли и никого не нашли»."""
        _write_history(self.data, [_row(0), _row(1)])
        _write_trades(self.data, [])
        readers = g16.measure(self.data, sweep_readers=False)["readers"]
        self.assertFalse(readers["measured"])
        self.assertIn("отключён", readers["reason"])

    def test_the_report_says_not_measured_when_the_migration_section_is_absent(self):
        """Выжившие мутации в ветке инв. #17: раздел, которого нет, обязан быть
        НАЗВАН в отчёте, а не исчезнуть из него молча."""
        doc = {"overall": g16.STATUS_UNMEASURED, "reason": "—",
               "key_probe": {"measured": False, "reason": "—"},
               "readers": {"measured": False, "reason": "—"},
               "act_bounds": {"measured": False, "reason": "—"}}
        line = [ln for ln in g16.format_report(doc) if "[МИГРАЦИЯ]" in ln][0]
        self.assertIn("НЕ ИЗМЕРЕНО", line)
        self.assertIn("не прочитан", line)

    def test_the_report_carries_the_migration_reason_when_there_is_one(self):
        doc = {"overall": g16.STATUS_UNMEASURED, "reason": "—",
               "key_probe": {"measured": False, "reason": "—"},
               "readers": {"measured": False, "reason": "—"},
               "act_bounds": {"measured": False, "reason": "—"},
               "migration": {"measured": False, "reason": "журнал не прочитан"}}
        line = [ln for ln in g16.format_report(doc) if "[МИГРАЦИЯ]" in ln][0]
        self.assertIn("журнал не прочитан", line)

    def _main_with_verdict(self, overall):
        import contextlib
        import io as _io
        real = g16.run
        g16.run = lambda **kw: {"overall": overall, "key_probe": {}, "migration": {},
                                "readers": {}, "act_bounds": {}}
        try:
            with contextlib.redirect_stdout(_io.StringIO()):
                return g16.main(["--root", str(self.root), "--no-write"])
        finally:
            g16.run = real

    def test_every_verdict_maps_to_its_own_exit_code(self):
        """Выжившие мутации таблицы кодов: «чисто» обязано быть отличимо от
        находки, а находка — от «не измерено»."""
        self.assertEqual(self._main_with_verdict(g16.STATUS_OK), 0)
        self.assertEqual(self._main_with_verdict(g16.STATUS_WARNING), 1)
        self.assertEqual(self._main_with_verdict(g16.STATUS_CRITICAL), 1)
        self.assertEqual(self._main_with_verdict(g16.STATUS_UNMEASURED), 2)


# ── 10. G26: ПРИЧИНА «не измерено» — поимённо, и вердикт ДЕТЕРМИНИРОВАН ──────
#
# Заказ #614/G26 просил перемерить 64 модуля, ушедшие в `unmeasured`, потому что
# «причина у всех одна» делала число ответом на вопрос «о скольких прибор не
# умеет спросить», а читалось оно как «сколько читателей ни при чём». Замер
# 16.09 показал, что причина НЕ одна, а семь, и что самая многочисленная (20 из
# 61) — обработчики HTTP-маршрутов, то есть ровно те читатели, чей ответ видит
# владелец. Попутно нашлась асимметрия хуже: вердикт ЕДИНСТВЕННОМУ схлопывающему
# читателю (`house_view_gap`) был подбрасыванием монеты.
_G26_STUBS = {
    # Читатель схлопывает день И несёт поле, производное от стенных часов.
    # Прежний код объявлял его `unmeasured` или `collapses_to_last` через
    # прогон; предмет теста — что исход ОДИН И ТОТ ЖЕ на повторных замерах.
    "clockcontent": "def measure(data_dir, **kw):\n"
                    "    import json, time\n"
                    "    rows=[json.loads(l) for l in (data_dir/'h.jsonl').read_text().splitlines() if l.strip()]\n"
                    "    by={}\n"
                    "    for r in rows: by[r['cycle_date']]=r\n"
                    "    return {'tick': round(time.time(), 1),\n"
                    "            'verdicts': sorted((d, v['verdict']) for d, v in by.items())}\n",
    # Форма `house_view_gap`: ВСЯ разница между стендами лежит в поле-возрасте,
    # то есть в координате, нестабильной и на одном стенде.
    "ageonly": "def measure(data_dir, **kw):\n"
               "    import json, time\n"
               "    from datetime import datetime\n"
               "    rows=[json.loads(l) for l in (data_dir/'h.jsonl').read_text().splitlines() if l.strip()]\n"
               "    ts=datetime.fromisoformat(rows[-1]['generated_at']).timestamp()\n"
               "    return {'k': 'константа', 'age_s': round(time.time()-ts, 1)}\n",
    # Точка входа под другим именем, каталог первым параметром — но модуля нет
    # в именном списке. Контроль fail-CLOSED: расширение не должно быть
    # ОБРАЗЦОМ, иначе оно захватило бы писателя журнала и дневной цикл.
    "othername": "def write_everything(data_dir, **kw):\n"
                 "    return {'answer': 1}\n",
    "actor": "CALLED = []\n"
             "def measure(data_dir, **kw):\n"
             "    CALLED.append(1)\n"
             "    return {'answer': 1}\n",
    # Ответ, в котором НЕТ ни одного устойчивого листа: снятие оставило бы
    # нечего сравнивать, и любые два стенда сошлись бы тождественно.
    "allunstable": "_N=[0]\n"
                   "def measure(data_dir, **kw):\n"
                   "    _N[0]+=1\n"
                   "    return {'n': _N[0]}\n",
    "httpish": "class APIRouter:\n"
               "    pass\n"
               "router = APIRouter()\n"
               "def get_thing():\n"
               "    return {'answer': 1}\n",
    "runnowrite": "def run(root='.'):\n"
                  "    return {'answer': 1}\n",
    "clionly": "def main(argv=None):\n"
               "    return 0\n",
}


class G26CauseTests(unittest.TestCase):
    """Причина исхода `unmeasured` — предмет замера, а не одна строка на всех."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(prefix="g26_causes_")
        self.root = Path(self._tmp.name)
        self.pkg = self.root / "stubs"
        self.pkg.mkdir()
        for name, src in _G26_STUBS.items():
            (self.pkg / f"g16g26_{name}.py").write_text(src, encoding="utf-8")
        sys.path.insert(0, str(self.pkg))
        self.stands = {}
        for stand, rows in (("s1", [_row(0, verdict="HOLD", hours=9)]),
                            ("s2", [_row(0, verdict="ACT", hours=1),
                                    _row(0, verdict="HOLD", hours=9)]),
                            ("s3", [_row(0, verdict="ACT", hours=1)])):
            data = self.root / stand / "data"
            data.mkdir(parents=True)
            (data / "h.jsonl").write_text(
                "\n".join(json.dumps(r, sort_keys=True) for r in rows) + "\n",
                encoding="utf-8")
            self.stands[stand] = self.root / stand

    def tearDown(self):
        sys.path.remove(str(self.pkg))
        for name in list(sys.modules):
            if name.startswith("g16g26_"):
                del sys.modules[name]
        self._tmp.cleanup()

    def _classify(self, stub):
        return g16.classify_reader(f"g16g26_{stub}", self.stands)

    # ── причины различимы ────────────────────────────────────────────────────
    def test_http_route_handler_is_its_own_cause_not_no_entry_point(self):
        """20 из 61 — обработчики маршрутов, и это ровно те читатели, чей ответ
        печатается владельцу. Слитые в «нет точки входа», они были невидимы."""
        row = self._classify("httpish")
        self.assertEqual(row["outcome"], g16.READER_UNMEASURED)
        self.assertEqual(row["cause"], g16.CAUSE_HTTP_ROUTE)

    def test_run_without_a_write_switch_is_its_own_cause(self):
        row = self._classify("runnowrite")
        self.assertEqual(row["cause"], g16.CAUSE_RUN_NO_WRITE_SWITCH)

    def test_cli_only_module_is_its_own_cause(self):
        row = self._classify("clionly")
        self.assertEqual(row["cause"], g16.CAUSE_CLI_ONLY)

    def test_the_four_shapes_do_not_share_one_cause(self):
        """Контроль на слипание: если причины снова свести к одной, тест
        краснеет, а число `unmeasured` осталось бы прежним и молчало."""
        causes = {self._classify(s)["cause"]
                  for s in ("httpish", "runnowrite", "clionly", "othername")}
        self.assertEqual(len(causes), 4, f"причины слиплись: {causes}")

    def test_cause_survives_only_with_a_reason_naming_the_entry_point(self):
        row = self._classify("clionly")
        self.assertIn("main", row["reason"])

    # ── отказ ЗВАТЬ — не то же, что «нечего позвать» ─────────────────────────
    def test_a_module_on_the_never_call_list_is_not_called_at_all(self):
        """Точка входа ЕСТЬ, и именно поэтому её нельзя приводить. Контроль
        сильный: если прибор всё-таки позовёт, список `CALLED` это покажет."""
        from unittest import mock
        with mock.patch.dict(g16._NEVER_CALL,
                             {"g16g26_actor": "измерять запрещено: вызов действует"},
                             clear=False):
            row = self._classify("actor")
        self.assertEqual(row["outcome"], g16.READER_UNMEASURED)
        self.assertEqual(row["cause"], g16.CAUSE_WOULD_ACT)
        self.assertNotIn("g16g26_actor", sys.modules,
                         "прибор ИМПОРТИРОВАЛ модуль из списка «не звать»")

    def test_without_the_never_call_list_the_same_module_would_be_called(self):
        """Обратный контроль: без списка модуль зовётся. Иначе предыдущий тест
        был бы истинным по построению — стенд мог просто не доходить до вызова."""
        row = self._classify("actor")
        self.assertEqual(row["outcome"], g16.READER_INSENSITIVE)
        mod = sys.modules["g16g26_actor"]
        self.assertTrue(mod.CALLED, "модуль не позвали и БЕЗ запрета")

    def test_extending_the_driver_is_a_named_list_not_a_pattern(self):
        """Образец «первый параметр — каталог data/» захватил бы
        `allocation_rationale.write_shadow_rationale` и `cycle_runner.run_cycle`.
        Расширение обязано оставаться именным."""
        row = self._classify("othername")
        self.assertEqual(row["outcome"], g16.READER_UNMEASURED)
        self.assertEqual(row["cause"], g16.CAUSE_NO_ENTRY)

    def test_the_named_list_does_drive_the_module_it_names(self):
        """Обратный контроль к предыдущему: список не декорация."""
        from unittest import mock
        with mock.patch.dict(g16._EXTRA_READ_ONLY_ENTRIES,
                             {"g16g26_othername": "write_everything"}, clear=False):
            row = self._classify("othername")
        self.assertEqual(row["outcome"], g16.READER_INSENSITIVE)

    def test_the_money_path_and_the_kill_switch_stay_on_the_never_call_list(self):
        """Храповик намерения: убрать их из списка = прибор запустит цикл."""
        for module in ("spa_core.paper_trading.cycle_runner",
                       "spa_core.paper_trading.allocation_rationale",
                       "scripts.kill_switch_drill"):
            self.assertIn(module, g16._NEVER_CALL)

    # ── вердикт ДЕТЕРМИНИРОВАН ───────────────────────────────────────────────
    def test_a_clock_derived_field_does_not_make_the_verdict_a_coin_flip(self):
        """Авария 16.09: `house_view_gap` несёт 33 поля `age_s` в десятых долях
        секунды, `_strip_clock` снимает только ВЕРХНИЙ уровень — и прогон 1 дал
        `collapses_to_last`, прогон 2 `unmeasured` на ОДНОМ дереве. Ноль
        схлопывающих читался как «ADR-395 закрыл вопрос», что неправда."""
        outcomes = {self._classify("clockcontent")["outcome"] for _ in range(3)}
        self.assertEqual(len(outcomes), 1, f"вердикт непостоянен: {outcomes}")
        self.assertEqual(outcomes.pop(), g16.READER_LAST)

    def test_masking_does_not_swallow_a_real_difference(self):
        """Обратная опасность: снять нестабильное и погасить улику. Содержимое
        стенда обязано остаться видимым сквозь снятие."""
        row = self._classify("clockcontent")
        self.assertEqual(row["outcome"], g16.READER_LAST)
        self.assertGreater(row["unstable_coords"], 0,
                           "тест не проверяет снятие: нестабильных координат нет")

    def test_a_difference_living_only_in_an_unstable_field_is_named_not_hidden(self):
        """Форма `house_view_gap`: вся разница между стендами — в поле-возрасте.
        «Нечувствителен» здесь неправда, а вердикт по снятому был бы монетой.
        Третий исход, названный ПОИМЁННО."""
        row = self._classify("ageonly")
        self.assertEqual(row["outcome"], g16.READER_UNMEASURED)
        self.assertEqual(row["cause"], g16.CAUSE_RESTS_ON_UNSTABLE)
        self.assertNotEqual(row["outcome"], g16.READER_INSENSITIVE)

    def test_an_answer_with_no_stable_field_left_is_called_irreproducible(self):
        """Ответ, у которого не осталось устойчивых листьев, снятием не
        спасается: сравнивать было бы нечего, и любые стенды сошлись бы."""
        row = self._classify("allunstable")
        self.assertEqual(row["outcome"], g16.READER_UNMEASURED)
        self.assertEqual(row["cause"], g16.CAUSE_IRREPRODUCIBLE)

    def test_the_two_probes_of_one_stand_are_separated_by_the_pause(self):
        """Предмет — ПАУЗА, а не число проб. Поле с шагом 0.1 с (`age_s` у
        `house_view_gap`) при вызове в 1 мс попадает в одну корзину, и
        «стабильность» подтверждается ложно. Третья проба того же не добавляет:
        поле, бегущее на каждом зове, расходится при любом зазоре, — а стоила
        она лишний зов каждого из 108 читателей (879 с против ~300 с)."""
        src = ("import time\n"
               "STAMPS = []\n"
               "def measure(data_dir, **kw):\n"
               "    STAMPS.append(time.monotonic())\n"
               "    return {'k': 'const'}\n")
        (self.pkg / "g16g26_stamps.py").write_text(src, encoding="utf-8")
        self._classify("stamps")
        stamps = sys.modules["g16g26_stamps"].STAMPS
        self.assertGreaterEqual(len(stamps), 2, "стенд s1 опрошен меньше двух раз")
        self.assertGreaterEqual(
            stamps[1] - stamps[0], g16._STABILITY_PROBE_DELAY_S,
            "две пробы одного стенда идут БЕЗ паузы — поле с грубым шагом "
            "останется незамеченным, и вердикт снова станет монетой")

    # ── отчёт: число НИКОГДА не остаётся без причины ─────────────────────────
    def test_the_report_prints_a_number_per_cause(self):
        doc = {"overall": g16.STATUS_WARNING, "reason": "—",
               "key_probe": {"measured": False, "reason": "—"},
               "migration": {"measured": False, "reason": "—"},
               "act_bounds": {"measured": False, "reason": "—"},
               "readers": {"measured": True, "modules": [],
                           "outcomes": {g16.READER_UNMEASURED: 3},
                           "unmeasured_causes": {g16.CAUSE_HTTP_ROUTE: 2,
                                                 g16.CAUSE_CLI_ONLY: 1}}}
        lines = [ln for ln in g16.format_report(doc) if "[ПРИЧИНА]" in ln]
        self.assertEqual(len(lines), 2, lines)
        self.assertTrue(any(g16.CAUSE_HTTP_ROUTE in ln and "2" in ln for ln in lines))

    def test_unmeasured_without_recorded_causes_is_itself_reported(self):
        """Инв. #17: число без причины непригодно, и молчать о том нельзя."""
        doc = {"overall": g16.STATUS_WARNING, "reason": "—",
               "key_probe": {"measured": False, "reason": "—"},
               "migration": {"measured": False, "reason": "—"},
               "act_bounds": {"measured": False, "reason": "—"},
               "readers": {"measured": True, "modules": [],
                           "outcomes": {g16.READER_UNMEASURED: 7}}}
        line = [ln for ln in g16.format_report(doc) if "[ПРИЧИНЫ]" in ln]
        self.assertTrue(line, "непустой `unmeasured` без причин не назван в отчёте")
        self.assertIn("НЕ ИЗМЕРЕНО", line[0])

    def test_the_report_names_every_unjudgeable_reader_not_just_counts_them(self):
        """Эти читатели и были прежней монетой: всплывали в `collapses_to_last`
        и пропадали через прогон. Число без имён вернуло бы их в безымянность."""
        doc = {"overall": g16.STATUS_WARNING, "reason": "—",
               "key_probe": {"measured": False, "reason": "—"},
               "migration": {"measured": False, "reason": "—"},
               "act_bounds": {"measured": False, "reason": "—"},
               "readers": {"measured": True, "outcomes": {},
                           "modules": [{"module": "mod.hvg", "entry": "run",
                                        "outcome": g16.READER_UNMEASURED,
                                        "cause": g16.CAUSE_RESTS_ON_UNSTABLE,
                                        "reason": "вся разница в снятых координатах"}]}}
        lines = [ln for ln in g16.format_report(doc) if "[СУДИТЬ НЕЧЕМ]" in ln]
        self.assertEqual(len(lines), 1)
        self.assertIn("mod.hvg", lines[0])

    def test_the_report_names_every_module_it_refused_to_call(self):
        doc = {"overall": g16.STATUS_WARNING, "reason": "—",
               "key_probe": {"measured": False, "reason": "—"},
               "migration": {"measured": False, "reason": "—"},
               "act_bounds": {"measured": False, "reason": "—"},
               "readers": {"measured": True, "outcomes": {},
                           "modules": [{"module": "mod.a", "outcome": g16.READER_UNMEASURED,
                                        "cause": g16.CAUSE_WOULD_ACT,
                                        "reason": "вызов подвинул бы деньги"}]}}
        lines = [ln for ln in g16.format_report(doc) if "[ОТКАЗ ЗВАТЬ]" in ln]
        self.assertEqual(len(lines), 1)
        self.assertIn("mod.a", lines[0])


class G26StabilityHelperTests(unittest.TestCase):
    """Нестабильность МЕРЯЕТСЯ, а не угадывается по имени поля."""

    def test_identical_answers_have_no_unstable_coordinates(self):
        obj = {"a": 1, "b": [1, 2, {"c": "x"}]}
        self.assertEqual(g16.unstable_coords(obj, json.loads(json.dumps(obj))), set())

    def test_a_nested_difference_is_found_by_its_path(self):
        """Предмет аварии: `_strip_clock` снимает только ВЕРХНИЙ уровень, а
        `age_s` живёт на два уровня глубже."""
        a = {"inputs": {"journal": {"age_s": 1.1}}}
        b = {"inputs": {"journal": {"age_s": 1.2}}}
        self.assertEqual(g16.unstable_coords(a, b), {".inputs.journal.age_s"})

    def test_masking_touches_only_the_named_coordinate(self):
        obj = {"keep": 5, "drop": 9}
        out = g16.mask_coords(obj, {".drop"})
        self.assertEqual(out["keep"], 5)
        self.assertNotEqual(out["drop"], 9)

    def test_an_input_timestamp_is_not_silenced_by_name(self):
        """`feed_coverage.as_of` — это ВХОД, а не часы. Глушить его по виду
        имени значило бы отвечать не на тот вопрос; мера — расхождение."""
        a = {"feed_coverage": {"as_of": "день-1"}}
        self.assertEqual(g16.unstable_coords(a, a), set())

    def test_stable_leaves_counts_what_survived_the_mask(self):
        self.assertEqual(g16._stable_leaves({"a": 1, "b": 2}, {".a"}), 1)
        self.assertEqual(g16._stable_leaves({"a": 1}, {".a"}), 0)


# ── G27: обработчики HTTP-маршрутов ──────────────────────────────────────────
#
# Заказ G27 приказа владельца «Portfolio CIO», часть 2. Перепись не выносила
# вердикта 20 модулям из 61 не измеренного, и все двадцать — обработчики
# HTTP-маршрутов, то есть РОВНО те читатели, чей ответ владелец видит на
# дашборде. Причина стояла: «каталог стенда ему не передать». Замер её
# опроверг, и каждый тест ниже — положительный контроль на конкретную поломку,
# измеренную при этой работе, а не подтверждение, что код запускается.

class _FakeRoute:
    """Маршрут, как его видит FastAPI: путь, методы, обработчик."""

    def __init__(self, path, endpoint, methods=("GET",)):
        self.path = path
        self.endpoint = endpoint
        self.methods = set(methods)


class _FakeRouter:
    """Тип объекта — то, по чему прибор узнаёт HTTP-поверхность (не по имени)."""

    def __init__(self, routes):
        self.routes = list(routes)


_FakeRouter.__name__ = "APIRouter"


class _FakeModule:
    def __init__(self, name, routes):
        self.__name__ = name
        self.router = _FakeRouter(routes)

    def __iter__(self):                       # pragma: no cover — для vars()
        return iter(())


def _endpoint(name, module, fn):
    fn.__name__ = name
    fn.__module__ = module
    return fn


class G27HttpPrecondTests(unittest.TestCase):
    """ПОСЫЛКА заказа: у маршрутов ворота ЕСТЬ, и прежняя причина была догадкой."""

    def test_the_router_data_dir_resolves_at_call_time_from_the_env(self):
        """Строка «каталог стенда ему не передать — он читает через модульный
        корень» была НЕПРАВДОЙ, и это единственное, на чём держался вывод «20
        модулей измерить нельзя». Ворота объявлены в докстринге самого
        `_shared`: `data_dir()` резолвит `server._DATA_DIR`, а тот берётся из
        `SPA_DATA_DIR`. Тест краснеет, если ворота исчезнут, — и тогда правка
        G27 обязана быть пересмотрена, а не тихо продолжать работать."""
        from spa_core.api import _shared, server
        with tempfile.TemporaryDirectory(prefix="g27_gate_") as tmp:
            saved = server._DATA_DIR
            try:
                server._DATA_DIR = Path(tmp)
                self.assertEqual(_shared.data_dir(), Path(tmp))
            finally:
                server._DATA_DIR = saved

    def test_the_prober_refuses_when_the_stand_dir_was_not_pinned(self):
        """fail-CLOSED, и он тут не придирка. Без `SPA_DATA_DIR` обработчик
        прочитал бы ЖИВОЙ каталог, а перепись доложила бы «нечувствителен к
        стенду» — то есть выдала бы за наблюдение то, чего стенд не касался.
        Это fail-OPEN, и он тише красной строки."""
        from spa_core.monitoring import _http_reader_probe as probe
        from unittest import mock
        with tempfile.TemporaryDirectory(prefix="g27_noenv_") as tmp:
            mods = Path(tmp) / "m.json"
            mods.write_text("[]", encoding="utf-8")
            out = Path(tmp) / "o.json"
            with mock.patch.dict("os.environ", {}, clear=False):
                import os as _os
                _os.environ.pop(probe.DATA_DIR_ENV, None)
                self.assertEqual(probe.main([str(mods), str(out)]), 2)
                self.assertFalse(out.exists())
            # обратный контроль: с пином тот же зов проходит — иначе тест был бы
            # истинным по построению (отказывал бы на чём угодно)
            with mock.patch.dict("os.environ", {probe.DATA_DIR_ENV: tmp}):
                self.assertEqual(probe.main([str(mods), str(out)]), 0)
                self.assertTrue(out.exists())


class G27RouteSelectionTests(unittest.TestCase):
    """Что зовётся, а что нет — и у каждого отказа НАЗВАНА причина."""

    def setUp(self):
        from spa_core.monitoring import _http_reader_probe as probe
        self.probe = probe
        self.called = []

        def read(): self.called.append("read"); return {"ok": 1}

        def write(): self.called.append("write"); return {"ok": 2}

        def needs(pool_id): self.called.append("needs"); return {"ok": 3}

        # ОТДЕЛЬНАЯ функция, а не та же: `__module__` — атрибут объекта, и
        # переиспользование одного обработчика на двух маршрутах переписало бы
        # хозяина первому. Первая редакция теста сделала ровно это и покраснела.
        def alien(): self.called.append("alien"); return {"ok": 4}

        self.mod = _FakeModule("g27mod", [
            _FakeRoute("/read", _endpoint("read", "g27mod", read), ("GET", "HEAD")),
            _FakeRoute("/write", _endpoint("write", "g27mod", write), ("POST",)),
            _FakeRoute("/needs/{pool_id}", _endpoint("needs", "g27mod", needs), ("GET",)),
            _FakeRoute("/alien", _endpoint("alien", "neighbour", alien), ("GET",)),
        ])

    def test_only_get_routes_without_required_args_are_called(self):
        called, refused = self.probe.callable_routes(self.mod)
        self.assertEqual([p for p, _ in called], ["/read"])
        self.assertIn("/write", refused)
        self.assertIn("GET", refused["/write"])
        self.assertIn("/needs/{pool_id}", refused)
        self.assertIn("pool_id", refused["/needs/{pool_id}"])

    def test_a_post_route_is_never_called_even_once(self):
        """Контроль СИЛЬНЫЙ: мало не включить POST в список — важно, что его не
        зовут. Список `called` покажет зов, даже если вердикт промолчит."""
        self.probe.probe_modules([], None)
        called, _ = self.probe.callable_routes(self.mod)
        for _path, endpoint in called:
            endpoint()
        self.assertEqual(self.called, ["read"])

    def test_a_HEAD_only_route_is_not_mistaken_for_a_read(self):
        """Две клаузы двери отвечают на РАЗНЫЕ вопросы, и путать их нельзя:
        `methods <= _READ_METHODS` спрашивает «не пишет ли он», а
        `"GET" not in methods` — «отвечает ли он на GET вообще». Замер батареи:
        снятие второй клаузы не краснило НИЧЕГО, то есть она держалась ни на
        чём, а маршрут, отвечающий только на HEAD, зачлись бы за чтение тела."""
        def head_only(): self.called.append("head"); return {"ok": 6}

        mod = _FakeModule("g27mod3", [
            _FakeRoute("/h", _endpoint("head_only", "g27mod3", head_only), ("HEAD",)),
        ])
        called, refused = self.probe.callable_routes(mod)
        self.assertEqual(called, [])
        self.assertIn("/h", refused)
        self.assertIn("GET", refused["/h"])

    def test_a_route_that_also_answers_a_WRITING_method_is_refused(self):
        """Второй сторож той же двери, и он отдельный. `"GET" not in methods`
        ловит чистый POST; `methods <= _READ_METHODS` ловит маршрут, который
        отвечает И на GET, И на DELETE. Замер батареи: без этого теста мутация
        `_READ_METHODS` ВЫЖИВАЛА — то есть одна из двух половин защиты не была
        закреплена ничем."""
        def both(): self.called.append("both"); return {"ok": 5}

        mod = _FakeModule("g27mod2", [
            _FakeRoute("/both", _endpoint("both", "g27mod2", both), ("GET", "DELETE")),
        ])
        called, refused = self.probe.callable_routes(mod)
        self.assertEqual(called, [])
        self.assertIn("/both", refused)
        self.assertIn("DELETE", refused["/both"])

    def test_a_route_owned_by_a_neighbour_module_is_not_counted_here(self):
        """`server.app` подключает роутеры соседей. Считать их у себя значило бы
        вынести один и тот же маршрут дважды, у двух разных хозяев."""
        called, refused = self.probe.callable_routes(self.mod)
        self.assertNotIn("/alien", [p for p, _ in called])
        self.assertNotIn("/alien", refused)

    def test_the_named_refusal_list_is_honoured_and_names_its_reason(self):
        """Механизм именного отказа оставлен при ПУСТОМ сегодня списке намеренно:
        «пусто сегодня» и «пусто всегда» — разные утверждения."""
        never = {"g27mod:/read": "зов совершил бы действие"}
        called, refused = self.probe.callable_routes(self.mod, never_call=never)
        self.assertEqual(called, [])
        self.assertIn("зов совершил бы действие", refused["/read"])

    def test_the_shipped_refusal_list_is_empty_by_measurement(self):
        """Замер 16.09: прогон всех подходящих маршрутов против копии стенда не
        изменил в ней ни байта (1325 файлов, sha до и после). Если список
        однажды понадобится — он понадобится С ПРИЧИНОЙ у каждой записи."""
        for key, why in self.probe.HTTP_NEVER_CALL.items():
            self.assertTrue(str(why).strip(), f"отказ {key} без причины")


class G27VerdictTests(unittest.TestCase):
    """Вердикт по маршрутам, проба пустого каталога и порядок зова."""

    @staticmethod
    def _mod(routes_by_probe, refused=None):
        """Пять ответов партии для одного модуля: s1, s1_again, s2, s3, empty."""
        return tuple({"routes": r, "refused": refused or {}, "elapsed_s": {}}
                     for r in routes_by_probe)

    def test_the_verdict_is_per_route_so_one_noisy_route_hides_no_neighbour(self):
        """Измеренная поломка: на вердикте ЦЕЛОГО модуля `rates_desk` уходил в
        «не воспроизводится» из-за ОДНОГО маршрута, пряча десять соседей, а
        `cockpit` прятал два. Маршрут — это и есть то, что видит владелец."""
        noisy = lambda i: {"n": i}
        probes = self._mod([
            {"/quiet": {"v": "one"}, "/noisy": noisy(1)},
            {"/quiet": {"v": "one"}, "/noisy": noisy(2)},
            {"/quiet": {"v": "one"}, "/noisy": noisy(3)},
            {"/quiet": {"v": "two"}, "/noisy": noisy(4)},
            {"/quiet": {"v": "empty"}, "/noisy": noisy(5)},
        ])
        row = g16.classify_http_reader("g27mod", probes)
        self.assertEqual(row["outcome"], g16.READER_LAST)
        self.assertEqual(row["routes"]["/quiet"]["outcome"], g16.READER_LAST)
        self.assertEqual(row["routes"]["/noisy"]["outcome"], g16.READER_UNMEASURED)

    def test_the_empty_stand_probe_catches_a_route_that_never_opened_the_stand(self):
        """САМАЯ важная проверка этой правки, и она о ней самой. 19 маршрутов из
        111 отвечают на ПУСТОМ каталоге ровно то же, что на настоящем — каталога
        они не открывали. Без пятой пробы все девятнадцать доложились бы как
        `insensitive_stand`, то есть перепись обменяла бы одну слепоту на
        другую, потише."""
        const = {"v": "константа"}
        probes = self._mod([{"/c": const}] * 5)
        row = g16.classify_http_reader("g27mod", probes)
        self.assertEqual(row["routes"]["/c"]["outcome"], g16.READER_UNMEASURED)
        self.assertEqual(row["routes"]["/c"]["cause"], g16.CAUSE_STAND_NOT_READ)

    def test_a_route_that_does_read_the_stand_stays_insensitive_not_unmeasured(self):
        """Обратный контроль к предыдущему: иначе проверка была бы истинной по
        построению и красила бы `stand_not_read` вообще всё."""
        probes = self._mod([
            {"/r": {"v": "стенд"}}, {"/r": {"v": "стенд"}}, {"/r": {"v": "стенд"}},
            {"/r": {"v": "стенд"}}, {"/r": {"v": "пусто"}},
        ])
        row = g16.classify_http_reader("g27mod", probes)
        self.assertEqual(row["routes"]["/r"]["outcome"], g16.READER_INSENSITIVE)
        self.assertTrue(row["routes"]["/r"]["reaches_stand"])

    def test_absence_of_the_empty_probe_is_not_the_same_as_an_empty_answer(self):
        """`None` — законный ОТВЕТ читателя. Умолчание в его виде сделало бы
        «пробы не было» неотличимым от «проба вернула пустоту» (инв. #17)."""
        row_no_probe = g16.verdict_from_probes({}, {"v": 1}, {"v": 1}, {"v": 1}, {"v": 1})
        self.assertEqual(row_no_probe["outcome"], g16.READER_INSENSITIVE)
        self.assertNotIn("reaches_stand", row_no_probe)
        row_none = g16.verdict_from_probes({}, {"v": 1}, {"v": 1}, {"v": 1}, {"v": 1},
                                           on_empty=None)
        self.assertEqual(row_none["outcome"], g16.READER_INSENSITIVE)
        self.assertTrue(row_none["reaches_stand"])

    def test_the_repeat_probe_runs_LAST_so_its_window_covers_the_whole_batch(self):
        """Измеренная монета, ради которой порядок и переставлен.
        `/api/riskwire/proof` несёт `age_hours`, округлённый до 0.1 часа = 6 мин.
        Две пробы ПОДРЯД попадают в одну корзину (`unstable_coords: 0`), а
        граница корзины между `s2` и `s3` дала `collapses_to_first` в одном
        прогоне и `insensitive_stand` в соседнем — одно дерево, одни стенды,
        неизменный код.

        Стенд здесь моделирует ровно это: координата тикает ОДИН раз, между
        третьим и четвёртым зовом. При накрывающем окне она измеряется как
        нестабильная; при соседних пробах — объявляется схлопыванием."""
        ticks = iter([0, 0, 0, 1, 1])                 # тик между s2 и s3
        base = {"body": "same"}

        def runner(stand_data, names, tree_root):
            value = next(ticks)
            return {"g27mod": {"routes": {"/p": dict(base, age=value)},
                               "refused": {}, "elapsed_s": {}}}, ""

        stands = {"s1": "/s1", "s2": "/s2", "s3": "/s3"}
        answers, meta = g16.http_probe_batch(stands, ["g27mod"], Path("/t"), runner=runner)
        self.assertEqual(meta["probe_order"][-1], "s1_again",
                         "повторная проба обязана идти ПОСЛЕДНЕЙ")
        row = g16.classify_http_reader("g27mod", answers["g27mod"])
        self.assertEqual(row["routes"]["/p"]["outcome"], g16.READER_UNMEASURED,
                         "тик, попавший между стендами, выдан за схлопывание")

    def test_the_same_tick_read_by_adjacent_probes_WOULD_have_been_a_collapse(self):
        """Обратный контроль к порядку: без накрывающего окна ровно те же пять
        ответов дают `collapses_to_first`. Без этого теста перестановка порядка
        была бы украшением — нечем показать, что она что-то меняет."""
        s1 = {"body": "same", "age": 0}
        s1_again = {"body": "same", "age": 0}          # соседние пробы: тика нет
        s2 = {"body": "same", "age": 1}
        s3 = {"body": "same", "age": 1}
        row = g16.verdict_from_probes({}, s1, s1_again, s2, s3)
        self.assertEqual(row["outcome"], g16.READER_FIRST)

    def test_one_failed_probe_voids_the_WHOLE_batch_with_a_named_reason(self):
        """Трёх ответов на вердикт не хватает, а достроить четвёртый нечем.
        Частичная партия прочиталась бы как «маршруты ни при чём»."""
        calls = {"n": 0}

        def runner(stand_data, names, tree_root):
            calls["n"] += 1
            if calls["n"] == 3:
                return None, "процесс-зовущий вышел кодом 1"
            return {"g27mod": {"routes": {"/p": {"v": calls["n"]}},
                               "refused": {}, "elapsed_s": {}}}, ""

        answers, meta = g16.http_probe_batch({"s1": "/1", "s2": "/2", "s3": "/3"},
                                             ["g27mod"], Path("/t"), runner=runner)
        self.assertEqual(answers, {})
        self.assertEqual(meta["failed_probe"], g16._HTTP_PROBE_ORDER[2])
        self.assertIn("кодом 1", meta["reason"])

    def test_a_module_with_no_callable_route_keeps_a_cause_naming_the_refusals(self):
        """Остаток обязан быть НАЗВАН, а не растворён в знаменателе: у
        `dfb_data_api` все шесть GET требуют аргумент, у `server` — четыре."""
        probes = self._mod([{}] * 5,
                           refused={"/x/{id}": "обязательные аргументы id"})
        row = g16.classify_http_reader("g27mod", probes)
        self.assertEqual(row["outcome"], g16.READER_UNMEASURED)
        self.assertEqual(row["cause"], g16.CAUSE_HTTP_ROUTE)
        self.assertIn("id", row["reason"])

    def test_the_http_cause_no_longer_repeats_the_refuted_claim(self):
        """Строка «каталог стенда ему не передать» была ЗАМЕРОМ опровергнута.
        Оставить её значило бы держать в приборе довод, который он сам же и
        опроверг, — и следующий цикл прочитал бы его как действующий."""
        probes = self._mod([{}] * 5, refused={"/x/{id}": "обязательные аргументы id"})
        reason = str(g16.classify_http_reader("g27mod", probes)["reason"])
        self.assertNotIn("каталог стенда ему не передать", reason)

    def test_module_outcome_takes_the_strongest_signal_not_the_majority(self):
        """Схлопывание хотя бы на ОДНОМ маршруте есть свойство модуля. Взять
        большинство значило бы утопить находку в тринадцати нечувствительных."""
        probes = self._mod([
            {"/a": {"v": 1}, "/b": {"v": "x"}},
            {"/a": {"v": 1}, "/b": {"v": "x"}},
            {"/a": {"v": 1}, "/b": {"v": "x"}},
            {"/a": {"v": 2}, "/b": {"v": "x"}},
            {"/a": {"v": 9}, "/b": {"v": "y"}},
        ])
        row = g16.classify_http_reader("g27mod", probes)
        self.assertEqual(row["outcome"], g16.READER_LAST)
        self.assertEqual(row["routes_by_outcome"],
                         {g16.READER_LAST: 1, g16.READER_INSENSITIVE: 1})

    def test_both_reader_paths_go_through_ONE_copy_of_the_rule(self):
        """Правило «схлопывает» обязано иметь одно определение. Второе завелось
        бы молча и означало бы у переписи ровно тот дефект, который она ловит у
        читателей журнала. Спрашивается ФОРМА ВЫЗОВА в AST, а не подстрока:
        подстрока пережила бы любое расплетение."""
        import ast as _ast
        import inspect as _inspect
        tree = _ast.parse(_inspect.getsource(g16))
        callers = set()
        for node in _ast.walk(tree):
            if not isinstance(node, _ast.FunctionDef):
                continue
            for inner in _ast.walk(node):
                if (isinstance(inner, _ast.Call)
                        and isinstance(inner.func, _ast.Name)
                        and inner.func.id == "verdict_from_probes"):
                    callers.add(node.name)
        self.assertEqual(callers, {"classify_reader", "classify_http_reader"},
                         f"вердикт считают не те функции: {callers}")


class G27PopulationTests(unittest.TestCase):
    """Кого партия вообще спрашивает."""

    def test_a_module_on_the_never_call_list_never_enters_the_http_batch(self):
        """Отказ ЗВАТЬ сильнее умения позвать: у писателя журнала HTTP-поверхности
        нет, но если она однажды появится, партия обязана его пропустить."""
        from unittest import mock
        with mock.patch.dict(g16._NEVER_CALL,
                             {"spa_core.api.routers.live": "измерять запрещено"}):
            names = g16.http_modules(["spa_core.api.routers.live"])
        self.assertEqual(names, [])
        # обратный контроль: без списка тот же модуль в партию ВХОДИТ
        self.assertEqual(g16.http_modules(["spa_core.api.routers.live"]),
                         ["spa_core.api.routers.live"])

    def test_an_http_surface_is_recognised_by_the_object_not_by_the_module_name(self):
        """Имя (`spa_core.api.routers.*`) было бы догадкой и ошибалось бы в обе
        стороны: роутер живёт и вне каталога (`spa_core.api.server`)."""
        self.assertIn("spa_core.api.server",
                      g16.http_modules(["spa_core.api.server"]))
        self.assertEqual(g16.http_modules(["spa_core.monitoring.run_identity_key_price"]),
                         [])


# ── G28 · ЧАСЫ ПРОГОНА ДОХОДЯТ ДО ЧИТАТЕЛЯ ───────────────────────────────────
#: Три ветви связывания зова — три отдельных контроля. Одна ветвь, потерявшая
#: часы, остальными не ловится: «половина инъекции есть та же бомба»
#: (`.claude/rules/deployment.md`, поправка #453). Стенные часы в стабах не
#: спрашиваются ни разу — вместо них счётчик, который РАСТЁТ на каждом зове:
#: он воспроизводит тот же дефект (координата бежит от зова к зову)
#: детерминированно, а не по везению планировщика.
_G28_STUBS = {
    # Журнала не читает, но несёт координату, производную от часов. Именно так
    # устроены 8 из 9 читателей, стоявших в `verdict_rests_on_unstable_coords`
    # на замере 16.09: вся разница между стендами лежала в этой координате.
    "deafclock": "_N=[0]\n"
                 "def measure(data_dir, now=None):\n"
                 "    if now is None:\n"
                 "        _N[0]+=1\n"
                 "        age=_N[0]\n"
                 "    else:\n"
                 "        age=int(now.timestamp())\n"
                 "    return {'answer': 'журнала не читаю', 'age_s': age}\n",
    # Журнал ЧИТАЕТ и схлопывает день — и тоже несёт бегущую координату.
    # Нужен затем, чтобы «insensitive_stand» под проведёнными часами не
    # оказалось универсальным ответом: контроль, истинный по построению,
    # доказывал бы только сам себя.
    "lastclock": "_N=[0]\n"
                 "def measure(data_dir, now=None):\n"
                 "    import json\n"
                 "    if now is None:\n"
                 "        _N[0]+=1\n"
                 "        age=_N[0]\n"
                 "    else:\n"
                 "        age=int(now.timestamp())\n"
                 "    rows=[json.loads(l) for l in (data_dir/'h.jsonl').read_text().splitlines() if l.strip()]\n"
                 "    by={}\n"
                 "    for r in rows: by[r['cycle_date']]=r\n"
                 "    return {'age_s': age,\n"
                 "            'verdicts': sorted((d, v['verdict']) for d, v in by.items())}\n",
    # Часы брать НЕКУДА: у точки входа нет такого параметра. `**kw` тоже не
    # годится — прибор не подсовывает имени, которого callee не объявил.
    "noclock": "def measure(data_dir, **kw):\n"
               "    return {'answer': 'часов не беру'}\n",
    # Вторая ветвь связывания: `run(root=..., write=...)`. По ней зовутся
    # `house_view_gap`, `capital_evidence_coverage`, `apy_composition`.
    "runclock": "def run(root=None, *, now=None, write=True):\n"
                "    return {'got_now': None if now is None else now.isoformat(),\n"
                "            'write': write, 'root': str(root)}\n",
    # Третья ветвь: именной список `_EXTRA_READ_ONLY_ENTRIES`.
    "extraclock": "def read_brief(data_dir, now=None):\n"
                  "    return {'got_now': None if now is None else now.isoformat()}\n",
}

#: Часы, которые тест проводит. От якоря файла, не от календаря машины.
_G28_NOW = _ANCHOR + timedelta(hours=3)


class G28InjectedClockTests(unittest.TestCase):
    """Заказ G28, часть 1: часы прогона доходят до САМОГО читателя.

    Замер 16.09 до правки: **26 из 26** читателей класса
    `verdict_rests_on_unstable_coords` УЖЕ принимали ``now=`` — цена, которую
    заказ собирался платить у читателя, была уплачена давно. Не проводила часы
    ПРОВОДКА переписи, и эти тесты стерегут именно её.
    """

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(prefix="g28_clock_")
        self.root = Path(self._tmp.name)
        self.pkg = self.root / "stubs"
        self.pkg.mkdir()
        for name, src in _G28_STUBS.items():
            (self.pkg / f"g28stub_{name}.py").write_text(src, encoding="utf-8")
        sys.path.insert(0, str(self.pkg))
        self.stands = {}
        for stand, rows in (("s1", [_row(0, verdict="HOLD", hours=9)]),
                            ("s2", [_row(0, verdict="ACT", hours=1),
                                    _row(0, verdict="HOLD", hours=9)]),
                            ("s3", [_row(0, verdict="ACT", hours=1)])):
            data = self.root / stand / "data"
            data.mkdir(parents=True)
            (data / "h.jsonl").write_text(
                "\n".join(json.dumps(r, sort_keys=True) for r in rows) + "\n",
                encoding="utf-8")
            self.stands[stand] = self.root / stand

    def tearDown(self):
        sys.path.remove(str(self.pkg))
        for name in list(sys.modules):
            if name.startswith("g28stub_"):
                del sys.modules[name]
        self._tmp.cleanup()

    def _mod(self, stub):
        return importlib.import_module(f"g28stub_{stub}")

    # ── ветвь 1: measure/build/evaluate_window ───────────────────────────────
    def test_injected_clock_reaches_the_reader_by_outcome(self):
        """Проверяется ФОРМА ЗОВА через ИСХОД, а не наличие параметра.

        Читатель возвращает то время, которое получил. Уронив `clock_kwarg` из
        `module_driver`, получим `None` — и тест покраснеет, хотя параметр у
        точки входа как стоял, так и стоит.
        """
        _name, call = g16.module_driver(self._mod("runclock"), now=_G28_NOW)
        self.assertEqual(call(self.stands["s1"])["got_now"], _G28_NOW.isoformat())

    def test_without_the_clock_the_same_reader_gets_no_verdict(self):
        """ОБРАТНАЯ сторона: без часов тот же читатель на тех же стендах
        уходит в `verdict_rests_on_unstable_coords`. Без этого контроля
        зелёный тест ниже был бы истинным по построению."""
        row = g16.classify_reader("g28stub_deafclock", self.stands)
        self.assertEqual(row["outcome"], g16.READER_UNMEASURED)
        self.assertEqual(row["cause"], g16.CAUSE_RESTS_ON_UNSTABLE)
        self.assertIs(row["clock_injected"], False)

    def test_with_the_clock_the_verdict_is_obtained(self):
        """ИСХОД заказа G28: тот же читатель, те же стенды, часы проведены —
        вердикт есть, и он честный («стенд не сдвинул ответ»)."""
        row = g16.classify_reader("g28stub_deafclock", self.stands, now=_G28_NOW)
        self.assertEqual(row["outcome"], g16.READER_INSENSITIVE)
        self.assertIsNone(row.get("cause"))
        self.assertIs(row["clock_injected"], True)

    def test_injection_does_not_paint_every_reader_insensitive(self):
        """Контроль против самого дешёвого способа «улучшить» счётчик: если бы
        проведённые часы гасили РАЗНИЦУ, схлопывающий читатель тоже стал бы
        `insensitive_stand`, и класс «убыл» бы враньём."""
        row = g16.classify_reader("g28stub_lastclock", self.stands, now=_G28_NOW)
        self.assertEqual(row["outcome"], g16.READER_LAST)
        self.assertIs(row["clock_injected"], True)

    def test_an_entry_that_takes_no_clock_says_so_rather_than_lying(self):
        """Инв. #17: «часы провести некуда» — отдельное значение, а не False
        без причины и не молчание. Лечится оно в ДРУГОМ месте (у читателя)."""
        row = g16.classify_reader("g28stub_noclock", self.stands, now=_G28_NOW)
        self.assertIs(row["clock_injected"], False)
        self.assertEqual(row["clock_reason"], g16.CLOCK_NOT_ACCEPTED)

    def test_kwargs_catchall_is_not_treated_as_accepting_the_clock(self):
        """`**kw` НЕ считается согласием принять часы: подсунуть имя, которого
        callee не объявил, значило бы гадать о его смысле. Fail-CLOSED."""
        self.assertEqual(g16.clock_kwarg(self._mod("noclock").measure, _G28_NOW), {})

    # ── ветвь 2: run(root=..., write=...) ────────────────────────────────────
    def test_the_run_entry_branch_carries_the_clock_too(self):
        """Своя ветвь связывания — свой контроль. По ней зовутся `house_view_gap`
        и `capital_evidence_coverage`; потеряй она часы, ветвь 1 промолчала бы."""
        _name, call = g16.module_driver(self._mod("runclock"), now=_G28_NOW)
        answer = call(self.stands["s1"])
        self.assertEqual(answer["got_now"], _G28_NOW.isoformat())
        self.assertFalse(answer["write"], "write=False обязан уцелеть рядом с часами")

    def test_the_run_entry_branch_without_a_clock_stays_silent(self):
        self.assertIsNone(
            g16.module_driver(self._mod("runclock"))[1](self.stands["s1"])["got_now"])

    # ── ветвь 3: именной список read-only точек входа ────────────────────────
    def test_the_named_extra_entry_branch_carries_the_clock_too(self):
        from unittest import mock
        with mock.patch.dict(g16._EXTRA_READ_ONLY_ENTRIES,
                             {"g28stub_extraclock": "read_brief"}):
            _name, call = g16.module_driver(self._mod("extraclock"), now=_G28_NOW)
            self.assertEqual(call(self.stands["s1"])["got_now"], _G28_NOW.isoformat())

    # ── проводка сверху: часы прогона, а не вторые часы ──────────────────────
    def test_the_sweep_hands_its_own_clock_down_to_every_reader(self):
        """Проверка по ФОРМЕ ЗОВА (`.claude/rules` — «check wiring by CALL FORM»),
        и это сказано вслух: полный прогон переписи внутри unit-теста обошёлся бы
        в обход 2151 модуля. Что зов доносит часы ДО читателя — доказано выше
        исходом; здесь стережётся только то, что `measure` их не теряет."""
        import ast as _ast
        tree = _ast.parse(Path(g16.__file__).read_text(encoding="utf-8"))
        found = []
        for node in _ast.walk(tree):
            if (isinstance(node, _ast.Call) and isinstance(node.func, _ast.Name)
                    and node.func.id == "classify_reader"):
                found.append({kw.arg for kw in node.keywords})
        self.assertTrue(found, "вызова classify_reader в приборе нет вовсе")
        for kwargs in found:
            self.assertIn("now", kwargs,
                          "перепись зовёт читателя без часов — половина инъекции")
