"""«Дней подряд готовности» обязано означать ровно то, что написано в имени.

Дефект, измеренный 2026-08-07. Система стала READY **впервые** в этот день —
накануне было 28/29. Отчёт показал **58 дней подряд**.

Причина в конструкции:

    seeded_days = max(1, (today - PAPER_REAL_START).days)
    return max(prior_days + 1, seeded_days)

``max(...)`` гарантировал, что число **никогда не будет маленьким** — то есть
счётчик непрерывности физически не мог сказать «мы только что стали готовы».
Он подставлял возраст paper-трека и выдавал прошлое за подтверждение. 58 было
больше и возраста честного трека (45 дней), и расстояния от evidenced-якоря (46).

Тот же механизм, что у порога TVL, который не мог вернуть False: выражение, по
построению неспособное дать неудобный ответ.

Опаснее среднего по трём причинам: звучит как доказательство устойчивости
(«58 дней подряд без сбоя»), лежит рядом с полем, которое уходит на публичную
страницу, и участвует в решении о выходе на живые деньги.

Тесты ниже — контракт поля целиком: четыре перехода, и первый из них тот самый,
который старая версия произвести не могла.
"""
from __future__ import annotations

import json
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

from spa_core.paper_trading.golive_checker import GoLiveChecker

_NOW = datetime(2026, 8, 7, 12, 0, tzinfo=timezone.utc)


def _checker(tmp: Path, now: datetime, prior: dict | None = None) -> GoLiveChecker:
    if prior is not None:
        (tmp / "golive_status.json").write_text(json.dumps(prior), encoding="utf-8")
    return GoLiveChecker(data_dir=tmp, now=now)


class TestCounterMeansWhatItSays(unittest.TestCase):

    def test_first_ready_day_is_ONE_not_the_track_age(self):
        """Тот самый случай. Старая версия здесь давала 58."""
        with TemporaryDirectory() as t:
            got = _checker(Path(t), _NOW)._compute_consecutive_ready_days(True)
        self.assertEqual(got, 1,
                         "первый READY — это ровно один день, а не возраст трека")

    def test_second_consecutive_day_is_two(self):
        with TemporaryDirectory() as t:
            prior = {"consecutive_ready_days": 1, "timestamp": "2026-08-06T12:00:00Z"}
            got = _checker(Path(t), _NOW, prior)._compute_consecutive_ready_days(True)
        self.assertEqual(got, 2)

    def test_a_rerun_on_the_same_day_does_not_inflate(self):
        """Цикл может отработать дважды за сутки — счётчик суток, а не прогонов."""
        with TemporaryDirectory() as t:
            prior = {"consecutive_ready_days": 5, "timestamp": "2026-08-07T06:00:00Z"}
            got = _checker(Path(t), _NOW, prior)._compute_consecutive_ready_days(True)
        self.assertEqual(got, 5)

    def test_losing_readiness_resets_to_zero(self):
        """Сторона, без которой счётчик стал бы просто календарём."""
        with TemporaryDirectory() as t:
            prior = {"consecutive_ready_days": 30, "timestamp": "2026-08-06T12:00:00Z"}
            got = _checker(Path(t), _NOW, prior)._compute_consecutive_ready_days(False)
        self.assertEqual(got, 0)

    def test_streak_restarts_at_one_after_a_break(self):
        """После срыва счёт начинается заново, а не продолжает старый."""
        with TemporaryDirectory() as t:
            prior = {"consecutive_ready_days": 0, "timestamp": "2026-08-06T12:00:00Z"}
            got = _checker(Path(t), _NOW, prior)._compute_consecutive_ready_days(True)
        self.assertEqual(got, 1)


class TestCounterCannotExceedReality(unittest.TestCase):
    """Свойство, нарушение которого и выдало дефект."""

    def test_counter_never_exceeds_days_since_the_first_ready_day(self):
        """Дней подряд не может быть больше, чем прошло дней.

        Это инвариант, а не придирка: именно его нарушение (58 > 45) сделало
        дефект заметным. Проверяем на длинной серии.
        """
        with TemporaryDirectory() as t:
            tmp = Path(t)
            days = 0
            start = _NOW
            for i in range(10):
                now = start + timedelta(days=i)
                prior = {"consecutive_ready_days": days,
                         "timestamp": (now - timedelta(days=1)).isoformat()}
                days = _checker(tmp, now, prior)._compute_consecutive_ready_days(True)
                self.assertLessEqual(days, i + 1,
                                     f"на день {i + 1} счётчик показал {days}")
            self.assertEqual(days, 10)

    def test_unreadable_prior_state_starts_at_one_not_at_the_calendar(self):
        """Битое состояние — не повод подставить историю."""
        with TemporaryDirectory() as t:
            prior = {"consecutive_ready_days": "мусор", "timestamp": "не-дата"}
            got = _checker(Path(t), _NOW, prior)._compute_consecutive_ready_days(True)
        self.assertEqual(got, 1)


if __name__ == "__main__":
    unittest.main()
