"""Дозапись пропущенных дней архива исходов (карточка #258 → цикл #271).

Зачем набор. Проверка полноты (`analyze_completeness`, цикл #259) умеет назвать
дыру, но у названной ею находки НЕ БЫЛО ПУТИ К ЗАКРЫТИЮ: ежедневный писатель по
построению знает только «сегодня», значит пропущенный день не догонялся ничем и
никогда. Находка, которая верна и не снимается никаким действием, — это класс
`irreversible-unchecked`: через несколько циклов её начинают пролистывать вместе
с разделом. Здесь закрывается ровно это.

Устройство набора (правило класса «сторож отвечает не на тот вопрос»):
  * положительные контроли воспроизводят форму настоящей дыры — закрытый
    evidenced-день без строки — и требуют, чтобы после дозаписи находка
    СНИМАЛАСЬ сама (иначе путь к закрытию по-прежнему отсутствует);
  * обратные контроли закрепляют то, что дозапись НЕ смеет делать: двигать
    якорь архива, выдумывать невосстановимые поля, лечить дыру молча внутри
    моста, терять уже записанные строки;
  * контроль порядка: дыра затыкается в СЕРЕДИНЕ, поэтому чистый append сломал
    бы дату-порядок файла — слияние обязано быть отсортированным И чисто
    добавляющим.

Время — ВХОД (`now=`) во всех тестах: фиксированы обе стороны сравнения (и часы,
и отметки дней), поэтому набор не протухает от смены календаря.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import tempfile
import unittest

from spa_core.monitoring import loop_retro as lr
from spa_core.monitoring import outcomes_archive as oa

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# FROZEN-DATE-OK: injected-clock — преференция #1 `.claude/rules/deployment.md`:
# часы инъектируются (`now=`) ВМЕСТЕ с фиксированными отметками дней; обе стороны
# сравнения закреплены. Даты здесь и есть предмет проверки: вопрос ровно в том,
# какой день уже ЗАКРЫТ и потому обязан иметь строку.
NOW = dt.datetime(2026, 8, 12, 9, 30, tzinfo=dt.timezone.utc)


def _days(first: str, last: str) -> list[str]:
    a = dt.date.fromisoformat(first)
    b = dt.date.fromisoformat(last)
    return [(a + dt.timedelta(days=i)).isoformat() for i in range((b - a).days + 1)]


def _write_tree(tmp: str, *, outcome_days, bars, rationale=(), verdicts=(),
                positions_day=None):
    """Мини-дерево: архив исходов + кривая (+ по желанию датированные источники).

    `bars` — [(дата, evidenced?)]; неevidenced-бар получает форму настоящих
    fail-closed дней трека (07-19 / 07-27): бар есть, живого цикла за ним нет.
    """
    io_dir = os.path.join(tmp, "data", "investment_os")
    os.makedirs(io_dir, exist_ok=True)
    with open(os.path.join(tmp, oa.OUTCOMES_REL), "w", encoding="utf-8") as f:
        for d in outcome_days:
            f.write(json.dumps({"schema": 1, "date": d, "equity_close": 100000.0,
                                "mark": "старая строка"}, ensure_ascii=False) + "\n")
    daily = []
    for date, evidenced in bars:
        bar = {"date": date, "close_equity": 100000.0 + _days("2026-01-01", date).__len__(),
               "daily_return_pct": 0.01, "evidenced": bool(evidenced)}
        if not evidenced:
            bar["source"] = "backfill"
        daily.append(bar)
    with open(os.path.join(tmp, "data", "equity_curve_daily.json"), "w",
              encoding="utf-8") as f:
        json.dump({"daily": daily}, f)
    if rationale:
        with open(os.path.join(tmp, "data", "allocation_rationale_history.jsonl"), "w",
                  encoding="utf-8") as f:
            for day in rationale:
                f.write(json.dumps({"cycle_date": day,
                                    "apy_evidenced_pct": {"aave_v3": 3.3}},
                                   ensure_ascii=False) + "\n")
    if verdicts:
        with open(os.path.join(io_dir, "chief_investment_verdicts.jsonl"), "w",
                  encoding="utf-8") as f:
            for day in verdicts:
                f.write(json.dumps({"date": day, "posture": "GREEN"}) + "\n")
    if positions_day:
        with open(os.path.join(tmp, "data", "current_positions.json"), "w",
                  encoding="utf-8") as f:
            json.dump({"generated_at": positions_day + "T06:00:00+00:00",
                       "positions": {"aave_v3": 40000.0}, "cash_usd": 10000.0}, f)


class HoleGetsAPathToClosure(unittest.TestCase):
    """Главное: названная дыра теперь СНИМАЕТСЯ, и снимается сама собой."""

    def test_backfill_closes_the_hole_and_the_finding_disappears(self):
        """ПОЛОЖИТЕЛЬНЫЙ КОНТРОЛЬ + приёмка карточки: до дозаписи находка есть,
        после — её нет, и это один и тот же код, а не два разных дерева."""
        with tempfile.TemporaryDirectory() as tmp:
            _write_tree(tmp,
                        outcome_days=["2026-08-06", "2026-08-07", "2026-08-08",
                                      "2026-08-09", "2026-08-11"],
                        bars=[(d, True) for d in _days("2026-08-06", "2026-08-11")])
            before = oa.analyze_completeness(tmp, now=NOW)
            self.assertEqual(before["missing_days"], ["2026-08-10"])
            self.assertIn("retro:outcomes_incomplete",
                          [f["key"] for f in lr.build_report(
                              [], None, None, NOW, outcomes_completeness=before)["findings"]])

            rep = oa.backfill_outcomes(tmp, now=NOW)

            self.assertTrue(rep["measured"], rep.get("reason"))
            self.assertEqual(rep["written"], ["2026-08-10"])
            self.assertTrue(rep["complete_after"], rep["reason"])
            after = oa.analyze_completeness(tmp, now=NOW)
            self.assertEqual(after["missing_days"], [])
            self.assertNotIn("retro:outcomes_incomplete",
                             [f["key"] for f in lr.build_report(
                                 [], None, None, NOW,
                                 outcomes_completeness=after)["findings"]])

    def test_backfill_is_idempotent(self):
        """Второй прогон не смеет ни задвоить строку, ни объявить успех."""
        with tempfile.TemporaryDirectory() as tmp:
            _write_tree(tmp,
                        outcome_days=["2026-08-06", "2026-08-08"],
                        bars=[(d, True) for d in _days("2026-08-06", "2026-08-08")])
            first = oa.backfill_outcomes(tmp, now=NOW)
            second = oa.backfill_outcomes(tmp, now=NOW)
        self.assertEqual(first["written"], ["2026-08-07"])
        self.assertEqual(second["written"], [])
        self.assertIn("дыр в диапазоне нет", second["reason"])

    def test_explicit_range_limits_what_is_written(self):
        """Карточка требует ЯВНЫЙ диапазон: остальные дыры остаются названными,
        а не тихо затянутыми заодно."""
        with tempfile.TemporaryDirectory() as tmp:
            _write_tree(tmp,
                        outcome_days=["2026-08-06", "2026-08-11"],
                        bars=[(d, True) for d in _days("2026-08-06", "2026-08-11")])
            rep = oa.backfill_outcomes(tmp, since="2026-08-08", until="2026-08-09",
                                       now=NOW)
        self.assertEqual(rep["written"], ["2026-08-08", "2026-08-09"])
        self.assertEqual(rep["out_of_range"], ["2026-08-07", "2026-08-10"])
        self.assertEqual(rep["missing_after"], ["2026-08-07", "2026-08-10"])
        self.assertFalse(rep["complete_after"])

    def test_dry_run_writes_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            _write_tree(tmp,
                        outcome_days=["2026-08-06", "2026-08-08"],
                        bars=[(d, True) for d in _days("2026-08-06", "2026-08-08")])
            rep = oa.backfill_outcomes(tmp, now=NOW, dry_run=True)
            self.assertEqual(rep["written"], ["2026-08-07"])
            self.assertEqual([r["date"] for r in oa.load_outcomes(tmp)],
                             ["2026-08-06", "2026-08-08"])
            self.assertEqual(oa.analyze_completeness(tmp, now=NOW)["missing_days"],
                             ["2026-08-07"])


class FileStaysOrderedAndWhole(unittest.TestCase):
    """Дыра затыкается в СЕРЕДИНЕ — значит порядок и сохранность под вопросом."""

    def test_dates_stay_ordered_after_a_middle_hole_is_filled(self):
        """Чистый append поставил бы 08-07 ПОСЛЕ 08-08 — файл перестал бы быть
        упорядоченным по датам, хотя выглядел бы «дозаписанным»."""
        with tempfile.TemporaryDirectory() as tmp:
            _write_tree(tmp,
                        outcome_days=["2026-08-06", "2026-08-08", "2026-08-09"],
                        bars=[(d, True) for d in _days("2026-08-06", "2026-08-09")])
            oa.backfill_outcomes(tmp, now=NOW)
            dates = [r["date"] for r in oa.load_outcomes(tmp)]
        self.assertEqual(dates, _days("2026-08-06", "2026-08-09"))
        self.assertEqual(dates, sorted(dates))

    def test_existing_lines_survive_byte_for_byte(self):
        """Слияние переписывает файл — значит обязано быть ЧИСТО ДОБАВЛЯЮЩИМ.
        Проверяем дословно: ни одна старая строка не изменилась и не пропала."""
        with tempfile.TemporaryDirectory() as tmp:
            _write_tree(tmp,
                        outcome_days=["2026-08-06", "2026-08-08"],
                        bars=[(d, True) for d in _days("2026-08-06", "2026-08-08")])
            path = os.path.join(tmp, oa.OUTCOMES_REL)
            before = [ln.rstrip("\n") for ln in open(path, encoding="utf-8") if ln.strip()]
            oa.backfill_outcomes(tmp, now=NOW)
            after = [ln.rstrip("\n") for ln in open(path, encoding="utf-8") if ln.strip()]
        for line in before:
            self.assertIn(line, after)
        self.assertEqual(len(after), len(before) + 1)

    def test_a_lossy_merge_is_refused_not_written(self):
        """ПОЛОЖИТЕЛЬНЫЙ КОНТРОЛЬ на fail-CLOSED: если слияние вдруг потеряет
        существующую строку, архив обязан остаться НЕТРОНУТЫМ.

        Подменяем само слияние на теряющее — так проверяется страж, а не
        сегодняшняя удача реализации."""
        with tempfile.TemporaryDirectory() as tmp:
            _write_tree(tmp,
                        outcome_days=["2026-08-06", "2026-08-08"],
                        bars=[(d, True) for d in _days("2026-08-06", "2026-08-08")])
            path = os.path.join(tmp, oa.OUTCOMES_REL)
            before = open(path, encoding="utf-8").read()
            orig = oa._merge_sorted_by_date
            oa._merge_sorted_by_date = lambda raw, new: orig(raw[1:], new)
            try:
                rep = oa.backfill_outcomes(tmp, now=NOW)
            finally:
                oa._merge_sorted_by_date = orig
            self.assertTrue(rep.get("refused"))
            self.assertEqual(rep["written"], [])
            self.assertIn("потеряло бы", rep["reason"])
            self.assertEqual(open(path, encoding="utf-8").read(), before)

    def test_undated_junk_line_is_not_silently_reshuffled(self):
        """Бездатная/битая строка не имеет права уехать в середину архива и
        притвориться днём — она остаётся головой файла, а не сортируется."""
        with tempfile.TemporaryDirectory() as tmp:
            _write_tree(tmp,
                        outcome_days=["2026-08-06", "2026-08-08"],
                        bars=[(d, True) for d in _days("2026-08-06", "2026-08-08")])
            path = os.path.join(tmp, oa.OUTCOMES_REL)
            body = open(path, encoding="utf-8").read()
            open(path, "w", encoding="utf-8").write("не-json мусор\n" + body)
            oa.backfill_outcomes(tmp, now=NOW)
            lines = [ln.rstrip("\n") for ln in open(path, encoding="utf-8") if ln.strip()]
            self.assertEqual(lines[0], "не-json мусор")
            self.assertEqual([r["date"] for r in oa.load_outcomes(tmp)],
                             _days("2026-08-06", "2026-08-08"))


class HonestyOfBackfilledFields(unittest.TestCase):
    """Что дозапись восстанавливает честно, а что обязана оставить `null`."""

    def test_dated_sources_are_recovered_for_a_past_day(self):
        """Замер на живом проде (17.08): equity/APY/постура датированы и за
        прошлый день читаются так же, как за сегодняшний."""
        with tempfile.TemporaryDirectory() as tmp:
            _write_tree(tmp,
                        outcome_days=["2026-08-06", "2026-08-08"],
                        bars=[(d, True) for d in _days("2026-08-06", "2026-08-08")],
                        rationale=["2026-08-07"], verdicts=["2026-08-07"])
            oa.backfill_outcomes(tmp, now=NOW)
            line = next(r for r in oa.load_outcomes(tmp) if r["date"] == "2026-08-07")
        self.assertIsNotNone(line["equity_close"])
        self.assertEqual(line["apy_evidenced_pct"], {"aave_v3": 3.3})
        self.assertEqual(line["posture_office"], "GREEN")

    def test_positions_of_a_past_day_stay_null_with_a_named_reason(self):
        """ОБРАТНЫЙ КОНТРОЛЬ и главная граница честности: снимок книги за
        СЕГОДНЯ не смеет быть приписан ВЧЕРАШНЕМУ дню. Невосстановимое остаётся
        null, и причина названа в самой строке, а не в чьей-то памяти.

        ИЗМЕНЕНО 2026-08-18 (карточка «Книги за прошлый день нет в архиве»),
        обоснование — инвариант 16 CLAUDE.md, проверка НЕ ослаблена:

        * граница, ради которой тест заведён, осталась той же и проверяется
          теми же двумя утверждениями — `positions is None` и `cash_usd is None`
          при снимке за 08-12 и строке за 08-07;
        * поменялись только ДВЕ строки причины, потому что причина стала другой
          по существу. Раньше книга бралась единственным источником — снимком
          «прямо сейчас», и за прошлый день другого кандидата не было вовсе.
          Теперь сборка сперва смотрит в ДАТИРОВАННЫЙ evidenced-бар кривой (туда
          `cycle_runner` кладёт тот же объект `effective_positions`, что и в
          снимок), и `null` здесь означает уже не «источника нет», а «в баре
          этого дня позиций нет» — что для фикстуры и верно: `_write_tree`
          строит бары без ключа `positions`;
        * тест при этом УСИЛЕН: добавлено утверждение, что причина ссылается
          именно на бар, а не на снимок, — иначе тихая регрессия «взяли книгу
          сегодняшнего снимка» прошла бы мимо.
        """
        with tempfile.TemporaryDirectory() as tmp:
            _write_tree(tmp,
                        outcome_days=["2026-08-06", "2026-08-08"],
                        bars=[(d, True) for d in _days("2026-08-06", "2026-08-08")],
                        positions_day="2026-08-12")  # снимок СЕГОДНЯШНЕГО дня
            oa.backfill_outcomes(tmp, now=NOW)
            line = next(r for r in oa.load_outcomes(tmp) if r["date"] == "2026-08-07")
        self.assertIsNone(line["positions"])
        self.assertIsNone(line["cash_usd"])
        self.assertIn("не приписываем", line["sources"]["positions"])
        self.assertIn("не восстановимы", line["sources"]["backfill"])


class WhatBackfillMustNotDo(unittest.TestCase):
    """Обратные контроли к самой правке."""

    def test_anchor_is_never_moved_backwards(self):
        """Дни РАНЬШЕ первой строки не сочиняются: до появления производителя
        его не было. `--since` за якорем не даёт ничего — и это не ошибка."""
        with tempfile.TemporaryDirectory() as tmp:
            _write_tree(tmp,
                        outcome_days=["2026-08-06", "2026-08-08"],
                        bars=[(d, True) for d in _days("2026-06-22", "2026-08-08")])
            rep = oa.backfill_outcomes(tmp, since="2026-06-22", now=NOW)
            dates = [r["date"] for r in oa.load_outcomes(tmp)]
        self.assertEqual(rep["anchor_date"], "2026-08-06")
        self.assertEqual(rep["written"], ["2026-08-07"])
        self.assertEqual(dates[0], "2026-08-06")

    def test_a_day_without_an_evidenced_bar_is_never_written(self):
        """07-19 / 07-27 — дни честного отказа. Строки они не ждут, и дозапись
        не имеет права их «починить»."""
        bars = [(d, d != "2026-08-07") for d in _days("2026-08-06", "2026-08-08")]
        with tempfile.TemporaryDirectory() as tmp:
            _write_tree(tmp, outcome_days=["2026-08-06", "2026-08-08"], bars=bars)
            rep = oa.backfill_outcomes(tmp, now=NOW)
            dates = [r["date"] for r in oa.load_outcomes(tmp)]
        self.assertEqual(rep["written"], [])
        self.assertEqual(dates, ["2026-08-06", "2026-08-08"])

    def test_today_is_never_backfilled(self):
        """Сегодняшний день ещё может быть дописан своим же тактом — требовать
        и занимать его дозаписью значило бы отнять у производителя его работу."""
        with tempfile.TemporaryDirectory() as tmp:
            _write_tree(tmp,
                        outcome_days=_days("2026-08-06", "2026-08-11"),
                        bars=[(d, True) for d in _days("2026-08-06", "2026-08-12")])
            rep = oa.backfill_outcomes(tmp, since="2026-08-12", until="2026-08-12",
                                       now=NOW)
        self.assertEqual(rep["written"], [])
        self.assertNotIn("2026-08-12", [r["date"] for r in oa.load_outcomes(tmp)])

    def test_unmeasured_completeness_writes_nothing(self):
        """fail-CLOSED: «не знаю, какие дни нужны» — это не «нужных дней нет».
        Кривая нечитаема ⇒ архив не трогаем вовсе."""
        with tempfile.TemporaryDirectory() as tmp:
            _write_tree(tmp, outcome_days=["2026-08-06"], bars=[])
            os.remove(os.path.join(tmp, "data", "equity_curve_daily.json"))
            path = os.path.join(tmp, oa.OUTCOMES_REL)
            before = open(path, encoding="utf-8").read()
            rep = oa.backfill_outcomes(tmp, now=NOW)
            self.assertFalse(rep["measured"])
            self.assertEqual(rep["written"], [])
            self.assertIn("equity_curve_daily", rep["reason"])
            self.assertEqual(open(path, encoding="utf-8").read(), before)

    def test_the_live_track_file_is_only_ever_read(self):
        """`data/equity_curve_daily.json` — живой трек (инвариант). Дозапись
        обязана его не касаться: сверяем содержимое и mtime."""
        with tempfile.TemporaryDirectory() as tmp:
            _write_tree(tmp,
                        outcome_days=["2026-08-06", "2026-08-08"],
                        bars=[(d, True) for d in _days("2026-08-06", "2026-08-08")])
            curve = os.path.join(tmp, "data", "equity_curve_daily.json")
            body, mtime = open(curve, encoding="utf-8").read(), os.stat(curve).st_mtime_ns
            oa.backfill_outcomes(tmp, now=NOW)
            self.assertEqual(open(curve, encoding="utf-8").read(), body)
            self.assertEqual(os.stat(curve).st_mtime_ns, mtime)


class NoSilentSelfHealing(unittest.TestCase):
    """Дозапись НЕ смеет стать шагом автоматики.

    Находка `retro:outcomes_incomplete` означает ОСТАНОВКУ записи. Если бы мост
    дозаписывал сам каждым прогоном, дыра затягивалась бы раньше, чем её кто-то
    прочитает: находка исчезала бы, причина остановки — нет. Это ровно тот
    обмен, который правило класса запрещает, поэтому он закреплён тестом, а не
    обещанием в комментарии.
    """

    def test_the_bridge_does_not_call_backfill(self):
        from spa_core.monitoring import findings_bridge
        src = open(findings_bridge.__file__, encoding="utf-8").read()
        self.assertIn("append_daily_outcome", src)  # ежедневная запись — да
        self.assertNotIn("backfill_outcomes", src)  # автолечение — нет

    def test_no_scheduled_agent_runs_the_backfill(self):
        """Ни один plist/скрипт запуска не зовёт дозапись — иначе «руками»
        осталось бы словом в докстринге."""
        hits = []
        for sub in ("launchd", "scripts"):
            base = os.path.join(REPO_ROOT, sub)
            for dirpath, _dirs, files in os.walk(base):
                for fn in files:
                    p = os.path.join(dirpath, fn)
                    try:
                        text = open(p, encoding="utf-8", errors="ignore").read()
                    except OSError:
                        continue
                    if "--backfill" in text or "backfill_outcomes" in text:
                        hits.append(os.path.relpath(p, REPO_ROOT))
        self.assertEqual(hits, [], f"дозапись оказалась в автоматике: {hits}")

    def test_the_finding_names_the_command_that_closes_it(self):
        """У находки обязан быть НАЗВАННЫЙ путь к закрытию — ровно то, чего ей
        не хватало. И она по-прежнему честно говорит, что сам производитель эти
        дни не догонит (это не изменилось и ослаблению не подлежит)."""
        comp = {"measured": True, "complete": False,
                "missing_days": ["2026-08-10"], "reason": "…"}
        rep = lr.build_report([], None, None, NOW, outcomes_completeness=comp)
        msg = {f["key"]: f for f in rep["findings"]}["retro:outcomes_incomplete"]["message"]
        self.assertIn("не догонит", msg)
        self.assertIn("--backfill", msg)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
