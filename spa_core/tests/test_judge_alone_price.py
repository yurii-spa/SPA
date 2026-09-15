"""Сторожа прибора G18 — цена починки СУДЬИ отдельно от остальных (ADR-386).

Каждый тест — положительный контроль: он краснеет на конкретной поломке, которую
прибор обязан ловить, а не на «что-то поменялось». Поломки взяты не из головы:
это дефекты, уже случавшиеся в этом ряду замеров (ADR-383…385) — перепись не того
населения, нулевой контроль-украшение, «не измерено», выданное за спокойный ноль,
и свёртка, которая «работает» оттого, что стенд построен в её пользу.
"""
# FROZEN-DATE-OK: injected-clock — все даты фикстур происходят от якоря NOW,
# который передаётся в measure(now=)/run(now=); стенных часов тест не спрашивает.
# Пометка стои́т КОММЕНТАРИЕМ, а не в докстринге: сторож ищет её в комментарии
# (карточка inbox-hrapovik-literalnyh-dat-krasnyi-na-main, замер цикла #603).
from __future__ import annotations

import json
import shutil
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from spa_core.monitoring import judge_alone_price as J

NOW = datetime(2026, 9, 15, 6, 0, 0, tzinfo=timezone.utc)


def _day(n: int) -> str:
    """Дата, происходящая ОТ ЯКОРЯ: стенных часов фикстура не спрашивает."""
    return (NOW - timedelta(days=n)).date().isoformat()


def _row(day: str, *, verdict: str = "HOLD", cur=None, tgt=None,
         turnover: float = 20_000.0, cost: float = 40.0,
         apy=None, reasons=None) -> dict:
    return {
        "cycle_date": day,
        "decision_id": f"adr060-shadow-{day}",
        "generated_at": f"{day}T23:31:36.000000+00:00",
        "verdict": verdict,
        "capital_usd": 100_000.0,
        "turnover_usd": turnover,
        "cost_usd": cost,
        "current_positions": cur if cur is not None else {"aave_v3": 60_000.0,
                                                          "maple": 40_000.0},
        "target_positions": tgt if tgt is not None else {"aave_v3": 40_000.0,
                                                         "maple": 60_000.0},
        "apy_evidenced_pct": apy if apy is not None else {"aave_v3": 3.0,
                                                          "maple": 9.0},
        "reasons": reasons if reasons is not None else ["gain_below_band:0.1pp<0.75pp"],
    }


def _journal(days: int = 12) -> list:
    return [_row(_day(days - i)) for i in range(days)]


def _data_dir(rows, root: Path) -> Path:
    data = root / "data"
    data.mkdir(parents=True, exist_ok=True)
    (data / J.HISTORY_FILENAME).write_text(
        "\n".join(json.dumps(r, sort_keys=True) for r in rows) + "\n", encoding="utf-8")
    return data


class FoldDayTest(unittest.TestCase):
    """Свёртка дня: что каждая форма ВИДИТ и чего не видит."""

    def setUp(self):
        self.early = _row(_day(5), verdict="ACT", turnover=30_000.0, cost=90.0)
        self.early["generated_at"] = f"{_day(5)}T06:00:11.000000+00:00"
        self.late = _row(_day(5), verdict="HOLD", turnover=11_111.0, cost=11.0)
        self.other = _row(_day(4))

    def test_any_act_takes_verdict_from_early_and_rest_from_last_row(self):
        got = J.fold_day([self.early, self.late, self.other], J.FORM_ANY_ACT)
        day = next(r for r in got if r["cycle_date"] == _day(5))
        self.assertEqual(day["verdict"], "ACT", "вердикт обязан прийти из РАННЕЙ строки")
        self.assertEqual(day["turnover_usd"], 11_111.0,
                         "всё остальное обязано прийти из ПОСЛЕДНЕЙ строки")

    def test_first_act_takes_the_early_row_whole(self):
        got = J.fold_day([self.early, self.late, self.other], J.FORM_FIRST_ACT)
        day = next(r for r in got if r["cycle_date"] == _day(5))
        self.assertEqual(day["verdict"], "ACT")
        self.assertEqual(day["turnover_usd"], 30_000.0,
                         "предложение обязано быть тем, которое было ПРИНЯТО")

    def test_null_control_form_is_blind_to_the_early_act(self):
        got = J.fold_day([self.early, self.late], J.FORM_NULL)
        self.assertEqual(got[0]["verdict"], "HOLD",
                         "нулевой контроль обязан остаться сегодняшним поведением")

    def test_every_form_is_idempotent_on_a_byte_identical_repeat(self):
        for form in J.FORMS:
            one = J.fold_day([self.late, self.other], form)
            two = J.fold_day([self.late, self.late, self.other], form)
            three = J.fold_day([self.late] * 3 + [self.other], form)
            self.assertEqual(one, two, f"{form}: повтор ×2 изменил свёртку")
            self.assertEqual(one, three, f"{form}: повтор ×3 изменил свёртку")

    def test_day_without_an_act_keeps_the_last_row_in_every_form(self):
        for form in J.FORMS:
            got = J.fold_day([self.late, self.other], form)
            self.assertEqual(next(r for r in got if r["cycle_date"] == _day(5)),
                             self.late, f"{form}: день без ACT свёрнут не в последнюю строку")

    def test_unknown_form_refuses_loudly(self):
        with self.assertRaises(ValueError):
            J.fold_day([self.late], "какая-то-третья-форма")


class JudgeValuesTest(unittest.TestCase):
    """Население величин берётся у ОТЧЁТА, а не выбирается прибором."""

    DOC = {
        "generated_at": "2026-09-15T06:00:00+00:00",
        "hit_rate": 0.9,
        "counts": {"act": 1, "scored": 16},
        "criteria": [{"criterion": "hit_rate", "actual": 0.9, "status": "PASS"},
                     {"criterion": "net_bps_if_followed", "actual": -8.4,
                      "status": "FAIL"}],
        "per_verdict": [{"cycle_date": "x"}, {"cycle_date": "y"}],
    }

    def test_clock_leaf_is_not_a_value(self):
        self.assertNotIn("generated_at", J.judge_values(self.DOC))

    def test_per_verdict_enters_only_as_its_length(self):
        vals = J.judge_values(self.DOC)
        self.assertEqual(vals["per_verdict.__len__"], 2)
        self.assertFalse([k for k in vals if k.startswith("per_verdict[")],
                         "подённый журнал не имеет права раздувать население величин")

    def test_criteria_are_addressed_by_name_not_by_index(self):
        """Порядок в списке — не имя: перестановка не имеет права переименовать величину."""
        flipped = dict(self.DOC)
        flipped["criteria"] = list(reversed(self.DOC["criteria"]))
        self.assertEqual(set(J.judge_values(self.DOC)), set(J.judge_values(flipped)))
        self.assertEqual(J.judge_values(flipped)["criteria[hit_rate].actual"], 0.9)

    def test_nested_scalars_are_reached(self):
        self.assertEqual(J.judge_values(self.DOC)["counts.scored"], 16)


class ClassifyValuesTest(unittest.TestCase):
    """Три исхода величине, и «нет сигнала» НЕ выдаётся за «нечувствительна»."""

    def test_value_that_moves_on_a_repeat_is_inflating(self):
        answers = {"f@1": {"n": 16}, "f@2": {"n": 17}, "f@3": {"n": 18}}
        row = J.classify_values(answers, ["f"])[0]
        self.assertEqual(row["outcome"], J.VALUE_INFLATES)
        self.assertEqual(row["inflates_in"], ["f"])

    def test_value_identical_everywhere_is_no_signal_not_repeat_safe(self):
        """Ровно тот дефект, ради которого инвариант #17 написан."""
        answers = {"a@1": {"n": 0}, "a@2": {"n": 0}, "a@3": {"n": 0},
                   "b@1": {"n": 0}, "b@2": {"n": 0}, "b@3": {"n": 0}}
        row = J.classify_values(answers, ["a", "b"])[0]
        self.assertEqual(row["outcome"], J.VALUE_NO_SIGNAL)
        self.assertIn("сигнал", row["reason"])

    def test_value_that_differs_between_families_but_not_on_repeat_is_repeat_safe(self):
        answers = {"a@1": {"n": 1}, "a@2": {"n": 1}, "a@3": {"n": 1},
                   "b@1": {"n": 2}, "b@2": {"n": 2}, "b@3": {"n": 2}}
        row = J.classify_values(answers, ["a", "b"])[0]
        self.assertEqual(row["outcome"], J.VALUE_REPEAT_SAFE)

    def test_a_value_moving_in_one_family_only_is_still_inflating(self):
        answers = {"a@1": {"n": 1}, "a@2": {"n": 1},
                   "b@1": {"n": 5}, "b@2": {"n": 6}}
        row = J.classify_values(answers, ["a", "b"])[0]
        self.assertEqual(row["outcome"], J.VALUE_INFLATES)
        self.assertEqual(row["inflates_in"], ["b"])


class CountingLoaderTest(unittest.TestCase):
    """Достижимость подмены СЧИТАЕТСЯ, а не предполагается."""

    def test_loader_counts_its_calls(self):
        loader = J._CountingLoader(None)
        with tempfile.TemporaryDirectory() as tmp:
            data = _data_dir(_journal(3), Path(tmp))
            rows, bad = loader(data)
        self.assertEqual(loader.calls, 1)
        self.assertEqual(bad, 0)
        self.assertEqual(len(rows), 3)

    def test_all_rows_form_keeps_both_rows_of_a_day(self):
        loader = J._CountingLoader(None)
        with tempfile.TemporaryDirectory() as tmp:
            rows = _journal(3)
            twin = J.twin_act(rows[0], rows[1]["cycle_date"])
            data = _data_dir([rows[0], twin, rows[1], rows[2]], Path(tmp))
            got, _ = loader(data)
        self.assertEqual(len(got), 4, "загрузчик обязан отдать ВСЕ строки дня")

    def test_ask_judge_reports_unmeasured_when_the_patched_loader_is_never_called(self):
        """Подмена могла не дотянуться — это НЕ «ничего не изменилось»."""
        class _Stub:
            load_history = staticmethod(lambda *a, **k: ([], 0))

            @staticmethod
            def evaluate_window(_data_dir, write=True):
                return {"hit_rate": 1.0}

        saved = sys.modules.get(J.JUDGE_MODULE)
        sys.modules[J.JUDGE_MODULE] = _Stub
        try:
            doc, why, calls = J._ask_judge(Path("/nonexistent"), None, patch=True)
        finally:
            if saved is None:
                del sys.modules[J.JUDGE_MODULE]
            else:
                sys.modules[J.JUDGE_MODULE] = saved
        self.assertIsNone(doc)
        self.assertEqual(calls, 0)
        self.assertIn("не вызван", why)

    def test_ask_judge_restores_the_loader_after_the_call(self):
        from spa_core.paper_trading import shadow_trigger_eval as ste
        before = ste.load_history
        with tempfile.TemporaryDirectory() as tmp:
            J._ask_judge(_data_dir(_journal(4), Path(tmp)), None, patch=True)
        self.assertIs(ste.load_history, before, "подмена обязана быть снята")


class DaysWithSecondRowTest(unittest.TestCase):
    def test_todays_shape_one_row_a_day_yields_nothing(self):
        self.assertEqual(J.days_with_second_row(_journal(5)), [])

    def test_a_duplicated_day_is_named(self):
        rows = _journal(5)
        self.assertEqual(J.days_with_second_row(rows + [rows[2]]),
                         [rows[2]["cycle_date"]])


class AttributeReadersTest(unittest.TestCase):
    """Перепись читателей — пять населений; «.load_history» само по себе НЕ улика.

    Положительный контроль на замер первой редакции: она дала 56 «читателей»
    судьи, потому что считала ЛЮБОЕ обращение с таким именем атрибута.
    """

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="g18tree_"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        (self.tmp / "spa_core/paper_trading").mkdir(parents=True)
        (self.tmp / "spa_core/paper_trading/shadow_trigger_eval.py").write_text(
            "def load_history(d, book_id=None):\n    return [], 0\n", encoding="utf-8")
        self.pkg = self.tmp / "pkg"
        self.pkg.mkdir()

    def _write(self, name: str, text: str) -> None:
        (self.pkg / name).write_text(text, encoding="utf-8")

    def test_five_populations_are_kept_apart(self):
        self._write("direct.py",
                    "from spa_core.paper_trading import shadow_trigger_eval as ste\n"
                    "def f(d):\n    return ste.load_history(d)\n")
        self._write("indirect.py",
                    "from pkg import direct as _dep\n"
                    "def f(d):\n    return _dep.ste.load_history(d)\n")
        self._write("own_copy.py",
                    "from spa_core.paper_trading.shadow_trigger_eval import load_history\n"
                    "def f(d):\n    return load_history(d)\n")
        self._write("own_method.py",
                    "class E:\n    def load_history(self):\n        return []\n"
                    "    def go(self):\n        return self.load_history()\n")
        self._write("stranger.py",
                    "def f(engine):\n    return engine.load_history()\n")
        got = J.attribute_readers(self.tmp)
        self.assertEqual(got["via_judge_module"], ["pkg/direct.py"])
        self.assertEqual(got["via_judge_module_indirect"], ["pkg/indirect.py"])
        self.assertEqual(got["own_copy_of_reference"], ["pkg/own_copy.py"])
        self.assertEqual(got["own_method"], ["pkg/own_method.py"])
        self.assertEqual(got["unresolved"], ["pkg/stranger.py"])

    def test_a_strangers_method_is_not_counted_as_a_reader(self):
        self._write("stranger.py", "def f(engine):\n    return engine.load_history()\n")
        got = J.attribute_readers(self.tmp)
        self.assertEqual(got["via_judge_module_count"], 0,
                         "чужое обращение с тем же именем атрибута — не читатель судьи")
        self.assertEqual(got["unresolved_count"], 1)

    def test_unparsed_file_is_a_third_outcome_not_a_silent_skip(self):
        self._write("broken.py", "def f(:\n")
        got = J.attribute_readers(self.tmp)
        self.assertTrue(any("broken.py" in u for u in got["unparsed"]))


class CapacityNullControlTest(unittest.TestCase):
    """Нулевой контроль обязан давать НОЛЬ, иначе стенд построен в пользу ответа."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="g18cap_"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        rows = _journal(10)
        src = self.tmp / "src"
        _data_dir(rows, src)
        self.carousel = J._Carousel(src / "data", self.tmp / "stand", rows)

    def test_null_control_returns_no_act_day_to_the_criterion(self):
        got = J.capacity(self.carousel, form=J.FORM_NULL)
        self.assertEqual(got["reaches_criterion"], 0)
        self.assertEqual(got["never_became_act"], got["days_tested"])

    def test_a_real_form_does_return_act_days(self):
        got = J.capacity(self.carousel, form=J.FORM_ANY_ACT)
        self.assertGreater(got["reaches_criterion"], 0,
                           "без этого нулевой контроль выше ничего не различает")
        self.assertEqual(got["form"], J.FORM_ANY_ACT)

    def test_material_is_counted_apart_from_the_total(self):
        got = J.capacity(self.carousel, form=J.FORM_ANY_ACT)
        self.assertLessEqual(got["reaches_criterion_material"], got["reaches_criterion"])

    def test_net_positive_counts_only_days_that_would_have_PAID(self):
        """Знак net — весь смысл третьей части заказа.

        Батарея мутаций цикла #605 нашла эту дыру: подмена ``> 0`` на ``<= 0``
        превращала «ни один ACT-день не окупился» в «окупились все пятнадцать»,
        и ни один тест не краснел. Число, читаемое владельцем как «рычаг
        работает», стояло без сторожа.
        """
        got = J.capacity(self.carousel, form=J.FORM_ANY_ACT)
        material = [r for r in got["days"] if r["material"]]
        expected = len([r for r in material
                        if isinstance(r.get("net_usd"), (int, float))
                        and r["net_usd"] > 0])
        self.assertEqual(got["reaches_criterion_material_net_positive"], expected)
        self.assertNotEqual(got["reaches_criterion_material_net_positive"],
                            len(material),
                            "на этом журнале ни один существенный ACT-день не "
                            "окупается — иначе проверка знака ничего не различает")

    def test_days_with_second_row_needs_MORE_than_one_row(self):
        rows = _journal(4)
        self.assertEqual(J.days_with_second_row(rows), [],
                         "один ряд в день — это НЕ вторая строка")


class CarouselTest(unittest.TestCase):
    def test_live_journal_is_not_written_to(self):
        tmp = Path(tempfile.mkdtemp(prefix="g18live_"))
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        rows = _journal(6)
        src = _data_dir(rows, tmp / "src")
        before = (src / J.HISTORY_FILENAME).read_bytes()
        carousel = J._Carousel(src, tmp / "stand", rows)
        carousel.set_day(2, [rows[2], rows[2], rows[2]])
        self.assertEqual((src / J.HISTORY_FILENAME).read_bytes(), before,
                         "прибор не имеет права писать в источник")
        self.assertEqual(len(carousel.journal.read_text().strip().splitlines()),
                         len(rows) + 2)


class VerdictTest(unittest.TestCase):
    def test_unmeasured_when_values_are_missing(self):
        self.assertEqual(J._verdict({})["status"], J.STATUS_UNMEASURED)

    def test_unmeasured_when_today_is_not_measured(self):
        doc = {"value_outcomes": {J.VALUE_INFLATES: 3}, "values_population": 10,
               "returns_today": {"act_days": None}}
        self.assertEqual(J._verdict(doc)["status"], J.STATUS_UNMEASURED)

    def test_critical_names_both_numbers(self):
        doc = {"value_outcomes": {J.VALUE_INFLATES: 26}, "values_population": 94,
               "returns_today": {"act_days": 0},
               "capacity": {J.FORM_NULL: {"reaches_criterion": 0},
                            J.FORM_ANY_ACT: {"reaches_criterion_material": 15}}}
        got = J._verdict(doc)
        self.assertEqual(got["status"], J.STATUS_CRITICAL)
        self.assertIn("26", got["headline"])
        self.assertIn("0 ACT-дн", got["headline"])
        self.assertIn("15", got["headline"])

    def test_warning_when_nothing_inflates(self):
        doc = {"value_outcomes": {J.VALUE_NO_SIGNAL: 94}, "values_population": 94,
               "returns_today": {"act_days": 0}, "capacity": None}
        self.assertEqual(J._verdict(doc)["status"], J.STATUS_WARNING)


class MeasureEndToEndTest(unittest.TestCase):
    """Замер целиком — по ИСХОДУ, на синтетическом журнале с инъектированными часами."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="g18e2e_"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.tree = self.tmp / "tree"
        (self.tree / "spa_core/paper_trading").mkdir(parents=True)
        (self.tree / "spa_core/paper_trading/shadow_trigger_eval.py").write_text(
            "def load_history(d, book_id=None):\n    return [], 0\n", encoding="utf-8")
        self.data = _data_dir(_journal(14), self.tmp / "src")

    def _measure(self, **kw):
        return J.measure(self.data, now=NOW, tree_root=self.tree,
                         stand_root=self.tmp / "stand", **kw)

    def test_answers_all_three_halves_of_the_order(self):
        doc = self._measure()
        self.assertEqual(doc["generated_at"], NOW.isoformat())
        self.assertIn("values", doc)                       # (а)
        self.assertIn("forms", doc)                        # (б)
        self.assertIn("capacity", doc)                     # (в)
        self.assertEqual(doc["returns_today"]["act_days"], 0,
                         "дней со второй строкой нет — критерию возвращается ноль")
        self.assertEqual(doc["capacity"][J.FORM_NULL]["reaches_criterion"], 0)

    def test_some_value_inflates_on_the_repeat(self):
        doc = self._measure()
        inflating = [r["value"] for r in doc["values"]
                     if r["outcome"] == J.VALUE_INFLATES]
        self.assertTrue(inflating, "судья обязан раздуваться хотя бы одной величиной")
        self.assertIn("per_verdict.__len__", inflating)

    def test_no_signal_values_are_reported_apart(self):
        doc = self._measure()
        self.assertIn(J.VALUE_NO_SIGNAL, doc["value_outcomes"])

    def test_every_form_stops_the_inflation_and_the_null_control_sees_nothing(self):
        doc = self._measure()
        for form in J.FORMS:
            self.assertEqual(doc["forms"][form]["still_inflates_on_repeat"], [],
                             f"{form}: свёртка применена не там — повтор всё ещё двигает")
        self.assertEqual(doc["forms"][J.FORM_NULL]["sees_early_act"], [],
                         "нулевой контроль не имеет права видеть ранний ACT")
        self.assertTrue(doc["forms"][J.FORM_ANY_ACT]["sees_early_act"],
                        "рабочая форма обязана видеть ранний ACT")

    def test_capacity_can_be_switched_off_and_says_so(self):
        doc = self._measure(with_capacity=False)
        self.assertIsNone(doc["capacity"])
        self.assertIn("with_capacity=False", doc["capacity_unmeasured_reason"])

    def test_missing_journal_is_unmeasured_with_a_reason(self):
        empty = self.tmp / "empty" / "data"
        empty.mkdir(parents=True)
        doc = J.measure(empty, now=NOW, tree_root=self.tree)
        self.assertEqual(doc["status"], J.STATUS_UNMEASURED)
        self.assertIn("журнал не прочитан", doc["unmeasured_reason"])

    def test_families_skip_the_first_day_it_has_no_donor(self):
        """У первого дня журнала соседа-донора нет — семья на нём невозможна."""
        rows = _journal(14)
        baseline = {"per_verdict": [{"cycle_date": rows[0]["cycle_date"],
                                     "trivial": False, "outcome": "hit"}]}
        picked, missing = J.pick_families(baseline, rows)
        self.assertEqual(picked, {})
        self.assertEqual(sorted(missing), sorted([J.FAMILY_SCORED_HOLD, J.FAMILY_ACT,
                                                  J.FAMILY_TRIVIAL, J.FAMILY_UNCHECKED]))

    def test_patch_false_leaves_the_judge_untouched(self):
        """Опорный ответ обязан идти через НАСТОЯЩИЙ загрузчик, иначе он не опора."""
        from spa_core.paper_trading import shadow_trigger_eval as ste
        calls = []
        original = ste.load_history

        def watching(*a, **k):
            calls.append(1)
            return original(*a, **k)

        ste.load_history = watching
        try:
            doc, why, n = J._ask_judge(self.data, None, patch=False)
        finally:
            ste.load_history = original
        self.assertIsNotNone(doc, why)
        self.assertEqual(n, -1, "без подмены счётчик достижимости не применим")
        self.assertEqual(len(calls), 1, "судья обязан позвать СВОЙ загрузчик")

    def test_a_journal_too_short_refuses_instead_of_guessing(self):
        short = _data_dir(_journal(2), self.tmp / "short")
        doc = J.measure(short, now=NOW, tree_root=self.tree)
        self.assertEqual(doc["status"], J.STATUS_UNMEASURED)
        self.assertIn("меньше трёх строк", doc["unmeasured_reason"])

    def test_report_prints_the_null_control_and_the_limits(self):
        lines = J.format_report(self._measure())
        text = "\n".join(lines)
        self.assertIn("НУЛЕВОЙ КОНТРОЛЬ", text)
        self.assertIn("НЕ ДОКАЗЫВАЕТ", text)
        self.assertIn("В · СЕГОДНЯ", text)

    def test_report_of_an_unmeasured_doc_says_so_and_stops(self):
        lines = J.format_report({"status": J.STATUS_UNMEASURED,
                                 "unmeasured_reason": "нечем"})
        self.assertEqual(len(lines), 1)
        self.assertIn("НЕ ИЗМЕРЕНО", lines[0])


class RunAndCliTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="g18run_"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        _data_dir(_journal(12), self.tmp)

    def test_run_writes_the_artifact_under_the_given_root(self):
        doc = J.run(root=str(self.tmp), now=NOW, with_capacity=False)
        written = json.loads((self.tmp / "data" / J.ARTIFACT).read_text(encoding="utf-8"))
        self.assertEqual(written["version"], J.VERSION)
        self.assertEqual(written["generated_at"], NOW.isoformat())
        self.assertEqual(doc["status"], written["status"])

    def test_run_can_be_asked_not_to_write(self):
        J.run(root=str(self.tmp), now=NOW, write=False, with_capacity=False)
        self.assertFalse((self.tmp / "data" / J.ARTIFACT).exists())


class WiringTest(unittest.TestCase):
    """Проводка проверяется по ИСХОДУ и в ОБЕИХ записях манифеста (урок ADR-376)."""

    ROOT = Path(__file__).resolve().parents[2]

    def test_bridge_declares_the_artifact_and_calls_the_stage_from_main(self):
        src = (self.ROOT / "spa_core/monitoring/findings_bridge.py").read_text(
            encoding="utf-8")
        self.assertIn(f"data/{J.ARTIFACT}", src, "артефакт не объявлен мосту")
        self.assertIn("judge_alone_price.run(", src, "ступень не вызывается")
        import ast
        tree = ast.parse(src)
        main_fn = next((n for n in tree.body
                        if isinstance(n, ast.FunctionDef) and n.name == "main"), None)
        self.assertIsNotNone(main_fn, "у моста нет main()")
        called = any(isinstance(n, ast.Attribute) and n.attr == "run"
                     and isinstance(n.value, ast.Name)
                     and n.value.id == "judge_alone_price"
                     for n in ast.walk(main_fn))
        self.assertTrue(called, "ступень объявлена, но из main() не зовётся")

    def test_manifest_carries_both_entries(self):
        manifest = json.loads((self.ROOT / "architecture/manifest.json")
                              .read_text(encoding="utf-8"))
        blob = json.dumps(manifest, ensure_ascii=False)
        self.assertIn(f"data/{J.ARTIFACT}", blob)
        produces = [a for agent in manifest.get("agents", [])
                    for a in (agent.get("produces") or [])
                    if J.ARTIFACT in str(a)]
        self.assertTrue(produces, "артефакт не значится продуктом ни одного паспорта")

    def test_office_step_knows_the_artifact_and_its_producer(self):
        src = (self.ROOT / "scripts/consume_office_reports.py").read_text(
            encoding="utf-8")
        self.assertIn(J.ARTIFACT, src)
        self.assertIn("spa_core/monitoring/judge_alone_price.py", src)


if __name__ == "__main__":
    unittest.main()


# ── Раунд 2 приёмки: координаты, пережившие первую батарею ───────────────────
# Батарея цикла #605 дала 220 координат и 106 выживших. Тесты ниже закрывают их
# КОНТРОЛЯМИ, а не сужением вопроса: каждый назван по той поломке, которую
# выжившая мутация описывает.

class ReadHistoryRobustnessTest(unittest.TestCase):
    def test_a_json_line_that_is_not_an_object_is_skipped_not_fatal(self):
        """`isinstance(...) and ...` → `or` роняло бы разбор на строке-списке."""
        tmp = Path(tempfile.mkdtemp(prefix="g18rh_"))
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        data = tmp / "data"
        data.mkdir()
        rows = _journal(3)
        (data / J.HISTORY_FILENAME).write_text(
            "\n".join(["[1, 2, 3]", '"строка"', "не json"]
                      + [json.dumps(r, sort_keys=True) for r in rows]) + "\n",
            encoding="utf-8")
        got, why = J.read_history(data)
        self.assertEqual(why, "")
        self.assertEqual(len(got), 3)

    def test_a_journal_of_only_garbage_is_unmeasured_with_a_reason(self):
        tmp = Path(tempfile.mkdtemp(prefix="g18rh2_"))
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        data = tmp / "data"
        data.mkdir()
        (data / J.HISTORY_FILENAME).write_text("не json\n[1]\n", encoding="utf-8")
        got, why = J.read_history(data)
        self.assertIsNone(got)
        self.assertIn("не содержит разбираемых строк", why)


class OrderingTest(unittest.TestCase):
    """Порядок — часть ответа: `sorted` → `list` переживало батарею молча."""

    def test_days_with_second_row_are_named_in_ascending_order(self):
        rows = _journal(6)
        doubled = [rows[0], rows[4], rows[4], rows[1], rows[1], rows[2]]
        self.assertEqual(J.days_with_second_row(doubled),
                         sorted([rows[4]["cycle_date"], rows[1]["cycle_date"]]))

    def test_fold_returns_days_in_ascending_order_whatever_the_input_order(self):
        rows = _journal(5)
        shuffled = [rows[3], rows[0], rows[4], rows[1], rows[2]]
        for form in J.FORMS:
            got = [r["cycle_date"] for r in J.fold_day(shuffled, form)]
            self.assertEqual(got, sorted(got), f"{form}: дни отданы не по возрастанию")

    def test_attribute_reader_populations_are_sorted(self):
        tmp = Path(tempfile.mkdtemp(prefix="g18ord_"))
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        (tmp / "spa_core/paper_trading").mkdir(parents=True)
        (tmp / "spa_core/paper_trading/shadow_trigger_eval.py").write_text(
            "def load_history(d, book_id=None):\n    return [], 0\n", encoding="utf-8")
        pkg = tmp / "pkg"
        pkg.mkdir()
        for name in ("zeta.py", "alpha.py", "mid.py"):
            (pkg / name).write_text(
                "from spa_core.paper_trading import shadow_trigger_eval as ste\n"
                "def f(d):\n    return ste.load_history(d)\n", encoding="utf-8")
        got = J.attribute_readers(tmp)
        self.assertEqual(got["via_judge_module"], sorted(got["via_judge_module"]))
        self.assertEqual(len(got["via_judge_module"]), 3)


class FoldTakesTheRightRowTest(unittest.TestCase):
    """У дня ТРИ строки: только тогда `[-1]` отличимо от `[1]`."""

    def setUp(self):
        day = _day(5)
        self.early = _row(day, verdict="ACT", turnover=30_000.0)
        self.middle = _row(day, verdict="HOLD", turnover=22_222.0)
        self.late = _row(day, verdict="HOLD", turnover=11_111.0)

    def test_any_act_takes_the_LAST_of_three_rows_not_the_middle(self):
        got = J.fold_day([self.early, self.middle, self.late], J.FORM_ANY_ACT)
        self.assertEqual(got[0]["turnover_usd"], 11_111.0)
        self.assertEqual(got[0]["verdict"], "ACT")

    def test_first_act_takes_the_FIRST_act_row_not_a_later_one(self):
        second_act = dict(self.middle)
        second_act["verdict"] = "ACT"
        got = J.fold_day([self.early, second_act, self.late], J.FORM_FIRST_ACT)
        self.assertEqual(got[0]["turnover_usd"], 30_000.0)

    def test_null_control_takes_the_LAST_of_three_rows(self):
        got = J.fold_day([self.early, self.middle, self.late], J.FORM_NULL)
        self.assertEqual(got[0]["turnover_usd"], 11_111.0)
        self.assertEqual(got[0]["verdict"], "HOLD")


class TwinDonorTest(unittest.TestCase):
    def test_the_twin_is_stamped_on_the_target_day_and_marked_ACT(self):
        rows = _journal(5)
        twin = J.twin_act(rows[2], rows[3]["cycle_date"])
        self.assertEqual(twin["cycle_date"], rows[3]["cycle_date"])
        self.assertEqual(twin["verdict"], "ACT")
        self.assertEqual(twin["turnover_usd"], rows[2]["turnover_usd"],
                         "материал обязан прийти от донора, а не быть выдуман")
        self.assertLess(twin["generated_at"], rows[3]["generated_at"],
                        "ранняя строка обязана быть РАНЬШЕ настоящей")


class PickFamiliesTest(unittest.TestCase):
    """Классы дня различает САМ судья; предикаты семей — не украшение."""

    def setUp(self):
        self.rows = _journal(8)
        d = [r["cycle_date"] for r in self.rows]
        self.per = [
            {"cycle_date": d[0], "trivial": False, "outcome": "hit"},   # первый — без донора
            {"cycle_date": d[1], "trivial": True, "outcome": "hit"},
            {"cycle_date": d[2], "trivial": False, "outcome": "UNCHECKED"},
            {"cycle_date": d[3], "trivial": False, "outcome": "hit"},
            {"cycle_date": d[4], "trivial": False, "outcome": "miss"},
        ]
        self.d = d

    def _pick(self):
        return J.pick_families({"per_verdict": self.per}, self.rows)

    def test_each_class_picks_its_own_day(self):
        picked, missing = self._pick()
        self.assertEqual(missing, [])
        self.assertEqual(self.rows[picked[J.FAMILY_TRIVIAL]]["cycle_date"], self.d[1])
        self.assertEqual(self.rows[picked[J.FAMILY_UNCHECKED]]["cycle_date"], self.d[2])
        self.assertEqual(self.rows[picked[J.FAMILY_SCORED_HOLD]]["cycle_date"], self.d[3],
                         "должен браться РАННИЙ подходящий день, а не любой")
        self.assertEqual(picked[J.FAMILY_ACT], picked[J.FAMILY_SCORED_HOLD])

    def test_a_trivial_day_is_not_offered_as_the_scored_family(self):
        """Тривиальный день оценён (`hit`), но предложения в нём нет — не семья."""
        self.per = [r for r in self.per if r["trivial"]]
        picked, missing = self._pick()
        self.assertIn(J.FAMILY_SCORED_HOLD, missing)
        self.assertIn(J.FAMILY_ACT, missing)
        self.assertIn(J.FAMILY_TRIVIAL, picked)

    def test_an_unchecked_day_is_not_offered_as_the_scored_family(self):
        self.per = [{"cycle_date": self.d[2], "trivial": False, "outcome": "UNCHECKED"}]
        picked, missing = self._pick()
        self.assertEqual(sorted(picked), [J.FAMILY_UNCHECKED])
        self.assertIn(J.FAMILY_SCORED_HOLD, missing)

    def test_a_missing_class_is_named_not_silently_dropped(self):
        self.per = []
        picked, missing = self._pick()
        self.assertEqual(picked, {})
        self.assertEqual(len(missing), 4)


class ClassifyValuesRepeatArmsTest(unittest.TestCase):
    """Урок ADR-385: детектор повтора обязан видеть КАЖДОЕ плечо порознь."""

    def test_a_value_that_moves_only_at_the_DOUBLE_is_caught(self):
        answers = {"f@1": {"n": 1}, "f@2": {"n": 2}, "f@3": {"n": 1}}
        self.assertEqual(J.classify_values(answers, ["f"])[0]["outcome"],
                         J.VALUE_INFLATES)

    def test_a_value_that_moves_only_at_the_TRIPLE_is_caught(self):
        answers = {"f@1": {"n": 1}, "f@2": {"n": 1}, "f@3": {"n": 2}}
        self.assertEqual(J.classify_values(answers, ["f"])[0]["outcome"],
                         J.VALUE_INFLATES)

    def test_a_value_absent_from_a_families_baseline_is_not_judged_by_it(self):
        answers = {"a@1": {}, "a@2": {"n": 9}, "b@1": {"n": 3}, "b@2": {"n": 3}}
        row = J.classify_values(answers, ["a", "b"])[0]
        self.assertEqual(row["outcome"], J.VALUE_NO_SIGNAL)


class RepeatCensusTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="g18rc_"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.rows = _journal(10)
        src = _data_dir(self.rows, self.tmp / "src")
        self.carousel = J._Carousel(src, self.tmp / "stand", self.rows)

    def test_every_family_is_asked_at_one_two_and_three_repeats(self):
        answers, refusals = J.repeat_census(
            self.carousel, {J.FAMILY_SCORED_HOLD: 4}, form=None, patch=True)
        self.assertEqual(sorted(answers), [f"{J.FAMILY_SCORED_HOLD}@{n}"
                                           for n in (1, 2, 3)])
        self.assertEqual(refusals, [])

    def test_the_act_family_really_relabels_the_row(self):
        answers, _ = J.repeat_census(self.carousel, {J.FAMILY_ACT: 4},
                                     form=None, patch=True)
        self.assertEqual(answers[f"{J.FAMILY_ACT}@1"]["counts.act"], 1)
        answers2, _ = J.repeat_census(self.carousel, {J.FAMILY_SCORED_HOLD: 4},
                                      form=None, patch=True)
        self.assertEqual(answers2[f"{J.FAMILY_SCORED_HOLD}@1"]["counts.act"], 0)

    def test_the_stand_journal_carries_exactly_the_asked_number_of_rows(self):
        self.carousel.set_day(4, [self.carousel.rows[4]] * 3)
        lines = self.carousel.journal.read_text(encoding="utf-8").strip().splitlines()
        self.assertEqual(len(lines), len(self.rows) + 2)

    def test_asking_the_judge_never_writes_into_the_stand(self):
        """`write=False` у судьи — часть обещания «прибор только ЧИТАЕТ»."""
        J._ask_judge(self.carousel.data, None, patch=True)
        J._ask_judge(self.carousel.data, None, patch=False)
        self.assertFalse((self.carousel.data / "shadow_trigger_evaluation.json").exists())


class FormSeesActRefusalTest(unittest.TestCase):
    def test_a_judge_that_refuses_gives_a_named_refusal_not_an_empty_verdict(self):
        tmp = Path(tempfile.mkdtemp(prefix="g18ref_"))
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        rows = _journal(6)
        carousel = J._Carousel(_data_dir(rows, tmp / "src"), tmp / "stand", rows)

        class _Stub:
            load_history = staticmethod(lambda *a, **k: ([], 0))

            @staticmethod
            def evaluate_window(_d, write=True):
                raise RuntimeError("судья сломан")

        saved = sys.modules.get(J.JUDGE_MODULE)
        sys.modules[J.JUDGE_MODULE] = _Stub
        try:
            seen, refusals, day = J.form_sees_act(carousel, 3, form=J.FORM_ANY_ACT,
                                                  values=["hit_rate"])
        finally:
            if saved is None:
                del sys.modules[J.JUDGE_MODULE]
            else:
                sys.modules[J.JUDGE_MODULE] = saved
        self.assertEqual(seen, {})
        self.assertEqual(len(refusals), 1)
        self.assertIn("судья упал", refusals[0])
        self.assertEqual(day, rows[3]["cycle_date"])

    def test_a_value_absent_from_either_side_is_unmeasured_not_blind(self):
        tmp = Path(tempfile.mkdtemp(prefix="g18ref2_"))
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        rows = _journal(8)
        carousel = J._Carousel(_data_dir(rows, tmp / "src"), tmp / "stand", rows)
        seen, refusals, _ = J.form_sees_act(carousel, 4, form=J.FORM_ANY_ACT,
                                            values=["такой величины нет"])
        self.assertEqual(refusals, [])
        self.assertEqual(seen["такой величины нет"], J.FORM_UNMEASURED)


class CapacityNetSignTest(unittest.TestCase):
    """Знак `net` меряется на журнале, где ПОЛОЖИТЕЛЬНЫЙ исход возможен.

    Батарея цикла #605 показала, что на живом журнале `> 0` и `> 1`
    неотличимы — там нет ни одного окупающегося дня. Это свойство НАСЕЛЕНИЯ, а
    не теста, и закрывается оно вторым журналом, а не подгонкой порога.
    """

    def _carousel(self, cost: float) -> J._Carousel:
        tmp = Path(tempfile.mkdtemp(prefix="g18net_"))
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        rows = [_row(_day(12 - i), cost=cost) for i in range(12)]
        return J._Carousel(_data_dir(rows, tmp / "src"), tmp / "stand", rows)

    def test_a_profitable_move_is_counted_as_net_positive(self):
        got = J.capacity(self._carousel(cost=1.0), form=J.FORM_ANY_ACT)
        self.assertGreater(got["reaches_criterion_material_net_positive"], 0)
        self.assertEqual(got["reaches_criterion_material_net_positive"],
                         got["reaches_criterion_material"])

    def test_the_same_move_at_a_ruinous_cost_is_counted_as_net_negative(self):
        got = J.capacity(self._carousel(cost=100_000.0), form=J.FORM_ANY_ACT)
        self.assertEqual(got["reaches_criterion_material_net_positive"], 0)
        self.assertGreater(got["reaches_criterion_material"], 0)


class AttributeReadersEdgeTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="g18attr_"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        (self.tmp / "spa_core/paper_trading").mkdir(parents=True)
        (self.tmp / "spa_core/paper_trading/shadow_trigger_eval.py").write_text(
            "def load_history(d, book_id=None):\n    return [], 0\n", encoding="utf-8")
        self.pkg = self.tmp / "pkg"
        self.pkg.mkdir()

    def test_a_plain_dotted_import_without_as_is_still_a_judge_alias(self):
        (self.pkg / "plain.py").write_text(
            "import spa_core.paper_trading.shadow_trigger_eval\n"
            "def f(d):\n"
            "    return spa_core.paper_trading.shadow_trigger_eval.load_history(d)\n",
            encoding="utf-8")
        got = J.attribute_readers(self.tmp)
        self.assertEqual(got["via_judge_module"], ["pkg/plain.py"])

    def test_importing_load_history_among_other_names_still_counts_as_own_copy(self):
        (self.pkg / "mixed.py").write_text(
            "from spa_core.paper_trading.shadow_trigger_eval import "
            "EVAL_VERSION, load_history\n"
            "def f(d):\n    return load_history(d)\n", encoding="utf-8")
        got = J.attribute_readers(self.tmp)
        self.assertEqual(got["own_copy_of_reference"], ["pkg/mixed.py"])

    def test_importing_only_other_names_is_not_a_copy_of_the_reference(self):
        (self.pkg / "other.py").write_text(
            "from spa_core.paper_trading.shadow_trigger_eval import EVAL_VERSION\n",
            encoding="utf-8")
        got = J.attribute_readers(self.tmp)
        self.assertEqual(got["own_copy_of_reference"], [])

    def test_test_files_are_left_out_of_every_population(self):
        tests = self.tmp / "spa_core/tests"
        tests.mkdir(parents=True)
        (tests / "test_thing.py").write_text(
            "from spa_core.paper_trading import shadow_trigger_eval as ste\n"
            "def f(d):\n    return ste.load_history(d)\n", encoding="utf-8")
        got = J.attribute_readers(self.tmp)
        self.assertEqual(got["via_judge_module"], [])

    def test_the_judge_itself_is_not_its_own_reader(self):
        got = J.attribute_readers(self.tmp)
        self.assertNotIn("spa_core/paper_trading/shadow_trigger_eval.py",
                         got["via_judge_module"] + got["own_copy_of_reference"]
                         + got["unresolved"] + got["own_method"])


class VerdictArithmeticTest(unittest.TestCase):
    def test_capacity_headline_takes_the_BEST_working_form_and_excludes_the_control(self):
        doc = {"value_outcomes": {J.VALUE_INFLATES: 5}, "values_population": 40,
               "returns_today": {"act_days": 0},
               "capacity": {J.FORM_NULL: {"reaches_criterion": 0,
                                          "reaches_criterion_material": 99},
                            J.FORM_ANY_ACT: {"reaches_criterion_material": 7},
                            J.FORM_FIRST_ACT: {"reaches_criterion_material": 12}}}
        head = J._verdict(doc)["headline"]
        self.assertIn("12 существенных", head)
        self.assertNotIn("99", head)

    def test_the_null_controls_own_number_is_printed_beside_it(self):
        doc = {"value_outcomes": {J.VALUE_INFLATES: 1}, "values_population": 2,
               "returns_today": {"act_days": 0},
               "capacity": {J.FORM_NULL: {"reaches_criterion": 4},
                            J.FORM_ANY_ACT: {"reaches_criterion_material": 1}}}
        self.assertIn("нулевой контроль: 4", J._verdict(doc)["headline"])


class ReportOnAThinDocTest(unittest.TestCase):
    """Отчёт обязан печататься и на бедном документе — без падения и без выдумок."""

    THIN = {"status": J.STATUS_WARNING, "journal": {}, "families": {},
            "value_outcomes": {}, "values": [], "forms": {},
            "returns_today": {}, "capacity": None, "fix_site": {},
            "what_it_does_not_prove": [], "advisory": []}

    def test_it_does_not_raise_and_says_what_is_not_measured(self):
        lines = J.format_report(dict(self.THIN))
        text = "\n".join(lines)
        self.assertIn("[В · ЁМКОСТЬ] НЕ ИЗМЕРЕНО", text)
        self.assertIn("причина не названа", text)

    def test_missing_reader_populations_print_a_dash_not_an_empty_join(self):
        lines = J.format_report(dict(self.THIN))
        self.assertTrue(any("—" in ln for ln in lines))

    def test_a_named_missing_family_is_printed(self):
        doc = dict(self.THIN)
        doc["families_missing"] = [J.FAMILY_TRIVIAL]
        self.assertIn("нет класса", "\n".join(J.format_report(doc)))


class CliTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="g18cli_"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        _data_dir(_journal(12), self.tmp)
        self.tree = self.tmp / "tree"
        (self.tree / "spa_core/paper_trading").mkdir(parents=True)
        (self.tree / "spa_core/paper_trading/shadow_trigger_eval.py").write_text(
            "def load_history(d, book_id=None):\n    return [], 0\n", encoding="utf-8")

    def test_tree_root_flag_really_redirects_the_fix_site_scan(self):
        """Без флага CLI обходил ТОЛЬКО свой репозиторий — спросить о чужом было нечем."""
        _code, out = self._run(["--data-dir", str(self.tmp / "data"),
                                "--stand-root", str(self.tmp / "s0"),
                                "--tree-root", str(self.tree),
                                "--no-capacity", "--json"])
        doc = json.loads(out)
        self.assertEqual(doc["fix_site"]["via_judge_module"], [],
                         "обход обязан идти по НАЗВАННОМУ дереву, а не по своему")
        self.assertEqual(doc["fix_site"]["own_method"], [])

    def _run(self, argv):
        import contextlib
        import io as _io
        buf = _io.StringIO()
        with contextlib.redirect_stdout(buf):
            code = J.main(argv)
        return code, buf.getvalue()

    def test_exit_code_is_one_on_critical_and_two_on_unmeasured(self):
        code, _ = self._run(["--data-dir", str(self.tmp / "data"),
                             "--stand-root", str(self.tmp / "s1"),
                             "--tree-root", str(self.tree), "--no-capacity"])
        self.assertEqual(code, 1, "раздувающиеся величины — это код 1, а не 0")
        empty = self.tmp / "empty"
        empty.mkdir()
        code2, out2 = self._run(["--data-dir", str(empty),
                                 "--stand-root", str(self.tmp / "s2"),
                                 "--tree-root", str(self.tree)])
        self.assertEqual(code2, 2)
        self.assertIn("НЕ ИЗМЕРЕНО", out2)

    def test_json_mode_prints_a_parsable_document(self):
        _code, out = self._run(["--data-dir", str(self.tmp / "data"),
                                "--stand-root", str(self.tmp / "s3"),
                                "--tree-root", str(self.tree),
                                "--no-capacity", "--json"])
        doc = json.loads(out)
        self.assertEqual(doc["version"], J.VERSION)
        self.assertIsNone(doc["capacity"])

    def test_no_capacity_flag_really_switches_the_third_half_off(self):
        _code, out = self._run(["--data-dir", str(self.tmp / "data"),
                                "--stand-root", str(self.tmp / "s4"),
                                "--tree-root", str(self.tree), "--no-capacity"])
        self.assertIn("[В · ЁМКОСТЬ] НЕ ИЗМЕРЕНО", out)
        _code2, out2 = self._run(["--data-dir", str(self.tmp / "data"),
                                  "--stand-root", str(self.tmp / "s5"),
                                  "--tree-root", str(self.tree)])
        self.assertIn(f"[В · ЁМКОСТЬ] {J.FORM_ANY_ACT}", out2)


class MeasureBoundaryTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="g18bnd_"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.tree = self.tmp / "tree"
        (self.tree / "spa_core/paper_trading").mkdir(parents=True)
        (self.tree / "spa_core/paper_trading/shadow_trigger_eval.py").write_text(
            "def load_history(d, book_id=None):\n    return [], 0\n", encoding="utf-8")

    def test_exactly_two_rows_refuse_and_exactly_three_are_measured(self):
        two = _data_dir(_journal(2), self.tmp / "two")
        three = _data_dir(_journal(3), self.tmp / "three")
        self.assertEqual(J.measure(two, now=NOW, tree_root=self.tree)["status"],
                         J.STATUS_UNMEASURED)
        got = J.measure(three, now=NOW, tree_root=self.tree,
                        stand_root=self.tmp / "s", with_capacity=False)
        self.assertNotEqual(got["status"], J.STATUS_UNMEASURED)

    def test_value_outcome_counts_sum_to_the_population(self):
        data = _data_dir(_journal(12), self.tmp / "full")
        doc = J.measure(data, now=NOW, tree_root=self.tree,
                        stand_root=self.tmp / "s2", with_capacity=False)
        self.assertEqual(sum(doc["value_outcomes"].values()), doc["values_population"])
        self.assertEqual(doc["values_population"], len(doc["values"]))

    def test_the_forms_are_measured_against_the_INFLATING_values_only(self):
        data = _data_dir(_journal(12), self.tmp / "full2")
        doc = J.measure(data, now=NOW, tree_root=self.tree,
                        stand_root=self.tmp / "s3", with_capacity=False)
        inflating = {r["value"] for r in doc["values"]
                     if r["outcome"] == J.VALUE_INFLATES}
        for form in J.FORMS:
            block = doc["forms"][form]
            judged = set(block["sees_early_act"]) | set(block["blind_to_early_act"]) \
                | set(block["unmeasured"])
            self.assertEqual(judged, inflating,
                             f"{form}: судились не те величины")


# ── Раунд 3 приёмки: координаты, пережившие вторую батарею ───────────────────

class CapacityNetThresholdTest(unittest.TestCase):
    """Порог знака — РОВНО ноль, а не «заметно больше нуля».

    Вторая батарея показала, что `> 0` переживает подмену на `> 1`: на прежнем
    журнале ни один окупающийся день не приносил меньше доллара. Различить их
    можно только днём, чья выгода лежит МЕЖДУ нулём и единицей, — и такой день
    строится стоимостью, а не подгонкой порога.
    """

    def _capacity(self, cost: float) -> dict:
        tmp = Path(tempfile.mkdtemp(prefix="g18thr_"))
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        rows = [_row(_day(12 - i), cost=cost) for i in range(12)]
        carousel = J._Carousel(_data_dir(rows, tmp / "src"), tmp / "stand", rows)
        return J.capacity(carousel, form=J.FORM_ANY_ACT)

    def test_a_day_earning_less_than_a_dollar_is_still_net_positive(self):
        got = self._capacity(cost=2.9)
        sub_dollar = [r for r in got["days"]
                      if r["material"] and 0 < (r["net_usd"] or 0) < 1]
        self.assertTrue(sub_dollar, "стенд не построил дня с выгодой внутри доллара")
        self.assertEqual(got["reaches_criterion_material_net_positive"],
                         got["reaches_criterion_material"],
                         "день с выгодой 0.39 $ обязан считаться окупившимся")


class AskJudgeFailurePathTest(unittest.TestCase):
    def test_an_unpatched_judge_that_raises_returns_a_named_reason(self):
        class _Stub:
            @staticmethod
            def evaluate_window(_d, write=True):
                raise RuntimeError("бум")

        saved = sys.modules.get(J.JUDGE_MODULE)
        sys.modules[J.JUDGE_MODULE] = _Stub
        try:
            doc, why, calls = J._ask_judge(Path("/nonexistent"), None, patch=False)
        finally:
            if saved is None:
                del sys.modules[J.JUDGE_MODULE]
            else:
                sys.modules[J.JUDGE_MODULE] = saved
        self.assertIsNone(doc)
        self.assertIn("судья упал", why)
        self.assertIn("RuntimeError", why)
        self.assertEqual(calls, -1, "без подмены счётчик неприменим и это -1, а не 0")


class DonorIsThePrecedingDayTest(unittest.TestCase):
    """Донор ранней строки — ПРЕДЫДУЩИЙ день, а не следующий и не любой."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="g18don_"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        # каждому дню — свой оборот, чтобы донора можно было опознать по числу
        self.rows = [_row(_day(10 - i), turnover=1000.0 * (i + 1))
                     for i in range(10)]
        self.carousel = J._Carousel(_data_dir(self.rows, self.tmp / "src"),
                                    self.tmp / "stand", self.rows)

    def _early_row_of(self, day: str) -> dict:
        lines = self.carousel.journal.read_text(encoding="utf-8").splitlines()
        rows = [json.loads(ln) for ln in lines if ln.strip()]
        same = [r for r in rows if r["cycle_date"] == day]
        return same[0]

    def test_the_stand_of_form_sees_act_borrows_from_the_previous_day(self):
        J.form_sees_act(self.carousel, 5, form=J.FORM_ANY_ACT, values=["hit_rate"])
        early = self._early_row_of(self.rows[5]["cycle_date"])
        self.assertEqual(early["verdict"], "ACT")
        self.assertEqual(early["turnover_usd"], self.rows[4]["turnover_usd"],
                         "донор обязан быть ПРЕДЫДУЩИМ днём")

    def test_the_capacity_sweep_borrows_from_the_previous_day_too(self):
        J.capacity(self.carousel, form=J.FORM_NULL)
        last = self.rows[-1]["cycle_date"]
        early = self._early_row_of(last)
        self.assertEqual(early["turnover_usd"], self.rows[-2]["turnover_usd"])


class FormBucketsAreDisjointTest(unittest.TestCase):
    def test_a_value_lands_in_exactly_one_bucket(self):
        tmp = Path(tempfile.mkdtemp(prefix="g18buck_"))
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        tree = tmp / "tree"
        (tree / "spa_core/paper_trading").mkdir(parents=True)
        (tree / "spa_core/paper_trading/shadow_trigger_eval.py").write_text(
            "def load_history(d, book_id=None):\n    return [], 0\n", encoding="utf-8")
        doc = J.measure(_data_dir(_journal(12), tmp / "src"), now=NOW, tree_root=tree,
                        stand_root=tmp / "stand", with_capacity=False)
        for form in J.FORMS:
            b = doc["forms"][form]
            seen, blind, unm = (set(b["sees_early_act"]), set(b["blind_to_early_act"]),
                                set(b["unmeasured"]))
            self.assertEqual(seen & blind, set(), f"{form}: величина и видна, и слепа")
            self.assertEqual(seen & unm, set(), f"{form}: величина и видна, и не измерена")
            self.assertEqual(blind & unm, set(), f"{form}: слепа и не измерена сразу")


class VerdictDefaultsTest(unittest.TestCase):
    def test_capacity_blocks_without_their_keys_read_as_zero_not_as_a_crash(self):
        doc = {"value_outcomes": {J.VALUE_INFLATES: 1}, "values_population": 2,
               "returns_today": {"act_days": 0},
               "capacity": {J.FORM_NULL: {}, J.FORM_ANY_ACT: {}}}
        head = J._verdict(doc)["headline"]
        self.assertIn("0 существенных", head)
        self.assertIn("нулевой контроль: 0", head)


class ReportLabelsTest(unittest.TestCase):
    DOC = {"status": J.STATUS_CRITICAL, "journal": {"rows": 1, "days": 1,
                                                    "days_with_second_row": []},
           "families": {}, "value_outcomes": {}, "values": [],
           "forms": {f: {"sees_early_act": [], "blind_to_early_act": [],
                         "unmeasured": [], "still_inflates_on_repeat": []}
                     for f in J.FORMS},
           "returns_today": {"act_days": 0, "reason": "—"},
           "capacity": {f: {"days_tested": 1, "reaches_criterion": 0,
                            "reaches_criterion_material": 0,
                            "reaches_criterion_material_net_positive": 0,
                            "act_but_unscored": 0, "never_became_act": 1}
                        for f in J.FORMS},
           "fix_site": {}, "what_it_does_not_prove": [], "advisory": []}

    def test_only_the_null_form_is_labelled_a_null_control(self):
        text = "\n".join(J.format_report(dict(self.DOC)))
        self.assertIn(f"[Б · НУЛЕВОЙ КОНТРОЛЬ] {J.FORM_NULL}", text)
        self.assertIn(f"[Б · ФОРМА] {J.FORM_ANY_ACT}", text)
        self.assertIn(f"[В · НУЛЕВОЙ КОНТРОЛЬ] {J.FORM_NULL}", text)
        self.assertIn(f"[В · ЁМКОСТЬ] {J.FORM_ANY_ACT}", text)
        self.assertNotIn(f"[Б · ФОРМА] {J.FORM_NULL}", text)
        self.assertNotIn(f"[В · ЁМКОСТЬ] {J.FORM_NULL}", text)


class ExitCodeTest(unittest.TestCase):
    def test_an_unknown_status_exits_two_not_zero(self):
        """«Не измерено» и «статус неизвестен» — один исход: НЕ успех."""
        import contextlib
        import io as _io
        saved = J.measure
        J.measure = lambda *a, **k: {"status": "какой-то новый статус"}
        try:
            with contextlib.redirect_stdout(_io.StringIO()):
                code = J.main(["--data-dir", "/nonexistent", "--no-capacity"])
        finally:
            J.measure = saved
        self.assertEqual(code, 2)

    def test_a_warning_status_exits_zero(self):
        import contextlib
        import io as _io
        saved = J.measure
        J.measure = lambda *a, **k: {"status": J.STATUS_WARNING}
        try:
            with contextlib.redirect_stdout(_io.StringIO()):
                code = J.main(["--data-dir", "/nonexistent", "--no-capacity"])
        finally:
            J.measure = saved
        self.assertEqual(code, 0)


class DeterministicOrderTest(unittest.TestCase):
    def test_value_rows_come_out_sorted_by_name(self):
        answers = {"f@1": {"zeta": 1, "alpha": 1, "mid": 1},
                   "f@2": {"zeta": 2, "alpha": 1, "mid": 3}}
        names = [r["value"] for r in J.classify_values(answers, ["f"])]
        self.assertEqual(names, sorted(names))

    def test_the_families_a_value_inflates_in_are_named_in_order(self):
        answers = {"zeta@1": {"n": 1}, "zeta@2": {"n": 2},
                   "alpha@1": {"n": 1}, "alpha@2": {"n": 2}}
        row = J.classify_values(answers, ["zeta", "alpha"])[0]
        self.assertEqual(row["inflates_in"], ["alpha", "zeta"])

    def test_judge_value_names_come_out_sorted(self):
        doc = {"zeta": 1, "alpha": 2, "counts": {"b": 1, "a": 2}}
        names = [k for k in J.judge_values(doc) if k != "per_verdict.__len__"]
        self.assertEqual(names, sorted(names))

    def test_families_are_picked_from_days_in_DATE_order_not_file_order(self):
        """`sorted(per)` → `list(per)` переживало батарею, пока фикстура шла по порядку."""
        rows = _journal(8)
        d = [r["cycle_date"] for r in rows]
        per = [  # НАМЕРЕННО в обратном порядке дат
            {"cycle_date": d[5], "trivial": False, "outcome": "hit"},
            {"cycle_date": d[3], "trivial": False, "outcome": "miss"},
            {"cycle_date": d[2], "trivial": False, "outcome": "hit"},
        ]
        picked, _missing = J.pick_families({"per_verdict": per}, rows)
        self.assertEqual(rows[picked[J.FAMILY_SCORED_HOLD]]["cycle_date"], d[2],
                         "браться обязан самый РАННИЙ подходящий день")

    def test_every_reader_population_is_sorted(self):
        tmp = Path(tempfile.mkdtemp(prefix="g18sort_"))
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        (tmp / "spa_core/paper_trading").mkdir(parents=True)
        (tmp / "spa_core/paper_trading/shadow_trigger_eval.py").write_text(
            "def load_history(d, book_id=None):\n    return [], 0\n", encoding="utf-8")
        pkg = tmp / "pkg"
        pkg.mkdir()
        for name in ("zeta.py", "alpha.py"):
            (pkg / name).write_text(
                "from spa_core.paper_trading.shadow_trigger_eval import load_history\n"
                "class E:\n    def load_history(self):\n        return []\n"
                "    def go(self):\n        return self.load_history()\n"
                "def f(engine):\n    return engine.load_history()\n", encoding="utf-8")
        got = J.attribute_readers(tmp)
        for key in ("via_judge_module", "via_judge_module_indirect",
                    "own_copy_of_reference", "own_method", "unresolved"):
            self.assertEqual(got[key], sorted(got[key]), f"{key} отдан не по порядку")
        self.assertEqual(got["own_copy_of_reference"], ["pkg/alpha.py", "pkg/zeta.py"])


# ── Раунд 4 приёмки: последние координаты с ПОВЕДЕНИЕМ за ними ───────────────

class PatchWiringTest(unittest.TestCase):
    """Кого спрашивают ПОДМЕНЁННЫМ загрузчиком, а кого — своим.

    Третья батарея показала, что `patch=True/False` переживает подмену: у
    `form_sees_act` две пробы, и порча ОДНОЙ оставляет разницу между стендами —
    только разницу не того рода. Проверять надо не «ответ изменился», а КОГО
    именно спросили: опора обязана идти через СОБСТВЕННЫЙ загрузчик судьи,
    иначе она не опора, а оба стенда формы — через подменённый, иначе они
    сравнивают форму с сегодняшним поведением.
    """

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="g18wire_"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.calls = []
        self.real = J._ask_judge

        def recording(data_dir, form, *, patch):
            self.calls.append((form, patch))
            return self.real(data_dir, form, patch=patch)

        J._ask_judge = recording
        self.addCleanup(lambda: setattr(J, "_ask_judge", self.real))

    def test_form_sees_act_asks_BOTH_stands_through_the_patched_loader(self):
        rows = _journal(10)
        carousel = J._Carousel(_data_dir(rows, self.tmp / "src"),
                               self.tmp / "stand", rows)
        J.form_sees_act(carousel, 5, form=J.FORM_ANY_ACT, values=["hit_rate"])
        self.assertEqual(self.calls, [(J.FORM_ANY_ACT, True), (J.FORM_ANY_ACT, True)])

    def test_the_baseline_is_asked_through_the_judges_OWN_loader(self):
        tree = self.tmp / "tree"
        (tree / "spa_core/paper_trading").mkdir(parents=True)
        (tree / "spa_core/paper_trading/shadow_trigger_eval.py").write_text(
            "def load_history(d, book_id=None):\n    return [], 0\n", encoding="utf-8")
        J.measure(_data_dir(_journal(12), self.tmp / "src2"), now=NOW, tree_root=tree,
                  stand_root=self.tmp / "stand2", with_capacity=False)
        self.assertEqual(self.calls[0], (None, False),
                         "опорный ответ обязан быть первым и БЕЗ подмены")
        self.assertTrue(all(patch for _form, patch in self.calls[1:]),
                        "все прочие пробы обязаны идти через подменённый загрузчик")


class OneSidedRefusalTest(unittest.TestCase):
    """Отказ ОДНОЙ стороны — уже отказ: `or` → `and` проглотил бы его."""

    def _judge_that_refuses_on(self, *, duplicate_day: bool):
        real = sys.modules.get(J.JUDGE_MODULE)
        if real is None:
            from spa_core.paper_trading import shadow_trigger_eval as real  # noqa

        class _Selective:
            #: `_ask_judge` подменит ЭТОТ атрибут; настоящему судье его надо
            #: передать, иначе счётчик достижимости честно скажет «не вызван»
            #: — и тест измерит не то, ради чего написан.
            load_history = staticmethod(real.load_history)

            @staticmethod
            def evaluate_window(data_dir, write=True):
                rows, _ = J.read_history(Path(data_dir))
                has_dup = bool(J.days_with_second_row(rows or []))
                if has_dup is duplicate_day:
                    raise RuntimeError("отказ ровно на этом стенде")
                saved = real.load_history
                real.load_history = _Selective.load_history
                try:
                    return real.evaluate_window(Path(data_dir), write=write)
                finally:
                    real.load_history = saved

        return _Selective

    def _measure(self, *, duplicate_day: bool):
        tmp = Path(tempfile.mkdtemp(prefix="g18one_"))
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        rows = _journal(10)
        carousel = J._Carousel(_data_dir(rows, tmp / "src"), tmp / "stand", rows)
        saved = sys.modules.get(J.JUDGE_MODULE)
        sys.modules[J.JUDGE_MODULE] = self._judge_that_refuses_on(
            duplicate_day=duplicate_day)
        try:
            return J.form_sees_act(carousel, 5, form=J.FORM_ANY_ACT,
                                   values=["hit_rate"])
        finally:
            if saved is None:
                del sys.modules[J.JUDGE_MODULE]
            else:
                sys.modules[J.JUDGE_MODULE] = saved

    def test_a_refusal_on_the_TWO_ROW_stand_alone_is_still_a_refusal(self):
        seen, refusals, _day = self._measure(duplicate_day=True)
        self.assertEqual(seen, {})
        self.assertEqual(len(refusals), 1)
        self.assertIn("судья упал", refusals[0])

    def test_a_refusal_on_the_ONE_ROW_stand_alone_is_still_a_refusal(self):
        seen, refusals, _day = self._measure(duplicate_day=False)
        self.assertEqual(seen, {})
        self.assertEqual(len(refusals), 1)
        self.assertIn("судья упал", refusals[0])


class ReportPrintsOnlyInflatingValuesTest(unittest.TestCase):
    def test_a_repeat_safe_value_is_not_printed_as_inflating(self):
        doc = {"status": J.STATUS_CRITICAL, "journal": {}, "families": {},
               "value_outcomes": {}, "forms": {}, "returns_today": {},
               "capacity": None, "fix_site": {}, "what_it_does_not_prove": [],
               "advisory": [],
               "values": [{"value": "раздувается", "outcome": J.VALUE_INFLATES,
                           "inflates_in": ["f"]},
                          {"value": "устойчива", "outcome": J.VALUE_REPEAT_SAFE},
                          {"value": "без сигнала", "outcome": J.VALUE_NO_SIGNAL}]}
        text = "\n".join(J.format_report(doc))
        self.assertIn("[РАЗДУВАЕТСЯ] раздувается", text)
        self.assertNotIn("устойчива", text)
        self.assertNotIn("без сигнала", text)


class SelfExclusionOnTheRealTreeTest(unittest.TestCase):
    """Прибор и судья не имеют права попасть в СВОЮ перепись читателей."""

    ROOT = Path(__file__).resolve().parents[2]

    def test_neither_the_judge_nor_this_instrument_appears_in_any_population(self):
        got = J.attribute_readers(self.ROOT)
        everywhere = (got["via_judge_module"] + got["via_judge_module_indirect"]
                      + got["own_copy_of_reference"] + got["own_method"]
                      + got["unresolved"])
        self.assertNotIn("spa_core/paper_trading/shadow_trigger_eval.py", everywhere)
        self.assertNotIn("spa_core/monitoring/judge_alone_price.py", everywhere,
                         "прибор читает `judge.load_history` сам — вход в перепись "
                         "изнутри переписи закрыт намеренно")
        self.assertTrue(got["via_judge_module"], "на живом дереве читатели ЕСТЬ")


class PopulationOrderDiscriminatesTest(unittest.TestCase):
    """Пять имён вместо двух: на паре порядок множества совпадал с сортировкой."""

    def test_sorted_is_distinguishable_from_set_order(self):
        tmp = Path(tempfile.mkdtemp(prefix="g18ord2_"))
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        (tmp / "spa_core/paper_trading").mkdir(parents=True)
        (tmp / "spa_core/paper_trading/shadow_trigger_eval.py").write_text(
            "def load_history(d, book_id=None):\n    return [], 0\n", encoding="utf-8")
        pkg = tmp / "pkg"
        pkg.mkdir()
        names = ["omega.py", "beta.py", "sigma.py", "alpha.py", "kappa.py",
                 "delta.py", "gamma.py"]
        for name in names:
            (pkg / name).write_text(
                "from spa_core.paper_trading.shadow_trigger_eval import load_history\n"
                "def f(d):\n    return load_history(d)\n", encoding="utf-8")
        got = J.attribute_readers(tmp)
        self.assertEqual(got["own_copy_of_reference"],
                         sorted(f"pkg/{n}" for n in names))


# ── Раунд 5 приёмки: порядок, умолчания и запасные ветви ─────────────────────

class EveryPopulationOrderDiscriminatesTest(unittest.TestCase):
    """Каждое из пяти населений — своя сортировка, и у каждого ≥3 имени.

    Четвёртая батарея показала, что `sorted` переживает подмену там, где в
    фикстуре было одно имя: проверка порядка на множестве из одного элемента
    не различает НИЧЕГО.
    """

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="g18pop_"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        (self.tmp / "spa_core/paper_trading").mkdir(parents=True)
        (self.tmp / "spa_core/paper_trading/shadow_trigger_eval.py").write_text(
            "def load_history(d, book_id=None):\n    return [], 0\n", encoding="utf-8")
        self.pkg = self.tmp / "pkg"
        self.pkg.mkdir()
        self.names = ["omega", "beta", "sigma", "alpha", "kappa"]

    def _spread(self, body: str) -> list:
        for n in self.names:
            (self.pkg / f"{n}.py").write_text(body, encoding="utf-8")
        return sorted(f"pkg/{n}.py" for n in self.names)

    def test_direct_readers_are_sorted(self):
        want = self._spread(
            "from spa_core.paper_trading import shadow_trigger_eval as ste\n"
            "def f(d):\n    return ste.load_history(d)\n")
        self.assertEqual(J.attribute_readers(self.tmp)["via_judge_module"], want)

    def test_indirect_readers_are_sorted(self):
        (self.tmp / "carrier.py").write_text(
            "from spa_core.paper_trading import shadow_trigger_eval as _ste\n",
            encoding="utf-8")
        want = self._spread(
            "import carrier as _dep\n"
            "def f(d):\n    return _dep._ste.load_history(d)\n")
        self.assertEqual(J.attribute_readers(self.tmp)["via_judge_module_indirect"], want)

    def test_own_method_files_are_sorted(self):
        want = self._spread(
            "class E:\n    def load_history(self):\n        return []\n"
            "    def go(self):\n        return self.load_history()\n")
        self.assertEqual(J.attribute_readers(self.tmp)["own_method"], want)

    def test_unresolved_files_are_sorted(self):
        want = self._spread("def f(engine):\n    return engine.load_history()\n")
        self.assertEqual(J.attribute_readers(self.tmp)["unresolved"], want)


class FormBucketOrderTest(unittest.TestCase):
    def test_the_three_buckets_are_each_sorted_by_value_name(self):
        tmp = Path(tempfile.mkdtemp(prefix="g18fb_"))
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        tree = tmp / "tree"
        (tree / "spa_core/paper_trading").mkdir(parents=True)
        (tree / "spa_core/paper_trading/shadow_trigger_eval.py").write_text(
            "def load_history(d, book_id=None):\n    return [], 0\n", encoding="utf-8")
        doc = J.measure(_data_dir(_journal(12), tmp / "src"), now=NOW, tree_root=tree,
                        stand_root=tmp / "stand", with_capacity=False)
        for form in J.FORMS:
            for key in ("sees_early_act", "blind_to_early_act", "unmeasured"):
                got = doc["forms"][form][key]
                self.assertEqual(got, sorted(got), f"{form}/{key} отдан не по порядку")
        self.assertGreater(len(doc["forms"][J.FORM_NULL]["blind_to_early_act"]), 2,
                           "на одном имени порядок не различается")


class FallbackFamilyTest(unittest.TestCase):
    """Нет оценённого дня — форма меряется по САМОМУ РАННЕМУ из доступных.

    Первая редакция этого теста звала выражение ``sorted(...)[0]`` РЯДОМ с
    `measure`, а не ЧЕРЕЗ него, — то есть проверяла свою же арифметику и была
    украшением в чистом виде (прицельная батарея это и показала: обе координаты
    выражения пережили её). Теперь ветвь достигается по-настоящему: журнал, в
    котором КАЖДЫЙ день тривиален, не даёт класса `scored_hold` вовсе.
    """

    def _trivial_journal(self, days: int = 12) -> list:
        # оборот ниже порога существенности ⇒ у судьи это `trivial`
        return [_row(_day(days - i), turnover=1.0,
                     cur={"aave_v3": 100_000.0}, tgt={"aave_v3": 100_000.0})
                for i in range(days)]

    def test_without_a_scored_family_the_forms_are_measured_on_the_earliest_day(self):
        tmp = Path(tempfile.mkdtemp(prefix="g18fb2_"))
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        tree = tmp / "tree"
        (tree / "spa_core/paper_trading").mkdir(parents=True)
        (tree / "spa_core/paper_trading/shadow_trigger_eval.py").write_text(
            "def load_history(d, book_id=None):\n    return [], 0\n", encoding="utf-8")
        rows = self._trivial_journal()
        seen_idx = []
        real = J.form_sees_act

        def recording(c, idx, *, form, values):
            seen_idx.append(idx)
            return real(c, idx, form=form, values=values)

        J.form_sees_act = recording
        self.addCleanup(lambda: setattr(J, "form_sees_act", real))
        doc = J.measure(_data_dir(rows, tmp / "src"), now=NOW, tree_root=tree,
                        stand_root=tmp / "stand", with_capacity=False)
        self.assertIn(J.FAMILY_SCORED_HOLD, doc["families_missing"],
                      "стенд не воспроизвёл журнал без оценённого дня")
        self.assertTrue(seen_idx, "формы не мерились вовсе")
        self.assertEqual(set(seen_idx), {min(doc_idx for doc_idx in seen_idx)},
                         "все три формы обязаны мериться на ОДНОМ дне")
        picked = list((doc["families"] or {}).values())  # имя семьи → ДАТА дня
        self.assertTrue(picked, "семей не нашлось вовсе — ветвь не достигнута")
        self.assertEqual(rows[seen_idx[0]]["cycle_date"], min(picked),
                         "запасной день — самый РАННИЙ из доступных семей")


class ReturnsTodayReasonTest(unittest.TestCase):
    def test_a_journal_without_second_rows_says_WHY_the_answer_is_zero(self):
        tmp = Path(tempfile.mkdtemp(prefix="g18rt_"))
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        tree = tmp / "tree"
        (tree / "spa_core/paper_trading").mkdir(parents=True)
        (tree / "spa_core/paper_trading/shadow_trigger_eval.py").write_text(
            "def load_history(d, book_id=None):\n    return [], 0\n", encoding="utf-8")
        doc = J.measure(_data_dir(_journal(12), tmp / "src"), now=NOW, tree_root=tree,
                        stand_root=tmp / "stand", with_capacity=False)
        self.assertEqual(doc["returns_today"]["act_days"], 0)
        self.assertIn("писатель удаляет раннюю строку",
                      doc["returns_today"]["reason"])

    def test_a_journal_WITH_second_rows_says_the_number_must_be_swept(self):
        tmp = Path(tempfile.mkdtemp(prefix="g18rt2_"))
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        tree = tmp / "tree"
        (tree / "spa_core/paper_trading").mkdir(parents=True)
        (tree / "spa_core/paper_trading/shadow_trigger_eval.py").write_text(
            "def load_history(d, book_id=None):\n    return [], 0\n", encoding="utf-8")
        rows = _journal(12)
        doc = J.measure(_data_dir(rows + [rows[4]], tmp / "src"), now=NOW,
                        tree_root=tree, stand_root=tmp / "stand", with_capacity=False)
        self.assertIsNone(doc["returns_today"]["act_days"])
        self.assertIn("считается перебором", doc["returns_today"]["reason"])
        self.assertEqual(doc["status"], J.STATUS_UNMEASURED,
                         "не измеренное число обязано красить вердикт, а не молчать")


class VerdictFallbackTest(unittest.TestCase):
    def test_capacity_with_ONLY_the_null_control_leaves_the_best_at_zero(self):
        doc = {"value_outcomes": {J.VALUE_INFLATES: 1}, "values_population": 2,
               "returns_today": {"act_days": 0},
               "capacity": {J.FORM_NULL: {"reaches_criterion": 3,
                                          "reaches_criterion_material": 3}}}
        head = J._verdict(doc)["headline"]
        self.assertIn("0 существенных", head)
        self.assertIn("нулевой контроль: 3", head)


class ReportFallbackTest(unittest.TestCase):
    def test_a_capacity_missing_one_form_prints_it_as_empty_not_crashes(self):
        doc = {"status": J.STATUS_CRITICAL, "journal": {}, "families": {},
               "value_outcomes": {}, "values": [],
               "forms": {}, "returns_today": {"act_days": 0, "reason": "—"},
               "capacity": {J.FORM_ANY_ACT: {"days_tested": 3,
                                             "reaches_criterion": 1,
                                             "reaches_criterion_material": 1,
                                             "reaches_criterion_material_net_positive": 0,
                                             "act_but_unscored": 0,
                                             "never_became_act": 2}},
               "fix_site": {}, "what_it_does_not_prove": [], "advisory": []}
        text = "\n".join(J.format_report(doc))
        self.assertIn(f"[В · ЁМКОСТЬ] {J.FORM_ANY_ACT}: из 3 дн.", text)
        self.assertIn(f"[В · НУЛЕВОЙ КОНТРОЛЬ] {J.FORM_NULL}: из None дн.", text)

    def test_families_and_counts_are_printed_in_order(self):
        doc = {"status": J.STATUS_CRITICAL,
               "journal": {"rows": 1, "days": 1, "days_with_second_row": []},
               "families": {"zeta": "d3", "alpha": "d1", "mid": "d2"},
               "value_outcomes": {"zeta": 1, "alpha": 2, "mid": 3},
               "values": [], "forms": {}, "returns_today": {"act_days": 0, "reason": "—"},
               "capacity": None, "fix_site": {}, "what_it_does_not_prove": [],
               "advisory": []}
        text = "\n".join(J.format_report(doc))
        self.assertIn("[СЕМЬИ] alpha=d1 · mid=d2 · zeta=d3", text)
        self.assertIn("alpha=2 · mid=3 · zeta=1", text)


class RunDefaultsTest(unittest.TestCase):
    def test_run_measures_capacity_unless_told_otherwise(self):
        tmp = Path(tempfile.mkdtemp(prefix="g18rd_"))
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        _data_dir(_journal(10), tmp)
        doc = J.run(root=str(tmp), now=NOW, write=False)
        self.assertIsNotNone(doc["capacity"], "ёмкость по умолчанию МЕРЯЕТСЯ")
        self.assertIn(J.FORM_NULL, doc["capacity"])
