"""Книга дня в архиве исходов: «не измерено» ≠ «книга была пуста» (карточка
`inbox-knigi-za-proshlyi-den-net-v-arhive-dozap`, замер 2026-08-18).

Что здесь закрепляется и почему именно это.

Находка. Дозаписанная задним числом строка `data/investment_os/outcomes.jsonl`
несла `positions: null` не иногда, а ВСЕГДА — по построению: `build_outcome_line`
брала книгу единственным источником из `data/current_positions.json`, снимка
«прямо сейчас», датированного одним полем `generated_at`. Условие
`generated_at[:10] == day` истинно самое большее для ОДНОГО дня — сегодняшнего, и
только пока цикл не отработал снова. При этом ровно та же книга уже лежала
датированной: `cycle_runner` кладёт один и тот же объект `effective_positions`
и в снимок, и в дневной бар кривой. Замер на треке в git: 13 evidenced-дней
2026-06-22…2026-07-04, и все 13 получили бы `positions: null` при том, что книга
за каждый из них наблюдена (7 позиций в баре).

Вторая находка того же места, форма fail-OPEN: `(pos.get("positions") or {})`
превращало ОТСУТСТВИЕ поля в пустую книгу, а `float(pos.get("cash_usd") or 0.0)`
— отсутствие кэша в измеренный ноль. То есть «не измерено» выглядело как
утверждение «весь капитал был в кэше» / «кэша было ноль». Для архива, которым
скептик перепроверяет трек, это хуже дыры: дыра видна, а выдуманный ноль — нет.

Устройство набора (правило класса «положительный контроль в обе стороны»):
  * ПОЛОЖИТЕЛЬНЫЕ — воспроизводят форму настоящей потери: прошлый день, книга
    восстановима, и она обязана быть в строке; отсутствие книги обязано быть
    названо и отличаться от пустой книги;
  * ОБРАТНЫЕ — нормальный день пишется РОВНО ОДИН раз и не дублируется ни
    повторным тактом, ни повторной дозаписью; неотгейченный (не evidenced) бар
    книгу не одалживает.

Время — ВХОД (`now=`) везде, отметки дней фиксированы вместе с часами: обе
стороны сравнения закреплены, от сдвига календаря набор не зависит.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import tempfile
import unittest

from spa_core.monitoring import outcomes_archive as oa

# FROZEN-DATE-OK: injected-clock — преференция #1 `.claude/rules/deployment.md`.
# Часы инъектируются (`now=`) ВМЕСТЕ с отметками дней; сами даты и есть предмет
# проверки (вопрос ровно в том, за КАКОЙ день книга).
NOW = dt.datetime(2026, 8, 12, 9, 30, tzinfo=dt.timezone.utc)
TODAY = "2026-08-12"
YESTERDAY = "2026-08-11"

BOOK_YDAY = {"aave_v3": 30000.0, "morpho_blue_base": 20000.0}
BOOK_TODAY = {"aave_v3": 25000.0, "spark_susds": 25000.0}


def _bar(date: str, positions: dict | None, *, evidenced: bool = True) -> dict:
    bar = {"date": date, "close_equity": 100100.0, "equity": 100100.0,
           "daily_return_pct": 0.01, "evidenced": bool(evidenced),
           "source": "cycle" if evidenced else "backfill"}
    if positions is not None:
        bar["positions"] = dict(positions)
    return bar


def _tree(tmp: str, *, bars, snapshot: dict | None, outcome_days=()) -> str:
    """Мини-дерево: кривая + (опционально) снимок книги + архив исходов."""
    os.makedirs(os.path.join(tmp, "data", "investment_os"), exist_ok=True)
    with open(os.path.join(tmp, "data", "equity_curve_daily.json"), "w",
              encoding="utf-8") as f:
        json.dump({"daily": list(bars)}, f)
    if snapshot is not None:
        with open(os.path.join(tmp, "data", "current_positions.json"), "w",
                  encoding="utf-8") as f:
            json.dump(snapshot, f)
    if outcome_days:
        with open(os.path.join(tmp, oa.OUTCOMES_REL), "w", encoding="utf-8") as f:
            for d in outcome_days:
                f.write(json.dumps({"schema": 1, "date": d,
                                    "equity_close": 100000.0}) + "\n")
    return tmp


def _snapshot(day: str, book: dict | None, cash) -> dict:
    snap = {"generated_at": f"{day}T06:00:00+00:00", "source": "cycle_runner"}
    if book is not None:
        snap["positions"] = dict(book)
    if cash is not None:
        snap["cash_usd"] = cash
    return snap


class BookOfAPastDay(unittest.TestCase):
    """ПОЛОЖИТЕЛЬНЫЕ КОНТРОЛИ — форма настоящей потери."""

    def test_past_day_recovers_the_book_from_the_dated_bar(self):
        """Снимок «прямо сейчас» датирован СЕГОДНЯ — за вчера он не годится;
        книга вчерашнего закрытия обязана прийти из датированного бара.

        Это и есть измеренная авария: до правки строка за вчера несла
        `positions: null` при наблюдённой книге в баре.
        """
        with tempfile.TemporaryDirectory() as tmp:
            _tree(tmp,
                  bars=[_bar(YESTERDAY, BOOK_YDAY), _bar(TODAY, BOOK_TODAY)],
                  snapshot=_snapshot(TODAY, BOOK_TODAY, 50000.0))
            line = oa.build_outcome_line(tmp, YESTERDAY)
        self.assertEqual(line["positions"], BOOK_YDAY, line["sources"])
        self.assertIn("equity_curve_daily", line["sources"]["positions"])
        # Кэш из бара не выводится: константа капитала не наблюдение.
        self.assertIsNone(line["cash_usd"])
        self.assertIn("null", line["sources"]["cash"])

    def test_backfilled_line_carries_the_book_and_says_so(self):
        """Дозапись за пропущенный закрытый день несёт книгу, а пометка
        `sources.backfill` говорит, что вышло НА САМОМ ДЕЛЕ, а не заготовку."""
        with tempfile.TemporaryDirectory() as tmp:
            _tree(tmp,
                  bars=[_bar("2026-08-09", {"aave_v3": 10.0}),
                        _bar("2026-08-10", {"aave_v3": 20.0}),
                        _bar(YESTERDAY, BOOK_YDAY)],
                  snapshot=_snapshot(TODAY, BOOK_TODAY, 50000.0),
                  outcome_days=["2026-08-09"])
            rep = oa.backfill_outcomes(tmp, now=NOW)
            self.assertEqual(rep["written"], ["2026-08-10", YESTERDAY], rep)
            rows = {r["date"]: r for r in oa.load_outcomes(tmp)}
        self.assertEqual(rows[YESTERDAY]["positions"], BOOK_YDAY)
        self.assertIn("книга: восстановлена", rows[YESTERDAY]["sources"]["backfill"])
        self.assertIn("кэш: НЕ восстановлен", rows[YESTERDAY]["sources"]["backfill"])

    def test_not_measured_is_null_and_never_an_empty_book(self):
        """Ни снимка за день, ни бара за день — книга `null` с названной
        причиной. Пустой книгой это притвориться не смеет."""
        with tempfile.TemporaryDirectory() as tmp:
            _tree(tmp, bars=[_bar(TODAY, BOOK_TODAY)],
                  snapshot=_snapshot(TODAY, BOOK_TODAY, 50000.0))
            line = oa.build_outcome_line(tmp, "2026-08-05")
        self.assertIsNone(line["positions"])
        self.assertNotEqual(line["positions"], {})
        self.assertIsNone(line["cash_usd"])
        self.assertTrue(line["sources"]["positions"].strip())

    def test_absent_fields_in_a_same_day_snapshot_are_not_zeros(self):
        """Снимок за ТОТ ЖЕ день, но без `positions` и без `cash_usd`.

        Это форма fail-OPEN до правки: `or {}` давало пустую книгу, `or 0.0` —
        измеренный ноль кэша. Отсутствие поля обязано остаться отсутствием.
        """
        with tempfile.TemporaryDirectory() as tmp:
            _tree(tmp, bars=[_bar(TODAY, None)],
                  snapshot=_snapshot(TODAY, None, None))
            line = oa.build_outcome_line(tmp, TODAY)
        self.assertIsNone(line["positions"])
        self.assertNotEqual(line["positions"], {})
        self.assertIsNone(line["cash_usd"])
        self.assertNotEqual(line["cash_usd"], 0.0)

    def test_observed_empty_book_is_distinguishable_from_not_measured(self):
        """День, когда книга ДЕЙСТВИТЕЛЬНО пуста (весь капитал в кэше), — это
        `{}` и `0.0` с источником-наблюдением, а не `null`. Две разные вещи
        обязаны выглядеть по-разному в обе стороны."""
        with tempfile.TemporaryDirectory() as tmp:
            _tree(tmp, bars=[_bar(TODAY, {})],
                  snapshot=_snapshot(TODAY, {}, 0.0))
            line = oa.build_outcome_line(tmp, TODAY)
        self.assertEqual(line["positions"], {})
        self.assertIsNotNone(line["positions"])
        self.assertEqual(line["cash_usd"], 0.0)
        self.assertIn("current_positions", line["sources"]["positions"])


class BookIsNeverBorrowed(unittest.TestCase):
    """ОБРАТНЫЕ КОНТРОЛИ — нормальный день пишется ровно один раз."""

    def test_non_evidenced_bar_does_not_lend_its_book(self):
        """Бар за день есть, но он не evidenced (07-19 / 07-27 — дни, когда
        система честно отказалась). Его книгу одалживать нельзя."""
        with tempfile.TemporaryDirectory() as tmp:
            _tree(tmp,
                  bars=[_bar(YESTERDAY, BOOK_YDAY, evidenced=False),
                        _bar(TODAY, BOOK_TODAY)],
                  snapshot=_snapshot(TODAY, BOOK_TODAY, 50000.0))
            line = oa.build_outcome_line(tmp, YESTERDAY)
        self.assertIsNone(line["positions"])
        self.assertIn("evidenced", line["sources"]["positions"])

    def test_daily_writer_appends_a_day_exactly_once(self):
        """Такт производителя идёт 4 раза в день. Строка за день обязана
        появиться ровно одна — повторный такт не дублирует и не переписывает."""
        with tempfile.TemporaryDirectory() as tmp:
            _tree(tmp, bars=[_bar(TODAY, BOOK_TODAY)],
                  snapshot=_snapshot(TODAY, BOOK_TODAY, 50000.0))
            first = oa.append_daily_outcome(tmp, now=NOW)
            second = oa.append_daily_outcome(tmp, now=NOW)
            rows = oa.load_outcomes(tmp)
        self.assertTrue(first["appended"], first)
        self.assertFalse(second["appended"], second)
        self.assertEqual([r["date"] for r in rows], [TODAY])
        self.assertEqual(rows[0]["positions"], BOOK_TODAY)

    def test_backfill_twice_does_not_duplicate_a_day(self):
        """Дозапись идемпотентна: второй прогон не находит дыр и ничего не
        добавляет — иначе архив копил бы по строке на каждый разбор."""
        with tempfile.TemporaryDirectory() as tmp:
            _tree(tmp,
                  bars=[_bar("2026-08-09", {"aave_v3": 10.0}),
                        _bar("2026-08-10", {"aave_v3": 20.0}),
                        _bar(YESTERDAY, BOOK_YDAY)],
                  snapshot=_snapshot(TODAY, BOOK_TODAY, 50000.0),
                  outcome_days=["2026-08-09"])
            oa.backfill_outcomes(tmp, now=NOW)
            again = oa.backfill_outcomes(tmp, now=NOW)
            dates = [r["date"] for r in oa.load_outcomes(tmp)]
        self.assertEqual(again["written"], [], again)
        self.assertEqual(dates, sorted(dates))
        self.assertEqual(len(dates), len(set(dates)), dates)
        self.assertEqual(dates, ["2026-08-09", "2026-08-10", YESTERDAY])


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
