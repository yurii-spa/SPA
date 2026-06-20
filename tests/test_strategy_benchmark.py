#!/usr/bin/env python3
"""tests/test_strategy_benchmark.py — MP-1252.

Test suite for the 3-dimension strategy benchmark comparison system:
  * spa_core/analytics/strategy_benchmark_tracker.py
  * spa_core/analytics/monthly_performance_report.py

Groups:
  A. Helpers — _safe_float / _normalize_id            (A1–A5)
  B. Backtest loading + normalisation                  (B1–B5)
  C. Paper-track summarisation                          (C1–C4)
  D. get_comparison (3-way per strategy)                (D1–D5)
  E. Leaderboard ranking                                (E1–E3)
  F. Active strategy vs benchmark                       (F1–F4)
  G. Snapshot persistence (atomic)                      (G1–G2)
  H. Monthly performance report                         (H1–H7)

Pure stdlib. Offline. Self-contained fixtures via tempdir. 30 tests.
"""
from __future__ import annotations

import json
import pathlib
import sys
import tempfile
import unittest

_HERE = pathlib.Path(__file__).resolve().parent
_REPO = _HERE.parent
sys.path.insert(0, str(_REPO))

from spa_core.analytics import strategy_benchmark_tracker as sbt
from spa_core.analytics.strategy_benchmark_tracker import StrategyBenchmarkTracker
from spa_core.analytics.monthly_performance_report import MonthlyPerformanceReport


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

_BACKTEST = {
    "data_source": "synthetic",
    "strategies": {
        "S0_baseline": {"annualised_return_pct": 5.72, "strategy_name": "Baseline", "risk_tier": "T1"},
        "S2_lp_stable": {"annualised_return_pct": 8.98, "strategy_name": "LP Stable", "risk_tier": "T2"},
        "S7_pendle": {"annualised_return_pct": 11.08, "strategy_name": "Pendle", "risk_tier": "T3"},
        "S3_yield_loop": {"annualised_return_pct": 0.0, "strategy_name": "Yield Loop", "risk_tier": "T3"},
    },
}

# 3 real (non-warmup) days: 100000 → 100010 → 100020 → 100030 (each +~0.01%)
_EQUITY = {
    "source": "cycle_runner",
    "daily": [
        {  # warmup — must be excluded
            "date": "2026-05-30", "open_equity": 100000.0, "close_equity": 100010.0,
            "daily_return_pct": 0.01, "apy_today": 3.9, "is_warmup": True,
            "positions": {"aave_v3": 100000.0},
        },
        {
            "date": "2026-06-10", "open_equity": 100000.0, "close_equity": 100010.0,
            "daily_return_pct": 0.0, "apy_today": 3.9, "is_warmup": False,
            "positions": {"aave_v3": 50000.0, "compound_v3": 50000.0},
        },
        {
            "date": "2026-06-11", "open_equity": 100010.0, "close_equity": 100020.0,
            "daily_return_pct": 0.01, "apy_today": 3.9, "is_warmup": False,
            "positions": {"aave_v3": 50000.0, "compound_v3": 50000.0},
        },
        {
            "date": "2026-06-12", "open_equity": 100020.0, "close_equity": 100030.0,
            "daily_return_pct": 0.01, "apy_today": 4.82, "is_warmup": False,
            "positions": {"aave_v3": 40000.0, "compound_v3": 35000.0, "morpho_blue": 25000.0},
        },
    ],
}


def _write_fixtures(data_dir: pathlib.Path) -> None:
    (data_dir / "backtest_results.json").write_text(json.dumps(_BACKTEST), encoding="utf-8")
    (data_dir / "equity_curve_daily.json").write_text(json.dumps(_EQUITY), encoding="utf-8")


class _Base(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.data_dir = pathlib.Path(self._tmp.name)
        _write_fixtures(self.data_dir)
        self.tracker = StrategyBenchmarkTracker(
            data_dir=str(self.data_dir), active_strategy_id="S0", benchmark_apy=3.10
        )

    def tearDown(self) -> None:
        self._tmp.cleanup()


# ---------------------------------------------------------------------------
# A. Helpers
# ---------------------------------------------------------------------------

class TestHelpers(unittest.TestCase):
    def test_A1_safe_float_valid(self):
        self.assertEqual(sbt._safe_float("3.5"), 3.5)

    def test_A2_safe_float_bool_is_none(self):
        self.assertIsNone(sbt._safe_float(True))

    def test_A3_safe_float_garbage(self):
        self.assertIsNone(sbt._safe_float("abc"))

    def test_A4_normalize_id_basic(self):
        self.assertEqual(sbt._normalize_id("S0_baseline"), "S0")

    def test_A5_normalize_id_already_short(self):
        self.assertEqual(sbt._normalize_id("s7"), "S7")


# ---------------------------------------------------------------------------
# B. Backtest loading
# ---------------------------------------------------------------------------

class TestBacktestLoad(_Base):
    def test_B1_all_strategies_loaded(self):
        bt = self.tracker.load_backtest()
        self.assertEqual(set(bt), {"S0", "S2", "S7", "S3"})

    def test_B2_normalised_keys(self):
        bt = self.tracker.load_backtest()
        self.assertIn("S0", bt)
        self.assertNotIn("S0_baseline", bt)

    def test_B3_annualised_value(self):
        bt = self.tracker.load_backtest()
        self.assertAlmostEqual(bt["S7"]["annualised_return_pct"], 11.08)

    def test_B4_keeps_original_key(self):
        bt = self.tracker.load_backtest()
        self.assertEqual(bt["S2"]["backtest_key"], "S2_lp_stable")

    def test_B5_missing_file_empty(self):
        empty_dir = tempfile.TemporaryDirectory()
        try:
            t = StrategyBenchmarkTracker(data_dir=empty_dir.name)
            self.assertEqual(t.load_backtest(), {})
        finally:
            empty_dir.cleanup()


# ---------------------------------------------------------------------------
# C. Paper track
# ---------------------------------------------------------------------------

class TestPaperTrack(_Base):
    def test_C1_excludes_warmup(self):
        paper = self.tracker.load_paper_track()
        self.assertEqual(paper["num_days"], 3)
        self.assertEqual(paper["start_date"], "2026-06-10")

    def test_C2_total_return(self):
        paper = self.tracker.load_paper_track()
        # 100000 → 100030 = +0.03%
        self.assertAlmostEqual(paper["total_return_pct"], 0.03, places=4)

    def test_C3_current_apy_is_last(self):
        paper = self.tracker.load_paper_track()
        self.assertAlmostEqual(paper["current_apy_pct"], 4.82)

    def test_C4_no_equity_file_unavailable(self):
        empty_dir = tempfile.TemporaryDirectory()
        try:
            t = StrategyBenchmarkTracker(data_dir=empty_dir.name)
            self.assertFalse(t.load_paper_track()["available"])
        finally:
            empty_dir.cleanup()


# ---------------------------------------------------------------------------
# D. get_comparison
# ---------------------------------------------------------------------------

class TestComparison(_Base):
    def test_D1_backtest_alpha(self):
        c = self.tracker.get_comparison("S0")
        self.assertAlmostEqual(c["alpha_vs_aave_backtest"], 5.72 - 3.10, places=4)

    def test_D2_active_has_paper(self):
        c = self.tracker.get_comparison("S0")
        self.assertTrue(c["is_active"])
        self.assertIsNotNone(c["paper_annualized"])

    def test_D3_inactive_no_paper(self):
        c = self.tracker.get_comparison("S7")
        self.assertFalse(c["is_active"])
        self.assertIsNone(c["paper_annualized"])
        self.assertIsNone(c["alpha_vs_aave_paper"])

    def test_D4_verdict_beats(self):
        c = self.tracker.get_comparison("S7")
        self.assertIn("beats Aave", c["verdict"])

    def test_D5_verdict_lags(self):
        c = self.tracker.get_comparison("S3")  # 0% < 3.1%
        self.assertIn("lags Aave", c["verdict"])

    def test_D6_unknown_strategy(self):
        c = self.tracker.get_comparison("S99")
        self.assertIsNone(c["backtest_annualized"])
        self.assertIn("no backtest data", c["verdict"])


# ---------------------------------------------------------------------------
# E. Leaderboard
# ---------------------------------------------------------------------------

class TestLeaderboard(_Base):
    def test_E1_ranked_by_alpha_desc(self):
        lb = self.tracker.get_leaderboard()
        alphas = [r["alpha_vs_aave_backtest"] for r in lb]
        self.assertEqual(alphas, sorted(alphas, reverse=True))

    def test_E2_top_is_s7(self):
        lb = self.tracker.get_leaderboard()
        self.assertEqual(lb[0]["strategy_id"], "S7")
        self.assertEqual(lb[0]["rank"], 1)

    def test_E3_all_present(self):
        lb = self.tracker.get_leaderboard()
        self.assertEqual({r["strategy_id"] for r in lb}, {"S0", "S2", "S7", "S3"})


# ---------------------------------------------------------------------------
# F. Active strategy vs benchmark
# ---------------------------------------------------------------------------

class TestActiveVsBenchmark(_Base):
    def test_F1_available(self):
        avb = self.tracker.get_active_strategy_vs_benchmark()
        self.assertTrue(avb["available"])
        self.assertEqual(avb["active_strategy_id"], "S0")

    def test_F2_alpha_usd_positive(self):
        avb = self.tracker.get_active_strategy_vs_benchmark()
        # SPA +0.03% beats lazy Aave's ~3 days of 3.1%/365
        self.assertGreater(avb["alpha_usd"], 0)

    def test_F3_cumulative_alpha_consistent(self):
        avb = self.tracker.get_active_strategy_vs_benchmark()
        expect = round(
            avb["cumulative_paper_return_pct"] - avb["cumulative_benchmark_return_pct"], 4
        )
        self.assertAlmostEqual(avb["cumulative_alpha_pct"], expect, places=4)

    def test_F4_unavailable_when_no_track(self):
        empty_dir = tempfile.TemporaryDirectory()
        try:
            t = StrategyBenchmarkTracker(data_dir=empty_dir.name, active_strategy_id="S0")
            self.assertFalse(t.get_active_strategy_vs_benchmark()["available"])
        finally:
            empty_dir.cleanup()


# ---------------------------------------------------------------------------
# G. Snapshot persistence
# ---------------------------------------------------------------------------

class TestSnapshot(_Base):
    def test_G1_save_creates_file(self):
        path = self.tracker.save_snapshot()
        self.assertTrue(pathlib.Path(path).exists())

    def test_G2_snapshot_roundtrip(self):
        path = self.tracker.save_snapshot()
        data = json.loads(pathlib.Path(path).read_text(encoding="utf-8"))
        self.assertEqual(data["mp"], "MP-1252")
        self.assertEqual(len(data["leaderboard"]), 4)
        self.assertTrue(data["active_vs_benchmark"]["available"])


# ---------------------------------------------------------------------------
# H. Monthly performance report
# ---------------------------------------------------------------------------

class TestMonthlyReport(_Base):
    def _report(self, month="2026-06"):
        return MonthlyPerformanceReport(
            data_dir=str(self.data_dir), month=month, benchmark_apy=3.10,
            active_strategy_id="S0",
        )

    def test_H1_period_excludes_warmup(self):
        r = self._report().build()
        self.assertTrue(r["available"])
        self.assertEqual(r["period"]["start"], "2026-06-10")
        self.assertEqual(r["period"]["track_days"], 3)

    def test_H2_cumulative_alpha_field(self):
        r = self._report().build()
        ret = r["returns"]
        expect = round(
            ret["spa_total_return_pct"] - ret["benchmark_total_return_pct"], 4
        )
        self.assertAlmostEqual(ret["cumulative_alpha_pct"], expect, places=4)

    def test_H3_capital_alpha_consistency(self):
        r = self._report().build()
        cap = r["capital"]
        expect = round(cap["spa_value_usd"] - cap["lazy_aave_value_usd"], 2)
        self.assertAlmostEqual(cap["alpha_usd"], expect, places=2)

    def test_H4_days_positive(self):
        r = self._report().build()
        # 2 of 3 days have +return (first real day is 0.0)
        self.assertEqual(r["risk"]["days_positive"], 2)
        self.assertEqual(r["risk"]["days_total"], 3)

    def test_H5_allocation_weights_sum_100(self):
        r = self._report().build()
        total = sum(p["weight_pct"] for p in r["allocation"]["positions"])
        self.assertAlmostEqual(total, 100.0, places=2)

    def test_H6_markdown_renders(self):
        rpt = self._report()
        md = rpt.render_markdown(rpt.build())
        self.assertIn("SPA Monthly Performance", md)
        self.assertIn("lazy Aave", md)
        self.assertIn("Alpha", md)

    def test_H7_save_writes_json_and_md(self):
        paths = self._report().save()
        self.assertTrue(pathlib.Path(paths["json"]).exists())
        self.assertTrue(pathlib.Path(paths["md"]).exists())
        data = json.loads(pathlib.Path(paths["json"]).read_text(encoding="utf-8"))
        self.assertEqual(data["month"], "2026-06")

    def test_H8_empty_month_unavailable(self):
        r = self._report(month="2099-01").build()
        self.assertFalse(r["available"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
