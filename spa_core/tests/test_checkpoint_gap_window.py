"""Недельная проверка обязана смотреть в своё окно, а не во всю историю.

Её собственное описание обещало «нет пробелов **за последние 7 дней**», а код
сканировал всю историю и падал на первой найденной дыре. Дыры
`2026-06-21 → 2026-06-30` восстановить нечем: цикл в те дни умер, а дорисовывать
трек запрещено. Значит проверка не могла быть закрыта **никаким действием** —
вечный замок, который каждую неделю рождал владельцу карточку.

Владелец уже решил этот класс в **ADR-087** (выписан как ADR-067) для гейта go-live: блокируют активные
дыры, историческая остаётся видимой. До недельной проверки решение не доехало —
она читает другой файл. Здесь оно применено ко второму потребителю.

Вторая сторона важнее первой. Проверка, которая только «пропускает старую дыру»,
прошла бы и на версии, пропускающей ВСЁ, — то есть на молча выключенной проверке
(`CLAUDE.md`, инвариант 16).

Дата инъектируется: тест про окно, завязанный на реальный календарь, — бомба
замедленного действия (`.claude/rules/deployment.md`).
"""
from __future__ import annotations

import importlib.util
import json
import unittest
from datetime import date
from pathlib import Path
from tempfile import TemporaryDirectory

_REPO = Path(__file__).resolve().parents[2]
_TODAY = date(2026, 8, 9)


def _load():
    spec = importlib.util.spec_from_file_location(
        "checkpoint_7day", str(_REPO / "scripts" / "checkpoint_7day.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class TestGapWindow(unittest.TestCase):

    def setUp(self):
        self.mod = _load()

    def _check(self, dates: list[str]) -> dict:
        with TemporaryDirectory() as t:
            d = Path(t)
            (d / "paper_evidence.json").write_text(
                json.dumps({"days": [{"date": x} for x in dates]}), encoding="utf-8")
            return self.mod.check_gaps(d, today=_TODAY)

    def test_the_real_incident_no_longer_fails_forever(self):
        """Тот самый случай: июньская дыра при непрерывном августе."""
        dates = ["2026-06-20", "2026-06-21", "2026-06-30"] + \
                [f"2026-08-{d:02d}" for d in range(1, 10)]
        res = self._check(dates)
        self.assertEqual(res["status"], "pass",
                         "невосстановимая дыра не может блокировать бессрочно")

    def test_the_historic_gap_stays_VISIBLE(self):
        """Пропустить — не значит спрятать: именно так трек и терял дни незаметно."""
        dates = ["2026-06-20", "2026-06-21", "2026-06-30"] + \
                [f"2026-08-{d:02d}" for d in range(1, 10)]
        res = self._check(dates)
        self.assertTrue(res["historic_gaps"], "историческая дыра обязана остаться в отчёте")
        self.assertIn("2026-06-30", res["detail"])
        self.assertIn("не блокирует", res["detail"])

    def test_a_FRESH_gap_still_fails(self):
        """Сторона, без которой это было бы молчаливым отключением проверки."""
        dates = [f"2026-08-{d:02d}" for d in (1, 2, 3, 7, 8, 9)]
        res = self._check(dates)
        self.assertEqual(res["status"], "fail", "свежая дыра обязана блокировать")
        self.assertTrue(res["gap_detected"])
        self.assertIn("2026-08-07", res["detail"])

    def test_a_gap_exactly_on_the_window_edge_still_fails(self):
        """Граница принадлежит окну — иначе дыра проскочит на день раньше срока."""
        dates = ["2026-07-30", "2026-08-02"] + [f"2026-08-{d:02d}" for d in range(3, 10)]
        res = self._check(dates)
        self.assertEqual(res["status"], "fail")

    def test_a_clean_track_passes_with_no_noise(self):
        res = self._check([f"2026-08-{d:02d}" for d in range(1, 10)])
        self.assertEqual(res["status"], "pass")
        self.assertEqual(res["historic_gaps"], [])

    def test_fresh_gap_wins_over_a_historic_one(self):
        """Если есть обе — блокирует свежая, а не «первая найденная»."""
        dates = ["2026-06-20", "2026-06-30"] + [f"2026-08-{d:02d}" for d in (1, 2, 7, 8, 9)]
        res = self._check(dates)
        self.assertEqual(res["status"], "fail")
        self.assertIn("2026-08-07", res["detail"])


class TestGapMonitorBranch(unittest.TestCase):
    """Вторая ветка той же функции — её нашли ЖИВЫЕ данные, а не тесты.

    Первая правка починила ветку по `paper_evidence`, и все шесть тестов позеленели.
    Прогон против настоящего `data/` показал `fail`: ветка по `gap_monitor.json`
    падала на `gap_detected`, истинном и для исторических дыр. Тесты этого не
    видели, потому что проверяли только тот путь, который автор чинил.

    Урок тот же, что записан в памяти проекта: править надо проводку целиком,
    а не деталь; и мерить на живом, а не только на фикстуре.
    """

    def setUp(self):
        self.mod = _load()

    def _check(self, gm: dict) -> dict:
        with TemporaryDirectory() as t:
            d = Path(t)
            (d / "gap_monitor.json").write_text(json.dumps(gm), encoding="utf-8")
            (d / "paper_evidence.json").write_text(
                json.dumps({"days": [{"date": f"2026-08-{x:02d}"} for x in range(1, 10)]}),
                encoding="utf-8")
            return self.mod.check_gaps(d, today=_TODAY)

    def _doc(self, **over) -> dict:
        doc = {"gap_detected": True, "has_gaps": True, "active_gaps": [],
               "hours_since_last_entry": 3.0,
               "day_gaps": [{"from": "2026-07-18", "to": "2026-07-20", "actionable": False}]}
        doc.update(over)
        return doc

    def test_historic_only_passes(self):
        """Ровно то, что показали живые данные."""
        self.assertEqual(self._check(self._doc())["status"], "pass")

    def test_an_active_gap_fails(self):
        res = self._check(self._doc(active_gaps=[{"from": "2026-08-07", "to": "2026-08-09"}]))
        self.assertEqual(res["status"], "fail")
        self.assertIn("Активная", res["detail"])

    def test_missing_field_falls_back_to_blocking(self):
        """Старый производитель ⇒ прежнее поведение, а не пропуск."""
        doc = self._doc()
        doc.pop("active_gaps")
        res = self._check(doc)
        self.assertEqual(res["status"], "fail")
        self.assertIn("fail-CLOSED", res["detail"])

    def test_garbage_in_the_field_does_not_pass_silently(self):
        res = self._check(self._doc(active_gaps="ноль"))
        self.assertEqual(res["status"], "fail")

    def test_a_stale_last_entry_still_fails(self):
        """Порог 26ч не тронут: свежесть — отдельный вопрос от дыр."""
        res = self._check(self._doc(hours_since_last_entry=40.0))
        self.assertEqual(res["status"], "fail")


if __name__ == "__main__":
    unittest.main()
