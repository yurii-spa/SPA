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

**ИЗМЕНЕНИЕ 2026-10-05 (ADR-580 C2, инв. #16 — явное обоснование).** Два теста ниже
(`test_real_positions_make_it_running_with_honest_apy`,
`test_mixed_history_counts_only_the_corrected_days`) до этой правки ожидали ЧИСЛОВУЮ
APY-ставку на ДВУХ честных барах. Это и был измеренный дефект D6
(`docs/rm_truth/A3_product.md` §2.1 / `REVIEW_1.md` claim 11): генератор публиковал
ставку с 2 баров, а страница отдельно гасила её до 30 — прод-полка 04.10 ровно поэтому
несла «Balanced −11.5%» на трёх барах. Порог зрелости (30, канон
`spa_core.defi_engine.package_status.REPORTABLE_AFTER`) теперь ОДИН и живёт в самом
генераторе (`_sleeve_paper_track`), поэтому оба теста обновлены: ставка на 2 барах —
`None` с `reportable=False`, а новый `TestMaturityGate` ниже закрывает сам порог
положительным контролем (29 баров не репортабельны, 30 — репортабельны). Это УСИЛЕНИЕ
проверки (новый класс запрещённого поведения ловится), а не ослабление: прежнее числовое
значение было ровно тем, что ADR-580 запрещает публиковать.
"""
from __future__ import annotations

import importlib.util
import json
import unittest
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]


def _reportable_after() -> int:
    """Канон порога — НЕ переписанный сюда литерал (та же причина, что в генераторе)."""
    spec = importlib.util.spec_from_file_location(
        "_pkg_status", _REPO / "spa_core" / "defi_engine" / "package_status.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.REPORTABLE_AFTER


def _load():
    spec = importlib.util.spec_from_file_location(
        "_gts", _REPO / "scripts" / "generate_track_snapshot.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _bar(date, equity, positions=0, dd=0.0, model="sleeve-econ-v2"):
    # По умолчанию бар посчитан исправленной моделью: с 2026-10-01 (ADR-531, вариант A
    # владельца) в число идут ТОЛЬКО v2-строки, а правила 19.08 действуют внутри них.
    bar = {"date": date, "equity": equity, "positions_count": positions,
           "drawdown_pct": dd}
    if model:
        bar["economics_model"] = model
    return bar


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

    def test_real_positions_make_it_running_but_apy_waits_for_maturity(self):
        """running ещё не значит "ставка готова" (C2, ADR-580) — см. обоснование в шапке файла."""
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
        self.assertIsNone(t["apy_pct"], "2 бара < порога зрелости — число не публикуется")
        self.assertFalse(t["reportable"])
        self.assertEqual(t["reportable_after"], _reportable_after())
        self.assertEqual(t["evidence"], "paper")

    def test_single_honest_bar_shows_running_but_no_apy_yet(self):
        """День 1 с позициями: тест идёт, но годовую ставку из одного бара не выдумываем."""
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            t = self._track(td, [_bar("2026-08-21", 100010.0, positions=4)])
        self.assertEqual(t["status"], "paper_test_running")
        self.assertIsNone(t["apy_pct"])

    def test_pre_fix_rows_restart_the_track_and_are_never_counted(self):
        """Вариант A 01.10: v1-строки сохранены, но ни в дни, ни в ставку, ни в NAV не входят."""
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            t = self._track(td, [_bar("2026-09-01", 100000.0, positions=3, model=None),
                                 _bar("2026-09-02", 99000.0, positions=3, model=None)])
        self.assertEqual(t["status"], "restarted_on_corrected_model")
        self.assertIsNone(t["apy_pct"])
        self.assertIsNone(t["dd_pct"])
        self.assertIsNone(t["nav_usd"], "NAV несёт итог искажённого периода")
        self.assertEqual(t["days_with_positions"], 0)
        self.assertEqual(t["pre_fix_period"]["days"], 2)
        self.assertEqual(t["pre_fix_period"]["status"], "distorted")

    def test_mixed_history_counts_only_the_corrected_days(self):
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            t = self._track(td, [_bar("2026-09-01", 100000.0, positions=3, model=None),
                                 _bar("2026-09-02", 90000.0, positions=3, model=None),
                                 _bar("2026-09-03", 100000.0, positions=3),
                                 _bar("2026-09-04", 100020.0, positions=3)])
        self.assertEqual(t["status"], "paper_test_running")
        self.assertEqual(t["days_with_positions"], 2)
        # 2 честных v2-бара < порога зрелости — ставка не публикуется (C2, см. обоснование
        # в шапке файла), но просадка v2-ряда всё равно считается и показывается (инв. #8).
        self.assertIsNone(t["apy_pct"])
        self.assertFalse(t["reportable"])
        self.assertEqual(t["dd_pct"], 0.0, "просадка v1-периода не входит в v2-ряд")
        self.assertEqual(t["observed_accrual_since"], "2026-09-03")
        self.assertEqual(t["pre_fix_period"]["days"], 2)


class TestMaturityGate(unittest.TestCase):
    """C2 (ADR-580): ставка рукава ниже порога зрелости — None, с reportable=False явно.

    Положительный контроль дефекта D6 (`docs/rm_truth/A3_product.md` §2.1 /
    `REVIEW_1.md` claim 11): генератор раньше публиковал ставку с 2 баров, страница сама
    гасила её до 30 — прод-полка 04.10 несла «Balanced −11.5%» именно так. Порог
    проверяется ОТ КАНОНА (`REPORTABLE_AFTER`), не от переписанного литерала «30»: если
    канон когда-нибудь изменится, этот тест изменится вместе с ним, а не разойдётся.
    """

    def _track(self, tmp, n_honest):
        import tempfile  # noqa: F401 — совместимость сигнатуры с остальными хелперами файла
        gts = _load()
        p = Path(tmp) / "hy_paper_trading.json"
        history = [_bar(f"2026-10-{i + 1:02d}", 100000.0 + i * 10.0, positions=2)
                   for i in range(n_honest)]
        p.write_text(json.dumps({"equity": history[-1]["equity"] if history else 0.0,
                                 "daily_history": history}), encoding="utf-8")
        return gts._sleeve_paper_track(p)

    def test_one_bar_short_of_maturity_is_not_reportable(self):
        import tempfile
        threshold = _reportable_after()
        with tempfile.TemporaryDirectory() as td:
            t = self._track(td, threshold - 1)
        self.assertEqual(t["days_with_positions"], threshold - 1)
        self.assertFalse(t["reportable"])
        self.assertIsNone(t["apy_pct"], "ниже порога — значение обязано быть None")

    def test_exactly_at_maturity_is_reportable(self):
        import tempfile
        threshold = _reportable_after()
        with tempfile.TemporaryDirectory() as td:
            t = self._track(td, threshold)
        self.assertEqual(t["days_with_positions"], threshold)
        self.assertTrue(t["reportable"])
        self.assertIsNotNone(t["apy_pct"], "на пороге — ставка обязана публиковаться")


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
