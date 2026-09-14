"""Сторож прибора G17 — цена наследников (ADR-385).

Форма набора та же, что у соседей [ADR-384]/[ADR-383]: каждый тест —
положительный контроль, воспроизводящий настоящую поломку или настоящую форму
ответа, а не украшение. Главный из них — НУЛЕВОЙ КОНТРОЛЬ: подмена загрузчика
на загрузчик с ТЕМ ЖЕ поведением обязана дать всем ``unchanged``. Без него
«ответ изменился» доказывало бы лишь то, что мы что-то подменили.

Время в наборе инъектировано: ``measure(..., now=)``.
"""

# FROZEN-DATE-OK: injected-clock — часы прибора принимаются параметром `now`, и
# тест передаёт закреплённый `NOW` (см. MeasureRefusesLoudly); даты дней журнала
# суть ДАННЫЕ стенда (какой день с каким соседом-донором), а не отметка свежести,
# поэтому от сдвига календаря вердикт не зависит ни одной стороной.
# Пометка стоит КОММЕНТАРИЕМ, а не в докстринге, намеренно: сторож ищет её
# регуляркой `#\s*FROZEN-DATE-OK`, и пометка внутри докстринга — это молчаливый
# отказ, который читается как решение. Ровно на этом `test_act_day_recovery.py`
# краснеет на origin/main (карточка `inbox-hrapovik-literalnyh-dat-krasnyi-na-main`).

from __future__ import annotations

import json
import sys
import types
import unittest
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

from spa_core.monitoring import heir_all_rows_price as H
from spa_core.paper_trading import shadow_trigger_eval as ste

NOW = datetime(2026, 9, 14, 12, 0, 0, tzinfo=timezone.utc)

# Три дня, у каждого по одной строке: материал, на котором строятся стенды.
_DAYS = ("2026-09-05", "2026-09-06", "2026-09-07")


def _row(day: str, verdict: str = "HOLD", turnover: float = 1000.0) -> dict:
    return {
        "cycle_date": day,
        "decision_id": f"adr060-shadow-{day}",
        "generated_at": f"{day}T18:00:00.000000+00:00",
        "verdict": verdict,
        "turnover_usd": turnover,
    }


def _journal(data_dir: Path, rows) -> None:
    data_dir.mkdir(parents=True, exist_ok=True)
    (data_dir / H.HISTORY_FILENAME).write_text(
        "\n".join(json.dumps(r, sort_keys=True) for r in rows) + "\n",
        encoding="utf-8")


def _stand_material(root: Path):
    """Каталог-источник с журналом из трёх однострочных дней."""
    src = root / "live" / "data"
    _journal(src, [_row(d, turnover=1000.0 * (i + 1)) for i, d in enumerate(_DAYS)])
    return src


# ── поддельные наследники: каждый воплощает ОДИН исход ───────────────────────
def _install(name: str, entry):
    """Поставить в ``sys.modules`` модуль с точкой входа ``measure(data_dir)``."""
    mod = types.ModuleType(name)
    mod.measure = entry  # type: ignore[attr-defined]
    entry.__module__ = name
    sys.modules[name] = mod
    return mod


class HeirClassificationControls(unittest.TestCase):
    """Каждый исход воспроизведён наследником, у которого он ВЕРЕН заведомо."""

    def setUp(self):
        self.tmp = TemporaryDirectory()
        root = Path(self.tmp.name)
        src = _stand_material(root)
        stands, why = H.build_stands(src, root / "stands", day="2026-09-06")
        self.assertIsNotNone(stands, f"стенды не построены: {why}")
        self.stands = stands
        self.installed = []

    def tearDown(self):
        for name in self.installed:
            sys.modules.pop(name, None)
        self.tmp.cleanup()

    def _heir(self, name: str, entry):
        self.installed.append(name)
        _install(name, entry)
        return H.classify_heir(name, self.stands)

    def test_a_reader_that_sums_rows_is_called_double_counts(self):
        """СУММА по строкам — ровно тот двойной счёт, против которого правило."""
        def measure(data_dir, write=False):
            rows, _ = ste.load_history(Path(data_dir))
            return {"total": sum(r.get("turnover_usd", 0) for r in rows)}
        row = self._heir("spa_core.tests._fake_summing_heir", measure)
        self.assertEqual(row["outcome"], H.HEIR_DOUBLE, row)
        self.assertTrue(row["inflates_on_repeat"])

    def test_a_reader_asking_was_there_an_ACT_and_how_the_day_ended_recovers(self):
        """Единственная форма, которую починка и должна была бы дать.

        «Был ли за день ACT» и «чем день кончился» — два РАЗНЫХ вопроса, и
        вместе они нечувствительны к числу строк (повтор HOLD ничего не
        прибавляет), но чувствительны к стёртому решению. Поэтому ответ на дне
        из двух строк не совпадает НИ с одним однострочным: по ранней строке
        день кончился ACT, по поздней ACT не было вовсе.
        """
        def measure(data_dir, write=False):
            rows, _ = ste.load_history(Path(data_dir))
            day = [r for r in rows if str(r["cycle_date"]) == "2026-09-06"]
            return {"had_act": any(r.get("verdict") == "ACT" for r in day),
                    "final": day[-1].get("verdict") if day else None}
        row = self._heir("spa_core.tests._fake_act_aware_heir", measure)
        self.assertEqual(row["outcome"], H.HEIR_RECOVERS, row)
        self.assertFalse(row["inflates_on_repeat"])
        self.assertTrue(row["changed_on_true"])

    def test_a_reader_listing_the_days_rows_is_called_double_counts(self):
        """СПИСОК строк дня раздувается на повторе — и это верный вердикт.

        Контроль соседний с предыдущим и нужен именно парой к нему: обе формы
        «видят» стёртый ACT, но одна платит за это двойным счётом, а другая нет.
        Ровно это различение заказ и требовал не слить.
        """
        def measure(data_dir, write=False):
            rows, _ = ste.load_history(Path(data_dir))
            day = [r for r in rows if str(r["cycle_date"]) == "2026-09-06"]
            return {"verdicts": [r.get("verdict") for r in day]}
        row = self._heir("spa_core.tests._fake_list_heir", measure)
        self.assertEqual(row["outcome"], H.HEIR_DOUBLE, row)

    def test_an_honest_integrator_whose_answer_coincides_is_NOT_called_recovers(self):
        """МНОЖЕСТВО вердиктов сводит обе строки честно — и совпадает с ранней.

        Контроль, из-за которого класс переименован. Первая редакция звала его
        ``moved_the_collapse``, то есть УТВЕРЖДАЛА, что схлопывание переехало.
        Здесь оно не переехало никуда: читатель честно свёл обе строки, и свод
        совпал с ответом по одной ранней. Замер обязан назвать двусмысленность,
        а не выбрать прочтение за читателя.
        """
        def measure(data_dir, write=False):
            rows, _ = ste.load_history(Path(data_dir))
            return {"verdicts": sorted({str(r.get("verdict")) for r in rows})}
        row = self._heir("spa_core.tests._fake_set_heir", measure)
        self.assertEqual(row["outcome"], H.HEIR_FIRST_COINCIDES, row)
        self.assertIn("неразличимы", str(row["reason"]))

    def test_a_reader_that_keeps_only_the_first_row_lands_in_the_same_class(self):
        """И НАСТОЯЩЕЕ переехавшее схлопывание попадает туда же — честно.

        Пара с тестом выше и есть доказательство, что класс назван верно: два
        читателя с РАЗНОЙ природой дают один и тот же наблюдаемый ответ, и
        различить их этим замером нельзя.
        """
        def measure(data_dir, write=False):
            rows, _ = ste.load_history(Path(data_dir))
            by = {}
            for r in rows:
                by.setdefault(str(r["cycle_date"]), r)  # первая строка побеждает
            return {"days": [by[d] for d in sorted(by)]}
        row = self._heir("spa_core.tests._fake_first_heir", measure)
        self.assertEqual(row["outcome"], H.HEIR_FIRST_COINCIDES, row)

    def test_a_reader_that_ignores_the_journal_is_called_unmeasured_not_unchanged(self):
        """Не позвал загрузчик ⇒ «не измерено», а НЕ «правка ему ничего не стоит».

        Это и есть дефект, ради которого написан счётчик достижимости: ссылка
        могла уехать в замыкание, и такой наследник молча уехал бы в
        ``unchanged``, то есть в измеренный ноль.
        """
        def measure(data_dir, write=False):
            return {"constant": 1}
        row = self._heir("spa_core.tests._fake_deaf_heir", measure)
        self.assertEqual(row["outcome"], H.HEIR_UNMEASURED, row)
        self.assertEqual(row["loader_calls"], 0)
        self.assertIn("загрузчик не вызван", str(row["reason"]))

    def test_a_reader_whose_answer_does_not_move_is_called_unchanged(self):
        """Читает журнал, но ответ от строк дня не зависит."""
        def measure(data_dir, write=False):
            rows, _ = ste.load_history(Path(data_dir))
            return {"days": sorted({str(r["cycle_date"]) for r in rows})}
        row = self._heir("spa_core.tests._fake_daylist_heir", measure)
        self.assertEqual(row["outcome"], H.HEIR_UNCHANGED, row)
        self.assertGreater(row["loader_calls"], 0)

    def test_a_reader_that_crashes_is_unmeasured_with_the_exception_named(self):
        def measure(data_dir, write=False):
            raise RuntimeError("стенд не по мне")
        row = self._heir("spa_core.tests._fake_crashing_heir", measure)
        self.assertEqual(row["outcome"], H.HEIR_UNMEASURED, row)
        self.assertIn("RuntimeError", str(row["reason"]))

    def test_a_reader_answering_differently_on_one_stand_is_unmeasured(self):
        """Невоспроизводимый ответ — «не измерено», а не «изменился»."""
        state = {"n": 0}

        def measure(data_dir, write=False):
            rows, _ = ste.load_history(Path(data_dir))
            state["n"] += 1
            return {"n": state["n"], "rows": len(rows)}
        row = self._heir("spa_core.tests._fake_jittery_heir", measure)
        self.assertEqual(row["outcome"], H.HEIR_UNMEASURED, row)
        self.assertIn("не воспроизводится", str(row["reason"]))

    def test_a_heir_that_does_not_collapse_at_all_is_refused(self):
        """Встроенный контроль стенда: не схлопывает — мерить нечего.

        Наследник ЭТОГО населения день схлопывает, поэтому БЕЗ подмены ответ на
        дне из двух строк обязан быть неотличим от ответа по одной последней.
        Читатель, который и без подмены видит обе строки, в население не входит,
        и вынести ему вердикт значило бы верно ответить не на тот вопрос.
        """
        def measure(data_dir, write=False):
            path = Path(data_dir) / H.HISTORY_FILENAME     # журнал НАПРЯМУЮ…
            n = len(path.read_text(encoding="utf-8").splitlines())
            ste.load_history(Path(data_dir))               # …но загрузчик позван
            return {"lines": n}
        row = self._heir("spa_core.tests._fake_noncollapsing_heir", measure)
        self.assertEqual(row["outcome"], H.HEIR_UNMEASURED, row)
        self.assertIn("день не схлопывает", str(row["reason"]))

    def test_the_instrument_refuses_to_measure_itself(self):
        row = H.classify_heir(H.__name__, self.stands)
        self.assertEqual(row["outcome"], H.HEIR_UNMEASURED)
        self.assertIn("сам прибор", str(row["reason"]))


class TheNullControl(unittest.TestCase):
    """Подмена на ТО ЖЕ поведение обязана дать ``unchanged`` КАЖДОМУ.

    Без этого контроля «ответ изменился» доказывало бы лишь то, что мы что-то
    подменили, а не то, ЧТО именно подменили: любой наследник, чей ответ хоть
    как-то зависит от разбора, покраснел бы одинаково при любой подмене.
    """

    def setUp(self):
        self.tmp = TemporaryDirectory()
        root = Path(self.tmp.name)
        src = _stand_material(root)
        self.stands, _ = H.build_stands(src, root / "stands", day="2026-09-06")
        self.installed = []

    def tearDown(self):
        for name in self.installed:
            sys.modules.pop(name, None)
        self.tmp.cleanup()

    @staticmethod
    def _same_behaviour(data_dir, book_id=None):
        """Свой разбор, ТО ЖЕ правило замены — поведение оригинала."""
        rows, bad = H.all_rows_loader(data_dir, book_id)
        by = {}
        for r in rows:
            by[str(r["cycle_date"])] = r
        return [by[d] for d in sorted(by)], bad

    def test_every_shape_of_heir_is_unchanged_under_an_identical_patch(self):
        def summing(data_dir, write=False):
            rows, _ = ste.load_history(Path(data_dir))
            return {"total": sum(r.get("turnover_usd", 0) for r in rows)}

        def verdicts(data_dir, write=False):
            rows, _ = ste.load_history(Path(data_dir))
            return {"verdicts": sorted({r.get("verdict") for r in rows})}

        for name, entry in (("spa_core.tests._null_sum", summing),
                            ("spa_core.tests._null_set", verdicts)):
            self.installed.append(name)
            _install(name, entry)
            row = H.classify_heir(name, self.stands,
                                  patched_loader=self._same_behaviour)
            self.assertEqual(row["outcome"], H.HEIR_UNCHANGED,
                             f"{name}: нулевой контроль обязан дать unchanged, "
                             f"получено {row}")

    def test_the_same_heirs_do_move_under_the_real_patch(self):
        """Обратная сторона: тот же наследник под НАСТОЯЩЕЙ подменой едет.

        Пара тестов и составляет контроль в обе стороны: без этого «нулевой
        контроль зелёный» могло бы означать, что подмена не доходит вообще.
        """
        def summing(data_dir, write=False):
            rows, _ = ste.load_history(Path(data_dir))
            return {"total": sum(r.get("turnover_usd", 0) for r in rows)}
        name = "spa_core.tests._null_sum_moves"
        self.installed.append(name)
        _install(name, summing)
        row = H.classify_heir(name, self.stands)
        self.assertEqual(row["outcome"], H.HEIR_DOUBLE, row)


class LoaderPatchReachesAliases(unittest.TestCase):
    """Подмена по ТОЖДЕСТВУ, а не по имени: чужой алиас обязан быть достигнут."""

    def test_a_module_holding_its_own_reference_is_rebound(self):
        name = "spa_core.tests._fake_alias_holder"
        mod = types.ModuleType(name)
        mod.borrowed = ste.load_history  # type: ignore[attr-defined]
        sys.modules[name] = mod
        try:
            original = ste.load_history          # ДО подмены: restore вернёт ЕГО
            sentinel = object()
            sites = H.rebind_everywhere(original, sentinel)
            try:
                self.assertIs(mod.borrowed, sentinel,
                              "подмена не достала чужой алиас — по имени искать нельзя")
                self.assertGreaterEqual(len(sites), 2)
            finally:
                H.restore(sites, original)
            self.assertIs(mod.borrowed, original)
            self.assertIs(ste.load_history, original)
        finally:
            sys.modules.pop(name, None)

    def test_restore_puts_the_original_back_everywhere(self):
        original = ste.load_history
        sites = H.rebind_everywhere(original, H.all_rows_loader)
        H.restore(sites, original)
        self.assertIs(ste.load_history, original)


class TheAllRowsLoaderItself(unittest.TestCase):
    """Обученный загрузчик отличается от исходного РОВНО схлопыванием."""

    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.data = Path(self.tmp.name) / "data"

    def tearDown(self):
        self.tmp.cleanup()

    def test_on_a_journal_without_repeats_both_loaders_agree(self):
        _journal(self.data, [_row(d) for d in _DAYS])
        mine, bad_a = H.all_rows_loader(self.data)
        theirs, bad_b = ste.load_history(self.data)
        self.assertEqual(mine, theirs)
        self.assertEqual(bad_a, bad_b)

    def test_on_a_repeated_day_it_keeps_both_rows_in_file_order(self):
        early, late = _row("2026-09-06", "ACT"), _row("2026-09-06", "HOLD")
        _journal(self.data, [_row("2026-09-05"), early, late])
        rows, _ = H.all_rows_loader(self.data)
        self.assertEqual([r["verdict"] for r in rows], ["HOLD", "ACT", "HOLD"])
        collapsed, _ = ste.load_history(self.data)
        self.assertEqual(len(collapsed), 2)

    def test_an_unparseable_line_is_counted_not_fatal(self):
        _journal(self.data, [_row("2026-09-05")])
        with (self.data / H.HISTORY_FILENAME).open("a", encoding="utf-8") as fh:
            fh.write("{не json\n")
        rows, bad = H.all_rows_loader(self.data)
        self.assertEqual(len(rows), 1)
        self.assertEqual(bad, 1)

    def test_a_missing_file_is_an_empty_history_not_a_crash(self):
        self.data.mkdir(parents=True)
        self.assertEqual(H.all_rows_loader(self.data), ([], 0))


class StandConstruction(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.src = _stand_material(self.root)

    def tearDown(self):
        self.tmp.cleanup()

    def test_the_duplicate_stands_carry_the_very_same_bytes(self):
        """Контроль обязан быть повтором БЕЗ новых сведений, иначе он не контроль."""
        stands, _ = H.build_stands(self.src, self.root / "s", day="2026-09-06")
        def day_rows(stand, day="2026-09-06"):
            path = Path(stand) / "data" / H.HISTORY_FILENAME
            return [ln for ln in path.read_text(encoding="utf-8").splitlines()
                    if json.loads(ln)["cycle_date"] == day]
        one = day_rows(stands["s_one"])
        self.assertEqual(day_rows(stands["s_dup2"]), one * 2)
        self.assertEqual(day_rows(stands["s_dup3"]), one * 3)

    def test_the_true_stand_carries_an_ACT_row_that_is_real_material(self):
        stands, _ = H.build_stands(self.src, self.root / "s", day="2026-09-06")
        path = Path(stands["s_true"]) / "data" / H.HISTORY_FILENAME
        rows = [json.loads(ln) for ln in path.read_text(encoding="utf-8").splitlines()]
        day = [r for r in rows if r["cycle_date"] == "2026-09-06"]
        self.assertEqual([r["verdict"] for r in day], ["ACT", "HOLD"])
        # донор — настоящая строка соседнего дня, а не выдумка: оборот её
        self.assertEqual(day[0]["turnover_usd"], 1000.0)

    def test_other_days_are_untouched_on_every_stand(self):
        stands, _ = H.build_stands(self.src, self.root / "s", day="2026-09-06")
        for key in ("s_one", "s_first", "s_true", "s_dup2", "s_dup3"):
            path = Path(stands[key]) / "data" / H.HISTORY_FILENAME
            rows = [json.loads(ln) for ln in path.read_text(encoding="utf-8").splitlines()]
            others = [r["cycle_date"] for r in rows if r["cycle_date"] != "2026-09-06"]
            self.assertEqual(others, ["2026-09-05", "2026-09-07"], key)

    def test_a_named_day_that_is_absent_is_refused_with_a_reason(self):
        stands, why = H.build_stands(self.src, self.root / "s", day="2026-01-01")
        self.assertIsNone(stands)
        self.assertIn("2026-01-01", why)

    def test_a_journal_of_one_row_refuses_loudly(self):
        src = self.root / "thin" / "data"
        _journal(src, [_row("2026-09-05")])
        stands, why = H.build_stands(src, self.root / "s2")
        self.assertIsNone(stands)
        self.assertIn("меньше двух строк", why)

    def test_a_missing_journal_is_named_not_treated_as_empty(self):
        empty = self.root / "empty" / "data"
        empty.mkdir(parents=True)
        stands, why = H.build_stands(empty, self.root / "s3")
        self.assertIsNone(stands)
        self.assertIn(H.HISTORY_FILENAME, why)

    def test_the_day_rule_takes_the_horizon_from_the_judge_itself(self):
        """Правило дня — у судьи, а не своей константой."""
        self.assertEqual(H._judge_horizon(), int(ste.DEFAULT_HORIZON_DAYS))

    def test_the_live_data_dir_is_never_opened_for_writing(self):
        before = {p.name: p.stat().st_mtime_ns for p in self.src.iterdir()}
        H.build_stands(self.src, self.root / "s4", day="2026-09-06")
        after = {p.name: p.stat().st_mtime_ns for p in self.src.iterdir()}
        self.assertEqual(before, after)


class WhosePropertyControls(unittest.TestCase):
    """Вторая половина заказа: свойство МОДУЛЯ против свойства ПРИБОРА."""

    def test_a_module_with_no_dir_driven_function_has_no_candidates(self):
        mod = types.ModuleType("spa_core.tests._fake_no_entry")

        def helper(a, b):
            return a + b
        helper.__module__ = mod.__name__
        mod.helper = helper  # type: ignore[attr-defined]
        self.assertEqual(H.dir_driven_candidates(mod), [])

    def test_a_function_under_a_name_the_neighbour_does_not_know_is_a_candidate(self):
        """`collect(data_dir)` — исправная точка входа; сосед её не знает."""
        mod = types.ModuleType("spa_core.tests._fake_wide_entry")

        def collect(data_dir, write=False):
            return {}
        collect.__module__ = mod.__name__
        mod.collect = collect  # type: ignore[attr-defined]
        self.assertEqual(H.dir_driven_candidates(mod), ["collect"])
        self.assertNotIn("collect", ("measure", "build", "evaluate_window", "run"))

    def test_a_function_needing_a_second_argument_is_not_a_candidate(self):
        mod = types.ModuleType("spa_core.tests._fake_needs_two")

        def measure(data_dir, cutoff):
            return {}
        measure.__module__ = mod.__name__
        mod.measure = measure  # type: ignore[attr-defined]
        self.assertEqual(H.dir_driven_candidates(mod), [])

    def test_a_private_or_imported_function_is_not_a_candidate(self):
        mod = types.ModuleType("spa_core.tests._fake_private")

        def _measure(data_dir):
            return {}
        _measure.__module__ = mod.__name__
        mod._measure = _measure  # type: ignore[attr-defined]
        mod.load_history = ste.load_history  # чужая, импортированная
        self.assertEqual(H.dir_driven_candidates(mod), [])


class VerdictAndReport(unittest.TestCase):
    def test_double_counting_is_critical(self):
        doc = {"heirs_population": 5, "heir_outcomes": {H.HEIR_DOUBLE: 2,
                                                        H.HEIR_UNCHANGED: 3}}
        self.assertEqual(H._verdict(doc)["status"], H.STATUS_CRITICAL)

    def test_recovery_without_inflation_is_a_warning(self):
        doc = {"heirs_population": 5, "heir_outcomes": {H.HEIR_RECOVERS: 1,
                                                        H.HEIR_UNCHANGED: 4}}
        self.assertEqual(H._verdict(doc)["status"], H.STATUS_WARNING)

    def test_nobody_moving_is_ok(self):
        doc = {"heirs_population": 5, "heir_outcomes": {H.HEIR_UNCHANGED: 5}}
        self.assertEqual(H._verdict(doc)["status"], H.STATUS_OK)

    def test_an_absent_count_is_unmeasured_not_zero(self):
        """Инв. #17: отсутствие наблюдения — отдельное значение, а не ноль."""
        self.assertEqual(H._verdict({"heirs_population": 5})["status"],
                         H.STATUS_UNMEASURED)
        self.assertEqual(H._verdict({"heir_outcomes": {}})["status"],
                         H.STATUS_UNMEASURED)

    def test_an_empty_population_is_unmeasured_not_a_calm_ok(self):
        doc = {"heirs_population": 0, "heir_outcomes": {}}
        self.assertEqual(H._verdict(doc)["status"], H.STATUS_UNMEASURED)

    def test_a_junk_count_is_unmeasured_not_a_number(self):
        doc = {"heirs_population": "много", "heir_outcomes": {H.HEIR_DOUBLE: 1}}
        self.assertEqual(H._verdict(doc)["status"], H.STATUS_UNMEASURED)

    def test_the_report_names_the_unmeasured_second_half_instead_of_silence(self):
        doc = {"status": H.STATUS_OK, "stand": {"day": "d", "donor_day": "c",
                                                "day_rule": "r"},
               "heirs_population": 1, "heir_outcomes": {H.HEIR_UNCHANGED: 1},
               "heirs": [], "whose_outcomes": None,
               "whose_unmeasured_reason": "sweep_entries=False"}
        text = "\n".join(H.format_report(doc))
        self.assertIn("[ЧЬЁ СВОЙСТВО] НЕ ИЗМЕРЕНО", text)
        self.assertIn("sweep_entries=False", text)

    def test_the_report_states_what_the_measure_does_not_prove(self):
        doc = {"status": H.STATUS_OK, "stand": {}, "heirs_population": 1,
               "heir_outcomes": {H.HEIR_UNCHANGED: 1}, "heirs": [],
               "whose_outcomes": {}, "what_it_does_not_prove":
                   list(H.WHAT_IT_DOES_NOT_PROVE), "advisory": ["x"]}
        text = "\n".join(H.format_report(doc))
        self.assertIn("[НЕ ДОКАЗЫВАЕТ]", text)
        self.assertIn("НЕ доказывает, что получившееся число", text)

    def test_an_unmeasured_doc_prints_the_reason_and_nothing_else(self):
        lines = H.format_report({"status": H.STATUS_UNMEASURED,
                                 "unmeasured_reason": "журнала нет"})
        self.assertEqual(len(lines), 1)
        self.assertIn("журнала нет", lines[0])

    def test_main_returns_a_distinct_code_for_each_outcome(self):
        """Коды возврата проверяются ВЫЗОВОМ, а не своей таблицей рядом."""
        seen = {}
        for status, expected in ((H.STATUS_OK, 0), (H.STATUS_WARNING, 0),
                                 (H.STATUS_CRITICAL, 1), (H.STATUS_UNMEASURED, 2)):
            with TemporaryDirectory() as tmp:
                data = Path(tmp) / "data"
                data.mkdir(parents=True)
                real = H.measure
                H.measure = lambda *a, **k: {"status": status,
                                             "unmeasured_reason": "стенд"}
                try:
                    seen[status] = H.main(["--data-dir", str(data), "--no-entries"])
                finally:
                    H.measure = real
            self.assertEqual(seen[status], expected, status)


class MeasureRefusesLoudly(unittest.TestCase):
    def test_a_directory_without_a_journal_is_unmeasured_with_a_reason(self):
        with TemporaryDirectory() as tmp:
            data = Path(tmp) / "data"
            data.mkdir(parents=True)
            doc = H.measure(data, now=NOW, tree_root=Path(tmp),
                            stand_root=Path(tmp) / "s", sweep_entries=False)
        self.assertEqual(doc["status"], H.STATUS_UNMEASURED)
        self.assertIn("стенды не построены", doc["unmeasured_reason"])
        self.assertEqual(doc["generated_at"], NOW.isoformat())

    def test_a_reentrant_call_refuses_instead_of_sweeping_inside_a_sweep(self):
        H._SWEEPING = True
        try:
            doc = H.measure(Path("/nonexistent"), now=NOW)
        finally:
            H._SWEEPING = False
        self.assertEqual(doc["status"], H.STATUS_UNMEASURED)
        self.assertIn("сам прибор", doc["unmeasured_reason"])

    def test_the_sweeping_flag_is_lowered_even_when_the_sweep_raises(self):
        with TemporaryDirectory() as tmp:
            src = _stand_material(Path(tmp))
            import spa_core.monitoring.run_identity_key_price as g16
            real = g16.reader_population
            g16.reader_population = lambda *a, **k: (_ for _ in ()).throw(
                RuntimeError("перепись упала"))
            try:
                with self.assertRaises(RuntimeError):
                    H.measure(src, now=NOW, tree_root=Path(tmp),
                              stand_root=Path(tmp) / "s", sweep_entries=False)
            finally:
                g16.reader_population = real
        self.assertFalse(H._SWEEPING, "флаг остался поднятым — следующий замер немой")


class WhosePropertyByOutcome(unittest.TestCase):
    """Вторая половина заказа — по ИСХОДУ, на НАСТОЯЩИХ файлах модулей.

    Поддельный модуль в ``sys.modules`` тут не годится: вердикт выносит
    отдельный процесс, и импортировать он умеет только то, что лежит на диске.
    Проверять in-memory подделкой значило бы проверять не тот путь.
    """

    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.tree = Path(self.tmp.name) / "tree"
        self.tree.mkdir(parents=True)
        root = Path(self.tmp.name)
        src = _stand_material(root)
        stands, _ = H.build_stands(src, root / "stands", day="2026-09-06")
        self.stand = Path(stands["s_one"])
        self.installed = []
        # Кандидаты перечисляются в РОДИТЕЛЬСКОМ процессе, вызываются — в
        # дочернем; дереву быть на пути надо обоим.
        sys.path.insert(0, str(self.tree))

    def tearDown(self):
        for name in self.installed:
            sys.modules.pop(name, None)
        sys.path.remove(str(self.tree))
        self.tmp.cleanup()

    def _module(self, name: str, body: str) -> str:
        (self.tree / f"{name}.py").write_text(body, encoding="utf-8")
        self.installed.append(name)
        return name

    def test_an_entry_under_an_unknown_name_that_reads_the_journal_is_the_instruments(self):
        """`collect(data_dir)` доходит до журнала — сосед просто не знал имени."""
        name = self._module("_g17_real_entry", (
            "from pathlib import Path\n"
            "from spa_core.paper_trading import shadow_trigger_eval as ste\n"
            "def collect(data_dir, write=False):\n"
            "    rows, _ = ste.load_history(Path(data_dir))\n"
            "    return {'n': len(rows)}\n"))
        row = H.whose_property(name, self.stand, self.tree)
        self.assertEqual(row["whose"], H.WHOSE_INSTRUMENT, row)
        self.assertEqual(row["entry"], "collect")
        self.assertGreater(row["loader_calls"], 0)

    def test_a_helper_that_runs_but_never_reads_the_journal_is_not_the_instruments(self):
        """Контроль, из-за которого счёт «свойство прибора» упал с 15 до 1."""
        name = self._module("_g17_helper_only", (
            "from pathlib import Path\n"
            "def resolve_root(data_dir, write=False):\n"
            "    return str(Path(data_dir).parent)\n"))
        row = H.whose_property(name, self.stand, self.tree)
        self.assertEqual(row["whose"], H.WHOSE_HELPER, row)
        self.assertEqual(row["loader_calls"], 0)

    def test_a_module_without_any_dir_driven_function_is_its_own_property(self):
        name = self._module("_g17_no_entry", "def add(a, b):\n    return a + b\n")
        row = H.whose_property(name, self.stand, self.tree)
        self.assertEqual(row["whose"], H.WHOSE_MODULE, row)
        self.assertEqual(row["candidates"], [])

    def test_a_candidate_that_raises_is_named_not_silently_dropped(self):
        name = self._module("_g17_raises", (
            "def measure(data_dir, write=False):\n"
            "    raise ValueError('каталога мало')\n"))
        row = H.whose_property(name, self.stand, self.tree)
        self.assertEqual(row["whose"], H.WHOSE_NEEDS_MORE, row)
        self.assertIn("ValueError", str(row["reason"]))

    def test_a_module_that_cannot_be_imported_is_unmeasured(self):
        row = H.whose_property("_g17_absent_module", self.stand, self.tree)
        self.assertEqual(row["whose"], H.WHOSE_UNMEASURED, row)
        self.assertIn("импорт", str(row["reason"]))


if __name__ == "__main__":
    unittest.main()
