"""Тесты `capital_evidence_coverage` — приёмка §5 ТЗ владельца «Portfolio CIO».

Каждый тест — положительный контроль: воспроизводит состояние, которое система
уже принимала или способна принять ПО ПОСТРОЕНИЮ кода, и краснеет, если сторож
перестанет его различать.

Время — ВХОД (`now=`), а не окружение: ни один тест не зависит от календаря.
"""

from __future__ import annotations

import datetime as dt
import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from spa_core.monitoring import capital_evidence_coverage as cec

# FROZEN-DATE-OK: injected-clock — NOW передаётся в measure/run/history параметром
# `now=`, а все отметки книг производит ts() от этого же NOW; календарь хоста не
# участвует ни в одном тесте файла.
NOW = dt.datetime(2026, 9, 4, 18, tzinfo=dt.timezone.utc)


def ts(hours_ago: float = 0.0) -> str:
    return (NOW - dt.timedelta(hours=hours_ago)).isoformat()


def book(positions, sources=None, *, hours_ago=0.0, live_pct=100.0, **extra):
    doc = {
        "generated_at": ts(hours_ago),
        "cash_usd": 5000.0,
        "positions": positions,
        "feed_coverage": {
            "live_pct": live_pct,
            "apy_sources": dict(sources or {}),
            "apy_used_pct": {},
            "blocked": {},
        },
    }
    doc["feed_coverage"].update(extra.pop("feed_coverage", {}))
    doc.update(extra)
    return doc


class TestHealthyBook(unittest.TestCase):
    def test_todays_real_book_reads_100_percent(self):
        """Замер 04.09 живой книги: $95k, все пять позиций с провенансом `live`."""
        rep = cec.measure(
            book(
                {
                    "compound_v3": 40000.0,
                    "fluid_usdc": 20000.0,
                    "maple": 20000.0,
                    "morpho_blue_base": 10000.0,
                    "aave_v3": 5000.0,
                },
                {
                    "compound_v3": "live",
                    "fluid_usdc": "live",
                    "maple": "live",
                    "morpho_blue_base": "live",
                    "aave_v3": "live",
                },
            ),
            now=NOW,
        )
        self.assertEqual(rep["verdict"], cec.OK)
        self.assertEqual(rep["capital_coverage_pct"], 100.0)
        self.assertEqual(rep["deployed_usd"], 95000.0)
        self.assertEqual(rep["usd"]["evidenced"], 95000.0)
        self.assertEqual(rep["usd"]["unmeasured"], 0)
        self.assertEqual(cec.exit_code(rep), 0)

    def test_baseline_and_target_travel_in_the_artifact(self):
        """Цель приёмки едет В отчёте: читатель не ходит за ней в документ."""
        rep = cec.measure(book({"aave_v3": 1000.0}, {"aave_v3": "live"}), now=NOW)
        self.assertEqual(rep["target_pct"], 100.0)
        self.assertEqual(rep["baseline_pct"], 25.0)
        self.assertIn("RS-portfolio-cio-diagnosis", rep["baseline_note"])


class TestHeldButUnevidenced(unittest.TestCase):
    """TestHeldButUnevidenced"""

    def test_position_absent_from_apy_sources_is_a_third_outcome(self):
        rep = cec.measure(
            book(
                {"aave_v3": 60000.0, "frax": 20000.0},
                {"aave_v3": "live"},
                feed_coverage={"blocked": {"frax": "unevidenced"}},
            ),
            now=NOW,
        )
        self.assertEqual(rep["verdict"], cec.UNCHECKED)
        self.assertEqual(rep["usd"]["unmeasured"], 20000.0)
        self.assertEqual(rep["usd"]["evidenced"], 60000.0)
        self.assertEqual(cec.exit_code(rep), 2)

    def test_unmeasured_dollar_is_never_counted_as_evidenced(self):
        """Ровно тот fail-OPEN, против которого написан контур."""
        rep = cec.measure(
            book({"aave_v3": 60000.0, "frax": 20000.0}, {"aave_v3": "live"}), now=NOW
        )
        self.assertEqual(rep["capital_coverage_pct"], 75.0)
        self.assertNotEqual(rep["capital_coverage_pct"], 100.0)

    def test_the_unmeasured_dollar_is_named_with_a_reason(self):
        rep = cec.measure(book({"frax": 20000.0}, {}), now=NOW)
        rows = [r for r in rep["by_protocol"] if r["protocol"] == "frax"]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["bucket"], "unmeasured")
        self.assertIn("НЕ ИЗМЕРЕНО", rows[0]["message"])

    def test_unknown_provenance_label_is_unmeasured_not_evidenced(self):
        """Незнакомая метка — повод сказать «не знаю», а не угадать в пользу входа."""
        rep = cec.measure(
            book({"aave_v3": 10000.0}, {"aave_v3": "probably_live"}), now=NOW
        )
        self.assertEqual(rep["usd"]["unmeasured"], 10000.0)
        self.assertEqual(rep["verdict"], cec.UNCHECKED)


class TestLabelledLiteral(unittest.TestCase):
    def test_capital_on_a_labelled_literal_is_its_own_bucket(self):
        """`fallback_stale` — не «не измерено» и не «наблюдение»: деньги стоят на
        числе, честно названном старым. Слить его с любой соседней корзиной
        значило бы потерять именно ту починку, которая нужна."""
        rep = cec.measure(
            book(
                {"aave_v3": 60000.0, "sdai": 20000.0},
                {"aave_v3": "live", "sdai": "fallback_stale"},
            ),
            now=NOW,
        )
        self.assertEqual(rep["verdict"], cec.WARN)
        self.assertEqual(rep["usd"]["literal"], 20000.0)
        self.assertEqual(rep["usd"]["unmeasured"], 0.0)
        self.assertEqual(rep["capital_coverage_pct"], 75.0)
        self.assertEqual(cec.exit_code(rep), 1)

    def test_unmeasured_outranks_literal_in_the_verdict(self):
        """Fail-CLOSED: «не знаю» громче, чем «знаю, что старое»."""
        rep = cec.measure(
            book({"a": 10000.0, "b": 10000.0}, {"a": "fallback_stale"}), now=NOW
        )
        self.assertEqual(rep["verdict"], cec.UNCHECKED)
        self.assertEqual(cec.exit_code(rep), 2)


class TestTheTwinNumber(unittest.TestCase):
    """TestTheTwinNumber"""

    def test_live_adapters_high_while_capital_coverage_is_zero(self):
        rep = cec.measure(
            book(
                {"frax": 80000.0},
                {"aave_v3": "live", "maple": "live"},
                live_pct=95.0,
            ),
            now=NOW,
        )
        self.assertEqual(rep["capital_coverage_pct"], 0.0)
        self.assertEqual(rep["adapters_live_pct"], 95.0)
        self.assertEqual(rep["divergence_pp"], 95.0)

    def test_live_adapters_low_while_capital_coverage_is_full(self):
        """Обратное направление — тоже авария: красный `live_pct` звал бы чинить
        то, что деньгам сейчас не мешает."""
        rep = cec.measure(
            book({"aave_v3": 80000.0}, {"aave_v3": "live"}, live_pct=50.0), now=NOW
        )
        self.assertEqual(rep["capital_coverage_pct"], 100.0)
        self.assertEqual(rep["divergence_pp"], -50.0)

    def test_missing_twin_is_none_not_zero(self):
        doc = book({"aave_v3": 100.0}, {"aave_v3": "live"})
        doc["feed_coverage"].pop("live_pct")
        rep = cec.measure(doc, now=NOW)
        self.assertIsNone(rep["adapters_live_pct"])
        self.assertIsNone(rep["divergence_pp"])


class TestEmptyBookIsNotFullCoverage(unittest.TestCase):
    def test_all_cash_book_is_unchecked_not_100(self):
        """0 из 0 — не «полное покрытие». Иначе книга-всё-в-кэше (HARD_KILL)
        давала бы самый зелёный отчёт за всю историю."""
        rep = cec.measure(book({}, {}), now=NOW)
        self.assertEqual(rep["verdict"], cec.UNCHECKED)
        self.assertIsNone(rep["capital_coverage_pct"])
        self.assertEqual(cec.exit_code(rep), 2)
        self.assertTrue(any("НЕ ОПРЕДЕЛЕНА" in r for r in rep["unchecked"]))

    def test_closed_positions_do_not_enter_the_denominator(self):
        """Ноль долларов — строка истории, а не капитал."""
        rep = cec.measure(
            book({"aave_v3": 50000.0, "sdai": 0.0}, {"aave_v3": "live"}), now=NOW
        )
        self.assertEqual(rep["deployed_usd"], 50000.0)
        self.assertEqual(rep["capital_coverage_pct"], 100.0)


class TestFailClosedInputs(unittest.TestCase):
    def test_stale_book_refuses_to_speak_in_the_present_tense(self):
        rep = cec.measure(
            book({"aave_v3": 100.0}, {"aave_v3": "live"}, hours_ago=48.0), now=NOW
        )
        self.assertEqual(rep["verdict"], cec.UNCHECKED)
        self.assertTrue(any("stale_input" in r for r in rep["unchecked"]))

    def test_book_without_a_timestamp_is_unchecked(self):
        doc = book({"aave_v3": 100.0}, {"aave_v3": "live"})
        doc.pop("generated_at")
        self.assertEqual(cec.measure(doc, now=NOW)["verdict"], cec.UNCHECKED)

    def test_missing_apy_sources_is_unmeasured_not_zero_live(self):
        doc = book({"aave_v3": 100.0}, {})
        doc["feed_coverage"].pop("apy_sources")
        rep = cec.measure(doc, now=NOW)
        self.assertEqual(rep["verdict"], cec.UNCHECKED)
        self.assertIsNone(rep["capital_coverage_pct"])

    def test_missing_positions_section_is_unchecked(self):
        doc = book({"a": 1.0}, {"a": "live"})
        doc.pop("positions")
        self.assertEqual(cec.measure(doc, now=NOW)["verdict"], cec.UNCHECKED)

    def test_non_numeric_position_size_is_unchecked_not_skipped(self):
        """Молча пропустить позицию значило бы уменьшить знаменатель и поднять долю."""
        rep = cec.measure(
            book({"aave_v3": 50000.0, "maple": "20k"}, {"aave_v3": "live", "maple": "live"}),
            now=NOW,
        )
        self.assertEqual(rep["verdict"], cec.UNCHECKED)
        self.assertIsNone(rep["capital_coverage_pct"])

    def test_bool_is_not_a_dollar_amount(self):
        rep = cec.measure(book({"aave_v3": True}, {"aave_v3": "live"}), now=NOW)
        self.assertEqual(rep["verdict"], cec.UNCHECKED)

    def test_book_that_is_not_an_object(self):
        self.assertEqual(cec.measure([], now=NOW)["verdict"], cec.UNCHECKED)

    def test_exit_code_of_a_report_without_a_verdict_is_two(self):
        """Храповик fail-OPEN: `report.get("verdict") or OK` дало бы зачёт."""
        self.assertEqual(cec.exit_code({}), 2)
        self.assertEqual(cec.exit_code({"verdict": None}), 2)


class TestRunReadsAndWrites(unittest.TestCase):
    def _dir(self, tmp, doc):
        base = Path(tmp) / "data"
        base.mkdir(parents=True, exist_ok=True)
        (base / "current_positions.json").write_text(json.dumps(doc), encoding="utf-8")
        return str(base)

    def test_missing_book_is_unchecked_not_a_clean_pass(self):
        with TemporaryDirectory() as tmp:
            base = Path(tmp) / "data"
            base.mkdir()
            rep = cec.run(data_dir=str(base), now=NOW)
            self.assertEqual(rep["verdict"], cec.UNCHECKED)
            self.assertEqual(cec.exit_code(rep), 2)

    def test_unparseable_book_is_unchecked(self):
        with TemporaryDirectory() as tmp:
            base = Path(tmp) / "data"
            base.mkdir()
            (base / "current_positions.json").write_text("{ broken", encoding="utf-8")
            rep = cec.run(data_dir=str(base), now=NOW)
            self.assertEqual(rep["verdict"], cec.UNCHECKED)

    def test_report_is_written_where_declared(self):
        with TemporaryDirectory() as tmp:
            base = self._dir(tmp, book({"aave_v3": 100.0}, {"aave_v3": "live"}))
            cec.run(data_dir=base, now=NOW)
            written = json.loads(
                (Path(base) / "capital_evidence_coverage.json").read_text(encoding="utf-8")
            )
            self.assertEqual(written["capital_coverage_pct"], 100.0)
            self.assertEqual(
                written["generated_by"],
                "spa_core/monitoring/capital_evidence_coverage.py",
            )

    def test_no_write_leaves_no_artifact(self):
        with TemporaryDirectory() as tmp:
            base = self._dir(tmp, book({"aave_v3": 100.0}, {"aave_v3": "live"}))
            cec.run(data_dir=base, now=NOW, write=False)
            self.assertFalse((Path(base) / "capital_evidence_coverage.json").exists())


class TestMemoryCountsBooksNotRuns(unittest.TestCase):
    def _base(self, tmp, doc):
        base = Path(tmp) / "data"
        base.mkdir(parents=True, exist_ok=True)
        (base / "current_positions.json").write_text(json.dumps(doc), encoding="utf-8")
        return str(base)

    def test_twenty_runs_on_one_book_leave_one_measurement(self):
        """Сторожа зовёт часовой агент, книгу пишет дневной цикл. Без ключа
        снимка «покрытие держалось 20 раз» означало бы «мы 20 раз посмотрели»."""
        with TemporaryDirectory() as tmp:
            base = self._base(tmp, book({"aave_v3": 100.0}, {"aave_v3": "live"}))
            for i in range(20):
                cec.run(data_dir=base, now=NOW + dt.timedelta(minutes=i))
            records, _ = cec.read_journal(base)
            measurements = [r for r in records if r.get("kind") == "measurement"]
            self.assertEqual(len(measurements), 1)

    def test_a_new_book_is_a_new_measurement(self):
        with TemporaryDirectory() as tmp:
            base = self._base(tmp, book({"aave_v3": 100.0}, {"aave_v3": "live"}))
            cec.run(data_dir=base, now=NOW)
            self._base(tmp, book({"aave_v3": 100.0}, {"aave_v3": "live"}, hours_ago=-24.0))
            cec.run(data_dir=base, now=NOW + dt.timedelta(hours=24))
            records, _ = cec.read_journal(base)
            measurements = [r for r in records if r.get("kind") == "measurement"]
            self.assertEqual(len(measurements), 2)

    def test_opening_line_separates_empty_journal_from_absent_one(self):
        with TemporaryDirectory() as tmp:
            base = self._base(tmp, book({"aave_v3": 100.0}, {"aave_v3": "live"}))
            cec.run(data_dir=base, now=NOW)
            records, _ = cec.read_journal(base)
            self.assertTrue(any(r.get("kind") == "journal_opened" for r in records))

    def test_history_on_an_absent_journal_is_unchecked_not_a_clean_record(self):
        with TemporaryDirectory() as tmp:
            hist = cec.history(str(Path(tmp) / "data"), now=NOW)
            self.assertEqual(hist["status"], cec.UNCHECKED)
            self.assertIn("журнал", hist["reason"].lower())

    def test_history_says_the_window_is_truncated_by_journal_age(self):
        """«100 % за 30 суток» по двухдневному журналу — ненаблюдение, и оно
        обязано называться."""
        with TemporaryDirectory() as tmp:
            base = self._base(tmp, book({"aave_v3": 100.0}, {"aave_v3": "live"}))
            cec.run(data_dir=base, now=NOW - dt.timedelta(days=2))
            hist = cec.history(base, days=30.0, now=NOW)
            self.assertTrue(hist["window_truncated"])
            self.assertLess(hist["covered_days"], 30.0)

    def test_history_reports_the_measured_range(self):
        with TemporaryDirectory() as tmp:
            base = self._base(
                tmp, book({"aave_v3": 60000.0, "frax": 20000.0}, {"aave_v3": "live"})
            )
            cec.run(data_dir=base, now=NOW - dt.timedelta(days=1))
            self._base(
                tmp,
                book({"aave_v3": 80000.0}, {"aave_v3": "live"}, hours_ago=-12.0),
            )
            cec.run(data_dir=base, now=NOW)
            hist = cec.history(base, days=30.0, now=NOW)
            self.assertEqual(hist["books_measured"], 2)
            self.assertEqual(hist["coverage_pct_min"], 75.0)
            self.assertEqual(hist["coverage_pct_max"], 100.0)

    def test_unmeasured_books_are_counted_separately_in_history(self):
        """Ряд без дыр и ряд с дырами — разные новости (инвариант #17)."""
        with TemporaryDirectory() as tmp:
            base = self._base(tmp, book({}, {}))
            cec.run(data_dir=base, now=NOW)
            hist = cec.history(base, days=30.0, now=NOW)
            self.assertEqual(hist["books_unmeasured"], 1)
            self.assertIsNone(hist["coverage_pct_min"])


class TestPrintedLines(unittest.TestCase):
    def test_unmeasured_dollars_are_printed_by_name(self):
        rep = cec.measure(
            book({"aave_v3": 60000.0, "frax": 20000.0}, {"aave_v3": "live"}), now=NOW
        )
        text = "\n".join(cec._lines(rep))
        self.assertIn("frax", text)
        self.assertIn("НЕ ИЗМЕРЕНО", text)

    def test_the_twin_number_is_printed_next_to_the_answer(self):
        rep = cec.measure(
            book({"frax": 80000.0}, {"aave_v3": "live"}, live_pct=95.0), now=NOW
        )
        text = "\n".join(cec._lines(rep))
        self.assertIn("ДРУГОЙ вопрос", text)
        self.assertIn("95.0", text)


if __name__ == "__main__":
    unittest.main()
