"""Закрытие выживших мутаций прибора G17 — набор НАСЛЕДНИКА (ADR-385).

Цикл #603 построил прибор и умер на ПЕРВОМ раунде батареи: 44 выживших из 157
кодовых координат. Наследовать чужую приёмку нельзя — «величина, представленная
дважды, требует сверки обоих представлений», — поэтому здесь каждая выжившая
координата закрыта КОНТРОЛЕМ, а не дописыванием в базу.

Каждый тест назван по тому, что он ловит, и падает на конкретной мутации:
координата указана в докстринге теста строкой вида ``строка N: X → Y``. Это не
украшение — это адрес, по которому проверяется, что контроль не самоочевиден.

Время здесь ВХОД, а не окружение: все даты порождены одним якорем ``NOW``, и он
же уходит в ``measure(now=...)`` / ``run(now=...)``.
"""

# FROZEN-DATE-OK: injected-clock — якорь NOW порождает КАЖДУЮ дату набора
# (`_day()` вычитает дни из NOW), и он же передаётся прибору параметром
# `now=` в `measure(..., now=NOW)` и `run(..., now=NOW)`. Стенных часов
# прибор на этом пути не спрашивает ни разу.

from __future__ import annotations

import inspect
import io
import json
import sys
import types
import unittest
from contextlib import redirect_stdout
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

from spa_core.monitoring import heir_all_rows_price as H
from spa_core.monitoring import run_identity_key_price as G16
from spa_core.paper_trading import shadow_trigger_eval as ste

NOW = datetime(2026, 9, 14, 12, 0, 0, tzinfo=timezone.utc)
HORIZON = int(ste.DEFAULT_HORIZON_DAYS)


def _day(days_ago: int) -> str:
    """Дата дня журнала — ФУНКЦИЯ якоря, а не отдельный литерал."""
    return (NOW - timedelta(days=days_ago)).date().isoformat()


def _row(day: str, verdict: str = "HOLD", turnover: float = 1000.0) -> dict:
    return {"cycle_date": day, "decision_id": f"adr060-shadow-{day}",
            "generated_at": f"{day}T18:00:00.000000+00:00",
            "verdict": verdict, "turnover_usd": turnover}


def _journal(data_dir: Path, rows, *, sort_keys: bool = True) -> None:
    data_dir.mkdir(parents=True, exist_ok=True)
    (data_dir / H.HISTORY_FILENAME).write_text(
        "\n".join(json.dumps(r, sort_keys=sort_keys) for r in rows) + "\n",
        encoding="utf-8")


def _material(root: Path, n_days: int = 3) -> Path:
    """Источник с журналом из ``n_days`` ОДНОСТРОЧНЫХ дней, старший — первым."""
    src = root / "live" / "data"
    days = [_day(n_days - i) for i in range(n_days)]
    _journal(src, [_row(d, turnover=1000.0 * (i + 1)) for i, d in enumerate(days)])
    return src


def _install(name: str, entry):
    mod = types.ModuleType(name)
    mod.measure = entry  # type: ignore[attr-defined]
    entry.__module__ = name
    sys.modules[name] = mod
    return mod


def _day_rows(data_dir, day: str):
    """Строки ОДНОГО дня так, как их видит наследник — через судью."""
    rows, _ = ste.load_history(Path(data_dir))
    return [r for r in rows if str(r.get("cycle_date")) == day]


# ── правило выбора дня стенда ────────────────────────────────────────────────
class TheDayRuleIsMeasuredByOutcome(unittest.TestCase):
    """Прежний тест спрашивал у ``_judge_horizon()`` его же число — украшение.

    Правило дня («позднейший день, за которым остаётся полный горизонт судьи»)
    решает, ЧТО именно меряет весь прибор: сосед [ADR-384] на этом же месте
    получил 13 схлопывающих вместо 20, взяв последний день журнала. Поэтому
    правило проверяется ИСХОДОМ — какой день выбран, — а не наличием функции.
    """

    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_the_chosen_day_leaves_the_judges_full_horizon_behind_it(self):
        """строка 279: `len(rows) - 1 - horizon` → `- 2 -` / `max(1,…)` → `max(2,…)`."""
        n = HORIZON + 5
        src = _material(self.root, n_days=n)
        stands, why = H.build_stands(src, self.root / "s")
        self.assertIsNotNone(stands, why)
        expected_idx = n - 1 - HORIZON
        self.assertEqual(stands["day"], _day(n - expected_idx))
        self.assertEqual(stands["donor_day"], _day(n - expected_idx + 1))

    def test_a_journal_exactly_one_day_longer_than_the_horizon_lands_on_the_floor(self):
        """строка 279: `max(1, …)` → `max(2, …)`.

        Длина ``horizon + 2`` даёт ровно 1 — единственное место, где пол виден.
        """
        n = HORIZON + 2
        src = _material(self.root, n_days=n)
        stands, why = H.build_stands(src, self.root / "s")
        self.assertIsNotNone(stands, why)
        self.assertEqual(stands["day"], _day(n - 1), "пол правила сдвинут")

    def test_the_day_rule_says_out_loud_which_horizon_it_used(self):
        """строка 281: `if horizon is not None` → `is None`."""
        src = _material(self.root, n_days=HORIZON + 5)
        stands, _ = H.build_stands(src, self.root / "s")
        self.assertIn("горизонт судьи", stands["day_rule"])
        self.assertIn(str(HORIZON), stands["day_rule"])

    def test_naming_the_first_day_shifts_the_stand_instead_of_taking_a_donor_that_is_not_there(self):
        """строка 284: `idx = len(rows) - 1` → `len(rows)` / `- 2`."""
        n = 4
        src = _material(self.root, n_days=n)
        stands, why = H.build_stands(src, self.root / "s", day=_day(n))
        self.assertIsNotNone(stands, why)
        self.assertEqual(stands["day"], _day(1), "сдвиг увёл не на последний день")
        self.assertEqual(stands["donor_day"], _day(2))
        self.assertIn("сдвинут", stands["day_rule"])

    def test_two_rows_are_enough_for_a_stand_and_the_refusal_starts_below_that(self):
        """строка 268: `len(rows) < 2` → `<= 2` / `< 3`."""
        src = _material(self.root, n_days=2)
        stands, why = H.build_stands(src, self.root / "s")
        self.assertIsNotNone(stands, f"двух строк ДОЛЖНО хватать: {why}")


# ── механика копии стенда ────────────────────────────────────────────────────
class StandCopyMechanics(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.src = _material(self.root, n_days=3)

    def tearDown(self):
        self.tmp.cleanup()

    def test_the_excluded_directory_is_the_only_one_left_behind(self):
        """строка 301: `if item.name in STAND_EXCLUDE` → `not in`."""
        excluded = self.src / H.STAND_EXCLUDE[0]
        excluded.mkdir(parents=True)
        (excluded / "heavy.json").write_text("{}", encoding="utf-8")
        kept = self.src / "keepme"
        kept.mkdir(parents=True)
        (kept / "light.json").write_text("{}", encoding="utf-8")

        stands, why = H.build_stands(self.src, self.root / "s")
        self.assertIsNotNone(stands, why)
        data = Path(stands["s_one"]) / "data"
        self.assertFalse((data / H.STAND_EXCLUDE[0]).exists(),
                         f"{H.STAND_EXCLUDE[0]} утащен в стенд")
        self.assertTrue((data / "light.json").parent.exists())
        self.assertTrue((data / "keepme" / "light.json").exists(),
                        "обычный подкаталог НЕ скопирован")

    def test_building_into_the_same_destination_twice_is_not_a_crash(self):
        """строки 299/305: `exist_ok=True` → `False`, `dirs_exist_ok=True` → `False`.

        Повторный прогон с тем же ``--stand-root`` — обычное дело (так гнался
        и первый замер на живых данных), и падать на нём прибор не вправе.
        """
        sub = self.src / "nested"
        sub.mkdir(parents=True)
        (sub / "x.json").write_text("{}", encoding="utf-8")
        dest = self.root / "same"
        first, why = H.build_stands(self.src, dest)
        self.assertIsNotNone(first, why)
        second, why2 = H.build_stands(self.src, dest)
        self.assertIsNotNone(second, f"вторая сборка в тот же каталог упала: {why2}")

    def test_the_stand_journal_is_written_with_sorted_keys_whatever_the_source_order(self):
        """строка 315: `sort_keys=True` → `False`.

        Стенд обязан быть воспроизводим побайтово независимо от порядка ключей
        в источнике — иначе «ответ не воспроизводится» станет свойством файла.
        """
        scrambled = {"turnover_usd": 1.0, "cycle_date": _day(2), "verdict": "HOLD",
                     "decision_id": "adr060-shadow", "generated_at": "x"}
        src = self.root / "scrambled" / "data"
        _journal(src, [dict(scrambled, cycle_date=_day(3)), scrambled], sort_keys=False)
        stands, why = H.build_stands(src, self.root / "s2")
        self.assertIsNotNone(stands, why)
        line = (Path(stands["s_one"]) / "data" / H.HISTORY_FILENAME
                ).read_text(encoding="utf-8").splitlines()[0]
        keys = list(json.loads(line).keys())
        self.assertEqual(keys, sorted(keys), "ключи стенда не отсортированы")


# ── разбор журнала ───────────────────────────────────────────────────────────
class JournalParsing(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_a_row_without_a_date_and_a_row_that_is_not_an_object_are_both_dropped(self):
        """строка 251: `isinstance(obj, dict) and obj.get(...)` → `or`."""
        data = self.root / "data"
        data.mkdir(parents=True)
        good = _row(_day(2))
        (data / H.HISTORY_FILENAME).write_text(
            "\n".join([json.dumps([1, 2]), json.dumps({"verdict": "HOLD"}),
                       json.dumps(good)]) + "\n", encoding="utf-8")
        rows, why = H.read_history(data)
        self.assertEqual(rows, [good], why)

    def test_the_bad_line_counter_counts_lines_and_not_merely_something(self):
        """строки 359/360: `bad += 1` → `+= 2`, `not isinstance(...) or not ...` → `and`."""
        data = self.root / "data"
        data.mkdir(parents=True)
        (data / ste._history_filename(None)).write_text(
            "\n".join(["{не json}", json.dumps({"verdict": "HOLD"}),
                       json.dumps(_row(_day(2)))]) + "\n", encoding="utf-8")
        rows, bad = H.all_rows_loader(data)
        self.assertEqual(bad, 2, "счётчик плохих строк считает не строки")
        self.assertEqual(len(rows), 1)

    def test_a_missing_journal_is_zero_bad_lines_and_not_one(self):
        """строка 350: `return [], 0` → `[], 1`.

        «Файла нет» — не «одна строка испорчена»: смешать их значит доложить
        наблюдение, которого не было (инв. #17).
        """
        self.assertEqual(H.all_rows_loader(self.root / "nowhere"), ([], 0))


# ── достижимость подмены ─────────────────────────────────────────────────────
class TheReachabilityCounterReportsANumber(unittest.TestCase):
    """``loader_calls`` печатается в отчёте как ЧИСЛО — значит оно под контролем."""

    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.root = Path(self.tmp.name)
        src = _material(self.root, n_days=3)
        self.stands, why = H.build_stands(src, self.root / "s", day=_day(2))
        self.assertIsNotNone(self.stands, why)
        self.installed = []

    def tearDown(self):
        for name in self.installed:
            sys.modules.pop(name, None)
        self.tmp.cleanup()

    def test_an_heir_calling_the_loader_twice_is_recorded_as_twice(self):
        """строка 407: `self.n += 1` → `+= 2`."""
        day = self.stands["day"]

        def entry(data_dir):
            first = _day_rows(data_dir, day)
            second = _day_rows(data_dir, day)
            return {"n": len(first) + len(second)}

        name = "fake_heir_two_calls"
        self.installed.append(name)
        _install(name, entry)
        row = H.classify_heir(name, self.stands)
        self.assertEqual(row.get("loader_calls"), 2, row)


# ── детектор повтора: обе руки ───────────────────────────────────────────────
class TheRepeatDetectorNeedsBothArms(unittest.TestCase):
    """``inflates_2 or inflates_3`` — центральное утверждение ADR-385.

    Прежний набор знал только наследников, раздувающихся на ОБОИХ повторах,
    поэтому `or` → `and` переживал батарею: подмена союза не меняла ни одного
    вердикта. Здесь по наследнику на КАЖДУЮ руку.
    """

    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.root = Path(self.tmp.name)
        src = _material(self.root, n_days=3)
        self.stands, why = H.build_stands(src, self.root / "s", day=_day(2))
        self.assertIsNotNone(self.stands, why)
        self.installed = []

    def tearDown(self):
        for name in self.installed:
            sys.modules.pop(name, None)
        self.tmp.cleanup()

    def _classify(self, name, entry):
        self.installed.append(name)
        _install(name, entry)
        return H.classify_heir(name, self.stands)

    def test_an_heir_blind_to_a_pair_but_not_to_a_triple_is_still_double_counting(self):
        """строки 514/517: `inflates_2 or inflates_3` → `and`.

        Читатель, сводящий строки ПАРАМИ (решение + подтверждение), на дне из
        двух побайтово равных строк отвечает как на дне из одной, а на трёх —
        уже иначе. Двойной счёт у него есть, и ловит его только правая рука.
        """
        day = self.stands["day"]
        row = self._classify(
            "fake_heir_pairs",
            lambda data_dir: {"pairs": (len(_day_rows(data_dir, day)) + 1) // 2})
        self.assertEqual(row["outcome"], H.HEIR_DOUBLE, row)
        self.assertTrue(row["inflates_on_repeat"])
        self.assertIn("×3", row["reason"])

    def test_an_heir_saturating_at_two_rows_is_caught_by_the_left_arm(self):
        """строки 514/517: та же пара координат с другой стороны."""
        day = self.stands["day"]
        row = self._classify(
            "fake_heir_saturates",
            lambda data_dir: {"n": min(len(_day_rows(data_dir, day)), 2)})
        self.assertEqual(row["outcome"], H.HEIR_DOUBLE, row)
        self.assertTrue(row["inflates_on_repeat"])
        self.assertIn("×2", row["reason"])


# ── сборка замера: КОГО меряем и как считаем ─────────────────────────────────
class MeasureSelectsAndCountsThePopulation(unittest.TestCase):
    """Ни один тест соседа не доводил ``measure()`` до конца.

    Поэтому переживали батарею отбор наследников (`== READER_LAST`), отбор
    «без точки входа», оба накопителя счётчиков и самоисключение прибора —
    то есть весь ответ целиком: прибор мог мерить ДРУГИЕ двадцать модулей и
    ни один тест не покраснел бы.
    """

    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.src = _material(self.root, n_days=3)
        self.installed = []
        self.seen_readers = []
        self.seen_whose = []

        day = _day(2)

        def sums(data_dir):
            return {"total": sum(float(r.get("turnover_usd") or 0)
                                 for r in _day_rows(data_dir, day))}

        for name in ("fake_last_a", "fake_last_b", "fake_first_only"):
            self.installed.append(name)
            _install(name, sums)

        self.roads = ["fake_last_a", "fake_last_b", "fake_first_only",
                      "fake_no_entry", "fake_broken", G16.__name__, H.__name__]
        self.outcomes = {
            "fake_last_a": {"outcome": G16.READER_LAST},
            "fake_last_b": {"outcome": G16.READER_LAST},
            "fake_first_only": {"outcome": G16.READER_FIRST},
            "fake_no_entry": {"outcome": G16.READER_UNMEASURED,
                              "reason": "нет приводимой точки входа"},
            "fake_broken": {"outcome": G16.READER_UNMEASURED,
                            "reason": "импорт не удался: ImportError"},
        }

        def fake_population(tree_root, **kw):
            return set(self.roads), {"population": len(self.roads)}

        def fake_classify(module_name, stands):
            self.seen_readers.append(module_name)
            row = {"module": module_name}
            row.update(self.outcomes[module_name])
            return row

        def fake_whose(module_name, stand, tree_root):
            self.seen_whose.append(module_name)
            return {"module": module_name, "whose": H.WHOSE_MODULE,
                    "reason": "стенд"}

        self._real = (G16.reader_population, G16.classify_reader, H.whose_property)
        G16.reader_population = fake_population
        G16.classify_reader = fake_classify
        H.whose_property = fake_whose

    def tearDown(self):
        (G16.reader_population, G16.classify_reader, H.whose_property) = self._real
        for name in self.installed:
            sys.modules.pop(name, None)
        self.tmp.cleanup()

    def _measure(self, **kw):
        return H.measure(self.src, now=NOW, tree_root=self.root,
                         stand_root=self.root / "stands", day=_day(2), **kw)

    def test_only_the_collapsing_readers_become_heirs(self):
        """строка 757: `== g16.READER_LAST` → `!=`."""
        doc = self._measure()
        self.assertEqual(doc["heirs_population"], 2)
        self.assertEqual(sorted(r["module"] for r in doc["heirs"]),
                         ["fake_last_a", "fake_last_b"])

    def test_the_outcome_counter_accumulates_one_per_heir(self):
        """строка 763: `counts.get(k, 0) + 1` → `+ 2` / `get(k, 1)`."""
        doc = self._measure()
        self.assertEqual(doc["heir_outcomes"], {H.HEIR_DOUBLE: 2})
        self.assertEqual(doc["status"], H.STATUS_CRITICAL)
        self.assertIn("2 из 2", doc["headline"])

    def test_only_the_no_entry_reason_reaches_the_second_half(self):
        """строки 767/768: `== READER_UNMEASURED` → `!=`, `and startswith` → `or`."""
        doc = self._measure()
        self.assertEqual(self.seen_whose, ["fake_no_entry"])
        self.assertEqual(doc["no_entry_population"], 1)

    def test_the_second_half_counter_accumulates_one_per_module(self):
        """строка 776: `wcounts.get(k, 0) + 1` → `+ 2` / `get(k, 1)`."""
        doc = self._measure()
        self.assertEqual(doc["whose_outcomes"], {H.WHOSE_MODULE: 1})

    def test_neither_instrument_is_driven_through_its_own_census(self):
        """строка 746: `if name in (g16.__name__, __name__)` → `not in`."""
        doc = self._measure()
        self.assertNotIn(G16.__name__, self.seen_readers)
        self.assertNotIn(H.__name__, self.seen_readers)
        self.assertEqual(doc["population"]["total"], len(self.roads))

    def test_the_second_half_is_measured_unless_it_is_switched_off(self):
        """строка 708: умолчание `sweep_entries: bool = True` → `False`."""
        doc = self._measure()
        self.assertIsNotNone(doc["whose_outcomes"])
        off = H.measure(self.src, now=NOW, tree_root=self.root,
                        stand_root=self.root / "stands2", day=_day(2),
                        sweep_entries=False)
        self.assertIsNone(off["whose_outcomes"])
        self.assertIn("sweep_entries=False", off["whose_unmeasured_reason"])

    def test_measuring_twice_into_the_same_stand_root_is_not_a_crash(self):
        """строка 729: `tmp.mkdir(parents=True, exist_ok=True)` → `exist_ok=False`."""
        self._measure()
        again = self._measure()
        self.assertEqual(again["status"], H.STATUS_CRITICAL)

    def test_a_measure_started_inside_a_measure_refuses(self):
        """строка 739: `_SWEEPING = True` → `False`.

        Прибор сам читает журнал; первый его прогон на живых данных вошёл в
        собственную перепись изнутри переписи. Заслон проверяется ИЗ хода
        замера, а не подъёмом флага руками.
        """
        nested = {}

        def population_that_reenters(tree_root, **kw):
            nested["doc"] = H.measure(self.src, now=NOW, tree_root=self.root,
                                      stand_root=self.root / "nested")
            return set(), {"population": 0}

        G16.reader_population = population_that_reenters
        doc = self._measure()
        self.assertEqual(nested["doc"]["status"], H.STATUS_UNMEASURED)
        self.assertIn("сам прибор", nested["doc"]["unmeasured_reason"])
        self.assertEqual(doc["status"], H.STATUS_UNMEASURED)


# ── дир-ведомые кандидаты ────────────────────────────────────────────────────
class DirDrivenCandidates(unittest.TestCase):
    def test_a_function_without_any_parameter_is_not_a_candidate(self):
        """строка 608: `if not params or params[0].name …` → `and`.

        С `and` пустая подпись доходит до `params[0]` и прибор падает на
        первом же модуле без аргументов — а таких в дереве большинство.
        """
        mod = types.ModuleType("fake_noargs_mod")

        def noargs():
            return 1

        def dirdriven(data_dir):
            return 2

        noargs.__module__ = "fake_noargs_mod"
        dirdriven.__module__ = "fake_noargs_mod"
        mod.noargs = noargs          # type: ignore[attr-defined]
        mod.dirdriven = dirdriven    # type: ignore[attr-defined]
        self.assertEqual(H.dir_driven_candidates(mod), ["dirdriven"])


# ── отчёт и код возврата ─────────────────────────────────────────────────────
class ReportAndExitCode(unittest.TestCase):
    def test_only_the_instrument_rows_are_printed_under_the_instrument_mark(self):
        """строка 848: `row.get("whose") == WHOSE_INSTRUMENT` → `!=`."""
        doc = {"status": H.STATUS_OK, "stand": {"day": _day(2), "donor_day": _day(3),
                                                "day_rule": "стенд"},
               "heir_outcomes": {}, "heirs_population": 0, "heirs": [],
               "no_entry_population": 2, "whose_outcomes": {H.WHOSE_MODULE: 1,
                                                            H.WHOSE_INSTRUMENT: 1},
               "whose": [{"module": "m.quiet", "whose": H.WHOSE_MODULE},
                         {"module": "m.loud", "whose": H.WHOSE_INSTRUMENT,
                          "entry": "build"}],
               "what_it_does_not_prove": [], "advisory": ["x"]}
        printed = [l for l in H.format_report(doc) if "[ПРИБОР]" in l]
        self.assertEqual(len(printed), 1)
        self.assertIn("m.loud", printed[0])
        self.assertNotIn("m.quiet", " ".join(printed))

    def test_a_status_nobody_declared_exits_as_not_measured(self):
        """строка 890: умолчание `.get(status, 2)` → `3`.

        Неизвестный статус — это «не измерено», а не свой отдельный код:
        различимых исходов ровно три, и четвёртого прибор не заводит.
        """
        with TemporaryDirectory() as tmp:
            data = Path(tmp) / "data"
            data.mkdir(parents=True)
            real = H.measure
            H.measure = lambda *a, **k: {"status": "СТАТУС-КОТОРОГО-НЕТ",
                                         "unmeasured_reason": "стенд"}
            try:
                buf = io.StringIO()
                with redirect_stdout(buf):
                    code = H.main(["--data-dir", str(data), "--no-entries"])
            finally:
                H.measure = real
        self.assertEqual(code, 2)

    def test_the_json_output_prints_russian_as_russian(self):
        """строка 885: `ensure_ascii=False` → `True`."""
        with TemporaryDirectory() as tmp:
            data = Path(tmp) / "data"
            data.mkdir(parents=True)
            real = H.measure
            H.measure = lambda *a, **k: {"status": H.STATUS_UNMEASURED,
                                         "unmeasured_reason": "журнала нет"}
            try:
                buf = io.StringIO()
                with redirect_stdout(buf):
                    H.main(["--data-dir", str(data), "--json"])
            finally:
                H.measure = real
        self.assertIn("журнала нет", buf.getvalue())

    def test_the_no_entries_flag_switches_the_second_half_off_and_not_on(self):
        """строка 883: `sweep_entries=not args.no_entries` → без `not`."""
        seen = {}

        def recorder(data_dir, **kw):
            seen.update(kw)
            return {"status": H.STATUS_UNMEASURED, "unmeasured_reason": "стенд"}

        with TemporaryDirectory() as tmp:
            data = Path(tmp) / "data"
            data.mkdir(parents=True)
            real = H.measure
            H.measure = recorder
            try:
                buf = io.StringIO()
                with redirect_stdout(buf):
                    H.main(["--data-dir", str(data), "--no-entries"])
                self.assertIs(seen["sweep_entries"], False)
                seen.clear()
                with redirect_stdout(buf):
                    H.main(["--data-dir", str(data)])
                self.assertIs(seen["sweep_entries"], True)
            finally:
                H.measure = real


class RunWritesTheArtifactUnlessToldNotTo(unittest.TestCase):
    """строка 858: умолчания `write: bool = True` / `sweep_entries: bool = True`."""

    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / "data").mkdir(parents=True)

    def tearDown(self):
        self.tmp.cleanup()

    def test_run_writes_by_default(self):
        H.run(str(self.root), now=NOW, sweep_entries=False)
        self.assertTrue((self.root / "data" / H.ARTIFACT).exists(),
                        "умолчание `write` перестало писать артефакт")

    def test_run_asked_not_to_write_leaves_no_artifact(self):
        H.run(str(self.root), now=NOW, write=False, sweep_entries=False)
        self.assertFalse((self.root / "data" / H.ARTIFACT).exists())



# ── раунд 2: координаты, пережившие первый раунд контролей ───────────────────
class TheFallbackWhenTheJudgeCannotBeRead(unittest.TestCase):
    """строка 279: ветка `else len(rows) - 1` — горизонт судьи НЕ прочитан.

    Первый раунд закрыл правило дня при читаемом судье и оставил открытой
    ровно ту ветку, ради которой сосед [ADR-384] переделывал стенд: когда
    горизонта нет, прибор берёт ПОСЛЕДНИЙ день журнала — день, за которым
    форвардных дней нет вовсе. Ветка законная, но она обязана быть измерена
    и НАЗВАНА в правиле дня, иначе «13 вместо 20» вернётся молча.
    """

    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.src = _material(self.root, n_days=HORIZON + 5)
        self._real = H._judge_horizon

    def tearDown(self):
        H._judge_horizon = self._real
        self.tmp.cleanup()

    def test_an_unreadable_horizon_falls_back_to_the_last_day_and_says_so(self):
        H._judge_horizon = lambda: None
        stands, why = H.build_stands(self.src, self.root / "s")
        self.assertIsNotNone(stands, why)
        self.assertEqual(stands["day"], _day(1), "запасная ветка взяла не последний день")
        self.assertIn("горизонт судьи не прочитан", stands["day_rule"])


class AnUnreadableJournalIsNotOneBadLine(unittest.TestCase):
    """строка 350: ветка `OSError` → `return [], 0` → `[], 1`.

    Первый раунд закрыл «файла нет». Осталась вторая дверь: файл ЕСТЬ и не
    читается. Обе обязаны давать НОЛЬ испорченных строк — «не прочитано» это
    не «одна строка испорчена» (инв. #17).
    """

    def test_a_journal_that_is_a_directory_is_zero_bad_lines(self):
        with TemporaryDirectory() as tmp:
            data = Path(tmp) / "data"
            (data / ste._history_filename(None)).mkdir(parents=True)
            self.assertEqual(H.all_rows_loader(data), ([], 0))


class TheRaisedListIsTruncatedToFour(unittest.TestCase):
    """строка 699: `raised[:4]` → `[:5]`.

    Причина `needs_more_than_a_dir` перечисляет упавших кандидатов, и перечень
    обрезан намеренно: отчёт читает человек. Обрезка проверяется ИСХОДОМ — на
    модуле с ПЯТЬЮ падающими кандидатами, в настоящем дочернем процессе.
    """

    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.pkg = self.root / "pkg"
        self.pkg.mkdir(parents=True)
        (self.pkg / "fake_five_raisers.py").write_text(
            "\n".join(f"def entry_{i}(data_dir):\n"
                      f"    raise ValueError('{i}')\n" for i in range(5)),
            encoding="utf-8")
        sys.path.insert(0, str(self.pkg))
        src = _material(self.root, n_days=3)
        self.stands, why = H.build_stands(src, self.root / "s", day=_day(2))
        self.assertIsNotNone(self.stands, why)

    def tearDown(self):
        sys.path.remove(str(self.pkg))
        sys.modules.pop("fake_five_raisers", None)
        self.tmp.cleanup()

    def test_five_failing_candidates_are_reported_as_four(self):
        row = H.whose_property("fake_five_raisers", self.stands["s_one"], self.pkg)
        self.assertEqual(row["whose"], H.WHOSE_NEEDS_MORE, row)
        self.assertEqual(len(row["raised"]), 5)
        named = [f"entry_{i}" for i in range(5) if f"entry_{i}:" in row["reason"]]
        self.assertEqual(len(named), 4, row["reason"])


class TheStandRootIsCreatedWithItsParents(unittest.TestCase):
    """строка 729: `tmp.mkdir(parents=True, …)` → `parents=False`.

    Первый раунд давал стенду каталог, чей родитель уже существовал, — и
    мутация проходила незаметно. `--stand-root` же указывают куда угодно.
    """

    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.src = _material(self.root, n_days=3)
        self._real = G16.reader_population
        G16.reader_population = lambda tree_root, **kw: (set(), {"population": 0})

    def tearDown(self):
        G16.reader_population = self._real
        self.tmp.cleanup()

    def test_a_stand_root_two_levels_deep_is_created_not_refused(self):
        deep = self.root / "нет" / "и" / "здесь"
        doc = H.measure(self.src, now=NOW, tree_root=self.root, stand_root=deep,
                        day=_day(2), sweep_entries=False)
        self.assertIn("stand", doc, doc.get("unmeasured_reason"))
        self.assertTrue(deep.exists())


class TheDefaultTreeRootIsTheRepositoryThisModuleLivesIn(unittest.TestCase):
    """строки 726/859/880: `Path(__file__).resolve().parents[2]` → `parents[3]`.

    Умолчание корня — тихий класс: с чужим корнем прибор честно отработает и
    честно доложит ответ о ДРУГОМ дереве. Проверяется на шве — чем именно
    прибор зовёт себя дальше, — потому что настоящий прогон корня занимает
    минуты, а ответ на вопрос «тот ли это корень» не требует их ни одной.
    """

    @staticmethod
    def _holds_this_module(root) -> bool:
        return (Path(root) / "spa_core" / "monitoring"
                / "heir_all_rows_price.py").exists()

    def test_measure_defaults_the_tree_root_to_this_repository(self):
        """строка 726."""
        seen = {}

        def population(tree_root, **kw):
            seen["tree"] = tree_root
            return set(), {"population": 0}

        with TemporaryDirectory() as tmp:
            src = _material(Path(tmp), n_days=3)
            real = G16.reader_population
            G16.reader_population = population
            try:
                H.measure(src, now=NOW, stand_root=Path(tmp) / "s",
                          day=_day(2), sweep_entries=False)
            finally:
                G16.reader_population = real
        self.assertTrue(self._holds_this_module(seen["tree"]), seen)

    def test_run_without_a_root_measures_this_repository(self):
        """строка 859."""
        seen = {}

        def recorder(data_dir, **kw):
            seen.update(kw, data_dir=data_dir)
            return {"status": H.STATUS_UNMEASURED, "unmeasured_reason": "шов"}

        real = H.measure
        H.measure = recorder
        try:
            H.run(now=NOW, write=False)
        finally:
            H.measure = real
        self.assertTrue(self._holds_this_module(seen["tree_root"]), seen)
        self.assertEqual(Path(seen["data_dir"]).name, "data")

    def test_run_measures_the_second_half_unless_told_otherwise(self):
        """строка 858: умолчание `sweep_entries: bool = True` у `run`."""
        seen = {}

        def recorder(data_dir, **kw):
            seen.update(kw)
            return {"status": H.STATUS_UNMEASURED, "unmeasured_reason": "шов"}

        real = H.measure
        H.measure = recorder
        try:
            H.run(now=NOW, write=False)
        finally:
            H.measure = real
        self.assertIs(seen["sweep_entries"], True)

    def test_main_without_a_data_dir_measures_this_repository(self):
        """строка 880."""
        seen = {}

        def recorder(data_dir, **kw):
            seen.update(kw, data_dir=data_dir)
            return {"status": H.STATUS_UNMEASURED, "unmeasured_reason": "шов"}

        real = H.measure
        H.measure = recorder
        try:
            buf = io.StringIO()
            with redirect_stdout(buf):
                H.main([])
        finally:
            H.measure = real
        self.assertTrue(self._holds_this_module(seen["tree_root"]), seen)


class TheHelpTextNamesTheInstrument(unittest.TestCase):
    """строка 871: `(__doc__ or "").splitlines()[0]` → `[1]`.

    `--help` — единственная дверь, за которой читатель узнаёт, ЧТО это за
    прибор. Вторая строка докстринга там пуста, и подмена превратила бы
    описание в пустоту молча.
    """

    def test_help_prints_the_first_line_of_the_module_docstring(self):
        buf = io.StringIO()
        with self.assertRaises(SystemExit):
            with redirect_stdout(buf):
                H.main(["--help"])
        first = (H.__doc__ or "").splitlines()[0].strip()
        self.assertTrue(first)
        self.assertIn(first.split("(")[0].strip(), buf.getvalue())


if __name__ == "__main__":
    unittest.main()
