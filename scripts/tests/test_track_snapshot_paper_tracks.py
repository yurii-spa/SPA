#!/usr/bin/env python3
"""Тесты paper-треков в снапшоте сайта (scripts/generate_track_snapshot.py, ADR-103).

Правило, которое здесь закреплено, — решение владельца 2026-08-19 (карточка
owner-decision-sbalansirovannyi-tir-…, вариант 1): «идёт paper-тест» показывается
ТОЛЬКО когда positions_count > 0 ИЗМЕРЕН. Замер #208: с 09.08 equity Balanced
рос при positions_count == 0 в каждой строке — начисление, а не трек. Поэтому:

  • статус paper_test_running требует хотя бы одного бара с позициями;
  • APY считается ТОЛЬКО по барам с позициями — фантомные бары в него не входят;
  • нет файла / нет данных → честные None, никогда не выдуманное число (инв. #8).

Оффлайн, stdlib, пути инжектируются.
"""
from __future__ import annotations

import importlib.util
import json
import unittest
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]


def _load():
    spec = importlib.util.spec_from_file_location(
        "_gts", _REPO / "scripts" / "generate_track_snapshot.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _bar(date, equity, positions=0, dd=0.0):
    return {"date": date, "equity": equity, "positions_count": positions,
            "drawdown_pct": dd}


class TestSleevePaperTrack(unittest.TestCase):
    def _track(self, tmp, history):
        p = Path(tmp) / "hy_paper_trading.json"
        p.write_text(json.dumps({"equity": (history[-1]["equity"] if history else 0.0),
                                 "daily_history": history}), encoding="utf-8")
        return _load()._sleeve_paper_track(p)

    def test_missing_file_is_all_none_not_invented(self):
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            t = _load()._sleeve_paper_track(Path(td) / "nope.json")
        self.assertEqual(t["status"], "not_started")
        self.assertIsNone(t["apy_pct"])
        self.assertIsNone(t["nav_usd"])

    def test_phantom_accrual_is_not_a_running_test(self):
        """Сердце правила 19.08: equity растёт, позиций ноль ⇒ это НЕ трек."""
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            t = self._track(td, [_bar("2026-08-09", 100000.0),
                                 _bar("2026-08-10", 100016.0),
                                 _bar("2026-08-11", 100032.0)])
        self.assertEqual(t["status"], "accrual_only_no_positions")
        self.assertIsNone(t["apy_pct"], "APY по фантомным барам — выдуманное число")
        self.assertEqual(t["days_with_positions"], 0)
        self.assertEqual(t["days_funded"], 3)

    def test_real_positions_make_it_running_with_honest_apy(self):
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            t = self._track(td, [
                _bar("2026-08-19", 100000.0, positions=0),   # фантомный бар — вне APY
                _bar("2026-08-20", 100000.0, positions=3),
                _bar("2026-08-21", 100020.0, positions=3, dd=-0.01),
            ])
        self.assertEqual(t["status"], "paper_test_running")
        self.assertEqual(t["days_with_positions"], 2)
        self.assertEqual(t["positions_count"], 3)
        # (100020/100000)^(365/2)-1 ≈ 3.72% годовых
        self.assertAlmostEqual(t["apy_pct"], 3.72, delta=0.05)
        self.assertEqual(t["evidence"], "paper")

    def test_single_honest_bar_shows_running_but_no_apy_yet(self):
        """День 1 с позициями: тест идёт, но годовую ставку из одного бара не выдумываем."""
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            t = self._track(td, [_bar("2026-08-21", 100010.0, positions=4)])
        self.assertEqual(t["status"], "paper_test_running")
        self.assertIsNone(t["apy_pct"])


class TestBuildSnapshotIntegration(unittest.TestCase):
    def test_paper_tracks_present_for_all_three_tiers(self):
        import tempfile
        gts = _load()
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "data").mkdir()
            (root / "landing" / "src" / "data").mkdir(parents=True)
            (root / "data" / "hy_paper_trading.json").write_text(json.dumps(
                {"equity": 66700.0, "daily_history": [
                    _bar("2026-08-20", 66666.0, positions=2),
                    _bar("2026-08-21", 66690.0, positions=2)]}), encoding="utf-8")
            gts.ROOT = root
            gts.OUT = root / "landing" / "src" / "data" / "track_snapshot.json"
            snap = gts.build_snapshot(golive_path=root / "data" / "golive_status.json",
                                      equity_path=root / "data" / "equity_curve_daily.json")
        pt = snap["paper_tracks"]
        self.assertEqual(set(pt), {"conservative", "balanced", "aggressive"})
        self.assertEqual(pt["balanced"]["status"], "paper_test_running")
        self.assertEqual(pt["aggressive"]["status"], "not_started")
        self.assertEqual(pt["balanced"]["evidence"], "paper")


class TestSiteFactGate(unittest.TestCase):
    """Карточка тира рендерит paper-строку ТОЛЬКО на status paper_test_running.

    Astro-страница не исполняется в этом наборе, поэтому закрепляется сама
    проводка: условие факта обязано стоять в шаблоне (сорванное условие =
    плашка «идёт тест» на фантомной книге — ровно то, что владелец снял 19.08).
    """

    def test_packages_page_gates_on_running_status(self):
        src = (_REPO / "landing" / "src" / "pages" / "packages.astro").read_text(encoding="utf-8")
        self.assertIn("paper_test_running", src)
        self.assertIn("paper_tracks", src)
        gate_pos = src.find("pt.status === 'paper_test_running'")
        self.assertGreater(gate_pos, -1, "фактовый гейт условия исчез со страницы")


if __name__ == "__main__":
    unittest.main()
