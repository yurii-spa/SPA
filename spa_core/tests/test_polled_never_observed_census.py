# FROZEN-DATE-OK: даты ряда — ПРЕДМЕТ замера, а не отметка свежести.
# Модуль не сравнивает ни одну дату с часами: `now` уходит только в
# `generated_at`, вердикт от календаря не зависит ни одной веткой. Литералы
# ниже суть входные данные окна ряда (как golden-файл парсинга), и заменить их
# относительными отметками значило бы сделать предмет плавающим.
"""Приёмка переписи «опрашиваем и не слышали ни разу» (заказ #597/G11).

Каждый тест — положительный контроль на дефект, который замер изготовил бы при
иначе написанном правиле. Ни один не проверяет структуру ради структуры.
"""
from __future__ import annotations

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from spa_core.monitoring import polled_never_observed_census as C


def _series(mapping: dict) -> dict:
    return {"generated_at": "2026-09-13T13:46:16+00:00",
            "source": "apy_series_accumulator (daily cycle hook)",
            "series": mapping}


def _producer(keys) -> dict:
    if isinstance(keys, dict):
        return {"adapters": keys}
    return {"adapters": {k: {"live_apy": 4.0, "apy": 4.0} for k in keys}}


def _book(positions: dict) -> dict:
    return {"generated_at": "2026-09-13T13:45:39+00:00", "positions": positions}


class _Base(unittest.TestCase):
    def setUp(self):
        self._tmp = TemporaryDirectory()
        self.dd = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)

    def write(self, *, series=None, producer=None, book=None):
        if series is not None:
            (self.dd / C.SERIES_FILENAME).write_text(json.dumps(series))
        if producer is not None:
            (self.dd / C.PRODUCER_FILENAME).write_text(json.dumps(producer))
        if book is not None:
            (self.dd / C.BOOK_FILENAME).write_text(json.dumps(book))

    def polled(self, pairs):
        """Подменить население переписи, не трогая POLLED_ADAPTERS."""
        original = C.polled_universe
        C.polled_universe = lambda: list(pairs)  # type: ignore[assignment]
        self.addCleanup(lambda: setattr(C, "polled_universe", original))


class TestOutcomes(_Base):
    """Четыре исхода по протоколу существуют и НЕ сливаются (инв. #17)."""

    def test_polled_key_at_producer_with_no_series_key_is_never_observed(self):
        """Предмет заказа: опрашиваем, производитель его знает, точек нет ни одной."""
        self.polled([("pendle", "T2"), ("aave_v3", "T1")])
        self.write(series=_series({"aave_v3": [["2026-08-06", 3.5]]}),
                   producer=_producer(["pendle", "aave_v3"]),
                   book=_book({"aave_v3": 5000.0}))
        doc = C.measure(self.dd)
        self.assertEqual(doc["answer"]["never_observed"], ["pendle"])
        row = next(r for r in doc["per_protocol"] if r["protocol"] == "pendle")
        self.assertEqual(row["outcome"], C.OUT_NEVER_OBSERVED)

    def test_one_parsed_point_is_enough_to_be_observed(self):
        self.polled([("maple", "T2")])
        self.write(series=_series({"maple": [["2026-08-06", 4.9]]}),
                   producer=_producer(["maple"]), book=_book({}))
        doc = C.measure(self.dd)
        self.assertEqual(doc["answer"]["never_observed"], [])
        self.assertEqual(doc["population"]["outcomes"][C.OUT_OBSERVED], 1)

    def test_unreadable_rows_are_UNMEASURED_not_silence(self):
        """Ключ в ряду есть, разобранных точек нет — это наш разбор, не фид.

        Слив этих двух исходов записал бы нечитаемую строку протоколу в долг и
        объявил бы молчащим того, о ком сказать нечего.
        """
        self.polled([("euler_v2", "T2"), ("maple", "T2")])
        self.write(series=_series({"euler_v2": [["2026-08-06", None], ["oops"]],
                                   "maple": [["2026-08-06", 4.9]]}),
                   producer=_producer(["euler_v2", "maple"]), book=_book({}))
        doc = C.measure(self.dd)
        row = next(r for r in doc["per_protocol"] if r["protocol"] == "euler_v2")
        self.assertEqual(row["outcome"], C.OUT_ROW_UNREADABLE)
        self.assertNotIn("euler_v2", doc["answer"]["never_observed"])
        self.assertEqual(doc["answer"]["unmeasured_count"], 1)

    def test_key_absent_from_producer_is_UNMEASURED_not_silence(self):
        """Накопителю ключ не предъявляли — «точек нет» о фиде не говорит ничего."""
        self.polled([("ghost", "T3"), ("maple", "T2")])
        self.write(series=_series({"maple": [["2026-08-06", 4.9]]}),
                   producer=_producer(["maple"]), book=_book({}))
        doc = C.measure(self.dd)
        row = next(r for r in doc["per_protocol"] if r["protocol"] == "ghost")
        self.assertEqual(row["outcome"], C.OUT_OUTSIDE_PRODUCER)
        self.assertEqual(doc["answer"]["never_observed"], [])
        self.assertEqual(doc["answer"]["unmeasured_count"], 1)

    def test_four_outcomes_are_four_distinct_values(self):
        names = {C.OUT_OBSERVED, C.OUT_NEVER_OBSERVED,
                 C.OUT_ROW_UNREADABLE, C.OUT_OUTSIDE_PRODUCER}
        self.assertEqual(len(names), 4)
        self.assertEqual(set(C.PROVEN_SILENT) & set(C.UNMEASURED_OUTCOMES), set())

    def test_non_finite_value_is_not_a_point(self):
        """Правило «что такое точка» чужое, и оно обязано действовать здесь."""
        # Второй протокол несёт настоящую точку: иначе в ряду не осталось бы
        # разобранных точек ни у кого и прибор отказал бы по ОКНУ, а предметом
        # этого теста является строка, а не окно.
        self.polled([("maple", "T2"), ("aave_v3", "T1")])
        self.write(series=_series({"maple": [["2026-08-06", "4.9"]],
                                   "aave_v3": [["2026-08-06", 3.5]]}),
                   producer=_producer(["maple", "aave_v3"]), book=_book({}))
        doc = C.measure(self.dd)
        row = next(r for r in doc["per_protocol"] if r["protocol"] == "maple")
        self.assertEqual(row["outcome"], C.OUT_ROW_UNREADABLE)


class TestSeriesRuleIsBorrowed(_Base):
    """Форму ряда разбирает ОДНО место — и проверяется это ИСХОДОМ."""

    def test_module_routes_through_the_single_owner_of_the_series_format(self):
        """Подменяем чужой разборщик — ответ обязан измениться.

        Проверка по подстроке («в тексте есть `series_points`») пережила бы любое
        расплетение: копия правила рядом дала бы тот же текст и другой ответ.
        """
        self.polled([("maple", "T2")])
        self.write(series=_series({"maple": [["2026-08-06", 4.9]]}),
                   producer=_producer(["maple"]), book=_book({}))
        self.assertEqual(C.measure(self.dd)["population"]["outcomes"][C.OUT_OBSERVED], 1)

        original = C._jbm.series_points
        C._jbm.series_points = lambda series: {}  # type: ignore[assignment]
        try:
            doc = C.measure(self.dd)
        finally:
            C._jbm.series_points = original
        # Ряд «опустел» только потому, что чужой разборщик так сказал.
        self.assertEqual(doc["status"], C.STATUS_UNMEASURED)


class TestSilenceDuration(_Base):
    def test_silence_is_the_window_content_not_the_ring_capacity(self):
        """«Не звучал 800 дней» утверждало бы знание о днях, которых не было."""
        self.polled([("pendle", "T2"), ("maple", "T2")])
        self.write(series=_series({"maple": [["2026-08-06", 4.9],
                                             ["2026-08-07", 4.8]]}),
                   producer=_producer(["pendle", "maple"]), book=_book({}))
        doc = C.measure(self.dd)
        row = next(r for r in doc["per_protocol"] if r["protocol"] == "pendle")
        self.assertEqual(row["silent_days"], 2)
        self.assertNotEqual(row["silent_days"], doc["series_window"]["ring_capacity_days"])

    def test_days_before_the_window_are_named_unmeasured_not_silent(self):
        self.polled([("pendle", "T2"), ("maple", "T2")])
        self.write(series=_series({"maple": [["2026-08-06", 4.9]]}),
                   producer=_producer(["pendle", "maple"]), book=_book({}))
        row = next(r for r in C.measure(self.dd)["per_protocol"]
                   if r["protocol"] == "pendle")
        self.assertEqual(row["unmeasured_before"], "2026-08-06")

    def test_a_day_nobody_wrote_is_not_charged_to_the_silent_protocol(self):
        """Молчание накопителя — не молчание фида конкретного протокола.

        Окно считается по датам, на которых точку принял ХОТЬ КТО-ТО; иначе
        дырка в работе цикла записывалась бы протоколу в долг.
        """
        self.polled([("pendle", "T2"), ("maple", "T2")])
        self.write(series=_series({"maple": [["2026-08-06", 4.9],
                                             ["2026-08-09", 4.7]]}),
                   producer=_producer(["pendle", "maple"]), book=_book({}))
        row = next(r for r in C.measure(self.dd)["per_protocol"]
                   if r["protocol"] == "pendle")
        # 07 и 08 не писал никто — в долг они не идут.
        self.assertEqual(row["silent_days"], 2)


class TestPriceInDollars(_Base):
    def test_money_on_a_never_observed_rate_is_CRITICAL(self):
        self.polled([("pendle", "T2"), ("maple", "T2")])
        self.write(series=_series({"maple": [["2026-08-06", 4.9]]}),
                   producer=_producer(["pendle", "maple"]),
                   book=_book({"pendle": 20000.0, "maple": 20000.0}))
        doc = C.measure(self.dd)
        self.assertEqual(doc["status"], C.STATUS_CRITICAL)
        self.assertEqual(doc["answer"]["never_observed_usd"], 20000.0)
        self.assertEqual(doc["answer"]["never_observed_pct_of_deployed"], 50.0)
        self.assertTrue(any(x.startswith("[CRITICAL]") for x in doc["findings"]))

    def test_silent_protocol_without_money_is_WARNING_not_CRITICAL_and_not_OK(self):
        """Замер 13.09 именно такой, и завышать его до CRITICAL нельзя.

        Молчащий без денег — дефект проводки; молчащий под капиталом — дефект
        решения о деньгах. Один цвет на оба утопил бы второй.
        """
        self.polled([("pendle", "T2"), ("maple", "T2")])
        self.write(series=_series({"maple": [["2026-08-06", 4.9]]}),
                   producer=_producer(["pendle", "maple"]),
                   book=_book({"maple": 20000.0}))
        doc = C.measure(self.dd)
        self.assertEqual(doc["status"], C.STATUS_WARNING)
        self.assertEqual(doc["answer"]["never_observed_usd"], 0.0)
        self.assertEqual(doc["answer"]["never_observed_count"], 1)

    def test_no_silent_protocols_at_all_is_OK(self):
        self.polled([("maple", "T2")])
        self.write(series=_series({"maple": [["2026-08-06", 4.9]]}),
                   producer=_producer(["maple"]), book=_book({"maple": 1.0}))
        self.assertEqual(C.measure(self.dd)["status"], C.STATUS_OK)

    def test_money_on_a_key_the_cycle_never_polls_and_never_saw_is_CRITICAL(self):
        """Деньги стоят там, где стоят — и спрашивать надо у книги, не у списка."""
        self.polled([("maple", "T2")])
        self.write(series=_series({"maple": [["2026-08-06", 4.9]]}),
                   producer=_producer(["maple"]),
                   book=_book({"maple": 10000.0, "mystery_pool": 30000.0}))
        doc = C.measure(self.dd)
        self.assertEqual(doc["status"], C.STATUS_CRITICAL)
        self.assertEqual(doc["answer"]["book_blind_keys"], ["mystery_pool"])
        self.assertEqual(doc["answer"]["book_blind_usd"], 30000.0)

    def test_unpolled_book_key_that_IS_in_the_series_is_not_called_blind(self):
        self.polled([("maple", "T2")])
        self.write(series=_series({"maple": [["2026-08-06", 4.9]],
                                   "sdai": [["2026-08-06", 4.1]]}),
                   producer=_producer(["maple", "sdai"]),
                   book=_book({"maple": 10000.0, "sdai": 30000.0}))
        doc = C.measure(self.dd)
        self.assertEqual(doc["answer"]["book_blind_keys"], [])
        row = next(r for r in doc["book"] if r["protocol"] == "sdai")
        self.assertEqual(row["book_outcome"], C.BOOK_NOT_POLLED)
        self.assertEqual(row["series_outcome"], C.OUT_OBSERVED)


class TestNameResemblance(_Base):
    def test_a_lookalike_key_does_not_lend_its_points(self):
        """`pendle_pt_susde` с полным рядом НЕ делает `pendle` наблюдённым.

        Родство ключей доказывается сторожем второй записи, а не похожестью
        имён; слияние этих объектов перевернуло бы ответ (ADR-378).
        """
        self.polled([("pendle", "T2")])
        self.write(series=_series({"pendle_pt_susde": [["2026-08-06", 4.8]]}),
                   producer=_producer(["pendle", "pendle_pt_susde"]),
                   book=_book({}))
        doc = C.measure(self.dd)
        self.assertEqual(doc["answer"]["never_observed"], ["pendle"])


class TestThirdOutcome(_Base):
    """Спросить было нечем ≠ молчащих нет. Каждый вход отказывает ГРОМКО."""

    def test_missing_series_refuses_with_a_reason(self):
        self.polled([("maple", "T2")])
        self.write(producer=_producer(["maple"]), book=_book({}))
        doc = C.measure(self.dd)
        self.assertEqual(doc["status"], C.STATUS_UNMEASURED)
        self.assertFalse(doc["answer"]["measured"])
        self.assertIn(C.SERIES_FILENAME, doc["answer"]["reason"])

    def test_missing_producer_refuses_and_does_not_call_everything_silent(self):
        """Без вселенной производителя каждый ключ выглядел бы «молчащим»."""
        self.polled([("maple", "T2")])
        self.write(series=_series({"maple": [["2026-08-06", 4.9]]}), book=_book({}))
        doc = C.measure(self.dd)
        self.assertEqual(doc["status"], C.STATUS_UNMEASURED)
        self.assertNotIn("never_observed", doc["answer"])

    def test_book_without_positions_map_refuses_instead_of_substituting_zero(self):
        """Ноль вместо цены был бы ответом «денег на молчащих нет» (инв. #17)."""
        self.polled([("maple", "T2")])
        self.write(series=_series({"maple": [["2026-08-06", 4.9]]}),
                   producer=_producer(["maple"]),
                   book={"generated_at": "2026-09-13T13:45:39+00:00"})
        doc = C.measure(self.dd)
        self.assertEqual(doc["status"], C.STATUS_UNMEASURED)
        self.assertIn(C.BOOK_FILENAME, doc["answer"]["reason"])

    def test_empty_polled_list_refuses(self):
        self.polled([])
        self.write(series=_series({"maple": [["2026-08-06", 4.9]]}),
                   producer=_producer(["maple"]), book=_book({}))
        self.assertEqual(C.measure(self.dd)["status"], C.STATUS_UNMEASURED)

    def test_series_with_no_parsed_point_from_anyone_refuses(self):
        """Окна молчания не существует — и это НЕ «все молчат 0 дней»."""
        self.polled([("maple", "T2")])
        self.write(series=_series({"maple": [["oops"]]}),
                   producer=_producer(["maple"]), book=_book({}))
        doc = C.measure(self.dd)
        self.assertEqual(doc["status"], C.STATUS_UNMEASURED)


class TestAdmissionRule(_Base):
    """Правило допуска МЕРЯЕТСЯ у производителя, а не пересказывается словами."""

    def test_key_present_as_null_is_refused_key_absent_would_be_admitted(self):
        self.polled([("a", "T2")])
        self.write(series=_series({"a": [["2026-08-06", 4.0]]}),
                   producer=_producer({
                       "a": {"live_apy": 4.0, "apy": 4.0},
                       "null_key": {"live_apy": None, "apy": 8.0},
                       "no_key": {"apy": 7.0},
                   }),
                   book=_book({}))
        adm = C.measure(self.dd)["admission_rule"]
        self.assertEqual(adm["key_null_finite_apy_REFUSED"], ["null_key"])
        self.assertEqual(adm["key_absent_finite_apy_ADMITTED"], ["no_key"])
        self.assertEqual(adm["live_apy_finite"], 1)

    def test_empty_admitted_class_is_a_measured_zero_not_a_missing_check(self):
        self.polled([("a", "T2")])
        self.write(series=_series({"a": [["2026-08-06", 4.0]]}),
                   producer=_producer({"a": {"live_apy": 4.0, "apy": 4.0}}),
                   book=_book({}))
        doc = C.measure(self.dd)
        self.assertTrue(doc["admission_rule"]["measured"])
        self.assertEqual(doc["admission_rule"]["key_absent_finite_apy_ADMITTED"], [])
        self.assertTrue(any("измеренный ноль" in x for x in doc["findings"]))


class TestSurvivorsOfTheBattery(_Base):
    """Пять тестов, каждый закрывает МУТАЦИЮ, пережившую первый прогон батареи.

    Батарея нашла их не потому, что модуль плох, а потому, что мои сцены не
    спрашивали о его собственных утверждениях: население бралось подменой,
    поимённый вывод не читался никем, а отказы различались только по цвету.
    """

    def test_population_is_POLLED_ADAPTERS_itself_not_a_neighbouring_registry(self):
        """Центральное утверждение модуля — и НИ ОДИН тест его не спрашивал.

        Все сцены подменяют `polled_universe`, поэтому настоящая функция не
        исполнялась ни разу: контроль, истинный по построению, есть украшение.
        Рядом живут ещё два набора с другим составом (`.claude/rules/adapters.md`),
        и перепись по ним ответила бы на чужой вопрос.
        """
        from spa_core.orchestrator.adapter_orchestrator import POLLED_ADAPTERS
        from spa_core.adapters import ADAPTER_REGISTRY

        got = C.polled_universe()
        self.assertEqual(got, [(str(k), str(t)) for k, t, _c in POLLED_ADAPTERS])
        # И это ДРУГОЙ набор, чем соседний реестр — иначе проверка выше пуста.
        self.assertNotEqual(len(got), len(ADAPTER_REGISTRY))

    def test_report_names_the_silent_protocol_its_days_and_its_dollars(self):
        """Заказ требует ПОИМЁННО; отчёт без имени отвечал бы не на тот вопрос."""
        self.polled([("pendle", "T2"), ("maple", "T2")])
        self.write(series=_series({"maple": [["2026-08-06", 4.9],
                                             ["2026-08-07", 4.8]]}),
                   producer=_producer(["pendle", "maple"]),
                   book=_book({"pendle": 20000.0, "maple": 20000.0}))
        line = next(x for x in C.measure(self.dd)["findings"]
                    if x.startswith("[ПОИМЁННО]"))
        self.assertIn("pendle", line)
        self.assertIn("2 дн.", line)
        self.assertIn("$20,000.00", line)
        self.assertIn("2026-08-06..2026-08-07", line)

    def test_unreadable_series_and_an_empty_one_give_DIFFERENT_reasons(self):
        """Оба отказывают, но диагнозы разные: файл против накопителя.

        Слив их в один цвет отправил бы читателя чинить не то место.
        """
        self.polled([("maple", "T2")])
        # (а) файла нет вовсе
        self.write(producer=_producer(["maple"]), book=_book({}))
        absent = C.measure(self.dd)["answer"]["reason"]
        # (б) файл есть и читается, но точек не принял никто
        self.write(series=_series({"maple": []}))
        empty = C.measure(self.dd)["answer"]["reason"]
        self.assertEqual(C.measure(self.dd)["status"], C.STATUS_UNMEASURED)
        self.assertNotEqual(absent, empty)
        self.assertIn("не прочитан", absent)
        self.assertIn("ни одной разобранной точки", empty)

    def test_admission_rule_reports_unmeasured_as_unmeasured(self):
        """Ветка недостижима из `measure` — значит спрашивать надо прямо.

        Объявив непрочитанное измеренным с нулями, отчёт сказал бы «потолок
        пуст» там, где никто не смотрел (инв. #17).
        """
        (self.dd / C.PRODUCER_FILENAME).write_text(json.dumps({"нет": "adapters"}))
        adm = C.admission_rule_exposure(self.dd)
        self.assertFalse(adm["measured"])
        self.assertIn("adapters", adm["reason"])
        self.assertNotIn("key_absent_finite_apy_ADMITTED", adm)

    def test_status_fails_loudly_on_a_malformed_answer_instead_of_saying_OK(self):
        """Прямой ключ, а не `.get(...) or 0`.

        Ответ не той формы — ошибка вызывающего; объявить его OK значило бы
        сделать «счёта нет» неотличимым от «измерено и равно нулю» у того
        самого числа, которое решает вердикт.

        Сцена подобрана ТОЧНО под решающую строку: пустой `answer` ронял бы
        `_status` на следующей же строке, и подстановка в первой прошла бы
        незамеченной — батарея поймала ровно это.
        """
        for missing in ("never_observed_usd", "book_blind_usd"):
            answer = {"never_observed_usd": 0.0, "book_blind_usd": 0.0,
                      "never_observed_count": 0, "unmeasured_count": 0}
            del answer[missing]
            with self.subTest(missing=missing):
                with self.assertRaises(KeyError):
                    C._status({"answer": answer})


class TestReportAndWiring(_Base):
    def test_unchecked_counts_unmeasured_separately_from_zeros(self):
        """Растворив «не измерено» в нулях, отчёт стал бы неотличим от чистого."""
        (self.dd / "data").mkdir()
        for name, payload in ((C.SERIES_FILENAME, _series({"maple": [["2026-08-06", 4.9]]})),
                              (C.PRODUCER_FILENAME, _producer(["maple"])),
                              (C.BOOK_FILENAME, _book({"maple": 1.0}))):
            (self.dd / "data" / name).write_text(json.dumps(payload))
        self.polled([("ghost", "T3"), ("maple", "T2")])
        doc = C.run(root=str(self.dd))
        self.assertEqual(doc["answer"]["never_observed_count"], 0)
        self.assertEqual(doc["answer"]["unmeasured_count"], 1)
        self.assertGreater(doc["counts"]["unchecked"], 0)

    def test_run_writes_the_artifact_and_publishes_overall(self):
        (self.dd / "data").mkdir()
        for name, payload in ((C.SERIES_FILENAME, _series({"maple": [["2026-08-06", 4.9]]})),
                              (C.PRODUCER_FILENAME, _producer(["maple", "pendle"])),
                              (C.BOOK_FILENAME, _book({"maple": 1.0}))):
            (self.dd / "data" / name).write_text(json.dumps(payload))
        self.polled([("maple", "T2"), ("pendle", "T2")])
        doc = C.run(root=str(self.dd))
        written = json.loads((self.dd / "data" / C.OUTPUT_FILENAME).read_text())
        self.assertEqual(written["overall"], doc["status"])
        self.assertEqual(doc["overall"], C.STATUS_WARNING)
        self.assertEqual(written["answer"]["never_observed"], ["pendle"])

    def test_refusal_still_carries_findings_for_the_office_step(self):
        """Отказ без строк читался бы шагом 0-офис как чистый прогон."""
        self.polled([("maple", "T2")])
        self.write(producer=_producer(["maple"]), book=_book({}))
        doc = C.measure(self.dd)
        self.assertTrue(C.format_report(doc))
        self.assertTrue(doc["findings"][0].startswith("[НЕ ИЗМЕРЕНО]"))


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
