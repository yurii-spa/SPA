#!/usr/bin/env python3
"""ADR-111 — книга за прошлый день берётся у ДАТИРОВАННОГО источника.

Решение владельца 2026-08-21 09:36Z (карточка
`own-2026-08-18-dozapisat-li-knigu-za-12-proshlyh-dnei`, **вариант A**).

Дефект, который здесь воспроизведён
-----------------------------------
`build_outcome_line` спрашивала книгу у `data/current_positions.json` — снимка,
у которого есть РОВНО ОДНА дата, сегодняшняя. Значит за вчера он не годится
никогда, и каждая дозаписанная задним числом строка навсегда несла
`positions: null` — не потому что книги нет, а потому что спрашивали не у того
файла. Та же самая книга всё это время лежала датированной рядом: дневной цикл
кладёт один и тот же набор позиций и в снимок, и в дневную запись кривой.

Граница честности, которую эти тесты стерегут не слабее самой починки:

* **кэш не восстанавливается** — дневная запись его суммы не несёт, а вывести
  из константы капитала значило бы подставить допущение вместо наблюдения;
* **`allocation_rationale_history` источником книги НЕ становится** — она даёт
  книгу на ВХОДЕ цикла, а нужна на закрытии;
* **сегодняшний снимок по-прежнему не приписывается вчерашнему дню** — это
  проверяет уже существующий тест `test_outcomes_backfill.py`, и он остаётся
  зелёным: там у баров книги нет, поэтому новый путь к ним не применяется.
"""
from __future__ import annotations

# FROZEN-DATE-OK: injected-clock — completeness and backfill are driven by an
# explicit ``now=NOW``, and every bar, outcome row and snapshot they compare it
# against is written by this file from the same fixed anchor. Both sides of every
# freshness judgement are pinned, so the calendar cannot move this test.

import datetime as dt
import json
import os
import tempfile

import spa_core.monitoring.outcomes_archive as oa

NOW = dt.datetime(2026, 8, 12, 9, 30, tzinfo=dt.timezone.utc)
_BOOK = {"aave_v3": 23_250.0, "compound_v3": 15_852.27, "maple": 15_852.27}


def _tree(tmp: str, *, days, book_on: dict | None = None,
          outcome_days=(), snapshot_day=None):
    """Мини-дерево: архив исходов + кривая, у баров опционально есть книга."""
    os.makedirs(os.path.join(tmp, "data", "investment_os"), exist_ok=True)
    with open(os.path.join(tmp, oa.OUTCOMES_REL), "w", encoding="utf-8") as f:
        for d in outcome_days:
            f.write(json.dumps({"schema": 1, "date": d,
                                "equity_close": 100_000.0}) + "\n")
    daily = []
    for i, day in enumerate(days):
        bar = {"date": day, "close_equity": 100_000.0 + i,
               "daily_return_pct": 0.01, "evidenced": True}
        if book_on and day in book_on:
            bar["positions"] = book_on[day]
        daily.append(bar)
    with open(os.path.join(tmp, "data", "equity_curve_daily.json"), "w",
              encoding="utf-8") as f:
        json.dump({"daily": daily}, f)
    if snapshot_day:
        with open(os.path.join(tmp, "data", "current_positions.json"), "w",
                  encoding="utf-8") as f:
            json.dump({"generated_at": snapshot_day + "T06:00:00+00:00",
                       "positions": {"WRONG_DAY": 99_999.0},
                       "cash_usd": 10_000.0}, f)


def _days(first: str, last: str) -> list[str]:
    a, b = dt.date.fromisoformat(first), dt.date.fromisoformat(last)
    return [(a + dt.timedelta(days=i)).isoformat() for i in range((b - a).days + 1)]


def test_book_of_a_past_day_is_recovered_from_the_dated_curve():
    """Положительный контроль: до ADR-111 это была дыра `positions: null`."""
    with tempfile.TemporaryDirectory() as tmp:
        _tree(tmp, days=_days("2026-08-06", "2026-08-08"),
              book_on={"2026-08-07": _BOOK})
        line = oa.build_outcome_line(tmp, "2026-08-07")

    assert line["positions"] == _BOOK, (
        f"книга того же дня лежала в дневной записи кривой, а строка исхода "
        f"получила {line['positions']!r}"
    )
    assert "equity_curve_daily" in line["sources"]["positions"], (
        "источник книги обязан быть назван в самой строке: скептик должен "
        "видеть, что это не снимок и не rationale"
    )


def test_cash_is_not_invented_from_the_capital_constant():
    """Кэша в дневной записи нет — и он остаётся null с названной причиной."""
    with tempfile.TemporaryDirectory() as tmp:
        _tree(tmp, days=_days("2026-08-06", "2026-08-08"),
              book_on={"2026-08-07": _BOOK})
        line = oa.build_outcome_line(tmp, "2026-08-07")

    assert line["cash_usd"] is None, (
        "кэш выведен из чего-то, чего не наблюдали — восстановленная книга не "
        "даёт права дорисовать остаток до константы капитала"
    )
    assert line["sources"].get("cash"), "молчаливый null: причина не названа"


def test_todays_snapshot_never_wins_over_the_dated_bar():
    """Снимок за ДРУГОЙ день не должен подмешаться в восстановленную книгу."""
    with tempfile.TemporaryDirectory() as tmp:
        _tree(tmp, days=_days("2026-08-06", "2026-08-08"),
              book_on={"2026-08-07": _BOOK}, snapshot_day="2026-08-12")
        line = oa.build_outcome_line(tmp, "2026-08-07")

    assert "WRONG_DAY" not in (line["positions"] or {}), (
        "книга сегодняшнего снимка приписана вчерашнему дню — ровно та "
        "подмена, из-за которой поле и было пустым by design"
    )
    assert line["positions"] == _BOOK


def test_a_day_whose_bar_has_no_book_still_says_null():
    """Обратный контроль: чинится ИСТОЧНИК, а не поле. Нет книги — нет книги."""
    with tempfile.TemporaryDirectory() as tmp:
        _tree(tmp, days=_days("2026-08-06", "2026-08-08"))
        line = oa.build_outcome_line(tmp, "2026-08-07")

    assert line["positions"] is None, (
        "у бара книги не было, а поле заполнилось — значит откуда-то её "
        "додумали"
    )
    assert line["sources"]["positions"], "null без причины"


def test_backfill_writes_the_recovered_book_and_labels_it():
    """Сквозь дозапись: строка приходит в архив с книгой И с признаком её происхождения.

    Признак — вариант C карточки, который владелец НЕ выбирал отдельно, но
    который вариант A получает бесплатно: `sources.backfill` говорит, что книга
    взята из записи кривой, а не из снимка. Скептик отличит дозаписанный день от
    записанного вживую, не сверяя даты руками.
    """
    with tempfile.TemporaryDirectory() as tmp:
        _tree(tmp, days=_days("2026-08-06", "2026-08-08"),
              book_on={"2026-08-07": _BOOK},
              outcome_days=["2026-08-06", "2026-08-08"])
        res = oa.backfill_outcomes(tmp, now=NOW)
        assert res["written"] == ["2026-08-07"], res
        line = next(r for r in oa.load_outcomes(tmp) if r["date"] == "2026-08-07")

    assert line["positions"] == _BOOK
    assert line["cash_usd"] is None
    assert "ADR-111" in line["sources"]["backfill"], (
        "дозаписанная строка обязана назвать, откуда у неё книга — иначе "
        "восстановленный день неотличим от прожитого"
    )


def test_existing_rows_are_still_never_rewritten():
    """Дозапись остаётся идемпотентной: ADR-111 меняет ИСТОЧНИК, не правила записи."""
    with tempfile.TemporaryDirectory() as tmp:
        _tree(tmp, days=_days("2026-08-06", "2026-08-08"),
              book_on={d: _BOOK for d in _days("2026-08-06", "2026-08-08")},
              outcome_days=["2026-08-06", "2026-08-08"])
        oa.backfill_outcomes(tmp, now=NOW)
        first = oa.load_outcomes(tmp)
        second_res = oa.backfill_outcomes(tmp, now=NOW)
        second = oa.load_outcomes(tmp)

    assert second_res["written"] == [], "повторный прогон дописал что-то ещё"
    assert first == second, "повторный прогон изменил уже существующие строки"
