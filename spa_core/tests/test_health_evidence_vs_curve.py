"""Монитор здоровья сам считает расхождение доказательной базы с кривой.

Почему проверка живёт в мониторе, а не только в тесте: тест-храповик
(`test_evidence_curve_divergence_ratchet`) требует живого трека и потому не
запускается ни в CI, ни агентом. Сторож, которого никто не зовёт, неотличим от
отсутствующего — тот самый класс, который проект закрывал восемь раз за две недели.
`cycle_health_monitor` ходит по живому дереву сам.

Результат — ЧИСЛО в состоянии монитора. Вывод, который никто не читает, уже был
отдельным дефектом: правило честности записывало флаг, а на сайт он не уезжал.
"""
from __future__ import annotations

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from spa_core.monitoring.cycle_health_monitor import CycleHealthMonitor


def _write(d: Path, ev_days, cu_days):
    (d / "paper_evidence.json").write_text(json.dumps({"days": ev_days}), encoding="utf-8")
    (d / "equity_curve_daily.json").write_text(json.dumps({"daily": cu_days}), encoding="utf-8")


class TestEvidenceVsCurve(unittest.TestCase):

    def _check(self, ev_days, cu_days) -> dict:
        with TemporaryDirectory() as t:
            d = Path(t)
            _write(d, ev_days, cu_days)
            return CycleHealthMonitor().check_evidence_matches_curve(str(d))

    def test_agreeing_days_are_healthy(self):
        r = self._check([{"date": "2026-08-01", "equity_value": 100.0}],
                        [{"date": "2026-08-01", "close_equity": 100.0}])
        self.assertEqual(r["status"], "HEALTHY")
        self.assertEqual(r["divergent_days"], 0)

    def test_a_divergent_day_is_counted_and_warned(self):
        """Сердце проверки: расхождение обязано стать ЧИСЛОМ, а не строкой в логе."""
        r = self._check([{"date": "2026-08-01", "equity_value": 100.0}],
                        [{"date": "2026-08-01", "close_equity": 104.0}])
        self.assertEqual(r["status"], "WARNING")
        self.assertEqual(r["divergent_days"], 1)
        self.assertEqual(r["max_delta_usd"], 4.0)
        self.assertEqual(r["latest_divergent"], "2026-08-01")

    def test_a_cent_of_difference_is_not_a_divergence(self):
        """Допуск существует, чтобы округление не поднимало ложную тревогу."""
        r = self._check([{"date": "2026-08-01", "equity_value": 100.00}],
                        [{"date": "2026-08-01", "close_equity": 100.01}])
        self.assertEqual(r["status"], "HEALTHY")

    def test_missing_files_are_UNCHECKED_not_healthy(self):
        """«Не смогли посмотреть» ≠ «посмотрели, и всё сходится»."""
        with TemporaryDirectory() as t:
            r = CycleHealthMonitor().check_evidence_matches_curve(t)
        self.assertEqual(r["status"], "UNCHECKED")
        self.assertIsNone(r["divergent_days"])

    def test_no_common_dates_is_UNCHECKED(self):
        """Пустое пересечение — нечего сравнивать, а не «всё хорошо»."""
        r = self._check([{"date": "2026-08-01", "equity_value": 100.0}],
                        [{"date": "2026-07-01", "close_equity": 100.0}])
        self.assertEqual(r["status"], "UNCHECKED")

    def test_it_is_part_of_the_health_report(self):
        """Проверка, не попавшая в отчёт, не существует для читателя."""
        with TemporaryDirectory() as t:
            d = Path(t)
            _write(d, [{"date": "2026-08-01", "equity_value": 100.0}],
                   [{"date": "2026-08-01", "close_equity": 104.0}])
            rep = CycleHealthMonitor().run_all_checks(str(d))
        self.assertIn("evidence_vs_curve", rep["checks"])
        self.assertEqual(rep["checks"]["evidence_vs_curve"]["divergent_days"], 1)


if __name__ == "__main__":
    unittest.main()
