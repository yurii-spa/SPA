# LLM_FORBIDDEN
"""Окно недельной проверки считается ДОКАЗАННЫМИ днями, а не календарными.

РЕШЕНИЕ ВЛАДЕЛЬЦА 09.08 (карточка `inbox-7-day-checkpoint-gap-check-schitat-ot-ev`):
проверка смотрит только на дни ПОСЛЕ якоря трека; историческая дыра 21.06 → 30.06
остаётся ВИДИМОЙ в отчёте, но не роняет чекпойнт вечно.

ДЕФЕКТ, КОТОРЫЙ ЭТО ЗАКРЫВАЕТ — FAIL-OPEN ПО ЧАСАМ. Первая правка проверки завела окно
«последние 7 дней» от `date.today()`. Вечный отказ она сняла, но принесла свой: дыра
перестаёт блокировать просто оттого, что сдвинулся календарь, — даже если после неё трек
не набрал НИ ОДНОГО доказанного дня. Замер на этом дереве 17.08 (`data/`): дыры
2026-07-18 → 2026-07-20 и 2026-07-26 → 2026-07-28 — настоящие, ПОСЛЕ якоря 2026-06-22 —
уже числились «историческими», потому что край окна уехал на 2026-08-10. «Подождать
подольше» стало способом закрыть проверку.

Трек считается доказанными барами, поэтому дыра выходит из окна только тогда, когда
после неё накопилось `window_days` НОВЫХ доказанных дней — то есть трек ДОКАЗАЛ, что
восстановился. Календарь на это больше не влияет.

ВТОРАЯ ЧАСТЬ РЕШЕНИЯ: `days_tracked` — доказанные дни, а не «сколько строк в файле».
На живых данных отчёт объявлял «44/30» при 13 доказанных днях: 30-дневная норма
выглядела взятой с двойным запасом там, где трек не добрал и половины (инвариант #8).

Определение доказанности здесь НЕ дублируется: используется канонический предикат
`spa_core.paper_trading.track_evidence.is_evidenced_bar`. Поэтому когда владелец закроет
карточку про день с пустой книгой (`owner-decision-dva-dnya-treka-pomecheny-...`), эта
проверка получит новое правило без единой правки — и не разойдётся с гейтом go-live.

Контроли в ОБЕ стороны (инвариант #16 — иначе это была бы молча выключенная проверка):
дыра до якоря не блокирует, но названа; дыра после якоря блокирует и НЕ выводится
календарём; неизвестный якорь / недоступный счёт ничего не прощают (fail-CLOSED).

Время — вход (`check_gaps(..., today=)`), даты фикстур строятся от одной константы:
литеральные отметки при настоящих часах — бомба замедленного действия
(`.claude/rules/deployment.md`).
"""
from __future__ import annotations

import importlib.util
import json
import unittest
from datetime import date, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory

_REPO = Path(__file__).resolve().parents[2]
_SCRIPT = _REPO / "scripts" / "checkpoint_7day.py"

# «Сегодня» этих тестов. Дальше от него отсчитываются ВСЕ отметки фикстур.
_TODAY = date(2026, 8, 17)
_ANCHOR = date(2026, 6, 22)   # якорь живого трека — предмет решения владельца


def _load():
    spec = importlib.util.spec_from_file_location("checkpoint_7day_evwin", str(_SCRIPT))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _bar(d: date, *, evidenced: bool = True) -> dict:
    """Бар трека с ЧЕСТНЫМИ метками — теми, по которым судит канонический предикат."""
    return {
        "date": d.isoformat(),
        "open_equity": 100_000.0,
        "close_equity": 100_010.0,
        "equity": 100_010.0,
        "evidenced": evidenced,
        "source": "cycle" if evidenced else "backfill",
    }


class _Fixture:
    """Каталог данных, собираемый по датам: доказанные бары + дни регистратора."""

    def __init__(self, tmp: str):
        self.dir = Path(tmp)

    def write(self, *, evidenced: list[date] | None = None,
              unevidenced: list[date] | None = None,
              recorded: list[date] | None = None,
              anchor: date | None = None,
              with_curve: bool = True) -> Path:
        curve = self.dir / "equity_curve_daily.json"
        if with_curve:
            bars = [_bar(d) for d in (evidenced or [])]
            bars += [_bar(d, evidenced=False) for d in (unevidenced or [])]
            bars.sort(key=lambda b: b["date"])
            curve.write_text(json.dumps({"summary": {}, "daily": bars}), encoding="utf-8")
        elif curve.exists():
            # «Кривой нет» обязано означать именно это: файл, оставшийся от
            # предыдущего вызова в том же каталоге, молча делал бы проверку холостой.
            curve.unlink()
        if recorded is not None:
            (self.dir / "paper_evidence.json").write_text(
                json.dumps({"days": [{"date": d.isoformat()} for d in recorded]}),
                encoding="utf-8")
        if anchor is not None:
            (self.dir / "golive_status.json").write_text(
                json.dumps({"evidenced_anchor": anchor.isoformat()}), encoding="utf-8")
        return self.dir


class _Base(unittest.TestCase):
    def setUp(self):
        self.mod = _load()
        self._tmp = TemporaryDirectory()
        self.fx = _Fixture(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def _check(self, **kw):
        window_days = kw.pop("window_days", 7)
        d = self.fx.write(**kw)
        return self.mod.check_gaps(d, window_days=window_days, today=_TODAY)


class TestTheClockNoLongerForgivesAGap(_Base):
    """Сам дефект: дыру нельзя закрыть тем, что просто прошло время."""

    def test_a_post_anchor_gap_still_blocks_however_old_the_calendar_says_it_is(self):
        """Дыра в июле, «сегодня» — 17 августа: календарное окно её прощало."""
        ev = [_ANCHOR + timedelta(days=i) for i in range(5)]          # 22–26.06
        ev += [_ANCHOR + timedelta(days=i) for i in range(9, 12)]     # 01–03.07 (дыра)
        res = self._check(evidenced=ev, anchor=_ANCHOR)
        self.assertEqual(res["status"], "fail",
                         f"дыра после якоря обязана блокировать, пока трек не доказал "
                         f"восстановление: {res}")
        self.assertTrue(res["gap_detected"])
        self.assertIn("2026-06-26", res["detail"])

    def test_the_gap_ages_out_when_it_leaves_the_window_of_evidenced_days(self):
        """Контроль в обратную сторону — иначе это был бы вечный замок.

        Окно — «последние `window_days` доказанных дней». Дыра выходит из него, когда
        день возобновления перестаёт в это окно попадать, то есть после него набралось
        `window_days` доказанных дней. Граница названа обоими тестами — этим и следующим.
        """
        ev = [_ANCHOR, _ANCHOR + timedelta(days=1)]
        resume = _ANCHOR + timedelta(days=5)
        # день возобновления + 7 доказанных дней после него ⇒ он вне окна из 7
        ev += [resume + timedelta(days=i) for i in range(8)]
        res = self._check(evidenced=ev, anchor=_ANCHOR, window_days=7)
        self.assertEqual(res["status"], "pass", res)
        self.assertTrue(res["historic_gaps"], "выведенная дыра обязана остаться видимой")
        self.assertIn("вне окна доказанных дней", res["detail"])

    def test_one_evidenced_day_short_of_leaving_the_window_still_blocks(self):
        """Граница принадлежит окну: на один доказанный день меньше — ещё блокирует."""
        ev = [_ANCHOR, _ANCHOR + timedelta(days=1)]
        resume = _ANCHOR + timedelta(days=5)
        ev += [resume + timedelta(days=i) for i in range(7)]    # на один меньше
        res = self._check(evidenced=ev, anchor=_ANCHOR, window_days=7)
        self.assertEqual(res["status"], "fail", res)

    def test_the_edge_is_evidenced_days_not_calendar_days(self):
        """Прямое сравнение двух моделей на одной фикстуре.

        Календарных дней после дыры — 50; доказанных — три. Календарная модель
        прощала, доказанная не прощает.
        """
        ev = [_ANCHOR, _ANCHOR + timedelta(days=1)]
        resume = _TODAY - timedelta(days=2)
        ev += [resume + timedelta(days=i) for i in range(3)]
        res = self._check(evidenced=ev, anchor=_ANCHOR, window_days=7)
        self.assertEqual(res["status"], "fail", res)
        self.assertEqual(res["window_edge"], _ANCHOR.isoformat(),
                         "доказанных дней меньше окна ⇒ край = якорь, ничего не выводится")


class TestTheAnchorCutsOffPrehistory(_Base):
    """Решение владельца: предыстория видна, но не блокирует."""

    def _the_real_shape(self) -> dict:
        """Форма ЖИВЫХ данных: предыстория не доказана, дыра — в журнале регистратора.

        Так это и лежит в `data/` (замер 17.08): бары 20–21.06 помечены `warmup`
        (поэтому якорь — 22.06), доказанный ряд с якоря непрерывен, а дыра
        2026-06-21 → 2026-06-30 живёт в `paper_evidence.json`.
        """
        ev = [_ANCHOR + timedelta(days=i) for i in range(13)]        # 22.06 – 04.07
        return {
            "evidenced": ev,
            "unevidenced": [date(2026, 6, 20), date(2026, 6, 21)],
            "recorded": [date(2026, 6, 20), date(2026, 6, 21)] + ev[8:],
            "anchor": _ANCHOR,
        }

    def test_a_gap_starting_before_the_anchor_does_not_block(self):
        """Тот самый случай 21.06 → 30.06: восстановить нечем, дорисовывать запрещено."""
        res = self._check(**self._the_real_shape())
        self.assertEqual(res["status"], "pass", res)
        self.assertEqual(res["anchor"], _ANCHOR.isoformat())

    def test_the_pre_anchor_gap_stays_VISIBLE(self):
        """Пропустить — не значит спрятать: именно так трек и терял дни незаметно.

        Отдельный положительный контроль ПРОТИВ МОЕЙ ЖЕ ПЕРВОЙ ВЕРСИИ: доказанный ряд
        начинается с якоря и про предысторию не знает, поэтому дыра исчезла из отчёта
        совсем — «не блокирует» превратилось в «не существует». Журнал регистратора
        читается ради видимости, но авторитетом для блокировки не становится.
        """
        res = self._check(**self._the_real_shape())
        self.assertTrue(res["historic_gaps"])
        self.assertIn("2026-06-21 → 2026-06-30", res["detail"])
        self.assertIn("не блокирует", res["detail"])
        self.assertIn("до якоря трека", res["detail"])
        self.assertIn("по регистратору", res["detail"])

    def test_the_recorder_alone_never_blocks_the_checkpoint(self):
        """Дни без честных меток не гейтят: авторитет — доказанный ряд.

        Контроль вхолостую был бы обратным: если бы журнал регистратора блокировал,
        расхождение двух файлов (а оно на живых данных есть) роняло бы проверку вечно.
        """
        ev = [_ANCHOR + timedelta(days=i) for i in range(9)]
        recorded = ev[:3] + ev[6:]          # дыра ТОЛЬКО в журнале регистратора
        res = self._check(evidenced=ev, recorded=recorded, anchor=_ANCHOR)
        self.assertEqual(res["status"], "pass", res)
        self.assertIn("по регистратору", res["detail"],
                      "и всё же она обязана быть НАЗВАНА")

    def test_the_anchor_is_derived_from_the_bars_not_from_a_literal(self):
        """Якорь двигается вместе с треком; вбитая дата рано или поздно начала бы врать."""
        moved = date(2026, 7, 1)
        ev = [moved + timedelta(days=i) for i in range(4)]
        res = self._check(evidenced=ev)          # golive_status НЕ пишем
        self.assertEqual(res["anchor"], moved.isoformat())

    def test_a_recorded_anchor_is_used_when_the_bars_cannot_supply_one(self):
        """Запасной источник — `golive_status.evidenced_anchor` (он уже критический файл)."""
        res = self._check(recorded=[_ANCHOR - timedelta(days=1), _ANCHOR,
                                    _ANCHOR + timedelta(days=4)],
                          anchor=_ANCHOR, with_curve=False)
        self.assertEqual(res["anchor"], _ANCHOR.isoformat())

    def test_an_unknown_anchor_forgives_NOTHING(self):
        """Fail-CLOSED: «мы не смогли посмотреть» не является прощением."""
        res = self._check(recorded=[date(2026, 6, 20), date(2026, 6, 30)],
                          with_curve=False)
        self.assertIsNone(res["anchor"])
        self.assertEqual(res["status"], "fail", res)
        self.assertTrue(res["gap_detected"])


class TestDaysTrackedIsEvidencedNotRecorded(_Base):
    """Отчёт больше не объявляет 44/30 там, где доказано 13."""

    def test_days_tracked_counts_only_evidenced_bars(self):
        ev = [_ANCHOR + timedelta(days=i) for i in range(13)]
        un = [_ANCHOR + timedelta(days=13 + i) for i in range(11)]
        res = self._check(evidenced=ev, unevidenced=un, anchor=_ANCHOR)
        self.assertEqual(res["days_tracked"], 13,
                         "неподтверждённые бары не имеют права попадать в счёт трека")

    def test_the_recorded_count_is_reported_too_not_hidden(self):
        """Разбавление обязано быть ВИДНО — «не считается» ≠ «не существует»."""
        ev = [_ANCHOR + timedelta(days=i) for i in range(5)]
        res = self._check(evidenced=ev, anchor=_ANCHOR,
                          recorded=[_ANCHOR + timedelta(days=i) for i in range(9)])
        self.assertEqual(res["days_recorded"], 9)
        self.assertEqual(res["days_tracked"], 5)
        self.assertIn("записано дней 9", res["detail"])
        self.assertIn("доказано 5", res["detail"])

    def test_an_unevidenced_day_inside_the_track_IS_a_hole(self):
        """Прямое следствие «трек считается доказанными барами».

        День записан, но не доказан ⇒ в доказанном ряду его нет ⇒ это дыра. Именно так
        решение про день с пустой книгой доедет сюда само, когда владелец его закроет.
        """
        ev = [_ANCHOR + timedelta(days=i) for i in range(3)]
        ev += [_ANCHOR + timedelta(days=i) for i in range(4, 7)]
        un = [_ANCHOR + timedelta(days=3)]          # ровно тот пропущенный день
        res = self._check(evidenced=ev, unevidenced=un, anchor=_ANCHOR)
        self.assertEqual(res["status"], "fail", res)
        self.assertIn("2026-06-24 → 2026-06-26", res["detail"],
                      "дыра называется своими краями — пропущенный день между ними")

    def test_the_evidence_source_is_NAMED(self):
        """Иначе «13 доказанных» и «13 записанных» в отчёте не отличить."""
        ev = [_ANCHOR + timedelta(days=i) for i in range(4)]
        res = self._check(evidenced=ev, anchor=_ANCHOR)
        self.assertIn("доказанные бары", res["evidence_source"])
        res2 = self._check(recorded=ev, anchor=_ANCHOR, with_curve=False)
        self.assertIn("метки доказанности отсутствуют", res2["evidence_source"])


class TestCleanTrackAndFailClosedPaths(_Base):
    """Проверка не имеет права ни шуметь на чистом треке, ни молчать при отказе."""

    def test_a_clean_evidenced_track_passes_with_no_noise(self):
        ev = [_ANCHOR + timedelta(days=i) for i in range(12)]
        res = self._check(evidenced=ev, anchor=_ANCHOR)
        self.assertEqual(res["status"], "pass", res)
        self.assertEqual(res["historic_gaps"], [])
        self.assertEqual(res["blocking_gaps"], [])

    def test_an_unavailable_evidence_module_fails_CLOSED(self):
        """Без канонического счёта ни одна дыра не выводится из окна."""
        ev = [_ANCHOR + timedelta(days=i) for i in range(12)]
        d = self.fx.write(evidenced=ev, anchor=_ANCHOR)

        def _boom():
            raise ImportError("track_evidence недоступен")

        self.mod._track_evidence_module = _boom
        res = self.mod.check_gaps(d, today=_TODAY)
        self.assertEqual(res["status"], "fail", res)
        self.assertIn("fail-CLOSED", res["detail"])

    def test_a_missing_curve_is_not_read_as_zero_evidenced_days(self):
        """«Доказанных ноль» и «мы не смотрели» — разные ответы (fail-CLOSED)."""
        series = self.mod.evidenced_series(Path(self._tmp.name), today=_TODAY)
        self.assertIsNone(series)

    def test_the_gap_monitor_branch_is_untouched(self):
        """Свежесть — отдельный вопрос от дыр, и порог 26ч не тронут."""
        d = self.fx.write(evidenced=[_ANCHOR + timedelta(days=i) for i in range(9)],
                          anchor=_ANCHOR)
        (d / "gap_monitor.json").write_text(
            json.dumps({"gap_detected": False, "active_gaps": [],
                        "hours_since_last_entry": 40.0}), encoding="utf-8")
        res = self.mod.check_gaps(d, today=_TODAY)
        self.assertEqual(res["status"], "fail")
        self.assertIn("40.0h", res["detail"])


class TestTheRealTreeNumbers(unittest.TestCase):
    """Замер на живых файлах этого чекаута — фикстура не заменяет реальность.

    Урок из `test_checkpoint_gap_window.py`: первая правка позеленила все тесты и
    падала на настоящих данных, потому что автор проверял только тот путь, который чинил.
    """

    def setUp(self):
        self.mod = _load()
        self.data = _REPO / "data"

    def test_the_committed_track_reports_evidenced_days_not_recorded_ones(self):
        if not (self.data / "equity_curve_daily.json").is_file():
            self.skipTest("в этом чекауте нет data/equity_curve_daily.json")
        res = self.mod.check_gaps(self.data, today=_TODAY)
        self.assertEqual(res["anchor"], _ANCHOR.isoformat(),
                         "якорь живого трека читается из данных")
        self.assertLess(res["days_tracked"], res["days_recorded"],
                        "доказанных дней меньше записанных — это и обязано быть видно")
        self.assertEqual(res["days_tracked"], 13,
                         "13 доказанных дней — то же число, что у гейта go-live")


if __name__ == "__main__":
    unittest.main()
