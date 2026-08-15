"""Гейт go-live: блокируют АКТИВНЫЕ дыры, историческая остаётся в отчёте.

ADR-087 (выписан как ADR-067 — номер разошёлся 2026-08-15), решение владельца 2026-08-06.

Критерий смотрел на ЛЮБУЮ дыру в треке. В треке их две — 2026-07-19 и
2026-07-27; оба дня цикл умер, не дойдя до аллокации, восстановить нечем, а
дорисовывать запрещено. Значит критерий нельзя было закрыть **никаким
действием**: вечный замок, а не порог, и go-live стоял на 28/29 бессрочно.

Это тот же класс, что «неизменяемое не-измерено забивает очередь»: отказ, который
не снимается ничем, перестаёт быть сигналом и начинает быть шумом.

Тесты держат обе стороны, и вторая важнее первой. Проверка, которая только
«пропускает историческую дыру», прошла бы и на версии, пропускающей ВСЁ.
"""
from __future__ import annotations

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from spa_core.paper_trading.golive_checker import GoLiveChecker


def _gap_doc(**over) -> dict:
    doc = {
        "checked_at": "2026-08-07T00:00:00Z",
        "status": "history_gap",
        "gap_detected": True,
        "has_gaps": True,
        "day_gaps": [
            {"from": "2026-07-18", "to": "2026-07-20", "days_missed": 1,
             "age_days": 20, "actionable": False},
        ],
        "active_gaps": [],
        "days_count": 44,
        "days_missed_total": 1,
    }
    doc.update(over)
    return doc


class TestActiveGapsOnly(unittest.TestCase):

    def _check(self, doc: dict) -> tuple[bool, list]:
        with TemporaryDirectory() as tmp:
            d = Path(tmp)
            (d / "gap_monitor.json").write_text(json.dumps(doc), encoding="utf-8")
            blockers: list = []
            ok = GoLiveChecker(data_dir=d)._check_gap_monitor_ok(blockers)
        return ok, blockers

    def test_a_historic_unrecoverable_gap_no_longer_blocks_forever(self):
        """Ровно наш случай: дыры есть, восстановить нельзя, активных ноль."""
        ok, blockers = self._check(_gap_doc())
        self.assertTrue(ok, "невосстановимая дыра не может блокировать бессрочно")
        self.assertEqual(blockers, [])

    def test_a_fresh_recoverable_gap_STILL_blocks(self):
        """Сторона, ради которой всё это не является ослаблением гейта.

        Без неё правка означала бы «дыры больше не мешают никогда».
        """
        ok, blockers = self._check(_gap_doc(active_gaps=[
            {"from": "2026-08-05", "to": "2026-08-07", "days_missed": 1,
             "age_days": 1, "actionable": True},
        ]))
        self.assertFalse(ok, "свежая восстановимая дыра обязана блокировать")
        self.assertTrue(blockers)
        self.assertIn("актив", blockers[0].lower())

    def test_the_historic_gap_stays_visible_in_the_report(self):
        """Прятать её нельзя — именно так трек и терял дни незаметно.

        Гейт её пропускает, но из отчёта она не исчезает.
        """
        doc = _gap_doc()
        self.assertTrue(doc["day_gaps"], "историческая дыра остаётся в day_gaps")
        self.assertTrue(doc["has_gaps"], "и has_gaps продолжает говорить правду")
        ok, _ = self._check(doc)
        self.assertTrue(ok)

    def test_missing_active_gaps_field_falls_back_to_blocking(self):
        """Старый производитель, не пишущий active_gaps ⇒ прежнее поведение.

        Fail-CLOSED: неизвестное не считается «чисто». Иначе правка стала бы
        дырой, через которую проезжает всё, чей формат мы не узнали.
        """
        doc = _gap_doc()
        doc.pop("active_gaps")
        ok, blockers = self._check(doc)
        self.assertFalse(ok, "нет поля ⇒ откат на старое поведение, а не пропуск")
        self.assertIn("fail-CLOSED", blockers[0])

    def test_a_clean_track_passes(self):
        ok, blockers = self._check(_gap_doc(status="ok", gap_detected=False,
                                            has_gaps=False, day_gaps=[]))
        self.assertTrue(ok)
        self.assertEqual(blockers, [])

    def test_unreadable_file_still_blocks(self):
        with TemporaryDirectory() as tmp:
            blockers: list = []
            ok = GoLiveChecker(data_dir=Path(tmp))._check_gap_monitor_ok(blockers)
        self.assertFalse(ok, "отсутствующий отчёт — не доказательство чистоты")
        self.assertTrue(blockers)

    def test_active_gaps_wrong_type_does_not_silently_pass(self):
        """Мусор в поле не должен читаться как «активных нет»."""
        ok, blockers = self._check(_gap_doc(active_gaps="ноль"))
        self.assertFalse(ok)


if __name__ == "__main__":
    unittest.main()
